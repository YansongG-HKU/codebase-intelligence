"""Deterministic lexical + structural ranking and search (SPEC §9).

The ranker answers one question: given a free-text task/query and an index, which
files and symbols are worth showing a model first?  Four independent signals are
combined, each with an explicit, bounded reason string:

``lexical``
    Token overlap against repository-relative paths, symbol names, qualified
    names, signatures and docstrings.  Exact matches beat camel/snake parts,
    which beat substrings.
``centrality``
    Normalized in-degree over *resolved* relations (unresolved and external
    edges are never counted as structure).
``proximity``
    Distance to paths explicitly named in the query, traversed over the import
    graph (one and two hops) plus a small same-directory fallback.
``entry``/``module``
    A small bonus for entry points and package/module declarations.

Scores are rounded to four decimals and every list has an explicit total order,
so two calls on the same index and query return identical bytes.  The graph is
accessed through the documented :class:`codebase_intelligence.graph.Graph` API
only; a missing method or a ``None`` graph simply means "no graph signal".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from codebase_intelligence.model import (
    IndexSnapshot,
    RelationType,
    ResolutionStatus,
    SymbolKind,
    SymbolRecord,
)
from codebase_intelligence.util import bounded_text

#: Bound on the echoed/scored query and on emitted evidence strings.
MAX_QUERY_CHARS = 500
MAX_REASON_CHARS = 96
MAX_REASONS = 4
MAX_LIMIT = 200
#: Explicitly named paths that seed the proximity walk.
MAX_NAMED_PATHS = 6
MAX_PROXIMITY_FRONTIER = 48
#: Fallbacks that keep a hub file from exploding the proximity walk.
MAX_NEIGHBORS = 64

#: Hard-coded small weights; changing them changes ranking output, not shapes.
#: Query terms keep their strength: a word typed by the user is strong, a
#: snake_case/camelCase or path fragment derived from it is weaker (otherwise
#: "build_context" would rank ``build.py`` above the symbol ``build_context``).
_TERM_DERIVED = 0.55
_TERM_PATH_FRAGMENT = 0.35
_PATH_EXACT = 2.0
_PATH_PART = 1.2
_PATH_SUBSTRING = 0.8
_NAME_EXACT = 2.5
_NAME_PART = 1.4
_NAME_SUBSTRING = 1.0
_QUALIFIED_EXACT = 2.2
_QUALIFIED_PART = 1.0
_QUALIFIED_SUBSTRING = 0.7
_SIGNATURE_EXACT = 0.8
_SIGNATURE_PART = 0.7
_SIGNATURE_SUBSTRING = 0.6
_DOC_EXACT = 0.6
_DOC_PART = 0.5
_DOC_SUBSTRING = 0.4
_CENTRALITY_SYMBOL = 0.6
_CENTRALITY_FILE = 0.5
_SYMBOL_PROXIMITY = {1: 0.8, 2: 0.5, 3: 0.25, 4: 0.2}
_FILE_PROXIMITY = {1: 1.0, 2: 0.6, 3: 0.3, 4: 0.2}
_ENTRY_BONUS = 0.25
_MODULE_BONUS = 0.05
_FILE_ENTRY_BONUS = 0.2
_FILE_PACKAGE_BONUS = 0.1

_ENTRY_STEMS = frozenset({"main", "cli", "app", "server", "run", "index"})
_WORD = re.compile(r"[A-Za-z0-9_]+")
_PATH_LIKE = re.compile(r"[A-Za-z0-9_.\-/]+\.[A-Za-z0-9]+")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]+")
_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "from",
        "by",
        "at",
        "as",
        "is",
        "are",
        "be",
        "was",
        "were",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "we",
        "you",
        "our",
        "your",
        "how",
        "what",
        "where",
        "when",
        "which",
        "who",
        "why",
        "do",
        "does",
        "did",
        "can",
        "could",
        "should",
        "would",
        "will",
        "please",
        "me",
        "my",
        "about",
        "into",
        "over",
        "under",
    }
)


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One ranked search result row (SPEC §10 ``search.results``)."""

    path: str
    line: int
    symbol: str | None
    kind: str
    language: str
    score: float
    match: str


@dataclass(frozen=True, slots=True)
class RankedSymbol:
    """Internal scored symbol candidate; ``reasons`` are bounded evidence strings."""

    id: str
    path: str
    line: int
    name: str
    qualified_name: str
    kind: str
    language: str
    score: float
    matched: tuple[str, ...]
    proximity: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RankedFile:
    """Internal scored file candidate; ``matched`` lists the lexical field kinds."""

    path: str
    language: str
    score: float
    matched: tuple[str, ...]
    proximity: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RankResult:
    """Ranked candidates, highest score first, with explicit tie-breaking."""

    symbols: tuple[RankedSymbol, ...] = ()
    files: tuple[RankedFile, ...] = ()


# ---------------------------------------------------------------------------
# Query tokenization
# ---------------------------------------------------------------------------
def _word_parts(value: str) -> list[str]:
    """Split an identifier/path fragment into lower-case parts (snake + camel)."""

    parts: list[str] = []
    for chunk in _SPLIT.split(value):
        if not chunk:
            continue
        parts.append(chunk.lower())
        parts.extend(piece.lower() for piece in _CAMEL.split(chunk) if piece)
    return parts


def _query_term_weights(query: str) -> dict[str, float]:
    """Weighted query terms: typed words strong, derived fragments weak."""

    raw = bounded_text(str(query or ""), MAX_QUERY_CHARS)
    weights: dict[str, float] = {}
    path_spans = [match.span() for match in _PATH_LIKE.finditer(raw)]

    def add(term: str, weight: float) -> None:
        term = term.strip().lower()
        if not term or term in _STOPWORDS:
            return
        if weight > weights.get(term, 0.0):
            weights[term] = weight

    for match in _PATH_LIKE.finditer(raw):
        add(match.group(0), 1.0)
    for match in _WORD.finditer(raw):
        inside_path = any(
            start <= match.start() and match.end() <= end for start, end in path_spans
        )
        base = _TERM_PATH_FRAGMENT if inside_path else 1.0
        word = match.group(0)
        add(word, base)
        for part in _word_parts(word):
            add(part, base * _TERM_DERIVED)
    for run in _CJK.findall(raw):
        for char in run:
            add(char, 1.0)
    return weights


def query_terms(query: str) -> tuple[str, ...]:
    """Deterministic, de-duplicated query terms (lowercase, sorted)."""

    return tuple(sorted(_query_term_weights(query)))


# ---------------------------------------------------------------------------
# Lexical scoring
# ---------------------------------------------------------------------------
def _field_score(
    text: str,
    terms: tuple[str, ...],
    weights: dict[str, float],
    *,
    exact: float,
    part: float,
    substring: float,
    min_substring: int = 3,
) -> tuple[float, tuple[str, ...]]:
    """Best score for one field plus the terms that matched it."""

    if not text:
        return 0.0, ()
    lower = text.lower()
    parts = frozenset(_word_parts(text))
    best = 0.0
    matched: list[str] = []
    for term in terms:
        weight = weights.get(term, 0.0)
        score = 0.0
        if lower == term:
            score = exact * weight
        elif term in parts:
            score = part * weight
        elif (len(term) >= min_substring or not term.isascii()) and term in lower:
            score = substring * weight
        if score > 0:
            matched.append(term)
        if score > best:
            best = score
    return best, tuple(matched)


def _path_score(
    path: str, terms: tuple[str, ...], weights: dict[str, float]
) -> tuple[float, tuple[str, ...]]:
    """Lexical score of a repository-relative path and the terms that matched."""

    lower = path.lower()
    base = lower.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    parts = frozenset(_word_parts(lower.replace("/", "_")))
    best = 0.0
    matched: list[str] = []
    for term in terms:
        weight = weights.get(term, 0.0)
        score = 0.0
        if term in (lower, base, stem):
            score = _PATH_EXACT * weight
        elif "/" in term and (lower == term or lower.endswith("/" + term)):
            score = _PATH_EXACT * weight
        elif term in parts:
            score = _PATH_PART * weight
        elif (len(term) >= 3 or not term.isascii()) and term in lower:
            score = _PATH_SUBSTRING * weight
        if score > 0:
            matched.append(term)
        if score > best:
            best = score
    return best, tuple(matched)


def _symbol_lexical(
    symbol: SymbolRecord, terms: tuple[str, ...], weights: dict[str, float]
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    """Lexical score, matched field kinds and bounded reason strings for a symbol."""

    path_score, path_matched = _path_score(symbol.path, terms, weights)
    name_score, name_matched = _field_score(
        symbol.name, terms, weights, exact=_NAME_EXACT, part=_NAME_PART, substring=_NAME_SUBSTRING
    )
    if symbol.qualified_name and symbol.qualified_name != symbol.name:
        qualified_score, qualified_matched = _field_score(
            symbol.qualified_name,
            terms,
            weights,
            exact=_QUALIFIED_EXACT,
            part=_QUALIFIED_PART,
            substring=_QUALIFIED_SUBSTRING,
        )
    else:
        qualified_score, qualified_matched = 0.0, ()
    signature_score, signature_matched = _field_score(
        symbol.signature or "",
        terms,
        weights,
        exact=_SIGNATURE_EXACT,
        part=_SIGNATURE_PART,
        substring=_SIGNATURE_SUBSTRING,
    )
    doc_score, doc_matched = _field_score(
        symbol.doc or "",
        terms,
        weights,
        exact=_DOC_EXACT,
        part=_DOC_PART,
        substring=_DOC_SUBSTRING,
    )
    total = (
        path_score * 0.8
        + name_score
        + qualified_score * 0.6
        + signature_score * 0.7
        + doc_score * 0.5
    )
    fields = (
        ("path", path_score, path_matched),
        ("name", name_score, name_matched),
        ("qualifiedName", qualified_score, qualified_matched),
        ("signature", signature_score, signature_matched),
        ("doc", doc_score, doc_matched),
    )
    matched = tuple(kind for kind, score, _ in fields if score > 0)
    reasons = tuple(
        f"lexical {kind}: {_clip(field_terms[0])}"
        for kind, score, field_terms in fields
        if score > 0 and field_terms
    )
    return total, matched, reasons


def _file_lexical(
    file_path: str, terms: tuple[str, ...], weights: dict[str, float]
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    path_score, matched = _path_score(file_path, terms, weights)
    if path_score <= 0:
        return 0.0, (), ()
    return path_score, ("path",), (f"lexical path: {_clip(matched[0])}",)


def _clip(text: str) -> str:
    return bounded_text(str(text), MAX_REASON_CHARS // 2)


# ---------------------------------------------------------------------------
# Structural signals: centrality + proximity + entry points
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _ScoringContext:
    terms: tuple[str, ...]
    weights: dict[str, float]
    named_paths: tuple[str, ...]
    proximity: dict[str, int]
    symbol_indegree: dict[str, int]
    file_indegree: dict[str, int]
    max_symbol_indegree: int
    max_file_indegree: int
    entry_symbol_ids: frozenset[str]


def _in_degrees(
    snapshot: IndexSnapshot,
) -> tuple[dict[str, int], dict[str, int], int, int]:
    """Resolved in-degree counters for symbols and files, plus their maxima."""

    symbol_indegree: dict[str, int] = {}
    file_indegree: dict[str, int] = {}
    for relation in snapshot.relations:
        if relation.status is not ResolutionStatus.RESOLVED or not relation.target_id:
            continue
        target = relation.target_id
        if target.startswith("sym:"):
            symbol_indegree[target] = symbol_indegree.get(target, 0) + 1
        elif target.startswith("file:") and relation.relation_type is RelationType.IMPORTS:
            path = target[len("file:") :]
            file_indegree[path] = file_indegree.get(path, 0) + 1
    symbol_max = max(symbol_indegree.values(), default=0)
    file_max = max(file_indegree.values(), default=0)
    return symbol_indegree, file_indegree, symbol_max, file_max


def _term_names_path(term: str, path: str) -> bool:
    """True when a query token is an actual path, filename or dotted module name.

    Plain keywords like ``core`` must not be treated as named paths: proximity is
    only claimed for paths/files/modules the task really mentions.
    """

    term = term.strip("/").lower()
    if not term:
        return False
    lower = path.lower()
    base = lower.rsplit("/", 1)[-1]
    if term == lower or term == base:
        return True
    if "/" in term:
        return lower == term or lower.endswith("/" + term)
    if "." in term:
        dotted = term.replace(".", "/")
        if lower == dotted + ".py" or lower.endswith("/" + dotted + ".py"):
            return True
        if lower.endswith("/" + dotted + "/__init__.py"):
            return True
    return False


def _named_paths(
    snapshot: IndexSnapshot,
    terms: tuple[str, ...],
    weights: dict[str, float],
    query_lower: str,
) -> tuple[str, ...]:
    """Repository files explicitly named in the query as a path/filename/module."""

    strong_path_terms = [
        term
        for term in terms
        if weights.get(term, 0.0) >= 0.9 and ("/" in term or "." in term)
    ]
    named: list[str] = []
    for file in sorted(snapshot.files, key=lambda item: item.path):
        lower = file.path.lower()
        if lower in query_lower or any(
            _term_names_path(term, file.path) for term in strong_path_terms
        ):
            named.append(file.path)
        if len(named) >= MAX_NAMED_PATHS:
            break
    return tuple(named)


def _graph_neighbors(graph: Any, path: str) -> tuple[str, ...]:
    """Undirected import neighbors from the documented Graph API (never raises)."""

    neighbors: set[str] = set()
    for method_name in ("file_imports", "file_dependents"):
        method = getattr(graph, method_name, None)
        if not callable(method):
            continue
        try:
            values = method(path)
        except Exception:  # noqa: BLE001 - a broken graph must never break ranking
            continue
        for value in values or ():
            if isinstance(value, str) and value:
                neighbors.add(value)
    return tuple(sorted(neighbors)[:MAX_NEIGHBORS])


def _proximity_stages(
    snapshot: IndexSnapshot, graph: Any, named_paths: tuple[str, ...]
) -> dict[str, int]:
    """Import-distance stages: 1 = named, 2 = one hop, 3 = two hops, 4 = same dir."""

    known = {file.path for file in snapshot.files}
    stages: dict[str, int] = {path: 1 for path in named_paths if path in known}
    frontier = sorted(path for path in named_paths if path in known)
    for level, stage in ((1, 2), (2, 3)):
        next_frontier: list[str] = []
        for path in frontier[:MAX_PROXIMITY_FRONTIER]:
            for neighbor in _graph_neighbors(graph, path):
                if neighbor in known and neighbor not in stages:
                    stages[neighbor] = stage
                    next_frontier.append(neighbor)
        frontier = sorted(set(next_frontier))
        if not frontier:
            break
    directories = {path.rsplit("/", 1)[0] for path in named_paths if "/" in path}
    for file in sorted(snapshot.files, key=lambda item: item.path):
        if file.path in stages:
            continue
        directory = file.path.rsplit("/", 1)[0] if "/" in file.path else ""
        if directory in directories:
            stages[file.path] = 4
    return stages


def _scoring_context(snapshot: IndexSnapshot, graph: Any, query: str) -> _ScoringContext:
    weights = _query_term_weights(query)
    terms = tuple(sorted(weights))
    query_lower = bounded_text(str(query or ""), MAX_QUERY_CHARS).lower()
    named = _named_paths(snapshot, terms, weights, query_lower)
    symbol_indegree, file_indegree, symbol_max, file_max = _in_degrees(snapshot)
    return _ScoringContext(
        terms=terms,
        weights=weights,
        named_paths=named,
        proximity=_proximity_stages(snapshot, graph, named),
        symbol_indegree=symbol_indegree,
        file_indegree=file_indegree,
        max_symbol_indegree=symbol_max,
        max_file_indegree=file_max,
        entry_symbol_ids=frozenset(symbol.id for symbol in snapshot.entry_points()),
    )


def _symbol_structural(
    symbol: SymbolRecord, context: _ScoringContext
) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    reasons: list[str] = []
    degree = context.symbol_indegree.get(symbol.id, 0)
    if degree > 0 and context.max_symbol_indegree > 0:
        score += _CENTRALITY_SYMBOL * (degree / context.max_symbol_indegree)
        reasons.append(f"centrality: {degree} resolved incoming")
    stage = context.proximity.get(symbol.path, 0)
    if stage:
        score += _SYMBOL_PROXIMITY.get(stage, 0.0)
        reasons.append(_proximity_reason(stage))
    if symbol.id in context.entry_symbol_ids:
        score += _ENTRY_BONUS
        reasons.append("entry point")
    if symbol.kind is SymbolKind.MODULE:
        score += _MODULE_BONUS
        reasons.append("module symbol")
    return score, tuple(reasons)


def _file_structural(file_path: str, context: _ScoringContext) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    reasons: list[str] = []
    degree = context.file_indegree.get(file_path, 0)
    if degree > 0 and context.max_file_indegree > 0:
        score += _CENTRALITY_FILE * (degree / context.max_file_indegree)
        reasons.append(f"centrality: imported by {degree} file(s)")
    stage = context.proximity.get(file_path, 0)
    if stage:
        score += _FILE_PROXIMITY.get(stage, 0.0)
        reasons.append(_proximity_reason(stage))
    base = file_path.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    if stem in _ENTRY_STEMS:
        score += _FILE_ENTRY_BONUS
        reasons.append("likely entry module")
    elif base == "__init__.py":
        score += _FILE_PACKAGE_BONUS
        reasons.append("package module")
    return score, tuple(reasons)


def _proximity_reason(stage: int) -> str:
    if stage == 1:
        return "proximity: path named in task"
    if stage == 2:
        return "proximity: direct dependency neighbor of named path"
    if stage == 3:
        return "proximity: two-hop dependency neighbor of named path"
    return "proximity: same directory as named path"


def _bounded_reasons(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    reasons: list[str] = []
    for value in values:
        text = bounded_text(str(value), MAX_REASON_CHARS)
        if text and text not in reasons:
            reasons.append(text)
        if len(reasons) >= MAX_REASONS:
            break
    return tuple(reasons)


# ---------------------------------------------------------------------------
# Public ranking + search
# ---------------------------------------------------------------------------
def rank(
    snapshot: IndexSnapshot,
    graph: Any,
    query: str,
    *,
    limit: int | None = None,
) -> RankResult:
    """Rank files and symbols for *query*; only relevant candidates are returned."""

    text = str(query or "").strip()
    if not text:
        return RankResult()
    context = _scoring_context(snapshot, graph, text)
    if not context.terms:
        return RankResult()

    symbols: list[RankedSymbol] = []
    for symbol in sorted(
        snapshot.symbols,
        key=lambda item: (item.path, item.span.start_line, item.kind.value, item.qualified_name),
    ):
        lexical, matched, lexical_reasons = _symbol_lexical(symbol, context.terms, context.weights)
        structural, structural_reasons = _symbol_structural(symbol, context)
        proximity = context.proximity.get(symbol.path, 0)
        if lexical <= 0 and proximity == 0:
            continue
        score = round(lexical + structural, 4)
        if score <= 0:
            continue
        symbols.append(
            RankedSymbol(
                id=symbol.id,
                path=symbol.path,
                line=symbol.span.start_line,
                name=symbol.name,
                qualified_name=symbol.qualified_name,
                kind=symbol.kind.value,
                language=symbol.language.value,
                score=score,
                matched=matched,
                proximity=proximity,
                reasons=_bounded_reasons((*lexical_reasons, *structural_reasons)),
            )
        )

    files: list[RankedFile] = []
    for file in sorted(snapshot.files, key=lambda item: item.path):
        lexical, matched, lexical_reasons = _file_lexical(file.path, context.terms, context.weights)
        structural, structural_reasons = _file_structural(file.path, context)
        proximity = context.proximity.get(file.path, 0)
        if lexical <= 0 and proximity == 0:
            continue
        score = round(lexical + structural, 4)
        if score <= 0:
            continue
        files.append(
            RankedFile(
                path=file.path,
                language=file.language.value,
                score=score,
                matched=matched,
                proximity=proximity,
                reasons=_bounded_reasons((*lexical_reasons, *structural_reasons)),
            )
        )

    symbols.sort(key=lambda item: (-item.score, item.path, item.line, item.qualified_name, item.id))
    files.sort(key=lambda item: (-item.score, item.path))
    if limit is not None:
        capped = max(1, min(int(limit), MAX_LIMIT))
        symbols = symbols[:capped]
        files = files[:capped]
    return RankResult(symbols=tuple(symbols), files=tuple(files))


def search(
    snapshot: IndexSnapshot,
    graph: Any,
    query: str,
    *,
    limit: int = 20,
) -> tuple[SearchHit, ...]:
    """Lexical search over files/symbols with structural boosts (SPEC §9)."""

    capped = max(1, min(int(limit), MAX_LIMIT))
    result = rank(snapshot, graph, query)
    hits: list[SearchHit] = []
    covered_paths: set[str] = set()
    for ranked_symbol in result.symbols:
        if not ranked_symbol.matched:
            continue
        hits.append(
            SearchHit(
                path=ranked_symbol.path,
                line=ranked_symbol.line,
                symbol=ranked_symbol.qualified_name,
                kind=ranked_symbol.kind,
                language=ranked_symbol.language,
                score=ranked_symbol.score,
                match=",".join(ranked_symbol.matched),
            )
        )
        covered_paths.add(ranked_symbol.path)
    for ranked_file in result.files:
        if not ranked_file.matched or ranked_file.path in covered_paths:
            continue
        hits.append(
            SearchHit(
                path=ranked_file.path,
                line=1,
                symbol=None,
                kind="file",
                language=ranked_file.language,
                score=ranked_file.score,
                match=",".join(ranked_file.matched),
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.path, hit.line, hit.kind, hit.symbol or ""))
    return tuple(hits[:capped])


def file_import_neighbors(graph: Any, path: str) -> tuple[str, ...]:
    """Public helper used by reporting to walk imports without importing Graph."""

    return _graph_neighbors(graph, path)


__all__ = [
    "MAX_LIMIT",
    "RankResult",
    "RankedFile",
    "RankedSymbol",
    "SearchHit",
    "file_import_neighbors",
    "query_terms",
    "rank",
    "search",
]
