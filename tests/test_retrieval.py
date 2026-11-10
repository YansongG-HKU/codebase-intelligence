"""Tests for retrieval: ranking, search and budgeted context packs (SPEC §4/§9).

Everything here builds :class:`IndexSnapshot` objects directly from a small
fixture index (``tests/fixtures/retrieval/snapshot.json``) and a local fake graph,
so the suite is green independently of the scanner/parser/graph modules that are
being written in parallel.  Context excerpts read the fixture sources from
``tests/fixtures/retrieval/repo`` — the same files the fixture index describes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from codebase_intelligence.errors import UsageError
from codebase_intelligence.model import (
    EvidenceKind,
    FileRecord,
    IndexSnapshot,
    Language,
    RelationRecord,
    RelationType,
    ResolutionStatus,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
    symbol_id,
)
from codebase_intelligence.retrieval import (
    ContextItem,
    ContextPack,
    build_context,
    context_payload_dict,
    estimate_tokens,
    fit_context,
    fit_rows,
    measured_tokens,
    rank,
    search,
)
from codebase_intelligence.retrieval.budget import (
    MAX_TOOL_TOKENS,
    MIN_MAX_TOKENS,
    clamp_max_tokens,
)
from codebase_intelligence.retrieval.context import MAX_EXCERPT_LINES
from codebase_intelligence.retrieval.paths import is_under_prefix, normalize_repo_prefix
from codebase_intelligence.retrieval.rank import query_terms
from codebase_intelligence.util import canonical_json, estimate_tokens as util_estimate_tokens

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "retrieval"
REPO = FIXTURES / "repo"
SNAPSHOT_JSON = FIXTURES / "snapshot.json"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------
def load_snapshot() -> IndexSnapshot:
    data = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
    return IndexSnapshot.from_public_dict(data, root=str(REPO))


class FakeGraph:
    """Tiny stand-in for ``codebase_intelligence.graph.Graph`` (documented API only)."""

    def __init__(self, snapshot: IndexSnapshot | None = None) -> None:
        self.snapshot = snapshot
        self.imports: dict[str, tuple[str, ...]] = {
            "src/app/cli.py": ("src/app/core.py",),
            "tools/build.py": ("src/app/core.py",),
        }
        self.dependents: dict[str, tuple[str, ...]] = {
            "src/app/core.py": ("src/app/cli.py", "tools/build.py"),
        }

    def file_imports(self, path: str) -> tuple[str, ...]:
        return tuple(self.imports.get(path, ()))

    def file_dependents(self, path: str) -> tuple[str, ...]:
        return tuple(self.dependents.get(path, ()))

    def transitive_dependents(self, path: str, *, max_depth: int = 10) -> tuple[tuple[str, int], ...]:
        seen: dict[str, int] = {}
        frontier = [path]
        for depth in range(1, max_depth + 1):
            following: list[str] = []
            for item in frontier:
                for dependent in self.file_dependents(item):
                    if dependent not in seen:
                        seen[dependent] = depth
                        following.append(dependent)
            frontier = following
            if not frontier:
                break
        return tuple(sorted(seen.items()))


class BrokenGraph:
    """Graph stand-in whose methods raise: ranking must degrade, not crash."""

    def file_imports(self, path: str) -> tuple[str, ...]:
        raise ValueError("boom")

    def file_dependents(self, path: str) -> tuple[str, ...]:
        raise TypeError("boom")


def record(path: str, *, language: Language = Language.PYTHON, lines: int = 10) -> FileRecord:
    return FileRecord(
        path=path,
        language=language,
        size_bytes=lines * 20,
        sha256="0" * 64,
        line_count=lines,
    )


def symbol(
    path: str,
    name: str,
    *,
    qualified: str | None = None,
    kind: SymbolKind = SymbolKind.FUNCTION,
    start: int = 1,
    end: int | None = None,
) -> SymbolRecord:
    qualified_name = qualified if qualified is not None else name
    return SymbolRecord(
        id=symbol_id(path, kind, qualified_name, start),
        path=path,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        language=Language.PYTHON,
        span=SourceSpan(path=path, start_line=start, end_line=end if end is not None else start),
        signature=f"{kind.value} {qualified_name}",
        doc=None,
    )


def relation(
    source: SymbolRecord | str,
    target: SymbolRecord | str | None,
    *,
    relation_type: RelationType = RelationType.REFERENCES,
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    evidence: EvidenceKind = EvidenceKind.PARSER,
    target_name: str | None = None,
) -> RelationRecord:
    source_id = source.id if isinstance(source, SymbolRecord) else source
    target_id = target.id if isinstance(target, SymbolRecord) else target
    return RelationRecord(
        source_id=source_id,
        relation_type=relation_type,
        status=status,
        evidence=evidence,
        target_id=target_id,
        target_name=target_name,
        confidence=0.9 if status is ResolutionStatus.RESOLVED else 0.0,
    )


def make_snapshot(
    *files: FileRecord,
    symbols: tuple[SymbolRecord, ...] = (),
    relations: tuple[RelationRecord, ...] = (),
    root: str = "",
) -> IndexSnapshot:
    return IndexSnapshot.build(
        engine_version="test-engine",
        policy_fingerprint="test-policy",
        root=root,
        files=files,
        symbols=symbols,
        relations=relations,
    )


def citations_are_valid(snapshot: IndexSnapshot, item: ContextItem) -> bool:
    file_count = next(
        (file.line_count for file in snapshot.files if file.path == item.path), 0
    )
    return 1 <= item.start_line <= item.end_line <= max(1, file_count)


# ---------------------------------------------------------------------------
# budget.py
# ---------------------------------------------------------------------------
def test_fit_rows_keeps_whole_prefix_and_counts_omissions() -> None:
    rows = [{"id": f"row-{index}", "text": "x" * 24} for index in range(12)]

    def measure(chunk: list[dict[str, str]]) -> int:
        return measured_tokens({"rows": list(chunk)})

    kept, omitted = fit_rows(rows, measure, 120)
    assert 0 < len(kept) < len(rows)
    assert kept == rows[: len(kept)]
    assert omitted == len(rows) - len(kept)
    assert measure(kept) <= 120
    assert measure([*kept, rows[len(kept)]]) > 120


def test_fit_rows_never_splits_a_row_and_handles_overhead_only_overflow() -> None:
    rows = [{"blob": "y" * 400}]

    def measure(chunk: list[dict[str, str]]) -> int:
        return measured_tokens({"rows": list(chunk)})

    kept, omitted = fit_rows(rows, measure, 64)
    assert kept == []
    assert omitted == 1


def test_fit_rows_with_empty_rows_is_empty() -> None:
    kept, omitted = fit_rows([], measured_tokens, 100)
    assert kept == []
    assert omitted == 0


def test_estimate_tokens_reexport_matches_util() -> None:
    assert estimate_tokens is util_estimate_tokens
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_tokens("上下文") == 3


def test_clamp_max_tokens_bounds() -> None:
    assert clamp_max_tokens(200) == 200
    assert clamp_max_tokens(1) == MIN_MAX_TOKENS
    assert clamp_max_tokens(0) == MIN_MAX_TOKENS
    assert clamp_max_tokens(-5) == MIN_MAX_TOKENS
    assert clamp_max_tokens(10**9) == MAX_TOOL_TOKENS
    assert clamp_max_tokens(None) == MAX_TOOL_TOKENS


def test_measured_tokens_uses_canonical_json() -> None:
    payload = {"b": 1, "a": [2, 3]}
    assert measured_tokens(payload) == estimate_tokens(canonical_json(payload))


# ---------------------------------------------------------------------------
# rank.py / search()
# ---------------------------------------------------------------------------
def test_query_terms_split_identifiers_and_drop_stopwords() -> None:
    terms = query_terms("How does build_context parse HTTPRequest tokens?")
    assert "build" in terms
    assert "context" in terms
    assert "http" in terms
    assert "request" in terms
    assert "tokens" in terms
    assert "how" not in terms
    assert "does" not in terms
    assert len(terms) == len(set(terms))


def test_search_matches_symbol_name_with_location_and_language() -> None:
    snapshot = load_snapshot()
    hits = search(snapshot, FakeGraph(snapshot), "build_context")
    assert hits
    top = hits[0]
    assert top.path == "src/app/core.py"
    assert top.line == 11
    assert top.symbol == "build_context"
    assert top.kind == "function"
    assert top.language == "python"
    assert top.score == round(top.score, 4)
    assert "name" in top.match


def test_search_matches_path_and_returns_file_kind() -> None:
    snapshot = load_snapshot()
    hits = search(snapshot, FakeGraph(snapshot), "docs/guide.md")
    assert hits
    assert hits[0].path == "docs/guide.md"
    assert hits[0].line == 1
    assert hits[0].symbol is None
    assert hits[0].kind == "file"
    assert "path" in hits[0].match


def test_search_cjk_query_matches_docstring() -> None:
    snapshot = load_snapshot()
    hits = search(snapshot, FakeGraph(snapshot), "上下文")
    assert hits
    assert any(hit.path == "src/app/core.py" and hit.line == 11 for hit in hits)
    assert "doc" in hits[0].match


def test_search_empty_query_returns_no_hits() -> None:
    snapshot = load_snapshot()
    assert search(snapshot, FakeGraph(snapshot), "") == ()
    assert search(snapshot, FakeGraph(snapshot), "   ") == ()


def test_search_respects_limit_and_is_deterministic() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    first = search(snapshot, graph, "context", limit=2)
    second = search(snapshot, graph, "context", limit=2)
    assert len(first) == 2
    assert first == second


def test_rank_centrality_boosts_referenced_symbol() -> None:
    file_a = record("pkg/a.py")
    file_b = record("pkg/b.py")
    handler_a = symbol("pkg/a.py", "handler", start=3, end=5)
    handler_b = symbol("pkg/b.py", "handler", start=3, end=5)
    callers = (
        relation("sym:pkg/a.py#function:caller@1", handler_a),
        relation("sym:pkg/a.py#function:caller2@1", handler_a),
    )
    snapshot = make_snapshot(
        file_a,
        file_b,
        symbols=(handler_a, handler_b, symbol("pkg/a.py", "caller"), symbol("pkg/a.py", "caller2")),
        relations=callers,
    )
    ranked = rank(snapshot, FakeGraph(snapshot), "handler")
    by_id = {item.id: item for item in ranked.symbols}
    assert by_id[handler_a.id].score > by_id[handler_b.id].score
    assert any("centrality" in reason for reason in by_id[handler_a.id].reasons)


def test_rank_proximity_follows_named_paths() -> None:
    snapshot = load_snapshot()
    result = rank(snapshot, FakeGraph(snapshot), "src/app/cli.py")
    files = {item.path: item for item in result.files}
    assert files["src/app/cli.py"].proximity == 1
    assert files["src/app/core.py"].proximity == 2
    assert any("proximity" in reason for reason in files["src/app/core.py"].reasons)
    assert files["src/app/model.py"].proximity == 4


def test_rank_plain_keywords_do_not_seed_proximity() -> None:
    snapshot = load_snapshot()
    result = rank(snapshot, FakeGraph(snapshot), "context build helpers")
    assert result.files and result.symbols
    assert all(item.proximity == 0 for item in result.files)
    assert all(item.proximity == 0 for item in result.symbols)
    assert all("named path" not in reason for item in result.files for reason in item.reasons)


def test_rank_dotted_module_path_seeds_proximity() -> None:
    snapshot = load_snapshot()
    result = rank(snapshot, FakeGraph(snapshot), "app.core")
    files = {item.path: item for item in result.files}
    assert files["src/app/core.py"].proximity == 1
    assert files["src/app/cli.py"].proximity == 2
    assert files["tools/build.py"].proximity == 2
    assert any("path named in task" in reason for reason in files["src/app/core.py"].reasons)


def test_context_reasons_never_claim_a_named_path_without_one() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "bounded context pack")
    assert pack.items
    assert all("named path" not in item.reason for item in pack.items)
    assert all("proximity" not in item.reason for item in pack.items)


def test_context_proximity_reason_requires_an_explicit_path() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "adjust build_context in src/app/cli.py")
    assert pack.items
    cli_items = [item for item in pack.items if item.path == "src/app/cli.py"]
    assert cli_items
    assert any("proximity: path named in task" in item.reason for item in cli_items)


def test_rank_scores_rounded_and_reasons_bounded() -> None:
    snapshot = load_snapshot()
    result = rank(snapshot, FakeGraph(snapshot), "context pack build")
    assert result.symbols and result.files
    for ranked_symbol in result.symbols:
        assert ranked_symbol.score == round(ranked_symbol.score, 4)
        assert 0 < len(ranked_symbol.reasons) <= 4
        assert all(len(reason) <= 96 for reason in ranked_symbol.reasons)
    for ranked_file in result.files:
        assert ranked_file.score == round(ranked_file.score, 4)
        assert all(len(reason) <= 96 for reason in ranked_file.reasons)


def test_rank_empty_query_and_none_graph_degrade_gracefully() -> None:
    snapshot = load_snapshot()
    assert rank(snapshot, None, "") == rank(snapshot, None, "")
    hits = search(snapshot, None, "build_context")
    assert hits
    assert hits[0].symbol == "build_context"


def test_rank_ignores_graph_errors() -> None:
    snapshot = load_snapshot()
    hits = search(snapshot, BrokenGraph(), "build_context")
    assert hits
    assert hits[0].path == "src/app/core.py"


# ---------------------------------------------------------------------------
# context.py
# ---------------------------------------------------------------------------
def test_build_context_citations_point_at_real_source_lines() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "build a bounded context pack")
    assert pack.items
    for item in pack.items:
        assert citations_are_valid(snapshot, item)
        source = (REPO / item.path).read_text(encoding="utf-8").splitlines()
        expected = "\n".join(source[item.start_line - 1 : item.end_line])
        assert item.excerpt == expected
        assert item.excerpt.split("\n")[0].strip()
        assert item.tokens_estimated == estimate_tokens(item.excerpt)
        assert item.reason


def test_build_context_prefers_the_definition_for_the_task() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "build a bounded context pack")
    assert pack.items
    first = pack.items[0]
    assert first.path == "src/app/core.py"
    assert (first.start_line, first.end_line) == (11, 14)
    assert "def build_context" in first.excerpt
    assert first.kind == "function"
    assert first.symbol == "build_context"


def test_build_context_enforces_excerpt_line_cap(tmp_path: Path) -> None:
    source = tmp_path / "pkg" / "big.py"
    source.parent.mkdir(parents=True)
    lines = ["def parse_target():"] + ["    value = 1"] * 299
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    target = symbol("pkg/big.py", "parse_target", start=1, end=300)
    snapshot = make_snapshot(
        record("pkg/big.py", lines=300), symbols=(target,), root=str(tmp_path)
    )
    pack = build_context(snapshot, None, "parse_target")
    assert pack.items
    item = pack.items[0]
    assert item.path == "pkg/big.py"
    assert item.end_line - item.start_line + 1 <= MAX_EXCERPT_LINES
    assert item.excerpt.split("\n")[0] == "def parse_target():"


@pytest.mark.parametrize("budget", [200, 500, 1200, 2200])
def test_build_context_payload_respects_budget(budget: int) -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "bounded context pack", max_tokens=budget)
    payload = context_payload_dict(snapshot, pack, max_tokens=budget)
    json.loads(canonical_json(payload))
    assert payload["budgets"]["maxTokens"] == budget
    assert payload["budgets"]["tokenEstimator"] == "chars4-wide-v1"
    assert payload["budgets"]["tokensEstimated"] == measured_tokens(payload)
    assert measured_tokens(payload) <= budget
    assert pack.tokens_estimated == payload["budgets"]["tokensEstimated"]


def test_build_context_small_budget_keeps_top_item_and_reports_omissions() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "bounded context pack", max_tokens=200)
    payload = context_payload_dict(snapshot, pack, max_tokens=200)
    assert payload["truncated"] is True
    assert measured_tokens(payload) <= 200
    assert 1 == len(payload["items"])
    assert payload["items"][0]["path"] == "src/app/core.py"
    assert payload["omitted"]
    assert all("path" in row and "reason" in row for row in payload["omitted"])
    assert "budget" in {row["reason"] for row in payload["omitted"]}


def test_build_context_omitted_paths_are_unique_and_ordered() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "context", max_tokens=200)
    assert len(pack.omitted) == len(set(pack.omitted))
    assert pack.omitted == tuple(pack.omitted)
    assert [omission.path for omission in pack.omissions] == list(pack.omitted)


def test_build_context_path_prefix_filters_candidates() -> None:
    snapshot = load_snapshot()
    pack = build_context(
        snapshot,
        FakeGraph(snapshot),
        "build a bounded context pack",
        path_prefix="src/app/model.py",
    )
    assert pack.items
    assert all(item.path == "src/app/model.py" for item in pack.items)
    for item in pack.items:
        assert is_under_prefix(item.path, "src/app/model.py")


def test_build_context_invalid_path_prefix_is_rejected() -> None:
    snapshot = load_snapshot()
    for prefix in ("../etc", "/absolute", "C:/Windows", "src/../secret"):
        with pytest.raises(UsageError):
            build_context(snapshot, FakeGraph(snapshot), "context", path_prefix=prefix)


def test_build_context_is_deterministic() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    first = build_context(snapshot, graph, "context pack ranking", max_tokens=500)
    second = build_context(snapshot, graph, "context pack ranking", max_tokens=500)
    assert first == second
    left = context_payload_dict(snapshot, first, max_tokens=500)
    right = context_payload_dict(snapshot, second, max_tokens=500)
    assert canonical_json(left) == canonical_json(right)


def test_build_context_records_missing_source_files() -> None:
    base = load_snapshot()
    ghost = symbol("src/app/ghost.py", "ghost_helper", start=1, end=2)
    snapshot = make_snapshot(
        *base.files,
        record("src/app/ghost.py"),
        symbols=(*base.symbols, ghost),
        relations=base.relations,
        root=str(REPO),
    )
    pack = build_context(snapshot, FakeGraph(snapshot), "ghost_helper")
    assert "src/app/ghost.py" in pack.omitted
    reasons = {omission.path: omission.reason for omission in pack.omissions}
    assert reasons["src/app/ghost.py"] == "source unavailable"
    assert all(item.path != "src/app/ghost.py" for item in pack.items)


def test_build_context_empty_task_returns_empty_pack() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "   ")
    assert pack.items == ()
    assert pack.omitted == ()
    assert pack.task == ""
    payload = context_payload_dict(snapshot, pack)
    assert payload["items"] == []
    assert measured_tokens(payload) <= payload["budgets"]["maxTokens"]


def test_build_context_never_emits_the_absolute_root() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "context")
    payload = context_payload_dict(snapshot, pack)
    assert str(REPO) not in canonical_json(payload)
    assert any(item["path"] for item in payload["items"])


def test_context_payload_can_rebudget_a_larger_pack() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "bounded context pack", max_tokens=2200)
    rebuilt = context_payload_dict(snapshot, pack, max_tokens=160)
    assert len(rebuilt["items"]) < len(pack.items)
    assert rebuilt["truncated"] is True
    assert rebuilt["omitted"]
    assert measured_tokens(rebuilt) <= 160


def test_context_pack_tokens_match_rendered_payload() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "bounded context pack")
    payload = context_payload_dict(snapshot, pack)
    assert pack.tokens_estimated == payload["budgets"]["tokensEstimated"]
    assert pack.token_estimator == payload["budgets"]["tokenEstimator"] == "chars4-wide-v1"


def test_fit_context_with_no_items_is_minimal() -> None:
    snapshot = load_snapshot()
    payload, kept, omissions = fit_context(snapshot, "task", (), (), max_tokens=200)
    assert kept == ()
    assert omissions == ()
    assert payload["items"] == []
    assert payload["omitted"] == []
    assert payload["truncated"] is False


def test_normalize_repo_prefix_and_is_under_prefix() -> None:
    assert normalize_repo_prefix(None) is None
    assert normalize_repo_prefix("") is None
    assert normalize_repo_prefix(".") is None
    assert normalize_repo_prefix("./src/app/") == "src/app"
    assert normalize_repo_prefix("src\\app") == "src/app"
    with pytest.raises(UsageError):
        normalize_repo_prefix("../outside")
    with pytest.raises(UsageError):
        normalize_repo_prefix("/etc")
    assert is_under_prefix("src/app/core.py", "src/app")
    assert not is_under_prefix("src/appx/core.py", "src/app")
    assert is_under_prefix("anything", None)


@dataclass(frozen=True)
class _MiniPack:
    """Contract check: the public dataclasses stay constructible as documented."""

    task: str
    items: tuple[ContextItem, ...]
    omitted: tuple[str, ...]
    tokens_estimated: int
    token_estimator: str


def test_context_dataclasses_expose_contract_fields() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "context") if snapshot.files else None
    assert isinstance(pack, ContextPack)
    assert pack is not None
    mini = _MiniPack(
        task=pack.task,
        items=pack.items,
        omitted=pack.omitted,
        tokens_estimated=pack.tokens_estimated,
        token_estimator=pack.token_estimator,
    )
    assert mini.omitted == pack.omitted
    assert isinstance(ContextPack("task", (), (), 0, "chars4-wide-v1"), ContextPack)
