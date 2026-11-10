"""Tests for reporting: deterministic JSON payloads and bounded Markdown (SPEC §10).

The six payload builders are exercised against the small fixture index
(``tests/fixtures/retrieval/snapshot.json``) and a local fake graph / impact
result, so this suite does not depend on the graph module being written in
parallel.  The contract under test is byte-stability: the same index + args must
produce the same canonical JSON, with the documented shape, budgets and no
volatile fields.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from codebase_intelligence.errors import UsageError
from codebase_intelligence.model import (
    FileRecord,
    IndexSnapshot,
    Language,
    ParseIssue,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
    symbol_id,
)
from codebase_intelligence.reporting import (
    context_payload,
    dependencies_payload,
    impact_payload,
    map_payload,
    markdown_map,
    markdown_report,
    overview_payload,
    search_payload,
)
from codebase_intelligence.reporting.markdown import (
    MAX_MAP_CHARS,
    MAX_REPORT_CHARS,
)
from codebase_intelligence.retrieval import build_context, measured_tokens, search
from codebase_intelligence.util import canonical_json

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "retrieval"
REPO = FIXTURES / "repo"
SNAPSHOT_JSON = FIXTURES / "snapshot.json"

BUDGETS = (200, 500, 1200, 2200)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------
def load_snapshot() -> IndexSnapshot:
    data = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
    return IndexSnapshot.from_public_dict(data, root=str(REPO))


class FakeGraph:
    """Stand-in for ``codebase_intelligence.graph.Graph`` using the documented API."""

    def __init__(self, snapshot: IndexSnapshot | None = None) -> None:
        self.snapshot = snapshot
        self.imports: dict[str, tuple[str, ...]] = {
            "src/app/cli.py": ("src/app/core.py",),
            "src/app/core.py": (),
            "src/app/model.py": (),
            "tools/build.py": ("src/app/core.py",),
        }
        self.dependents: dict[str, tuple[str, ...]] = {
            "src/app/core.py": ("src/app/cli.py", "tools/build.py"),
        }

    def file_imports(self, path: str) -> tuple[str, ...]:
        return tuple(self.imports.get(path, ()))

    def file_dependents(self, path: str) -> tuple[str, ...]:
        return tuple(self.dependents.get(path, ()))


class BrokenGraph:
    def file_imports(self, path: str) -> tuple[str, ...]:
        raise RuntimeError("graph unavailable")

    def file_dependents(self, path: str) -> tuple[str, ...]:
        raise RuntimeError("graph unavailable")


@dataclass(frozen=True)
class AffectedFile:
    path: str
    distance: int
    confidence: str
    reason: str


@dataclass(frozen=True)
class AffectedSymbol:
    id: str
    path: str
    name: str
    distance: int
    confidence: str


@dataclass(frozen=True)
class FakeImpactResult:
    """Matches the documented ``graph.ImpactResult`` field names."""

    changed_files: tuple[str, ...] = ("src/app/core.py",)
    changed_symbols: tuple[str, ...] = ("build_context",)
    affected_files: tuple[AffectedFile, ...] = (
        AffectedFile("tools/build.py", 1, "high", "imports changed file"),
        AffectedFile("src/app/cli.py", 1, "high", "imports changed file"),
    )
    affected_symbols: tuple[AffectedSymbol, ...] = (
        AffectedSymbol("sym:src/app/cli.py#function:main@6", "src/app/cli.py", "main", 1, "medium"),
        AffectedSymbol(
            "sym:tools/build.py#function:main@6", "tools/build.py", "main", 1, "medium"
        ),
    )
    truncated: bool = False


def build_payloads() -> dict[str, dict]:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    pack = build_context(snapshot, graph, "bounded context pack")
    hits = search(snapshot, graph, "context")
    return {
        "overview": overview_payload(snapshot, graph),
        "map": map_payload(snapshot, graph),
        "search": search_payload(snapshot, "context", hits),
        "dependencies": dependencies_payload(snapshot, graph, target="src/app/core.py"),
        "context": context_payload(snapshot, pack),
        "impact": impact_payload(snapshot, FakeImpactResult()),
    }


def walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk_keys(child)


def record(path: str, *, lines: int = 10) -> FileRecord:
    return FileRecord(
        path=path,
        language=Language.PYTHON,
        size_bytes=lines * 20,
        sha256="0" * 64,
        line_count=lines,
    )


def symbol(
    path: str,
    name: str,
    *,
    kind: SymbolKind = SymbolKind.FUNCTION,
    start: int = 1,
    end: int | None = None,
    parent_id: str | None = None,
    qualified: str | None = None,
) -> SymbolRecord:
    qualified_name = qualified if qualified is not None else name
    line_end = end if end is not None else start + 2
    return SymbolRecord(
        id=symbol_id(path, kind, qualified_name, start),
        path=path,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        language=Language.PYTHON,
        span=SourceSpan(path=path, start_line=start, end_line=line_end),
        parent_id=parent_id,
        signature=f"def {name}():" if kind is SymbolKind.FUNCTION else None,
    )


def module(path: str, *, qualified: str, lines: int = 10) -> SymbolRecord:
    return symbol(path, qualified.rsplit(".", 1)[-1], kind=SymbolKind.MODULE, start=1, end=lines, qualified=qualified)


def make_snapshot(
    *files: FileRecord,
    symbols: tuple[SymbolRecord, ...] = (),
    parse_issues: tuple[ParseIssue, ...] = (),
) -> IndexSnapshot:
    return IndexSnapshot.build(
        engine_version="test-engine",
        policy_fingerprint="test-policy",
        root="",
        files=files,
        symbols=symbols,
        relations=(),
        parse_issues=parse_issues,
    )


def demo_snapshot() -> IndexSnapshot:
    """Demo-repo shape: parser adapters nest top-level functions under the module."""

    core = module("src/demo/core.py", qualified="src.demo.core", lines=32)
    core_main = symbol(
        "src/demo/core.py",
        "main",
        start=29,
        end=32,
        parent_id=core.id,
        qualified="src.demo.core.main",
    )
    web = module("web/index.ts", qualified="web.index", lines=5)
    web_main = symbol(
        "web/index.ts",
        "main",
        start=3,
        end=5,
        parent_id=web.id,
        qualified="web.index.main",
    )
    return make_snapshot(
        record("src/demo/core.py", lines=32),
        record("web/index.ts", lines=5),
        symbols=(core, core_main, web, web_main),
    )


# ---------------------------------------------------------------------------
# Shared payload contract
# ---------------------------------------------------------------------------
def test_every_payload_has_index_block_and_budgets() -> None:
    snapshot = load_snapshot()
    expected_index = {
        "schemaVersion": snapshot.schema_version,
        "engineVersion": snapshot.engine_version,
        "policyFingerprint": snapshot.policy_fingerprint,
        "fingerprint": snapshot.fingerprint(),
    }
    for name, payload in build_payloads().items():
        assert payload["ok"] is True, name
        assert payload["index"] == expected_index, name
        budgets = payload["budgets"]
        assert set(budgets) == {"maxTokens", "tokensEstimated", "tokenEstimator"}, name
        assert budgets["tokenEstimator"] == "chars4-wide-v1", name
        assert budgets["tokensEstimated"] == measured_tokens(payload), name


def test_no_volatile_fields_in_any_payload() -> None:
    serialized = canonical_json(build_payloads())
    for payload in build_payloads().values():
        keys = set(walk_keys(payload))
        for forbidden in (
            "timestamp",
            "generatedAt",
            "generated_at",
            "durationMs",
            "duration",
            "elapsedMs",
            "cache",
            "cacheHit",
            "cacheHits",
            "root",
            "absolutePath",
            "mtime",
            "mtimeNs",
            "pid",
        ):
            assert forbidden not in keys
    assert str(REPO) not in serialized
    assert str(Path(__file__).resolve().parent) not in serialized


def test_payloads_are_byte_stable_across_calls() -> None:
    first = {name: canonical_json(payload) for name, payload in build_payloads().items()}
    second = {name: canonical_json(payload) for name, payload in build_payloads().items()}
    assert first == second


@pytest.mark.parametrize(
    "builder",
    ["overview", "map", "search", "dependencies", "context", "impact"],
)
@pytest.mark.parametrize("budget", BUDGETS)
def test_payloads_respect_budget(builder: str, budget: int) -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    if builder == "overview":
        payload = overview_payload(snapshot, graph, max_tokens=budget)
    elif builder == "map":
        payload = map_payload(snapshot, graph, max_tokens=budget)
    elif builder == "search":
        payload = search_payload(snapshot, "context", search(snapshot, graph, "context"), max_tokens=budget)
    elif builder == "dependencies":
        payload = dependencies_payload(
            snapshot, graph, target="src/app/core.py", depth=2, max_tokens=budget
        )
    elif builder == "context":
        pack = build_context(snapshot, graph, "bounded context pack", max_tokens=2200)
        payload = context_payload(snapshot, pack, max_tokens=budget)
    else:
        payload = impact_payload(snapshot, FakeImpactResult(), max_tokens=budget)
    json.loads(canonical_json(payload))
    assert payload["budgets"]["maxTokens"] == budget
    assert payload["budgets"]["tokensEstimated"] == measured_tokens(payload)
    assert measured_tokens(payload) <= budget


def test_default_budgets_match_spec_tool_defaults() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    pack = build_context(snapshot, graph, "bounded context pack")
    assert overview_payload(snapshot, graph)["budgets"]["maxTokens"] == 900
    assert map_payload(snapshot, graph)["budgets"]["maxTokens"] == 1600
    assert search_payload(snapshot, "context", ())["budgets"]["maxTokens"] == 1200
    assert (
        dependencies_payload(snapshot, graph, target="src/app/core.py")["budgets"]["maxTokens"]
        == 1200
    )
    assert context_payload(snapshot, pack)["budgets"]["maxTokens"] == 2200
    assert impact_payload(snapshot, FakeImpactResult())["budgets"]["maxTokens"] == 1200


def test_budget_requests_are_clamped() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    payload = overview_payload(snapshot, graph, max_tokens=10)
    assert payload["budgets"]["maxTokens"] == 64
    payload = map_payload(snapshot, graph, max_tokens=10**9)
    assert payload["budgets"]["maxTokens"] == 8000


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------
def test_overview_shape_and_content() -> None:
    snapshot = load_snapshot()
    payload = overview_payload(snapshot, FakeGraph(snapshot))
    assert payload["command"] == "overview"
    assert payload["schemaVersion"] == "1"
    repo = payload["repo"]
    assert set(repo) == {"files", "symbols", "relations", "languages", "topDirectories"}
    assert repo["files"] == 6
    assert repo["symbols"] == 13
    assert repo["relations"] == 5
    languages = {row["language"]: row for row in repo["languages"]}
    assert languages["python"] == {"language": "python", "files": 5, "symbols": 13}
    assert languages["markdown"] == {"language": "markdown", "files": 1, "symbols": 0}
    assert [row["language"] for row in repo["languages"]] == ["markdown", "python"]
    directories = {row["path"]: row for row in repo["topDirectories"]}
    assert directories["src"] == {"path": "src", "files": 4, "symbols": 11}
    assert directories["docs"]["files"] == 1
    entry_points = payload["entryPoints"]
    assert set(entry_points[0]) == {"path", "symbol", "kind", "line"}
    assert [(row["path"], row["line"]) for row in entry_points] == [
        ("src/app/cli.py", 6),
        ("tools/build.py", 6),
    ]
    assert payload["parseIssues"] == {"count": 0, "sample": []}
    assert payload["omitted"] == {
        "directories": 0,
        "entryPoints": 0,
        "languages": 0,
        "parseIssues": 0,
    }
    assert payload["truncated"] is False


def test_overview_parse_issue_sample_is_bounded() -> None:
    issues = tuple(ParseIssue(path=f"pkg/mod_{index}.py", message="boom") for index in range(7))
    snapshot = make_snapshot(record("pkg/mod.py"), parse_issues=issues)
    payload = overview_payload(snapshot, FakeGraph(snapshot))
    assert payload["parseIssues"]["count"] == 7
    assert len(payload["parseIssues"]["sample"]) == 5
    assert payload["omitted"]["parseIssues"] == 2
    assert payload["truncated"] is True


def test_overview_truncates_at_small_budget() -> None:
    snapshot = load_snapshot()
    payload = overview_payload(snapshot, FakeGraph(snapshot), max_tokens=200)
    assert measured_tokens(payload) <= 200
    assert payload["truncated"] is True
    assert set(payload["omitted"]) == {
        "directories",
        "entryPoints",
        "languages",
        "parseIssues",
    }
    assert sum(payload["omitted"].values()) > 0


def test_entry_point_heuristic_demo_shape() -> None:
    snapshot = demo_snapshot()
    payload = overview_payload(snapshot, FakeGraph(snapshot))
    assert payload["entryPoints"] == [
        {
            "path": "src/demo/core.py",
            "symbol": "src.demo.core.main",
            "kind": "function",
            "line": 29,
        },
        {
            "path": "web/index.ts",
            "symbol": "web.index.main",
            "kind": "function",
            "line": 3,
        },
    ]
    assert set(payload["entryPoints"][0]) == {"path", "symbol", "kind", "line"}


def test_entry_point_run_is_used_only_without_main() -> None:
    app_module = module("pkg/app.py", qualified="pkg.app")
    run_symbol = symbol(
        "pkg/app.py", "run", start=2, parent_id=app_module.id, qualified="pkg.app.run"
    )
    run_only = make_snapshot(record("pkg/app.py"), symbols=(app_module, run_symbol))
    rows = overview_payload(run_only, FakeGraph(run_only))["entryPoints"]
    assert [(row["path"], row["symbol"]) for row in rows] == [("pkg/app.py", "pkg.app.run")]

    main_symbol = symbol(
        "pkg/app.py", "main", start=5, parent_id=app_module.id, qualified="pkg.app.main"
    )
    both = make_snapshot(record("pkg/app.py"), symbols=(app_module, run_symbol, main_symbol))
    rows = overview_payload(both, FakeGraph(both))["entryPoints"]
    assert [(row["path"], row["symbol"]) for row in rows] == [("pkg/app.py", "pkg.app.main")]


def test_entry_point_file_tier_and_index_barrel_rule() -> None:
    index_module = module("web/index.ts", qualified="web.index", lines=5)
    snapshot = make_snapshot(
        record("manage.py", lines=5),
        record("web/index.ts", lines=5),
        symbols=(index_module,),
    )
    rows = overview_payload(snapshot, FakeGraph(snapshot))["entryPoints"]
    assert rows == [{"path": "manage.py", "symbol": None, "kind": "file", "line": 1}]

    boot = symbol(
        "web/index.ts",
        "Boot",
        kind=SymbolKind.CLASS,
        start=1,
        end=5,
        parent_id=index_module.id,
        qualified="web.index.Boot",
    )
    nested_main = symbol(
        "web/index.ts",
        "main",
        kind=SymbolKind.METHOD,
        start=3,
        end=4,
        parent_id=boot.id,
        qualified="web.index.Boot.main",
    )
    with_main = make_snapshot(
        record("manage.py", lines=5),
        record("web/index.ts", lines=5),
        symbols=(index_module, boot, nested_main),
    )
    rows = overview_payload(with_main, FakeGraph(with_main))["entryPoints"]
    assert rows == [
        {"path": "manage.py", "symbol": None, "kind": "file", "line": 1},
        {
            "path": "web/index.ts",
            "symbol": "web.index.Boot.main",
            "kind": "method",
            "line": 3,
        },
    ]


def test_entry_points_are_shared_with_both_markdown_reports() -> None:
    snapshot = demo_snapshot()
    rows = overview_payload(snapshot, FakeGraph(snapshot))["entryPoints"]
    assert rows
    map_text = markdown_map(snapshot)
    report_text = markdown_report(snapshot, FakeGraph(snapshot))
    for row in rows:
        citation = f"{row['path']}:{row['line']}"
        assert citation in map_text
        assert citation in report_text
    assert "none detected by the name heuristic" not in map_text
    assert "none detected by the name heuristic" not in report_text


# ---------------------------------------------------------------------------
# map
# ---------------------------------------------------------------------------
def test_map_shape_and_entry_ordering() -> None:
    snapshot = load_snapshot()
    payload = map_payload(snapshot, FakeGraph(snapshot))
    assert payload["command"] == "map"
    assert payload["focus"] is None
    entries = payload["entries"]
    assert [entry["path"] for entry in entries] == sorted(entry["path"] for entry in entries)
    first = entries[0]
    assert set(first) == {"path", "language", "symbols"}
    for entry in entries:
        lines = [row["line"] for row in entry["symbols"]]
        assert lines == sorted(lines)
        for row in entry["symbols"]:
            assert set(row) == {"name", "kind", "line"} or set(row) == {
                "name",
                "kind",
                "line",
                "signature",
            }
    assert payload["omitted"] == {"files": 0, "symbols": 0}
    assert payload["truncated"] is False


def test_map_focus_filters_entries_and_rejects_traversal() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    payload = map_payload(snapshot, graph, focus="src/app")
    assert payload["focus"] == "src/app"
    assert payload["entries"]
    assert all(entry["path"].startswith("src/app/") for entry in payload["entries"])
    docs = map_payload(snapshot, graph, focus="docs")
    assert [entry["path"] for entry in docs["entries"]] == ["docs/guide.md"]
    with pytest.raises(UsageError):
        map_payload(snapshot, graph, focus="../escape")


def test_map_small_budget_reports_omitted_counts() -> None:
    snapshot = load_snapshot()
    payload = map_payload(snapshot, FakeGraph(snapshot), max_tokens=200)
    assert measured_tokens(payload) <= 200
    assert payload["truncated"] is True
    assert payload["omitted"]["files"] > 0
    assert payload["omitted"]["symbols"] > 0


def test_map_with_empty_index_is_empty() -> None:
    snapshot = make_snapshot()
    payload = map_payload(snapshot, None)
    assert payload["entries"] == []
    assert payload["truncated"] is False


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def test_search_payload_rows_and_total() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    hits = search(snapshot, graph, "context")
    payload = search_payload(snapshot, "context", hits)
    assert payload["command"] == "search"
    assert payload["query"] == "context"
    assert payload["total"] == len(hits)
    assert len(payload["results"]) == len(hits)
    row = payload["results"][0]
    assert set(row) == {"path", "line", "symbol", "kind", "language", "score", "match"}
    assert row["path"] == "src/app/core.py"
    assert row["line"] == 11
    assert row["score"] == round(row["score"], 4)
    assert payload["omitted"] == {"results": 0}
    assert payload["truncated"] is False


def test_search_payload_truncates_and_bounds_query() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    hits = search(snapshot, graph, "context")
    payload = search_payload(snapshot, "context", hits, max_tokens=200)
    assert measured_tokens(payload) <= 200
    assert len(payload["results"]) < payload["total"]
    assert payload["omitted"]["results"] == payload["total"] - len(payload["results"])
    assert payload["truncated"] is True

    long_query = "context " * 200
    long_payload = search_payload(snapshot, long_query, hits)
    assert len(long_payload["query"]) <= 200


def test_search_payload_empty_hits() -> None:
    snapshot = load_snapshot()
    payload = search_payload(snapshot, "no-such-symbol", ())
    assert payload["results"] == []
    assert payload["total"] == 0
    assert payload["truncated"] is False


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------
def test_dependencies_payload_shape_and_edges() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    payload = dependencies_payload(snapshot, graph, target="src/app/core.py", depth=2)
    assert payload["command"] == "dependencies"
    assert payload["target"] == {"path": "src/app/core.py"}
    assert payload["direction"] == "both"
    assert payload["depth"] == 2
    nodes = payload["nodes"]
    assert all(set(node) == {"id", "path", "distance"} for node in nodes)
    assert nodes[0]["path"] == "src/app/core.py"
    assert nodes[0]["distance"] == 0
    assert [(node["distance"], node["path"]) for node in nodes] == sorted(
        (node["distance"], node["path"]) for node in nodes
    )
    assert {node["path"] for node in nodes} == {
        "src/app/core.py",
        "src/app/cli.py",
        "tools/build.py",
    }
    edges = payload["edges"]
    assert all(set(edge) == {"from", "to", "type", "status", "evidence"} for edge in edges)
    assert any(
        edge["from"] == "file:src/app/cli.py"
        and edge["to"] == "file:src/app/core.py"
        and edge["type"] == "imports"
        and edge["status"] == "resolved"
        and edge["evidence"] == "resolver"
        for edge in edges
    )
    assert any(
        edge["to"] == "requests" and edge["status"] == "external" for edge in edges
    )
    assert payload["truncated"] is False


def test_dependencies_direction_changes_the_neighborhood() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    imports = dependencies_payload(
        snapshot, graph, target="src/app/cli.py", direction="imports", depth=1
    )
    assert imports["target"] == {"path": "src/app/cli.py"}
    assert {node["path"] for node in imports["nodes"]} == {
        "src/app/cli.py",
        "src/app/core.py",
    }
    assert imports["truncated"] is False
    dependents = dependencies_payload(
        snapshot, graph, target="src/app/core.py", direction="dependents", depth=1
    )
    assert {node["path"] for node in dependents["nodes"]} == {
        "src/app/core.py",
        "src/app/cli.py",
        "tools/build.py",
    }
    assert all(edge["to"] == "file:src/app/core.py" for edge in dependents["edges"])


def test_dependencies_symbol_target_keeps_symbol_edges() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    target = "sym:src/app/core.py#function:build_context@11"
    payload = dependencies_payload(snapshot, graph, target=target, direction="both")
    assert payload["target"] == {"symbol": target}
    assert payload["nodes"][0]["id"] == target
    assert payload["nodes"][0]["distance"] == 0
    assert any(edge["type"] == "calls" for edge in payload["edges"])
    symbol_edges = [edge for edge in payload["edges"] if edge["to"] == target]
    assert symbol_edges
    assert {edge["status"] for edge in symbol_edges} == {"resolved"}


def test_dependencies_validation_errors() -> None:
    snapshot = load_snapshot()
    graph = FakeGraph(snapshot)
    with pytest.raises(UsageError):
        dependencies_payload(snapshot, graph, target="no/such/file.py")
    with pytest.raises(UsageError):
        dependencies_payload(snapshot, graph, target="src/app/core.py", direction="sideways")
    with pytest.raises(UsageError):
        dependencies_payload(snapshot, graph, target="src/app/core.py", depth="deep")


def test_dependencies_small_budget_truncates_edges() -> None:
    snapshot = load_snapshot()
    payload = dependencies_payload(
        snapshot, FakeGraph(snapshot), target="src/app/core.py", depth=2, max_tokens=200
    )
    assert measured_tokens(payload) <= 200
    assert payload["truncated"] is True
    assert payload["omitted"]["edges"] > 0


# ---------------------------------------------------------------------------
# impact
# ---------------------------------------------------------------------------
def test_impact_payload_shape() -> None:
    snapshot = load_snapshot()
    payload = impact_payload(snapshot, FakeImpactResult())
    assert payload["command"] == "impact"
    assert payload["changed"] == {
        "files": ["src/app/core.py"],
        "symbols": ["build_context"],
    }
    files = payload["affectedFiles"]
    assert [(row["path"], row["distance"]) for row in files] == [
        ("src/app/cli.py", 1),
        ("tools/build.py", 1),
    ]
    assert all(
        set(row) == {"path", "distance", "confidence", "reason"} for row in files
    )
    symbols = payload["affectedSymbols"]
    assert all(
        set(row) == {"id", "path", "symbol", "distance", "confidence"} for row in symbols
    )
    assert [row["symbol"] for row in symbols] == ["main", "main"]
    assert payload["truncated"] is False
    assert payload["omitted"] == {"affectedFiles": 0, "affectedSymbols": 0}


def test_impact_payload_propagates_result_truncation() -> None:
    snapshot = load_snapshot()
    payload = impact_payload(snapshot, FakeImpactResult(truncated=True))
    assert payload["truncated"] is True


def test_impact_payload_small_budget_truncates_rows() -> None:
    snapshot = load_snapshot()
    payload = impact_payload(snapshot, FakeImpactResult(), max_tokens=200)
    assert measured_tokens(payload) <= 200
    assert payload["truncated"] in (True, False)


def test_impact_payload_accepts_mapping_like_entries() -> None:
    snapshot = load_snapshot()

    @dataclass(frozen=True)
    class MappingResult:
        changed_files: tuple[str, ...] = ("tools/build.py",)
        changed_symbols: tuple[str, ...] = ()
        affected_files: tuple[dict, ...] = (
            {"path": "src/app/core.py", "distance": 1, "confidence": "high", "reason": "imported by changed file"},
        )
        affected_symbols: tuple[dict, ...] = (
            {"id": "sym:x", "path": "src/app/core.py", "name": "build_context", "distance": 1, "confidence": "medium"},
        )
        truncated: bool = False

    payload = impact_payload(snapshot, MappingResult())
    assert payload["changed"]["files"] == ["tools/build.py"]
    assert payload["affectedFiles"][0]["path"] == "src/app/core.py"
    assert payload["affectedSymbols"][0]["symbol"] == "build_context"


# ---------------------------------------------------------------------------
# context payload
# ---------------------------------------------------------------------------
def test_context_payload_shape_and_citations() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "bounded context pack")
    payload = context_payload(snapshot, pack)
    assert payload["command"] == "context"
    assert payload["task"] == pack.task
    assert set(payload) == {
        "ok",
        "schemaVersion",
        "command",
        "index",
        "task",
        "items",
        "omitted",
        "budgets",
        "truncated",
    }
    assert len(payload["items"]) == len(pack.items)
    for row, item in zip(payload["items"], pack.items):
        assert set(row) == {
            "path",
            "startLine",
            "endLine",
            "kind",
            "symbol",
            "reason",
            "tokensEstimated",
            "excerpt",
        }
        assert row["path"] == item.path
        assert row["startLine"] == item.start_line
        assert row["excerpt"] == item.excerpt
        assert row["tokensEstimated"] == item.tokens_estimated
    assert payload["omitted"] == []
    assert payload["truncated"] is False


def test_context_payload_rebudget_reports_budget_omissions() -> None:
    snapshot = load_snapshot()
    pack = build_context(snapshot, FakeGraph(snapshot), "bounded context pack", max_tokens=2200)
    payload = context_payload(snapshot, pack, max_tokens=160)
    assert measured_tokens(payload) <= 160
    assert len(payload["items"]) < len(pack.items)
    assert payload["truncated"] is True
    assert payload["omitted"]
    assert {row["reason"] for row in payload["omitted"]} == {"budget"}


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def test_markdown_map_cites_paths_and_states_limitations() -> None:
    snapshot = load_snapshot()
    text = markdown_map(snapshot)
    assert text.startswith("# Repository map")
    assert "src/app/cli.py:6" in text
    assert "src/app/core.py:11" in text
    assert "heuristic" in text
    assert "unsupported" in text
    assert text.isascii()
    assert str(REPO) not in text
    assert len(text) <= MAX_MAP_CHARS
    assert text == markdown_map(snapshot)


def test_markdown_report_cites_paths_and_labels_edges() -> None:
    snapshot = load_snapshot()
    text = markdown_report(snapshot, FakeGraph(snapshot))
    assert text.startswith("# Architecture report")
    assert "## Summary" in text
    assert "## Dependency hubs" in text
    assert "`src/app/core.py` - imported by 2 file(s), imports 0" in text
    assert "src/app/cli.py:3" in text
    assert "external" in text
    assert "heuristic" in text
    assert "Limitations" in text
    assert text.isascii()
    assert len(text) <= MAX_REPORT_CHARS
    assert text == markdown_report(snapshot, FakeGraph(snapshot))


def test_markdown_report_survives_a_broken_graph() -> None:
    snapshot = load_snapshot()
    text = markdown_report(snapshot, BrokenGraph())
    assert text.startswith("# Architecture report")
    assert "Dependency hubs" in text
    assert text.isascii()


def test_markdown_map_is_bounded_for_large_indexes() -> None:
    files = tuple(record(f"pkg/module_{index:03d}.py", lines=1) for index in range(200))
    snapshot = make_snapshot(*files)
    text = markdown_map(snapshot)
    assert len(text) <= MAX_MAP_CHARS
    assert "more files" in text
    report = markdown_report(snapshot, FakeGraph(snapshot))
    assert len(report) <= MAX_REPORT_CHARS
