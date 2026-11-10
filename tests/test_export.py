"""Tests for deterministic ``cbi export`` (PANEL_CONTRACT §1/§2, SPEC §3/§4/§10/§11).

Coverage map:

* the fixed eight-file bundle, its payload shape and per-file statuses,
* byte determinism across repeated runs, fresh caches and checkout locations,
  and "unchanged files are not touched",
* ``--check``: writes nothing, exit 0/1, per-file plan, no index required,
* ``manifest.json``: sorted repo-relative entries, bytes/sha256 match the files,
  ``manifestFingerprint`` equals the sha256 of the manifest bytes,
* no timestamps / absolute paths / CRLF in any generated file,
* write safety: ``..``, absolute paths, symlinked components and file/directory
  collisions are refused, only the fixed names are written, nothing deleted,
* the generation directory is excluded from scan/index/overview (and stays
  excluded after an export), while unrelated same-named packages stay indexed,
* Mermaid graph, context brief and Markdown artifact content sanity,
* edge bound, label escaping and "build the index once" behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from codebase_intelligence import api
from codebase_intelligence import cli as cli_module
from codebase_intelligence import export as export_module
from codebase_intelligence.errors import OutsideRootError, RepositoryError, UsageError
from codebase_intelligence.export import (
    EXPORT_FILE_NAMES,
    GENERATED_FILE_NAMES,
    MANIFEST_FILE_NAME,
    MAX_DEPENDENCY_EDGES,
    MAP_MAX_TOKENS,
    OVERVIEW_MAX_TOKENS,
    build_export,
    render_bundle,
    render_context_brief,
    render_dependencies_mermaid,
    resolve_out_dir,
)
from codebase_intelligence.model import (
    EvidenceKind,
    FileRecord,
    IndexSnapshot,
    Language,
    RelationRecord,
    RelationType,
    ResolutionStatus,
    file_id,
)
from codebase_intelligence.scanner import scan_repository
from codebase_intelligence.scanner.discovery import SKIP_GENERATED_DIR
from codebase_intelligence.scanner.policy import DEFAULT_EXCLUDED_PATHS
from codebase_intelligence.util import canonical_json

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cli" / "demo_repo"

GENERATED_DIR = "docs/codebase-intelligence"
EXPECTED_PAIRS = {
    ("src/demo/__init__.py", "src/demo/core.py"),
    ("src/demo/core.py", "src/demo/util.py"),
    ("src/demo/sub/helper.py", "src/demo/core.py"),
    ("src/demo/sub/helper.py", "src/demo/util.py"),
    ("web/index.ts", "web/api.ts"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """A writable copy of the CLI demo fixture (exports never touch fixtures)."""

    target = tmp_path / name
    shutil.copytree(FIXTURE, target)
    return target


def cache_dir(tmp_path: Path, name: str = "cache") -> str:
    return str(tmp_path / name)


def run_cli(argv: list[str], capsys: Any) -> tuple[int, str, str]:
    code = cli_module.run(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def export_json(argv: list[str], capsys: Any, expected_code: int = 0) -> dict[str, Any]:
    code, out, err = run_cli([*argv, "--json"], capsys)
    assert code == expected_code, f"exit={code} stderr={err}"
    payload = json.loads(out)
    assert canonical_json(payload) + "\n" == out
    return payload


def bundle_paths(repo: Path, out_dir: str = GENERATED_DIR) -> dict[str, Path]:
    return {name: repo / out_dir / name for name in EXPORT_FILE_NAMES}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_mtime_ns(path: Path) -> int:
    return path.stat().st_mtime_ns


def symlink_or_skip(target: Path, link: Path, *, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")


def parse_mermaid(text: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    nodes: dict[str, str] = {}
    edges: list[tuple[str, str]] = []
    node_pattern = re.compile(r'^\s+(n\d+)\["(.*)"\]$')
    edge_pattern = re.compile(r"^\s+(n\d+) --> (n\d+)$")
    for line in text.splitlines():
        node_match = node_pattern.match(line)
        if node_match:
            nodes[node_match.group(1)] = node_match.group(2)
            continue
        edge_match = edge_pattern.match(line)
        if edge_match:
            edges.append((edge_match.group(1), edge_match.group(2)))
    return nodes, edges


# ---------------------------------------------------------------------------
# Bundle, payload shape and content
# ---------------------------------------------------------------------------
def test_export_writes_the_fixed_bundle(tmp_path: Path, capsys: Any) -> None:
    repo = make_repo(tmp_path)
    payload = export_json(
        ["export", str(repo), "--cache-dir", cache_dir(tmp_path)], capsys
    )

    assert set(payload) == {
        "ok",
        "schemaVersion",
        "command",
        "check",
        "outDir",
        "index",
        "files",
        "manifestFingerprint",
        "stale",
    }
    assert payload["ok"] is True
    assert payload["schemaVersion"] == "1"
    assert payload["command"] == "export"
    assert payload["check"] is False
    assert payload["outDir"] == GENERATED_DIR
    assert payload["stale"] is False
    assert set(payload["index"]) == {
        "schemaVersion",
        "engineVersion",
        "policyFingerprint",
        "fingerprint",
    }
    assert [item["path"] for item in payload["files"]] == [
        f"{GENERATED_DIR}/{name}" for name in EXPORT_FILE_NAMES
    ]
    assert [item["status"] for item in payload["files"]] == ["created"] * len(EXPORT_FILE_NAMES)
    rendered = canonical_json(payload)
    assert str(repo) not in rendered
    assert repo.as_posix() not in rendered
    assert str(tmp_path) not in rendered

    out_dir = repo / GENERATED_DIR
    assert sorted(item.name for item in out_dir.iterdir()) == sorted(EXPORT_FILE_NAMES)
    for item in payload["files"]:
        assert set(item) == {"path", "status", "bytes", "sha256"}
        target = repo / item["path"]
        assert target.is_file()
        assert target.stat().st_size == item["bytes"]
        assert sha256_file(target) == item["sha256"]


def test_two_builds_are_byte_identical_and_untouched(tmp_path: Path, capsys: Any) -> None:
    repo = make_repo(tmp_path)
    cache = cache_dir(tmp_path)
    first = export_json(["export", str(repo), "--cache-dir", cache], capsys)
    paths = bundle_paths(repo)
    before = {name: (path.read_bytes(), snapshot_mtime_ns(path)) for name, path in paths.items()}

    second = export_json(["export", str(repo), "--cache-dir", cache], capsys)
    assert [item["status"] for item in second["files"]] == [
        "unchanged"
    ] * len(EXPORT_FILE_NAMES)
    assert second["stale"] is False
    assert second["manifestFingerprint"] == first["manifestFingerprint"]
    assert second["index"] == first["index"]

    after = {name: (path.read_bytes(), snapshot_mtime_ns(path)) for name, path in paths.items()}
    assert after == before, "unchanged files must not be rewritten"


def test_determinism_across_checkout_locations_and_fresh_caches(
    tmp_path: Path, capsys: Any
) -> None:
    first_repo = make_repo(tmp_path, "first")
    second_repo = make_repo(tmp_path, "second")
    first = export_json(
        ["export", str(first_repo), "--cache-dir", cache_dir(tmp_path, "cache-a")], capsys
    )
    second = export_json(
        ["export", str(second_repo), "--cache-dir", cache_dir(tmp_path, "cache-b")], capsys
    )
    # The payload itself is location/fingerprint independent (no absolute paths).
    assert canonical_json(first) == canonical_json(second)
    for name in EXPORT_FILE_NAMES:
        assert (first_repo / GENERATED_DIR / name).read_bytes() == (
            second_repo / GENERATED_DIR / name
        ).read_bytes(), name

    # A rebuild with a completely different cache must not change a single byte.
    baseline = {name: (first_repo / GENERATED_DIR / name).read_bytes() for name in EXPORT_FILE_NAMES}
    third = export_json(
        ["export", str(first_repo), "--cache-dir", cache_dir(tmp_path, "cache-c")], capsys
    )
    assert third["manifestFingerprint"] == first["manifestFingerprint"]
    for name in EXPORT_FILE_NAMES:
        assert (first_repo / GENERATED_DIR / name).read_bytes() == baseline[name], name


def test_manifest_hashes_bytes_and_fingerprint(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    result = build_export(repo, cache_dir=cache_dir(tmp_path))
    manifest_path = repo / GENERATED_DIR / MANIFEST_FILE_NAME
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)

    assert set(manifest) == {
        "schemaVersion",
        "engineVersion",
        "policyFingerprint",
        "fingerprint",
        "outDir",
        "files",
    }
    assert manifest["schemaVersion"] == "1"
    assert manifest["engineVersion"] == "0.1.0"
    assert manifest["fingerprint"] == result.index["fingerprint"]
    assert manifest["policyFingerprint"] == result.index["policyFingerprint"]
    assert manifest["outDir"] == GENERATED_DIR
    assert canonical_json(manifest) + "\n" == manifest_bytes.decode("utf-8")

    entries = manifest["files"]
    assert [entry["path"] for entry in entries] == sorted(entry["path"] for entry in entries)
    assert {entry["path"] for entry in entries} == {
        f"{GENERATED_DIR}/{name}" for name in GENERATED_FILE_NAMES
    }
    for entry in entries:
        target = repo / entry["path"]
        assert entry["bytes"] == target.stat().st_size
        assert entry["sha256"] == sha256_file(target)

    assert result.manifest_fingerprint == hashlib.sha256(manifest_bytes).hexdigest()
    assert MANIFEST_FILE_NAME not in {entry["path"].rsplit("/", 1)[-1] for entry in entries}


def test_generated_files_have_no_volatile_values_and_are_canonical(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    result = build_export(repo, cache_dir=cache_dir(tmp_path))
    paths = bundle_paths(repo)
    for name, path in paths.items():
        data = path.read_bytes()
        text = data.decode("utf-8")
        assert b"\r" not in data, f"{name} must be LF-only"
        for forbidden in (
            str(repo),
            repo.as_posix(),
            str(tmp_path),
            "generated at",
            "Generated at",
        ):
            assert forbidden not in text, f"{name} leaked {forbidden!r}"
        assert "\\" not in text, f"{name} must use repository-relative POSIX paths"
        for pattern in (
            r"\b(19|20)\d{2}-\d{2}-\d{2}",
            r"\d{2}:\d{2}:\d{2}",
            r"\b\d{4}-\d{2}-\d{2}T",
        ):
            assert re.search(pattern, text) is None, f"{name} looks like it has a timestamp"
        if name.endswith(".json"):
            parsed = json.loads(text)
            assert canonical_json(parsed) + "\n" == text, f"{name} is not canonical JSON"
            if name == MANIFEST_FILE_NAME:
                assert parsed["fingerprint"] == result.index["fingerprint"]
            elif name == "graph.snapshot.json":
                assert parsed["graph"]["policyFingerprint"] == result.index["policyFingerprint"]
            else:
                assert parsed["index"]["fingerprint"] == result.index["fingerprint"]


def test_json_artifacts_use_the_export_budgets(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    result = build_export(repo, cache_dir=cache_dir(tmp_path))
    overview = json.loads((repo / GENERATED_DIR / "overview.json").read_text(encoding="utf-8"))
    repo_map = json.loads((repo / GENERATED_DIR / "repo-map.json").read_text(encoding="utf-8"))
    assert overview["command"] == "overview"
    assert overview["budgets"]["maxTokens"] == OVERVIEW_MAX_TOKENS
    assert overview["budgets"]["tokensEstimated"] <= OVERVIEW_MAX_TOKENS
    assert repo_map["command"] == "map"
    assert repo_map["budgets"]["maxTokens"] == MAP_MAX_TOKENS
    assert repo_map["budgets"]["tokensEstimated"] <= MAP_MAX_TOKENS
    for payload in (overview, repo_map):
        assert payload["index"]["fingerprint"] == result.index["fingerprint"]
        assert payload["ok"] is True


def test_markdown_artifacts_cite_repository_paths(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    build_export(repo, cache_dir=cache_dir(tmp_path))
    architecture = (repo / GENERATED_DIR / "ARCHITECTURE.generated.md").read_text(encoding="utf-8")
    repo_map = (repo / GENERATED_DIR / "REPO_MAP.md").read_text(encoding="utf-8")
    assert architecture.startswith("# Architecture report")
    assert "src/demo/core.py:" in architecture
    assert "## Limitations" in architecture
    assert repo_map.startswith("# Repository map")
    assert "### src/demo/core.py" in repo_map
    assert str(repo) not in architecture
    assert str(repo) not in repo_map


def test_empty_repository_export_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    first = build_export(root, cache_dir=cache_dir(tmp_path, "cache-a"))
    assert [item.status for item in first.files] == ["created"] * len(EXPORT_FILE_NAMES)
    mermaid = (root / GENERATED_DIR / "dependencies.mmd").read_text(encoding="utf-8")
    assert "%% no resolved import edges between indexed files" in mermaid
    brief = (root / GENERATED_DIR / "CONTEXT_BRIEF.md").read_text(encoding="utf-8")
    assert "- none: no files were indexed" in brief
    second = build_export(root, cache_dir=cache_dir(tmp_path, "cache-b"))
    assert [item.status for item in second.files] == ["unchanged"] * len(EXPORT_FILE_NAMES)
    assert second.manifest_fingerprint == first.manifest_fingerprint


# ---------------------------------------------------------------------------
# --check contract
# ---------------------------------------------------------------------------
def test_check_passes_on_a_fresh_export(tmp_path: Path, capsys: Any) -> None:
    repo = make_repo(tmp_path)
    cache = cache_dir(tmp_path)
    export_json(["export", str(repo), "--cache-dir", cache], capsys)
    paths = bundle_paths(repo)
    before = {name: (path.read_bytes(), snapshot_mtime_ns(path)) for name, path in paths.items()}

    payload = export_json(["export", str(repo), "--check", "--cache-dir", cache], capsys)
    assert payload["check"] is True
    assert payload["stale"] is False
    assert [item["status"] for item in payload["files"]] == ["unchanged"] * len(EXPORT_FILE_NAMES)
    after = {name: (path.read_bytes(), snapshot_mtime_ns(path)) for name, path in paths.items()}
    assert after == before, "--check must not write"


def test_check_reports_tampered_missing_and_restores(tmp_path: Path, capsys: Any) -> None:
    repo = make_repo(tmp_path)
    cache = cache_dir(tmp_path)
    export_json(["export", str(repo), "--cache-dir", cache], capsys)

    (repo / GENERATED_DIR / "overview.json").write_text("tampered\n", encoding="utf-8")
    (repo / GENERATED_DIR / "REPO_MAP.md").unlink()
    payload = export_json(
        ["export", str(repo), "--check", "--cache-dir", cache], capsys, expected_code=1
    )
    assert payload["stale"] is True
    statuses = {item["path"].rsplit("/", 1)[-1]: item["status"] for item in payload["files"]}
    assert statuses["overview.json"] == "updated"
    assert statuses["REPO_MAP.md"] == "created"
    assert statuses["manifest.json"] in {"unchanged", "updated"}

    fixed = export_json(["export", str(repo), "--cache-dir", cache], capsys)
    fixed_statuses = {item["path"].rsplit("/", 1)[-1]: item["status"] for item in fixed["files"]}
    assert fixed_statuses["overview.json"] == "updated"
    assert fixed_statuses["REPO_MAP.md"] == "created"
    assert export_json(
        ["export", str(repo), "--check", "--cache-dir", cache], capsys
    )["stale"] is False


def test_check_without_generation_directory_neither_writes_nor_needs_an_index(
    tmp_path: Path, capsys: Any
) -> None:
    repo = make_repo(tmp_path)
    cache = cache_dir(tmp_path)
    payload = export_json(
        ["export", str(repo), "--check", "--cache-dir", cache], capsys, expected_code=1
    )
    assert payload["stale"] is True
    assert [item["status"] for item in payload["files"]] == ["created"] * len(EXPORT_FILE_NAMES)
    assert not (repo / GENERATED_DIR).exists()
    assert (tmp_path / "cache" / "index.v1.json").is_file()


def test_human_output_for_write_and_check(tmp_path: Path, capsys: Any) -> None:
    repo = make_repo(tmp_path)
    cache = cache_dir(tmp_path)
    code, out, _ = run_cli(["export", str(repo), "--cache-dir", cache], capsys)
    assert code == 0
    assert f"exported {len(EXPORT_FILE_NAMES)} file(s) under {GENERATED_DIR}" in out
    assert "manifest " in out

    code, out, _ = run_cli(["export", str(repo), "--check", "--cache-dir", cache], capsys)
    assert code == 0
    assert "up to date" in out

    (repo / GENERATED_DIR / "overview.json").write_text("{}\n", encoding="utf-8")
    code, out, _ = run_cli(["export", str(repo), "--check", "--cache-dir", cache], capsys)
    assert code == 1
    assert "stale" in out
    assert "updated" in out


# ---------------------------------------------------------------------------
# Manifest write order and "index built once"
# ---------------------------------------------------------------------------
def test_manifest_is_written_last(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = make_repo(tmp_path)
    written: list[str] = []
    original = export_module._atomic_write

    def recording_write(path: Path, data: bytes) -> None:
        written.append(path.name)
        original(path, data)

    monkeypatch.setattr(export_module, "_atomic_write", recording_write)
    build_export(repo, cache_dir=cache_dir(tmp_path))
    assert written == list(EXPORT_FILE_NAMES)
    assert written[-1] == MANIFEST_FILE_NAME


def test_index_is_built_exactly_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from codebase_intelligence import indexing

    calls: list[Path] = []
    original = indexing.ensure_index

    def counting_ensure_index(root: Any, policy: Any = None, **kwargs: Any) -> Any:
        calls.append(Path(root))
        return original(root, policy, **kwargs)

    monkeypatch.setattr(indexing, "ensure_index", counting_ensure_index)
    build_export(make_repo(tmp_path), cache_dir=cache_dir(tmp_path))
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Write safety
# ---------------------------------------------------------------------------
def test_relative_traversal_is_refused(tmp_path: Path, capsys: Any) -> None:
    repo = make_repo(tmp_path)
    for bad in ("../escape", "docs/../../escape", "a/../b"):
        code, out, _ = run_cli(
            ["export", str(repo), "--out", bad, "--json", "--cache-dir", cache_dir(tmp_path)],
            capsys,
        )
        assert code == 2, bad
        payload = json.loads(out)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "invalid_arguments"
    assert not (tmp_path / "escape").exists()
    assert not (repo / "b").exists()


def test_absolute_out_paths_are_refused(tmp_path: Path, capsys: Any) -> None:
    repo = make_repo(tmp_path)
    for bad in (str(tmp_path / "outside"), str(repo / "docs" / "absolute-target")):
        code, out, _ = run_cli(
            ["export", str(repo), "--out", bad, "--json", "--cache-dir", cache_dir(tmp_path)],
            capsys,
        )
        assert code == 2, bad
        assert json.loads(out)["error"]["code"] == "invalid_arguments"
    assert not (tmp_path / "outside").exists()
    assert not (repo / "docs" / "absolute-target").exists()


def test_symlinked_out_directory_is_refused(tmp_path: Path, capsys: Any) -> None:
    repo = make_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_or_skip(outside, repo / "docs-link", is_dir=True)
    code, out, _ = run_cli(
        ["export", str(repo), "--out", "docs-link", "--json", "--cache-dir", cache_dir(tmp_path)],
        capsys,
    )
    assert code == 3
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "outside_root"
    assert list(outside.iterdir()) == []


def test_symlinked_target_file_is_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    out_dir = repo / GENERATED_DIR
    out_dir.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside content\n", encoding="utf-8")
    symlink_or_skip(outside, out_dir / "REPO_MAP.md")
    with pytest.raises(OutsideRootError) as raised:
        build_export(repo, cache_dir=cache_dir(tmp_path))
    assert raised.value.code == "outside_root"
    assert outside.read_text(encoding="utf-8") == "outside content\n"


def test_file_and_directory_collisions_are_refused(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / GENERATED_DIR).parent.mkdir(parents=True, exist_ok=True)
    (repo / GENERATED_DIR).write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(RepositoryError) as raised:
        build_export(repo, cache_dir=cache_dir(tmp_path))
    assert raised.value.code == "export_failed"
    assert (repo / GENERATED_DIR).read_text(encoding="utf-8") == "not a directory\n"


def test_only_fixed_files_are_written_and_other_files_kept(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    out_dir = repo / GENERATED_DIR
    out_dir.mkdir(parents=True)
    keep = out_dir / "operator-notes.txt"
    keep.write_text("keep me\n", encoding="utf-8")
    unrelated = repo / "src" / "demo" / "core.py"
    unrelated_before = unrelated.read_bytes()

    build_export(repo, cache_dir=cache_dir(tmp_path))
    assert sorted(item.name for item in out_dir.iterdir()) == sorted(
        [*EXPORT_FILE_NAMES, "operator-notes.txt"]
    )
    assert keep.read_text(encoding="utf-8") == "keep me\n"
    assert unrelated.read_bytes() == unrelated_before
    assert not (tmp_path / "escape").exists()


def test_missing_root_is_a_repository_error(tmp_path: Path, capsys: Any) -> None:
    missing = tmp_path / "does-not-exist"
    code, out, _ = run_cli(["export", str(missing), "--json"], capsys)
    assert code == 3
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_a_directory"


def test_resolve_out_dir_normalizes_and_validates(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    path, relative = resolve_out_dir(root, None)
    assert relative == GENERATED_DIR
    assert path == root / GENERATED_DIR
    assert resolve_out_dir(root, "")[1] == GENERATED_DIR
    assert resolve_out_dir(root, "docs/panel/")[1] == "docs/panel"
    assert resolve_out_dir(root, "./docs/./panel/")[1] == "docs/panel"
    assert resolve_out_dir(root, Path("nested/out"))[1] == "nested/out"
    for bad in (".", "   ", "../escape", "docs/../escape", "a/../b", str(tmp_path / "absolute")):
        with pytest.raises(UsageError):
            resolve_out_dir(root, bad)


# ---------------------------------------------------------------------------
# Generation-directory exclusion from scan/index
# ---------------------------------------------------------------------------
def test_generated_directory_is_excluded_from_scan_and_index(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    artifacts = repo / GENERATED_DIR
    artifacts.mkdir(parents=True)
    (artifacts / "artifact.py").write_text("GENERATED = True\n", encoding="utf-8")
    cache = cache_dir(tmp_path, "index-cache")

    scan = scan_repository(repo)
    assert DEFAULT_EXCLUDED_PATHS == (GENERATED_DIR,)
    assert scan.stats.skip_map()[SKIP_GENERATED_DIR] == 1
    assert not [path for path in scan.paths() if path.startswith(f"{GENERATED_DIR}/")]
    assert "src/demo/core.py" in scan.paths()

    scan_payload = api.scan_payload(repo)
    assert not [
        item["path"]
        for item in scan_payload["files"]
        if item["path"].startswith(f"{GENERATED_DIR}/")
    ]
    index_payload = api.index_payload(repo, cache_dir=Path(cache))
    assert index_payload["repo"]["files"] == len(scan.files)
    overview = api.run_overview(repo, cache_dir=Path(cache))
    assert overview["repo"]["files"] == len(scan.files)

    # Exporting does not feed the generated files back into the index.
    build_export(repo, cache_dir=cache)
    after_scan = scan_repository(repo)
    assert after_scan.paths() == scan.paths()
    after_index = api.index_payload(repo, cache_dir=Path(cache), force=True)
    assert after_index["repo"]["files"] == len(scan.files)
    assert after_index["index"]["fingerprint"] == index_payload["index"]["fingerprint"]


def test_same_basename_elsewhere_is_still_indexed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    package = repo / "src" / "codebase-intelligence"
    package.mkdir(parents=True)
    (package / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    duplicate_name = repo / "foo" / "codebase-intelligence"
    duplicate_name.mkdir(parents=True)
    (duplicate_name / "notes.md").write_text("# notes\n", encoding="utf-8")

    build_export(repo, cache_dir=cache_dir(tmp_path))
    scan = scan_repository(repo)
    assert "src/codebase-intelligence/mod.py" in scan.paths()
    assert "foo/codebase-intelligence/notes.md" in scan.paths()
    assert not [path for path in scan.paths() if path.startswith(f"{GENERATED_DIR}/")]
    assert scan.stats.skip_map()[SKIP_GENERATED_DIR] == 1


def test_custom_out_directory_stays_deterministic(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    cache = cache_dir(tmp_path)
    first = build_export(repo, out="generated/panel", cache_dir=cache)
    assert first.out_dir == "generated/panel"
    assert first.stale is False
    second = build_export(repo, out="generated/panel", cache_dir=cache)
    assert [item.status for item in second.files] == ["unchanged"] * len(EXPORT_FILE_NAMES)
    assert second.manifest_fingerprint == first.manifest_fingerprint
    manifest = json.loads(
        (repo / "generated" / "panel" / MANIFEST_FILE_NAME).read_text(encoding="utf-8")
    )
    assert manifest["outDir"] == "generated/panel"
    # The export's own index build excludes the custom generation directory, so a
    # second export never renders a bundle that includes the first bundle.
    export_policy = api.build_policy(excludes=(f"{first.out_dir}/",))
    assert not [
        path for path in scan_repository(repo, export_policy).paths() if path.startswith("generated/")
    ]


def test_export_honors_policy_flags(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    default = build_export(repo, cache_dir=cache_dir(tmp_path, "cache-default"))
    default_overview = json.loads(
        (repo / GENERATED_DIR / "overview.json").read_text(encoding="utf-8")
    )

    limited = build_export(repo, cache_dir=cache_dir(tmp_path, "cache-limited"), max_file_bytes=100)
    limited_overview = json.loads(
        (repo / GENERATED_DIR / "overview.json").read_text(encoding="utf-8")
    )
    assert limited_overview["repo"]["files"] < default_overview["repo"]["files"]
    assert limited.index["policyFingerprint"] != default.index["policyFingerprint"]

    excluded = build_export(
        repo, cache_dir=cache_dir(tmp_path, "cache-excluded"), excludes=("src/demo/",)
    )
    repo_map = json.loads((repo / GENERATED_DIR / "repo-map.json").read_text(encoding="utf-8"))
    assert not [entry for entry in repo_map["entries"] if entry["path"].startswith("src/demo/")]
    assert excluded.index["policyFingerprint"] != default.index["policyFingerprint"]


# ---------------------------------------------------------------------------
# dependencies.mmd
# ---------------------------------------------------------------------------
def test_dependencies_mermaid_matches_resolved_imports(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    result = build_export(repo, cache_dir=cache_dir(tmp_path))
    text = (repo / GENERATED_DIR / "dependencies.mmd").read_text(encoding="utf-8")

    assert text.startswith("%% Codebase Intelligence dependency graph")
    assert f"%% index fingerprint: {result.index['fingerprint']}" in text
    assert "graph LR" in text
    assert "not dependencies" in text
    assert "file:" not in text
    assert "sym:" not in text

    nodes, edges = parse_mermaid(text)
    assert nodes and edges
    assert set(nodes.values()) == {
        path for pair in EXPECTED_PAIRS for path in pair
    }
    assert {(nodes[source], nodes[target]) for source, target in edges} == EXPECTED_PAIRS
    # Node ids follow sorted path order so the ids are stable.
    assert [nodes[f"n{index}"] for index in range(len(nodes))] == sorted(nodes.values())
    assert len(edges) == len(EXPECTED_PAIRS)
    assert "%% resolved import edges among indexed files: 5" in text
    assert "%% omitted 3 unresolved/external/out-of-scope import edge(s)" in text


def test_dependencies_mermaid_edge_bound_and_label_escaping() -> None:
    files = [
        FileRecord(
            path=f"src/file-{index:03d}.py",
            language=Language.PYTHON,
            size_bytes=1,
            sha256="0" * 64,
            line_count=1,
        )
        for index in range(MAX_DEPENDENCY_EDGES + 20)
    ]
    target = files[0].path
    relations = [
        RelationRecord(
            source_id=file_id(record.path),
            relation_type=RelationType.IMPORTS,
            status=ResolutionStatus.RESOLVED,
            evidence=EvidenceKind.RESOLVER,
            target_id=file_id(target),
            confidence=1.0,
        )
        for record in files[1:]
    ]
    relations.extend(
        [
            RelationRecord(
                source_id=file_id(target),
                relation_type=RelationType.IMPORTS,
                status=ResolutionStatus.UNRESOLVED,
                evidence=EvidenceKind.HEURISTIC,
                target_name="missing.module",
            ),
            RelationRecord(
                source_id=file_id(target),
                relation_type=RelationType.IMPORTS,
                status=ResolutionStatus.EXTERNAL,
                evidence=EvidenceKind.RESOLVER,
                target_name="os",
            ),
            RelationRecord(
                source_id=file_id(target),
                relation_type=RelationType.CONTAINS,
                status=ResolutionStatus.RESOLVED,
                evidence=EvidenceKind.PARSER,
            ),
        ]
    )
    snapshot = IndexSnapshot.build(
        engine_version="0.1.0",
        policy_fingerprint="policy",
        root="",
        files=files,
        symbols=(),
        relations=relations,
    )
    text = render_dependencies_mermaid(
        snapshot,
        {
            "fingerprint": "fingerprint",
            "engineVersion": "0.1.0",
            "schemaVersion": "1",
            "policyFingerprint": "policy",
        },
    )
    _, edges = parse_mermaid(text)
    assert len(edges) == MAX_DEPENDENCY_EDGES
    assert f"%% resolved import edges among indexed files: {len(files) - 1}" in text
    assert "edge bound" in text
    assert "%% omitted 2 unresolved/external/out-of-scope import edge(s)" in text
    assert render_dependencies_mermaid(snapshot, {"fingerprint": "x"}) == render_dependencies_mermaid(
        snapshot, {"fingerprint": "x"}
    )

    weird = IndexSnapshot.build(
        engine_version="0.1.0",
        policy_fingerprint="policy",
        root="",
        files=[
            FileRecord(
                path='src/a&b "quoted".py',
                language=Language.PYTHON,
                size_bytes=1,
                sha256="0" * 64,
                line_count=1,
            ),
            FileRecord(
                path="src/plain.py",
                language=Language.PYTHON,
                size_bytes=1,
                sha256="0" * 64,
                line_count=1,
            ),
        ],
        symbols=(),
        relations=(
            RelationRecord(
                source_id=file_id("src/plain.py"),
                relation_type=RelationType.IMPORTS,
                status=ResolutionStatus.RESOLVED,
                evidence=EvidenceKind.RESOLVER,
                target_id=file_id('src/a&b "quoted".py'),
                confidence=1.0,
            ),
        ),
    )
    escaped = render_dependencies_mermaid(weird, {"fingerprint": "x"})
    assert 'src/a&amp;b &quot;quoted&quot;.py' in escaped


# ---------------------------------------------------------------------------
# CONTEXT_BRIEF.md and bundle purity
# ---------------------------------------------------------------------------
class _NullGraph:
    """Minimal graph double for snapshots without relations."""

    def file_dependents(self, path: str) -> tuple[str, ...]:
        return ()

    def file_imports(self, path: str) -> tuple[str, ...]:
        return ()


def _empty_snapshot() -> IndexSnapshot:
    return IndexSnapshot.build(
        engine_version="0.1.0",
        policy_fingerprint="policy",
        root="",
        files=(),
        symbols=(),
        relations=(),
    )


def test_context_brief_is_a_useful_deterministic_orientation(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    result = build_export(repo, cache_dir=cache_dir(tmp_path))
    text = (repo / GENERATED_DIR / "CONTEXT_BRIEF.md").read_text(encoding="utf-8")
    file_count = len(scan_repository(repo).files)

    assert text.startswith("# Codebase intelligence brief")
    for heading in (
        "## Snapshot",
        "## Languages",
        "## Entry points",
        "## Top modules by resolved in-degree",
        "## Files with the most declarations",
        "## How to query this codebase",
        "## Limitations",
    ):
        assert heading in text
    assert f"index fingerprint: `{result.index['fingerprint']}`" in text
    assert f"- files: {file_count}" in text
    assert "python:" in text
    assert "src/demo/core.py:29" in text and "src.demo.core.main" in text
    assert "`src/demo/core.py` - imported by 2 file(s)" in text
    assert "cbi overview . --json" in text
    assert "cbi context . --task" in text
    assert str(repo) not in text
    assert str(tmp_path) not in text

    index = {"fingerprint": "f", "engineVersion": "0.1.0", "schemaVersion": "1"}
    assert render_context_brief(
        _empty_snapshot(), _NullGraph(), index, out_dir="docs/custom"
    ) == render_context_brief(_empty_snapshot(), _NullGraph(), index, out_dir="docs/custom")
    empty_text = render_context_brief(_empty_snapshot(), _NullGraph(), index, out_dir="docs/custom")
    assert "- none: no files were indexed" in empty_text
    assert "docs/custom" in empty_text


def test_render_bundle_is_pure_and_ordered() -> None:
    graph = _NullGraph()
    first = render_bundle(_empty_snapshot(), graph, out_dir=GENERATED_DIR)
    second = render_bundle(_empty_snapshot(), graph, out_dir=GENERATED_DIR)
    assert list(first) == list(EXPORT_FILE_NAMES)
    assert first == second
    for name, data in first.items():
        assert isinstance(data, bytes) and data
        assert data.endswith(b"\n"), name
    assert json.loads(first[MANIFEST_FILE_NAME])["outDir"] == GENERATED_DIR
