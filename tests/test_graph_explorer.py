import json
from dataclasses import replace
from pathlib import Path

import pytest

from codebase_intelligence import api
from codebase_intelligence.cli import run
from codebase_intelligence.errors import RepositoryError, UsageError
from codebase_intelligence.export import DEFAULT_OUT_DIR, build_export
from codebase_intelligence.graph.snapshot import GRAPH_FILE_NAME
from codebase_intelligence.graph.explorer import MAX_NODES, graph_view, source_excerpt
from codebase_intelligence.model import EvidenceKind, RelationRecord, RelationType, ResolutionStatus

FIXTURE = Path(__file__).parent / "fixtures/plugin/demo_repo"


def test_drilldown_to_source(tmp_path: Path) -> None:
    snapshot = api.open_index(FIXTURE, cache_dir=tmp_path).snapshot
    root = graph_view(snapshot)
    assert "dir:app" in {item["id"] for item in root["nodes"]}
    package = graph_view(snapshot, "dir:app")
    assert {"file:app/main.py", "file:app/services.py"} <= {item["id"] for item in package["nodes"]}
    assert any(edge["type"] == "imports" and edge["sites"] for edge in package["edges"])
    file = graph_view(snapshot, "file:app/main.py")
    symbol = next(node for node in file["nodes"] if node["label"] == "main")
    relations = graph_view(snapshot, symbol["id"])
    assert [item["id"] for item in relations["breadcrumbs"]] == [
        "dir:app", "file:app/main.py", symbol["id"],
    ]
    edge = next(edge for edge in relations["edges"] if edge["type"] == "calls")
    site = edge["sites"][0]
    excerpt = source_excerpt(FIXTURE, snapshot.files, site["path"], site["startLine"])
    assert "main()" in excerpt["lines"][excerpt["line"] - excerpt["startLine"]]


def test_cycles_and_pagination_keep_focus_and_bound_the_graph(tmp_path: Path) -> None:
    snapshot = api.open_index(FIXTURE, cache_dir=tmp_path).snapshot
    source = next(symbol for symbol in snapshot.symbols if symbol.name == "main")
    target = next(symbol for symbol in snapshot.symbols if symbol.name == "TaskService")
    edges = [
        RelationRecord(source.id, RelationType.CALLS, ResolutionStatus.RESOLVED, EvidenceKind.RESOLVER,
                       target_id=target.id),
        RelationRecord(target.id, RelationType.CALLS, ResolutionStatus.RESOLVED, EvidenceKind.RESOLVER,
                       target_id=source.id),
    ]
    edges.extend(
        RelationRecord(source.id, RelationType.CALLS, ResolutionStatus.UNRESOLVED,
                       EvidenceKind.HEURISTIC, target_name=f"function-{i:03}")
        for i in range(100)
    )
    snapshot = replace(snapshot, relations=tuple(edges))
    first = graph_view(snapshot, source.id)
    assert len(first["nodes"]) == MAX_NODES
    assert first["nodes"][0]["id"] == source.id
    assert first["nextOffset"] == MAX_NODES - 1
    assert next(node for node in first["nodes"] if node["id"] == target.id)["side"] == "both"
    second = graph_view(snapshot, source.id, first["nextOffset"])
    assert second["nextOffset"] is None
    assert {n["id"] for n in first["nodes"]} & {n["id"] for n in second["nodes"]} == {source.id}
    assert first["omittedEdges"] > 0


def test_source_rejects_unknown_paths_and_edits_after_index(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text("value = 1\n", encoding="utf-8")
    snapshot = api.open_index(tmp_path).snapshot
    with pytest.raises(RepositoryError, match="not in"):
        source_excerpt(tmp_path, snapshot.files, "../sample.py", 1)
    with pytest.raises(UsageError, match="outside"):
        source_excerpt(tmp_path, snapshot.files, "sample.py", 50)
    path.write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(RepositoryError, match="changed"):
        source_excerpt(tmp_path, snapshot.files, "sample.py", 1)


def test_cli_rejects_stale_fingerprint_and_supports_relation_filter(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "sample.py"
    path.write_text("value = 1\n", encoding="utf-8")
    args = ["graph", "--root", str(tmp_path), "--json"]
    assert run(args) == 0
    before = json.loads(capsys.readouterr().out)
    assert before["nodes"][0]["path"] == "sample.py"
    path.write_text("value = 2\n", encoding="utf-8")
    assert run([*args, "--source=sample.py", "--fingerprint", before["fingerprint"]]) != 0
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "stale_graph"
    assert run([*args, "--relation=calls", "--focus=file:sample.py"]) == 0
    assert json.loads(capsys.readouterr().out)["relation"] == "calls"
    assert run([*args, "--relation=invalid"]) != 0
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_arguments"


def test_saved_graph_skips_indexing_until_explicit_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from codebase_intelligence.graph import snapshot as storage

    root = tmp_path / "repo"
    root.mkdir()
    path = root / "sample.py"
    path.write_text("def original(): pass\n", encoding="utf-8")
    cache = tmp_path / "cache"
    args = ["graph", str(root), "--cache-dir", str(cache), "--json"]
    assert run(args) == 0
    original = json.loads(capsys.readouterr().out)
    assert original["snapshotSource"] == "built"
    saved = next(cache.glob("graph-*.json"))
    mtime = saved.stat().st_mtime_ns
    path.write_text("def updated(): pass\n", encoding="utf-8")
    api.open_index(root, cache_dir=cache)

    def unexpected_scan(*args: object, **kwargs: object) -> None:
        pytest.fail("saved graph unexpectedly started an index scan")

    with monkeypatch.context() as patch:
        patch.setattr(storage, "ensure_index", unexpected_scan)
        assert run([*args, "--focus=file:sample.py"]) == 0
        retained = json.loads(capsys.readouterr().out)
        assert retained["snapshotSource"] == "cache"
        assert retained["fingerprint"] == original["fingerprint"]
        assert [node["label"] for node in retained["nodes"]] == ["original", "sample"]
        assert saved.stat().st_mtime_ns == mtime

    assert run([*args, "--refresh", "--focus=file:sample.py"]) == 0
    refreshed = json.loads(capsys.readouterr().out)
    assert refreshed["snapshotSource"] == "refreshed"
    assert refreshed["fingerprint"] != original["fingerprint"]
    assert [node["label"] for node in refreshed["nodes"]] == ["sample", "updated"]
    assert run([*args, "--source=sample.py", "--fingerprint", original["fingerprint"]]) != 0
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "stale_graph"
    assert run([*args, "--source=sample.py", "--fingerprint", refreshed["fingerprint"]]) == 0
    assert json.loads(capsys.readouterr().out)["lines"] == ["def updated(): pass"]


def test_repository_graph_bootstrap_and_corrupt_fallback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "sample.py").write_text(
        'def public(value="signature-secret-marker"):\n    """doc-secret-marker"""\n',
        encoding="utf-8",
    )
    build_export(root, cache_dir=tmp_path / "export-cache")
    published = root / DEFAULT_OUT_DIR / GRAPH_FILE_NAME
    document = published.read_text(encoding="utf-8")
    assert "-secret-marker" not in document
    assert "## Project graph" in (published.parent / "REPO_MAP.md").read_text(encoding="utf-8")
    cache = tmp_path / "viewer-cache"
    args = ["graph", str(root), "--cache-dir", str(cache), "--json", "--focus=file:sample.py"]
    assert run(args) == 0
    replayed = json.loads(capsys.readouterr().out)
    assert replayed["snapshotSource"] == "repository"
    assert not cache.exists()
    assert replayed["fingerprint"] == json.loads(document)["graph"]["fingerprint"]
    assert run([*args, "--exclude=other.py"]) == 0
    assert json.loads(capsys.readouterr().out)["snapshotSource"] == "built"

    tampered = json.loads(document)
    tampered["graph"]["symbols"][0]["name"] = "tampered"
    published.write_text(json.dumps(tampered), encoding="utf-8")
    assert run(args) == 0
    rebuilt = json.loads(capsys.readouterr().out)
    assert rebuilt["snapshotSource"] == "built"
    assert rebuilt["fingerprint"] == replayed["fingerprint"]
    for saved in cache.glob("graph-*.json"):
        saved.write_text("{", encoding="utf-8")
    assert run(args) == 0
    assert json.loads(capsys.readouterr().out)["snapshotSource"] == "built"
