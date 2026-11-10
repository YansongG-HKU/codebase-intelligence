"""Tests for import resolution, graph queries and impact analysis (SPEC §7).

The fixtures are the same small multi-language tree used by the parser tests, so
these tests also prove the parser → resolver contract end to end: parser emits a
raw specifier, graph resolves it *where safe*, and everything else keeps its
honest status.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from codebase_intelligence.graph import Graph, resolve_imports
from codebase_intelligence.model import (
    EvidenceKind,
    FileRecord,
    IndexSnapshot,
    Language,
    ResolutionStatus,
)
from codebase_intelligence.parsers import parse_file

FIXTURES = Path(__file__).parent / "fixtures" / "parser"
ENGINE_VERSION = "0.1.0"
POLICY_FINGERPRINT = "fixture-policy"

LANGUAGE_BY_SUFFIX = {
    ".py": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".go": Language.GO,
}


def make_record(path: str, language: Language, text: str) -> FileRecord:
    data = text.encode("utf-8")
    line_count = text.count("\n") + (1 if data and not text.endswith("\n") else 0)
    return FileRecord(
        path=path,
        language=language,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        line_count=max(1, line_count),
    )


def snapshot_from_sources(sources: dict[str, str]) -> IndexSnapshot:
    records: list[FileRecord] = []
    symbols = []
    relations = []
    issues = []
    for path in sorted(sources):
        language = LANGUAGE_BY_SUFFIX[Path(path).suffix]
        record = make_record(path, language, sources[path])
        result = parse_file(record, sources[path])
        records.append(record)
        symbols.extend(result.symbols)
        relations.extend(result.relations)
        issues.extend(result.issues)
    return IndexSnapshot.build(
        engine_version=ENGINE_VERSION,
        policy_fingerprint=POLICY_FINGERPRINT,
        root="",
        files=records,
        symbols=symbols,
        relations=relations,
        parse_issues=issues,
    )


def fixture_snapshot() -> IndexSnapshot:
    sources: dict[str, str] = {}
    for path in sorted(FIXTURES.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in LANGUAGE_BY_SUFFIX:
            continue
        relative = path.relative_to(FIXTURES).as_posix()
        sources[relative] = path.read_text(encoding="utf-8")
    return snapshot_from_sources(sources)


@pytest.fixture(scope="module")
def snapshot() -> IndexSnapshot:
    return fixture_snapshot()


@pytest.fixture(scope="module")
def graph(snapshot: IndexSnapshot) -> Graph:
    return Graph(snapshot)


def symbol_by_qualified(snapshot: IndexSnapshot, qualified_name: str):
    matches = [symbol for symbol in snapshot.symbols if symbol.qualified_name == qualified_name]
    assert len(matches) == 1, f"{qualified_name!r} matched {len(matches)} symbols"
    return matches[0]


def import_relations(graph: Graph, source_path: str) -> dict[str, list]:
    grouped: dict[str, list] = {}
    source_id = f"file:{source_path}"
    for relation in graph.relations:
        if relation.source_id != source_id:
            continue
        if relation.relation_type.value != "imports":
            continue
        grouped.setdefault(relation.target_name or "", []).append(relation)
    return grouped


# ---------------------------------------------------------------------------
# Import resolution: Python
# ---------------------------------------------------------------------------
def test_python_relative_imports_resolve(graph: Graph) -> None:
    assert graph.file_imports("python_pkg/app.py") == (
        "python_pkg/helpers.py",
        "python_pkg/models.py",
    )
    assert graph.file_imports("python_pkg/nested/deep.py") == ("python_pkg/helpers.py",)


def test_python_absolute_and_package_imports_resolve(graph: Graph) -> None:
    assert graph.file_imports("python_pkg/absolute.py") == ("python_pkg/models.py",)
    assert graph.file_imports("python_pkg/uses_pkg.py") == ("python_pkg/__init__.py",)


def test_python_external_import_is_labelled_external(graph: Graph) -> None:
    relations = import_relations(graph, "python_pkg/app.py")
    assert relations["os"][0].status is ResolutionStatus.EXTERNAL
    assert relations["os"][0].evidence is EvidenceKind.RESOLVER
    assert relations["os"][0].target_id is None


def test_python_unresolved_relative_import_is_preserved(graph: Graph) -> None:
    relations = import_relations(graph, "python_pkg/app.py")
    missing = relations[".missing"][0]
    assert missing.status is ResolutionStatus.UNRESOLVED
    assert missing.target_name == ".missing"
    assert missing.target_id is None
    assert missing.evidence is EvidenceKind.RESOLVER
    assert missing.confidence < 0.5


def test_python_local_prefix_without_file_is_unresolved_not_external(graph: Graph) -> None:
    relations = import_relations(graph, "python_pkg/app.py")
    ghost = relations["python_pkg.ghost"][0]
    assert ghost.status is ResolutionStatus.UNRESOLVED
    assert ghost.target_name == "python_pkg.ghost"
    assert ghost.confidence >= 0.3


def test_python_ambiguous_module_is_ambiguous_without_target(graph: Graph) -> None:
    relations = import_relations(graph, "python_pkg/uses_amb.py")
    ambiguous = relations["amb"][0]
    assert ambiguous.status is ResolutionStatus.AMBIGUOUS
    assert ambiguous.target_id is None
    assert ambiguous.target_name == "amb"
    assert graph.file_imports("python_pkg/uses_amb.py") == ()


# ---------------------------------------------------------------------------
# Import resolution: JS / TS / Go
# ---------------------------------------------------------------------------
def test_javascript_resolution_statuses(graph: Graph) -> None:
    relations = import_relations(graph, "web/app.js")
    assert relations["./helpers"][0].status is ResolutionStatus.RESOLVED
    assert relations["./helpers"][0].target_id == "file:web/helpers.js"
    assert relations["./dupe"][0].status is ResolutionStatus.AMBIGUOUS
    assert relations["./dupe"][0].target_id is None
    assert relations["./nope"][0].status is ResolutionStatus.UNRESOLVED
    assert relations["react"][0].status is ResolutionStatus.EXTERNAL


def test_typescript_relative_resolution(graph: Graph) -> None:
    assert graph.file_imports("web/app.ts") == ("web/helpers.js", "web/types.ts")


def test_go_package_directory_resolution(graph: Graph) -> None:
    relations = import_relations(graph, "go/service/main.go")
    assert relations["example.com/fixture/go/service/util"][0].status is ResolutionStatus.RESOLVED
    assert relations["example.com/fixture/go/service/util"][0].target_id == (
        "file:go/service/util/util.go"
    )
    assert relations["fmt"][0].status is ResolutionStatus.EXTERNAL
    assert graph.file_imports("go/service/main.go") == ("go/service/util/util.go",)


# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------
def test_file_dependents_are_direct_and_sorted(graph: Graph) -> None:
    assert graph.file_dependents("python_pkg/helpers.py") == (
        "python_pkg/app.py",
        "python_pkg/nested/deep.py",
    )
    assert graph.file_dependents("python_pkg/models.py") == (
        "python_pkg/absolute.py",
        "python_pkg/app.py",
        "python_pkg/helpers.py",
    )
    assert graph.file_dependents("python_pkg/broken.py") == ()


def test_file_imports_and_dependents_for_unknown_path_are_empty(graph: Graph) -> None:
    assert graph.file_imports("nope.py") == ()
    assert graph.file_dependents("nope.py") == ()


def test_transitive_dependents_with_distances(graph: Graph) -> None:
    assert graph.transitive_dependents("python_pkg/models.py") == (
        ("python_pkg/absolute.py", 1),
        ("python_pkg/app.py", 1),
        ("python_pkg/helpers.py", 1),
        ("python_pkg/nested/deep.py", 2),
        ("python_pkg/nested/__init__.py", 3),
    )
    assert graph.transitive_dependents("python_pkg/models.py", max_depth=1) == (
        ("python_pkg/absolute.py", 1),
        ("python_pkg/app.py", 1),
        ("python_pkg/helpers.py", 1),
    )
    assert graph.transitive_dependents("does/not/exist.py") == ()


def test_transitive_dependents_is_cycle_safe() -> None:
    snapshot = snapshot_from_sources(
        {
            "a.py": "import b\n",
            "b.py": "import a\n",
            "c.py": "import a\n",
        }
    )
    graph = Graph(snapshot)
    assert graph.transitive_dependents("a.py") == (("b.py", 1), ("c.py", 1))


def test_graph_from_raw_and_resolved_snapshots_agree(snapshot: IndexSnapshot) -> None:
    resolved_relations = resolve_imports(snapshot.files, snapshot.relations)
    resolved_snapshot = IndexSnapshot.build(
        engine_version=snapshot.engine_version,
        policy_fingerprint=snapshot.policy_fingerprint,
        root="",
        files=snapshot.files,
        symbols=snapshot.symbols,
        relations=resolved_relations,
        parse_issues=snapshot.parse_issues,
    )
    from_raw = Graph(snapshot)
    from_resolved = Graph(resolved_snapshot)
    assert from_raw.relations == from_resolved.relations
    for file in snapshot.files:
        assert from_raw.file_imports(file.path) == from_resolved.file_imports(file.path)
        assert from_raw.file_dependents(file.path) == from_resolved.file_dependents(file.path)


def test_resolve_imports_is_idempotent(snapshot: IndexSnapshot) -> None:
    first = resolve_imports(snapshot.files, snapshot.relations)
    second = resolve_imports(snapshot.files, first)
    assert first == second


# ---------------------------------------------------------------------------
# Source-root ("src layout") resolution
# ---------------------------------------------------------------------------
def test_src_layout_absolute_import_resolves() -> None:
    snapshot = snapshot_from_sources(
        {
            "src/demo/__init__.py": '"""Demo."""\n',
            "src/demo/core.py": (
                "from demo.util import clamp\n"
                "\n"
                "\n"
                "class Engine:\n"
                "    def clamp_value(self, value):\n"
                "        return clamp(value)\n"
            ),
            "src/demo/util.py": "def clamp(value):\n    return value\n",
            "src/demo/sub/__init__.py": '"""Sub."""\n',
            "src/demo/sub/helper.py": (
                "from ..core import Engine\n\n\ndef make():\n    return Engine()\n"
            ),
        }
    )
    graph = Graph(snapshot)
    assert graph.file_imports("src/demo/core.py") == ("src/demo/util.py",)
    relation = import_relations(graph, "src/demo/core.py")["demo.util"][0]
    assert relation.status is ResolutionStatus.RESOLVED
    assert relation.evidence is EvidenceKind.RESOLVER
    assert relation.target_id == "file:src/demo/util.py"
    # Relative imports across packages keep resolving through the same index.
    assert graph.file_imports("src/demo/sub/helper.py") == ("src/demo/core.py",)
    assert ("src/demo/core.py", 1) in graph.transitive_dependents("src/demo/util.py")


def test_detect_source_roots_helper() -> None:
    from codebase_intelligence.graph import detect_source_roots

    src_layout = snapshot_from_sources(
        {
            "src/demo/__init__.py": "",
            "src/demo/core.py": "",
            "src/demo/sub/__init__.py": "",
            "src/demo/sub/helper.py": "",
        }
    )
    assert detect_source_roots(src_layout.files) == ("", "src")

    flat_layout = snapshot_from_sources(
        {"app.py": "", "pkg/__init__.py": "", "pkg/mod.py": "", "nested/__init__.py": ""}
    )
    assert detect_source_roots(flat_layout.files) == ("",)


def test_src_root_prefers_candidate_in_importers_package_tree() -> None:
    snapshot = snapshot_from_sources(
        {
            "one/app.py": "from lib.util import helper\n",
            "one/lib/__init__.py": "",
            "one/lib/util.py": "def helper():\n    return 1\n",
            "two/lib/__init__.py": "",
            "two/lib/util.py": "def helper():\n    return 2\n",
        }
    )
    graph = Graph(snapshot)
    assert graph.file_imports("one/app.py") == ("one/lib/util.py",)


def test_src_root_candidates_without_preference_are_ambiguous() -> None:
    snapshot = snapshot_from_sources(
        {
            "main.py": "import lib.util\n",
            "one/lib/__init__.py": "",
            "one/lib/util.py": "def helper():\n    return 1\n",
            "two/lib/__init__.py": "",
            "two/lib/util.py": "def helper():\n    return 2\n",
        }
    )
    graph = Graph(snapshot)
    relations = import_relations(graph, "main.py")
    assert relations["lib.util"][0].status is ResolutionStatus.AMBIGUOUS
    assert graph.file_imports("main.py") == ()


# ---------------------------------------------------------------------------
# Symbol neighborhood
# ---------------------------------------------------------------------------
def test_symbol_neighborhood_reports_direction_relation_and_confidence(
    snapshot: IndexSnapshot, graph: Graph
) -> None:
    helper = symbol_by_qualified(snapshot, "python_pkg.helpers.helper")
    entries = graph.symbol_neighborhood(helper.id, depth=1)
    assert entries
    calls = [
        entry
        for entry in entries
        if entry["relation"] == "calls" and entry["direction"] == "in"
    ]
    assert len(calls) == 1
    assert calls[0]["symbol"] == "add"
    assert calls[0]["evidence"] == "heuristic"
    assert calls[0]["confidence"] == 0.8
    # Deterministic order: repeated calls return exactly the same entries.
    assert graph.symbol_neighborhood(helper.id, depth=1) == entries
    deeper = graph.symbol_neighborhood(helper.id, depth=2)
    assert len(deeper) >= len(entries)


def test_symbol_neighborhood_unknown_symbol_returns_empty(graph: Graph) -> None:
    assert graph.symbol_neighborhood("sym:nope.py#function:nope@1") == ()


# ---------------------------------------------------------------------------
# Impact
# ---------------------------------------------------------------------------
def test_impact_file_reverse_dependencies(graph: Graph) -> None:
    result = graph.impact(files=["python_pkg/helpers.py"])
    assert result.changed_files == ("python_pkg/helpers.py",)
    assert result.changed_symbols == ()
    affected = {entry.path: entry for entry in result.affected_files}
    assert set(affected) == {
        "python_pkg/app.py",
        "python_pkg/nested/deep.py",
        "python_pkg/nested/__init__.py",
    }
    assert affected["python_pkg/app.py"].distance == 1
    assert affected["python_pkg/nested/deep.py"].distance == 1
    assert affected["python_pkg/nested/__init__.py"].distance == 2
    for entry in affected.values():
        assert entry.confidence == "high"
        assert "import" in entry.reason
    assert result.truncated is False
    payload = result.to_dict()
    assert payload["changed"] == {"files": ["python_pkg/helpers.py"], "symbols": []}
    assert payload["affectedFiles"][0]["reason"]


def test_impact_symbol_call_edge_is_medium(
    snapshot: IndexSnapshot, graph: Graph
) -> None:
    helper = symbol_by_qualified(snapshot, "python_pkg.helpers.helper")
    result = graph.impact(symbols=[helper.id])
    assert result.changed_symbols == (helper.id,)
    assert result.changed_files == ("python_pkg/helpers.py",)
    entries = {entry.id: entry for entry in result.affected_symbols}
    add = symbol_by_qualified(snapshot, "python_pkg.helpers.Calculator.add")
    assert add.id in entries
    assert entries[add.id].confidence == "medium"
    assert entries[add.id].to_dict()["symbol"] == "add"


def test_impact_base_edges_expose_confidence_tiers(
    snapshot: IndexSnapshot, graph: Graph
) -> None:
    base = symbol_by_qualified(snapshot, "python_pkg.models.Base")
    result = graph.impact(symbols=["python_pkg.models.Base"])
    assert result.changed_symbols == (base.id,)
    entries = {entry.id: entry for entry in result.affected_symbols}
    user = symbol_by_qualified(snapshot, "python_pkg.models.User")
    app = symbol_by_qualified(snapshot, "python_pkg.app.App")
    calculator = symbol_by_qualified(snapshot, "python_pkg.helpers.Calculator")
    assert entries[user.id].confidence == "high"
    assert entries[app.id].confidence == "medium"
    assert entries[calculator.id].confidence == "medium"
    # Sorted deterministically by (distance, path, id).
    keys = [(entry.distance, entry.path, entry.id) for entry in result.affected_symbols]
    assert keys == sorted(keys)


def test_impact_name_coincidence_is_low() -> None:
    snapshot = snapshot_from_sources(
        {
            "one.py": "def shared():\n    return 1\n",
            "two.py": "def shared():\n    return 2\n",
        }
    )
    graph = Graph(snapshot)
    shared = [symbol for symbol in snapshot.symbols if symbol.qualified_name == "one.shared"][0]
    result = graph.impact(symbols=[shared.id])
    entries = {entry.path: entry for entry in result.affected_symbols}
    assert "two.py" in entries
    assert entries["two.py"].confidence == "low"
    assert entries["two.py"].name == "shared"


def test_impact_unknown_inputs_are_ignored() -> None:
    snapshot = snapshot_from_sources({"a.py": "def a():\n    return 1\n"})
    graph = Graph(snapshot)
    result = graph.impact(files=["ghost.py"], symbols=["ghost", "a.no.such.symbol"])
    assert result.changed_files == ()
    assert result.changed_symbols == ()
    assert result.affected_files == ()
    assert result.affected_symbols == ()
    assert result.truncated is False


def test_impact_max_results_truncates_deterministically() -> None:
    sources = {"base.py": "def target():\n    return 1\n"}
    for index in range(5):
        sources[f"user{index}.py"] = "from base import target\n\ndef run():\n    return target()\n"
    graph = Graph(snapshot_from_sources(sources))
    full = graph.impact(files=["base.py"], max_results=200)
    assert len(full.affected_files) == 5
    assert full.truncated is False
    limited = graph.impact(files=["base.py"], max_results=2)
    assert len(limited.affected_files) == 2
    assert limited.truncated is True
    assert [entry.path for entry in limited.affected_files] == [
        entry.path for entry in full.affected_files[:2]
    ]


def test_impact_is_deterministic(snapshot: IndexSnapshot) -> None:
    graph = Graph(snapshot)
    first = graph.impact(files=["python_pkg/models.py"], symbols=["python_pkg.models.Base"])
    second = graph.impact(files=["python_pkg/models.py"], symbols=["python_pkg.models.Base"])
    assert first == second
    assert first.to_dict() == second.to_dict()
