"""Tests for incremental indexing and the two JSON artefacts (SPEC §8).

These tests drive the real scanner and parsers over temporary repositories so
they cover the whole pipeline: scan → (cached) parse → import resolution →
canonical index → cache.  They assert byte stability, cache reuse/invalidation,
incremental edit/delete/add semantics, bounded parse issues, and that indexing
never writes inside the repository when an explicit ``cache_dir`` is given.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codebase_intelligence.errors import RepositoryError
from codebase_intelligence.indexing import (
    CACHE_FILE_NAME,
    INDEX_FILE_NAME,
    SERVE_FILE_NAME,
    ensure_index,
    index_dir,
    load_served_index,
)
from codebase_intelligence.indexing.serving import read_serving_metadata, repository_stamp
from codebase_intelligence.indexing import engine as engine_module
from codebase_intelligence.model import Language
from codebase_intelligence.scanner import default_policy
from codebase_intelligence.util import canonical_json

PY_HELPERS = "def helper(value):\n    return value\n"
PY_APP = "from .helpers import helper\n\n\ndef main():\n    return helper(1)\n"


def write_repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    return root


def tree_files(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )


def read_index(result) -> dict:
    return json.loads(result.index_path.read_text(encoding="utf-8"))


def read_cache(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def symbol_names(snapshot) -> set[str]:
    return {symbol.name for symbol in snapshot.symbols}


# ---------------------------------------------------------------------------
# Determinism and artefact shape
# ---------------------------------------------------------------------------
def test_ensure_index_writes_canonical_deterministic_documents(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {
            "pkg/__init__.py": '"""Pkg."""\n',
            "pkg/helpers.py": PY_HELPERS,
            "pkg/app.py": PY_APP,
            "web/app.js": "import './util';\nconst x = 1;\n",
            "web/util.js": "export function util() {}\n",
            "README.md": "# demo\n",
        },
    )
    cache = tmp_path / "cache"

    first = ensure_index(root, cache_dir=cache)
    assert first.index_path == cache / INDEX_FILE_NAME
    assert first.index_path.is_file()
    assert (cache / CACHE_FILE_NAME).is_file()
    first_cache_bytes = (cache / CACHE_FILE_NAME).read_bytes()
    first_index_bytes = first.index_path.read_bytes()

    raw_index = first.index_path.read_text(encoding="utf-8")
    parsed = json.loads(raw_index)
    assert raw_index == canonical_json(parsed) + "\n"
    assert parsed["fingerprint"] == first.snapshot.fingerprint()
    assert parsed["schemaVersion"] == first.snapshot.schema_version
    assert parsed["engineVersion"] == engine_module.ENGINE_VERSION
    assert str(root) not in raw_index
    assert root.as_posix() not in raw_index

    cache_document = read_cache(cache / CACHE_FILE_NAME)
    for key in (
        "cacheVersion",
        "schemaVersion",
        "engineVersion",
        "policyFingerprint",
        "parserVersionsDigest",
        "files",
    ):
        assert key in cache_document
    app_entry = cache_document["files"]["pkg/app.py"]
    for key in ("sizeBytes", "mtimeNs", "sha256", "parserVersion", "parse"):
        assert key in app_entry
    assert app_entry["parserVersion"] == "ast-v1"

    second = ensure_index(root, cache_dir=cache)
    assert second.index_path.read_bytes() == first_index_bytes
    assert (cache / CACHE_FILE_NAME).read_bytes() == first_cache_bytes
    assert second.snapshot.fingerprint() == first.snapshot.fingerprint()
    assert second.cache.cache_hit is True
    assert second.cache.files_reparsed == 0
    assert sorted(path.name for path in cache.iterdir()) == [
        CACHE_FILE_NAME,
        INDEX_FILE_NAME,
        SERVE_FILE_NAME,
    ]


def test_second_run_reuses_cache_without_calling_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_repo(
        tmp_path / "repo",
        {"a.py": "def a():\n    return 1\n", "b.js": "const b = 1;\n"},
    )
    cache = tmp_path / "cache"
    calls = {"count": 0}
    real_parse = engine_module.parse_file

    def counting_parse(record, text):
        calls["count"] += 1
        return real_parse(record, text)

    monkeypatch.setattr(engine_module, "parse_file", counting_parse)
    first = ensure_index(root, cache_dir=cache)
    assert calls["count"] == 2
    assert first.cache.files_reparsed == 2

    calls["count"] = 0
    second = ensure_index(root, cache_dir=cache)
    assert calls["count"] == 0
    assert second.cache.files_reused == 2
    assert second.cache.files_reparsed == 0
    assert second.snapshot.fingerprint() == first.snapshot.fingerprint()


def test_index_roundtrips_through_public_dict(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {"pkg/helpers.py": PY_HELPERS, "pkg/app.py": PY_APP})
    result = ensure_index(root, cache_dir=tmp_path / "cache")
    payload = read_index(result)
    from codebase_intelligence.model import IndexSnapshot

    restored = IndexSnapshot.from_public_dict(payload)
    assert restored.fingerprint() == result.snapshot.fingerprint()
    assert [item.to_dict() for item in restored.files] == [
        item.to_dict() for item in result.snapshot.files
    ]
    assert [item.to_dict() for item in restored.symbols] == [
        item.to_dict() for item in result.snapshot.symbols
    ]
    assert [item.to_dict() for item in restored.relations] == [
        item.to_dict() for item in result.snapshot.relations
    ]
    assert [issue.to_dict() for issue in restored.parse_issues] == [
        issue.to_dict() for issue in result.snapshot.parse_issues
    ]


def test_index_contains_resolved_import_relations(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {"pkg/helpers.py": PY_HELPERS, "pkg/app.py": PY_APP})
    result = ensure_index(root, cache_dir=tmp_path / "cache")
    resolved = [
        relation
        for relation in result.snapshot.relations
        if relation.relation_type.value == "imports"
        and relation.status.value == "resolved"
    ]
    assert len(resolved) == 1
    assert resolved[0].source_id == "file:pkg/app.py"
    assert resolved[0].target_id == "file:pkg/helpers.py"
    assert resolved[0].evidence.value == "resolver"


# ---------------------------------------------------------------------------
# Incremental behaviour
# ---------------------------------------------------------------------------
def test_incremental_edit_delete_and_add(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {
            "a.py": "def alpha():\n    return 1\n",
            "b.py": "def beta():\n    return 2\n",
            "c.py": "def gamma():\n    return 3\n",
        },
    )
    cache = tmp_path / "cache"
    ensure_index(root, cache_dir=cache)

    with open(root / "b.py", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("def beta_two():\n    return 22\n")
    (root / "c.py").unlink()
    with open(root / "d.py", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("def delta():\n    return 4\n")

    result = ensure_index(root, cache_dir=cache)
    assert result.cache.files_reused == 1
    assert result.cache.files_reparsed == 2
    assert result.cache.files_removed == 1
    assert result.cache.cache_hit is False
    names = symbol_names(result.snapshot)
    assert {"beta_two", "delta", "alpha"} <= names
    assert "beta" not in names
    assert "gamma" not in names

    again = ensure_index(root, cache_dir=cache)
    assert again.cache.cache_hit is True
    assert again.cache.files_reused == 3
    assert again.snapshot.fingerprint() == result.snapshot.fingerprint()
    assert again.index_path.read_bytes() == result.index_path.read_bytes()


def test_content_change_with_same_size_and_mtime_reparses(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {"x.py": "def aaa():\n    return 1\n"})
    cache = tmp_path / "cache"
    ensure_index(root, cache_dir=cache)
    stat = (root / "x.py").stat()

    with open(root / "x.py", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("def bbb():\n    return 2\n")
    import os

    os.utime(root / "x.py", ns=(stat.st_atime_ns, stat.st_mtime_ns))

    result = ensure_index(root, cache_dir=cache)
    assert result.cache.files_reparsed == 1
    names = symbol_names(result.snapshot)
    assert "bbb" in names
    assert "aaa" not in names


def test_force_rebuild_reparses_everything_but_keeps_bytes(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {"a.py": "def alpha():\n    return 1\n", "b.py": "def beta():\n    return 2\n"},
    )
    cache = tmp_path / "cache"
    normal = ensure_index(root, cache_dir=cache)
    forced = ensure_index(root, cache_dir=cache, force=True)
    assert forced.cache.files_reparsed == 2
    assert forced.cache.files_reused == 0
    assert forced.cache.cache_hit is False
    assert forced.cache.files_removed == 0
    assert forced.snapshot.fingerprint() == normal.snapshot.fingerprint()
    assert forced.index_path.read_bytes() == normal.index_path.read_bytes()


def test_cache_dir_is_only_write_target(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {"pkg/helpers.py": PY_HELPERS, "pkg/app.py": PY_APP, "web/app.js": "const x = 1;\n"},
    )
    cache = tmp_path / "elsewhere" / "cache"
    before = tree_files(root)
    ensure_index(root, cache_dir=cache)
    assert tree_files(root) == before
    assert not (root / ".codebase-intelligence").exists()
    assert (cache / INDEX_FILE_NAME).is_file()


def test_default_cache_dir_lives_under_root_and_is_not_scanned(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {"a.py": "def a():\n    return 1\n"})
    result = ensure_index(root)
    expected_directory = index_dir(root)
    assert expected_directory == (root / ".codebase-intelligence").resolve()
    assert result.index_path == expected_directory / INDEX_FILE_NAME
    assert (expected_directory / CACHE_FILE_NAME).is_file()
    pages = {file.path for file in result.snapshot.files}
    assert pages == {"a.py"}

    second = ensure_index(root)
    assert second.cache.cache_hit is True
    assert {file.path for file in second.snapshot.files} == {"a.py"}
    assert sorted(path.name for path in expected_directory.iterdir()) == [
        CACHE_FILE_NAME,
        INDEX_FILE_NAME,
        SERVE_FILE_NAME,
    ]


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------
def test_policy_change_invalidates_cache(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {"small.py": "X = 1\n", "big.py": "Y = '" + "z" * 200 + "'\n"},
    )
    cache = tmp_path / "cache"
    first = ensure_index(root, cache_dir=cache)
    assert {file.path for file in first.snapshot.files} == {"big.py", "small.py"}

    limited_policy = default_policy(max_file_bytes=100)
    second = ensure_index(root, limited_policy, cache_dir=cache)
    assert {file.path for file in second.snapshot.files} == {"small.py"}
    assert second.snapshot.policy_fingerprint != first.snapshot.policy_fingerprint
    assert second.cache.files_reused == 0
    assert second.cache.files_reparsed == 1
    assert second.cache.cache_hit is False


def test_tampered_cache_header_forces_full_rebuild(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {"a.py": "def alpha():\n    return 1\n", "b.py": "def beta():\n    return 2\n"},
    )
    cache = tmp_path / "cache"
    first = ensure_index(root, cache_dir=cache)
    cache_path = cache / CACHE_FILE_NAME
    document = read_cache(cache_path)
    document["policyFingerprint"] = "0" * 64
    cache_path.write_text(canonical_json(document) + "\n", encoding="utf-8", newline="\n")

    second = ensure_index(root, cache_dir=cache)
    assert second.cache.files_reused == 0
    assert second.cache.files_reparsed == 2
    assert second.cache.cache_hit is False
    assert second.snapshot.fingerprint() == first.snapshot.fingerprint()

    # The cache was rewritten and is valid again.
    third = ensure_index(root, cache_dir=cache)
    assert third.cache.cache_hit is True


def test_tampered_parser_digest_forces_full_rebuild(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {"a.py": "def alpha():\n    return 1\n"})
    cache = tmp_path / "cache"
    ensure_index(root, cache_dir=cache)
    cache_path = cache / CACHE_FILE_NAME
    document = read_cache(cache_path)
    document["parserVersionsDigest"] = "f" * 64
    cache_path.write_text(canonical_json(document) + "\n", encoding="utf-8", newline="\n")
    result = ensure_index(root, cache_dir=cache)
    assert result.cache.files_reused == 0
    assert result.cache.cache_hit is False


def test_corrupt_cache_file_degrades_to_full_rebuild(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {"a.py": "def alpha():\n    return 1\n"})
    cache = tmp_path / "cache"
    ensure_index(root, cache_dir=cache)
    (cache / CACHE_FILE_NAME).write_text("{not json", encoding="utf-8", newline="\n")
    result = ensure_index(root, cache_dir=cache)
    assert result.cache.files_reparsed == 1
    assert result.cache.files_reused == 0
    assert (cache / CACHE_FILE_NAME).is_file()


def test_corrupt_single_cache_entry_is_ignored(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {"a.py": "def alpha():\n    return 1\n", "b.py": "def beta():\n    return 2\n"},
    )
    cache = tmp_path / "cache"
    ensure_index(root, cache_dir=cache)
    cache_path = cache / CACHE_FILE_NAME
    document = read_cache(cache_path)
    del document["files"]["a.py"]["parse"]
    cache_path.write_text(canonical_json(document) + "\n", encoding="utf-8", newline="\n")

    result = ensure_index(root, cache_dir=cache)
    assert result.cache.files_reparsed == 1
    assert result.cache.files_reused == 1


# ---------------------------------------------------------------------------
# Malformed / unsupported inputs
# ---------------------------------------------------------------------------
def test_parse_issues_are_recorded_and_bounded(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {
            "healthy.py": "def fine():\n    return 1\n",
            "broken.py": "def broken(:\n    return 1\n",
        },
    )
    result = ensure_index(root, cache_dir=tmp_path / "cache")
    assert len(result.snapshot.parse_issues) == 1
    issue = result.snapshot.parse_issues[0]
    assert issue.path == "broken.py"
    assert "syntax error" in issue.message
    assert len(issue.message) <= 300
    assert "fine" in symbol_names(result.snapshot)


def test_unsupported_language_is_indexed_as_file_only(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {"data.json": '{"a": 1}\n', "styles.css": "body { color: red; }\n"},
    )
    result = ensure_index(root, cache_dir=tmp_path / "cache")
    assert {file.path for file in result.snapshot.files} == {"data.json", "styles.css"}
    assert result.snapshot.symbols == ()
    assert result.snapshot.parse_issues == ()
    languages = {file.language for file in result.snapshot.files}
    assert languages == {Language.JSON, Language.CSS}


def test_indexing_never_executes_scanned_code(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        {
            "pwned.py": (
                "from pathlib import Path\n"
                'Path("pwned-marker.txt").write_text("executed")\n'
                'raise SystemExit("should never run")\n'
            )
        },
    )
    result = ensure_index(root, cache_dir=tmp_path / "cache")
    assert (root / "pwned.py").is_file()
    assert not (root / "pwned-marker.txt").exists()
    assert result.snapshot.files


# ---------------------------------------------------------------------------
# Helpers and errors
# ---------------------------------------------------------------------------
def test_index_dir_helper(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {"a.py": "X = 1\n"})
    assert index_dir(root) == (root / ".codebase-intelligence").resolve()
    custom = tmp_path / "my-index"
    assert index_dir(root, cache_dir=custom) == custom.resolve()
    policy = default_policy(index_dir_name=".custom-index")
    assert index_dir(root, policy) == (root / ".custom-index").resolve()


def test_missing_or_invalid_root_raises_repository_error(tmp_path: Path) -> None:
    with pytest.raises(RepositoryError):
        ensure_index(tmp_path / "does-not-exist")
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(RepositoryError):
        ensure_index(file_path)


def test_empty_repository_indexes_and_hits_cache(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {})
    cache = tmp_path / "cache"
    first = ensure_index(root, cache_dir=cache)
    assert first.snapshot.files == ()
    assert first.snapshot.symbols == ()
    assert first.index_path.is_file()
    second = ensure_index(root, cache_dir=cache)
    assert second.cache.cache_hit is True
    assert second.snapshot.fingerprint() == first.snapshot.fingerprint()
    assert second.index_path.read_bytes() == first.index_path.read_bytes()


def test_identical_bytes_across_cache_directories(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {"a.py": "def alpha():\n    return 1\n"})
    first = ensure_index(root, cache_dir=tmp_path / "cache-a")
    second = ensure_index(root, cache_dir=tmp_path / "cache-b")
    assert second.cache.files_reparsed == 1
    assert first.index_path.read_bytes() == second.index_path.read_bytes()
    assert first.snapshot.fingerprint() == second.snapshot.fingerprint()


def test_served_index_skips_rebuild_and_invalidates_on_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_repo(tmp_path / "repo", {"sample.py": "def original():\n    return 1\n"})
    cache = tmp_path / "cache"
    first = ensure_index(root, cache_dir=cache)
    metadata = read_serving_metadata(cache)
    assert metadata is not None
    assert metadata["defaultPolicy"] is True
    assert metadata["stamp"] == repository_stamp(root, cache)
    assert metadata["snapshotFingerprint"] == first.snapshot.fingerprint()

    from codebase_intelligence import api
    from codebase_intelligence.indexing import engine

    def unexpected_scan(*args: object, **kwargs: object) -> None:
        pytest.fail("served index unexpectedly rebuilt the index")

    with monkeypatch.context() as patch:
        patch.setattr(engine, "ensure_index", unexpected_scan)
        served = api.open_index(root, cache_dir=cache)
        assert served.cache.cache_hit is True
        assert served.snapshot.fingerprint() == first.snapshot.fingerprint()
        assert served.snapshot.files[0].path == "sample.py"

    assert load_served_index(root, cache_dir=cache) is not None
    (root / "sample.py").write_text("def updated():\n    return 2\n", encoding="utf-8")
    assert load_served_index(root, cache_dir=cache) is None
    refreshed = api.open_index(root, cache_dir=cache)
    assert refreshed.snapshot.fingerprint() != first.snapshot.fingerprint()
    assert any(symbol.name == "updated" for symbol in refreshed.snapshot.symbols)


def test_non_default_policy_is_not_served_from_default_sidecar(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", {"sample.py": "def original(): pass\n"})
    cache = tmp_path / "cache"
    ensure_index(root, cache_dir=cache)
    from codebase_intelligence import api

    ensure_index(root, api.build_policy(include_hidden=True), cache_dir=cache)
    assert load_served_index(root, cache_dir=cache) is None
