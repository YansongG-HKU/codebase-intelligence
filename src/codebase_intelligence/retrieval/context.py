"""Task-aware, token-budgeted context packs (SPEC §4/§9).

Selection pipeline (all deterministic):

1. rank files/symbols with :func:`codebase_intelligence.retrieval.rank.rank`;
2. keep the relevant candidates (lexical hit or dependency proximity), bounded
   by an explicit candidate cap, and filter by ``pathPrefix``;
3. read the source from the *indexed root only* and expand each candidate to a
   bounded definition excerpt (≤120 lines) with a ``path`` + line citation;
4. greedily keep the highest-ranked whole items whose measured payload fits the
   budget, trimming the first excerpt by whole lines before giving up;
5. report every dropped candidate with a reason.

The payload shape is built here (not in :mod:`codebase_intelligence.reporting`)
because it is what the budget is measured against; the reporting layer reuses
:func:`context_payload_dict` so build-time and report-time bytes agree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Sequence

from codebase_intelligence.model import IndexSnapshot
from codebase_intelligence.model.entities import SCHEMA_VERSION
from codebase_intelligence.retrieval.budget import (
    budgets_block,
    clamp_max_tokens,
    estimate_tokens,
    finalize_payload,
    index_block,
    measured_tokens,
)
from codebase_intelligence.retrieval.paths import is_under_prefix, normalize_repo_prefix
from codebase_intelligence.retrieval.rank import RankResult, rank
from codebase_intelligence.util import TOKEN_ESTIMATOR, bounded_text, is_within, to_posix

#: A definition excerpt is bounded even when the symbol body is huge.
MAX_EXCERPT_LINES = 120
#: Below this a trimmed excerpt stops being useful; the item is omitted instead.
MIN_EXCERPT_LINES = 1
#: Candidate caps keep ranking and source I/O bounded on big repositories.
MAX_SYMBOL_CANDIDATES = 24
MAX_FILE_CANDIDATES = 8
MAX_CANDIDATES = 40
#: Echoed task strings and item reasons are bounded like every other payload text.
MAX_TASK_CHARS = 200
MAX_ITEM_REASON_CHARS = 120
MAX_OMISSION_REASON_CHARS = 120
#: Never read an implausibly large file just to build one excerpt.
MAX_SOURCE_BYTES = 4 * 1024 * 1024
#: Tool default for ``codebase_context`` (SPEC §4): when the reporting layer is
#: called with this default it keeps the pack's own (possibly larger) budget.
DEFAULT_CONTEXT_TOKENS = 2200

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True, slots=True)
class Omission:
    """A candidate that was not included, with a human-readable reason."""

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class ContextItem:
    """One cited excerpt inside a context pack (SPEC §9)."""

    path: str
    start_line: int
    end_line: int
    kind: str
    symbol: str | None
    reason: str
    excerpt: str
    tokens_estimated: int


@dataclass(frozen=True, slots=True)
class ContextPack:
    """The budgeted result of one :func:`build_context` call.

    ``omitted``/``tokens_estimated``/``token_estimator`` are the SPEC §9 fields.
    ``omissions`` carries the per-path reason required by the §10 payload shape;
    ``max_tokens`` and ``snapshot`` let the reporting layer re-budget and render
    the required ``index`` block without guessing.  They are excluded from
    equality so packs compare on their contract fields.
    """

    task: str
    items: tuple[ContextItem, ...]
    omitted: tuple[str, ...]
    tokens_estimated: int
    token_estimator: str = TOKEN_ESTIMATOR
    omissions: tuple[Omission, ...] = ()
    max_tokens: int = 2200
    snapshot: IndexSnapshot | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class _CandidatePlan:
    """A ranked candidate before its definition excerpt is read."""

    path: str
    start_line: int
    end_line: int
    kind: str
    symbol: str | None
    score: float
    reasons: tuple[str, ...]
    file_level: bool


@dataclass(frozen=True, slots=True)
class _Candidate:
    """A candidate whose source excerpt is available and clipped."""

    path: str
    start_line: int
    end_line: int
    kind: str
    symbol: str | None
    score: float
    reasons: tuple[str, ...]
    lines: tuple[str, ...]


# ---------------------------------------------------------------------------
# Source access (bounded, root-confined)
# ---------------------------------------------------------------------------
def _read_source(root: str, path: str, cache: dict[str, tuple[str, ...] | None]) -> tuple[str, ...] | None:
    """Read one indexed file as lines, staying inside the indexed root.

    Paths come from the index, but the index is data too: absolute paths, ``..``
    segments and symlinks escaping the root are refused (SPEC §5 security rules).
    """

    if path in cache:
        return cache[path]
    cache[path] = None
    if not root:
        return None
    posix = to_posix(path)
    if not posix or posix.startswith("/") or _DRIVE_PREFIX.match(posix):
        return None
    if any(part == ".." for part in posix.split("/")):
        return None
    root_path = Path(root)
    candidate = root_path / posix
    if not is_within(root_path, candidate):
        return None
    try:
        if candidate.stat().st_size > MAX_SOURCE_BYTES:
            return None
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    cache[path] = tuple(text.splitlines())
    return cache[path]


def _clip_span(
    lines: Sequence[str], start_line: int, end_line: int, *, max_lines: int = MAX_EXCERPT_LINES
) -> tuple[int, int, tuple[str, ...]]:
    """Clip a 1-based line span to the file and to ``max_lines`` whole lines."""

    total = len(lines)
    if total == 0:
        return 1, 1, ("",)
    start = max(1, min(int(start_line), total))
    end = max(start, min(int(end_line), total))
    end = min(end, start + max_lines - 1)
    return start, end, tuple(lines[start - 1 : end])


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------
def _select_candidates(
    snapshot: IndexSnapshot,
    ranked: RankResult,
    prefix: str | None,
) -> tuple[list[_Candidate], list[Omission]]:
    files_by_path, symbols_by_id, _ = snapshot.index_maps()
    plans: list[_CandidatePlan] = []
    covered: set[str] = set()

    symbol_count = 0
    for ranked_symbol in ranked.symbols:
        if symbol_count >= MAX_SYMBOL_CANDIDATES:
            break
        if ranked_symbol.path not in files_by_path:
            continue
        if not is_under_prefix(ranked_symbol.path, prefix):
            continue
        if not ranked_symbol.matched and ranked_symbol.proximity == 0:
            continue
        symbol_record = symbols_by_id.get(ranked_symbol.id)
        if symbol_record is None:
            continue
        plans.append(
            _CandidatePlan(
                path=ranked_symbol.path,
                start_line=ranked_symbol.line,
                end_line=symbol_record.span.end_line,
                kind=ranked_symbol.kind,
                symbol=ranked_symbol.qualified_name,
                score=ranked_symbol.score,
                reasons=ranked_symbol.reasons,
                file_level=False,
            )
        )
        symbol_count += 1
        covered.add(ranked_symbol.path)

    file_count = 0
    for ranked_file in ranked.files:
        if file_count >= MAX_FILE_CANDIDATES:
            break
        if ranked_file.path not in files_by_path:
            continue
        if not is_under_prefix(ranked_file.path, prefix):
            continue
        if ranked_file.path in covered:
            continue
        if not ranked_file.matched and ranked_file.proximity == 0:
            continue
        plans.append(
            _CandidatePlan(
                path=ranked_file.path,
                start_line=1,
                end_line=0,
                kind="file",
                symbol=None,
                score=ranked_file.score,
                reasons=ranked_file.reasons,
                file_level=True,
            )
        )
        file_count += 1
        covered.add(ranked_file.path)

    # Concrete definitions first: a module/file excerpt is a coarser fallback, so
    # it never outranks an actual declaration for the same budget.
    plans.sort(
        key=lambda plan: (
            0 if plan.kind not in ("module", "file") else 1,
            -plan.score,
            plan.path,
            plan.start_line,
            plan.kind,
            plan.symbol or "",
        )
    )
    plans = plans[:MAX_CANDIDATES]

    source_cache: dict[str, tuple[str, ...] | None] = {}
    candidates: list[_Candidate] = []
    omissions: list[Omission] = []
    seen_unavailable: set[str] = set()
    for plan in plans:
        lines = _read_source(snapshot.root, plan.path, source_cache)
        if lines is None:
            if plan.path not in seen_unavailable:
                seen_unavailable.add(plan.path)
                omissions.append(Omission(path=plan.path, reason="source unavailable"))
            continue
        requested_end = len(lines) if plan.file_level or plan.end_line <= 0 else plan.end_line
        start, end, excerpt_lines = _clip_span(lines, plan.start_line, requested_end)
        candidates.append(
            _Candidate(
                path=plan.path,
                start_line=start,
                end_line=end,
                kind=plan.kind,
                symbol=plan.symbol,
                score=plan.score,
                reasons=plan.reasons,
                lines=excerpt_lines,
            )
        )
    return candidates, omissions


# ---------------------------------------------------------------------------
# Payload composition + fitting (shared with reporting)
# ---------------------------------------------------------------------------
def _item_reason(reasons: Sequence[str]) -> str:
    """Two short, factual reasons: the lexical hit plus the best structural one."""

    lexical = [reason for reason in reasons if reason.startswith("lexical")]
    structural = [reason for reason in reasons if not reason.startswith("lexical")]
    selected = [*lexical[:1], *structural[:1]]
    text = "; ".join(selected) if selected else ""
    return bounded_text(text or "ranked match", MAX_ITEM_REASON_CHARS)


def _candidate_item(candidate: _Candidate) -> ContextItem:
    excerpt = "\n".join(candidate.lines)
    return ContextItem(
        path=candidate.path,
        start_line=candidate.start_line,
        end_line=candidate.end_line,
        kind=candidate.kind,
        symbol=candidate.symbol,
        reason=_item_reason(candidate.reasons),
        excerpt=excerpt,
        tokens_estimated=estimate_tokens(excerpt),
    )


def _trim_item(item: ContextItem, keep_lines: int) -> ContextItem:
    lines = item.excerpt.split("\n")[:keep_lines]
    excerpt = "\n".join(lines)
    end_line = item.start_line + len(lines) - 1
    reason = bounded_text(
        f"{item.reason} (trimmed to {len(lines)} lines)", MAX_ITEM_REASON_CHARS
    )
    return replace(
        item,
        end_line=end_line,
        reason=reason,
        excerpt=excerpt,
        tokens_estimated=estimate_tokens(excerpt),
    )


def _item_row(item: ContextItem) -> dict[str, Any]:
    return {
        "path": item.path,
        "startLine": item.start_line,
        "endLine": item.end_line,
        "kind": item.kind,
        "symbol": item.symbol,
        "reason": item.reason,
        "tokensEstimated": item.tokens_estimated,
        "excerpt": item.excerpt,
    }


def _omission_row(omission: Omission) -> dict[str, str]:
    return {
        "path": omission.path,
        "reason": bounded_text(omission.reason, MAX_OMISSION_REASON_CHARS),
    }


def _payload_rows(
    dropped: Sequence[ContextItem],
    base_omissions: Sequence[Omission],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for omission in base_omissions:
        if omission.path in seen:
            continue
        seen.add(omission.path)
        rows.append(_omission_row(omission))
    for item in dropped:
        if item.path in seen:
            continue
        seen.add(item.path)
        rows.append(_omission_row(Omission(path=item.path, reason="budget")))
    return rows


def fit_context(
    snapshot: IndexSnapshot,
    task: str,
    items: Sequence[ContextItem],
    base_omissions: Sequence[Omission] = (),
    *,
    max_tokens: int = 2200,
) -> tuple[dict[str, Any], tuple[ContextItem, ...], tuple[Omission, ...]]:
    """Fit *items* into a context payload; return payload, kept items, omissions."""

    budget = clamp_max_tokens(max_tokens)
    item_list = list(items)
    base = tuple(base_omissions)

    def make(kept: Sequence[ContextItem], placeholder: int) -> dict[str, Any]:
        dropped = item_list[len(kept) :]
        omitted_rows = _payload_rows(dropped, base)
        return {
            "ok": True,
            "schemaVersion": SCHEMA_VERSION,
            "command": "context",
            "index": index_block(snapshot),
            "task": task,
            "items": [_item_row(item) for item in kept],
            "omitted": omitted_rows,
            "budgets": budgets_block(budget, tokens_estimated=placeholder),
            "truncated": bool(omitted_rows),
        }

    def measure(kept: Sequence[ContextItem]) -> int:
        return measured_tokens(make(kept, budget))

    kept: list[ContextItem] = []
    if measure(kept) <= budget:
        index = 0
        while index < len(item_list):
            item = item_list[index]
            if measure([*kept, item]) <= budget:
                kept.append(item)
                index += 1
                continue
            if not kept:
                trimmed = _largest_trimmed_item(item, budget, measure)
                if trimmed is not None:
                    kept.append(trimmed)
                    index += 1
                    continue
            break

    payload = finalize_payload(make(kept, budget), budget)
    while kept and measured_tokens(payload) > budget:
        kept = kept[:-1]
        payload = finalize_payload(make(kept, budget), budget)
    dropped_items = item_list[len(kept) :]
    omissions = [*base, *(Omission(path=item.path, reason="budget") for item in dropped_items)]
    return payload, tuple(kept), tuple(omissions)


def _largest_trimmed_item(
    item: ContextItem,
    budget: int,
    measure: Any,
) -> ContextItem | None:
    """Largest whole-line trim of *item* whose single-item payload fits."""

    line_count = len(item.excerpt.split("\n"))
    if line_count <= MIN_EXCERPT_LINES:
        return None
    low, high = MIN_EXCERPT_LINES, line_count - 1
    best: ContextItem | None = None
    while low <= high:
        middle = (low + high) // 2
        candidate = _trim_item(item, middle)
        if measure([candidate]) <= budget:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def context_payload_dict(
    snapshot: IndexSnapshot,
    pack: ContextPack,
    *,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Render (and re-budget) one context pack into the SPEC §10 payload shape.

    The pack already fits ``pack.max_tokens``; this only shrinks further when the
    caller asks for a smaller budget.  Passing the tool default means "keep the
    budget the pack was built with" (the API layer may have requested a larger
    one), so a large request is never silently reduced to the default.
    """

    if max_tokens is None or max_tokens == DEFAULT_CONTEXT_TOKENS:
        requested = pack.max_tokens
    else:
        requested = max_tokens
    effective = min(clamp_max_tokens(requested), clamp_max_tokens(pack.max_tokens))
    base_omissions = pack.omissions or tuple(
        Omission(path=path, reason="not selected") for path in pack.omitted
    )
    payload, _kept, _omissions = fit_context(
        snapshot,
        pack.task,
        pack.items,
        base_omissions,
        max_tokens=effective,
    )
    return payload


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def build_context(
    snapshot: IndexSnapshot,
    graph: Any,
    task: str,
    *,
    max_tokens: int = 2200,
    path_prefix: str | None = None,
) -> ContextPack:
    """Rank and excerpt the smallest reliable context for *task* (SPEC §9)."""

    budget = clamp_max_tokens(max_tokens)
    prefix = normalize_repo_prefix(path_prefix, field="pathPrefix")
    text = bounded_text(str(task or "").strip(), MAX_TASK_CHARS)
    if not text:
        payload, _kept, _omissions = fit_context(snapshot, "", (), (), max_tokens=budget)
        return ContextPack(
            task="",
            items=(),
            omitted=(),
            tokens_estimated=int(payload["budgets"]["tokensEstimated"]),
            max_tokens=budget,
            snapshot=snapshot,
        )

    ranked = rank(snapshot, graph, text)
    candidates, unavailable = _select_candidates(snapshot, ranked, prefix)
    items = [_candidate_item(candidate) for candidate in candidates]
    payload, kept, omissions = fit_context(
        snapshot,
        text,
        items,
        tuple(unavailable),
        max_tokens=budget,
    )
    unique_omissions: list[Omission] = []
    seen_paths: set[str] = set()
    for omission in omissions:
        if omission.path in seen_paths:
            continue
        seen_paths.add(omission.path)
        unique_omissions.append(omission)
    return ContextPack(
        task=text,
        items=kept,
        omitted=tuple(omission.path for omission in unique_omissions),
        tokens_estimated=int(payload["budgets"]["tokensEstimated"]),
        max_tokens=budget,
        omissions=tuple(unique_omissions),
        snapshot=snapshot,
    )


__all__ = [
    "MAX_EXCERPT_LINES",
    "ContextItem",
    "ContextPack",
    "Omission",
    "build_context",
    "context_payload_dict",
    "fit_context",
]
