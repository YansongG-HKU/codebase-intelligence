"""Tests for deterministic repository discovery and the frozen scan policy.

Coverage map (``docs/SPEC.md`` section 5):

* language detection and default policy contract,
* ``.gitignore`` subset: comments, blanks, negation, anchoring, trailing slash,
  ``**`` / ``*`` / ``?`` / character classes, last-match-wins, nested files,
  parent-excluded directories not re-included,
* default excludes, index directory, hidden entries,
* secret-name filtering plus the explicit ``CBI_INCLUDE_SECRETS=1`` override,
* binary and oversize skipping, line counting and sha256,
* symlinks: skipped by default, out-of-root escape rejection, in-root follow,
  directory cycle detection, symlinked ignore file never read outside root,
* unicode paths, determinism of two identical scans and of two checkout
  locations (no absolute paths or timestamps in payloads / fingerprints).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from codebase_intelligence.errors import RepositoryError
from codebase_intelligence.model import Language
from codebase_intelligence.scanner import (
    DEFAULT_EXCLUDES,
    DEFAULT_SECRET_PATTERNS,
    INCLUDE_SECRETS_ENV,
    SECRET_PATTERNS,
    ScanPolicy,
    ScanResult,
    default_policy,
    detect_language,
    include_secrets_from_env,
    is_secret_name,
    policy_fingerprint,
    scan_repository,
)
from codebase_intelligence.scanner.discovery import (
    SKIP_BINARY,
    SKIP_CYCLE,
    SKIP_DEFAULT_EXCLUDE,
    SKIP_EXTRA_EXCLUDE,
    SKIP_GENERATED_DIR,
    SKIP_GITIGNORE,
    SKIP_HIDDEN,
    SKIP_INDEX_DIR,
    SKIP_OVERSIZE,
    SKIP_PATH_ESCAPE,
    SKIP_SECRET,
    SKIP_SYMLINK,
    SKIP_SYMLINK_ESCAPE,
)
from codebase_intelligence.scanner.gitignore import GitIgnoreMatcher
from codebase_intelligence.scanner.policy import DEFAULT_EXCLUDED_PATHS
from codebase_intelligence.util import canonical_json

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scanner"

GITIGNORE_EXPECTED = [
    "app.py",
    "datax.bin",
    "keep.log",
    "notes/readme.md",
    "notes/temp-ab.txt",
    "other/root-only.txt",
    "src/main.py",
    "src/nested/code.py",
    "src/nested/deeper/anchored.txt",
    "src/nested/important.tmp",
    "src/nested/nested.log",
]

NO_GITIGNORE_EXPECTED = [
    "app.py",
    "blocked/include-me.py",
    "data1.bin",
    "datax.bin",
    "debug.log",
    "keep.log",
    "notes/cache/ignored.py",
    "notes/readme.md",
    "notes/temp-a.txt",
    "notes/temp-ab.txt",
    "other/root-only.txt",
    "root-only.txt",
    "src/generated/out.py",
    "src/main.py",
    "src/nested/anchored.txt",
    "src/nested/code.py",
    "src/nested/deeper/anchored.txt",
    "src/nested/deeper/other.tmp",
    "src/nested/important.tmp",
    "src/nested/nested.log",
    "src/nested/scratch.tmp",
]

SECRETS_VISIBLE = [
    "app.py",
    "credentials.json",
    "id_ed25519.pub",
    "id_rsa",
    "identity.pfx",
    "private.key",
    "safe.txt",
    "secrets.yaml",
    "server.pem",
    "store.p12",
    "vault.kdbx",
]

SECRETS_ALL = [".env", ".env.local", ".netrc", ".npmrc", *SECRETS_VISIBLE]


def scan_fixture(name: str, policy: ScanPolicy | None = None) -> ScanResult:
    return scan_repository(FIXTURES / name, policy)


def skip_map(result: ScanResult) -> dict[str, int]:
    return result.stats.skip_map()


def symlink_or_skip(target: Path, link: Path, *, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")


# ---------------------------------------------------------------------------
# language detection and policy contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/app.py", Language.PYTHON),
        ("src/APP.PY", Language.PYTHON),
        ("pkg/types.pyi", Language.PYTHON),
        ("web/app.js", Language.JAVASCRIPT),
        ("web/app.mjs", Language.JAVASCRIPT),
        ("web/app.cjs", Language.JAVASCRIPT),
        ("web/app.jsx", Language.JAVASCRIPT),
        ("web/app.ts", Language.TYPESCRIPT),
        ("web/app.tsx", Language.TYPESCRIPT),
        ("cmd/main.go", Language.GO),
        ("src/lib.rs", Language.RUST),
        ("src/Main.java", Language.JAVA),
        ("src/util.c", Language.C),
        ("src/util.h", Language.C),
        ("src/util.cpp", Language.CPP),
        ("src/util.hpp", Language.CPP),
        ("src/Program.cs", Language.CSHARP),
        ("app/models.rb", Language.RUBY),
        ("Rakefile", Language.RUBY),
        ("web/index.php", Language.PHP),
        ("scripts/deploy.sh", Language.SHELL),
        ("scripts/deploy.bash", Language.SHELL),
        (".bashrc", Language.SHELL),
        ("index.html", Language.HTML),
        ("styles/site.css", Language.CSS),
        ("styles/site.scss", Language.CSS),
        ("data/config.json", Language.JSON),
        ("data/config.yaml", Language.YAML),
        ("data/config.yml", Language.YAML),
        ("pyproject.toml", Language.TOML),
        ("docs/readme.md", Language.MARKDOWN),
        ("docs/readme.markdown", Language.MARKDOWN),
        ("db/schema.sql", Language.SQL),
        ("plainfile", Language.OTHER),
        ("Makefile", Language.OTHER),
        ("LICENSE", Language.OTHER),
        (".env", Language.OTHER),
        ("archive.tar.gz", Language.OTHER),
        ("", Language.OTHER),
    ],
)
def test_detect_language(path: str, expected: Language) -> None:
    assert detect_language(path) is expected


def test_detect_language_accepts_windows_separators() -> None:
    assert detect_language("src\\pkg\\module.py") is Language.PYTHON
    assert detect_language("web\\app.tsx") is Language.TYPESCRIPT


def test_default_policy_contract() -> None:
    policy = default_policy()
    assert policy == ScanPolicy()
    assert policy.max_file_bytes == 1_048_576
    assert policy.follow_symlinks is False
    assert policy.use_gitignore is True
    assert policy.include_hidden is False
    assert policy.index_dir_name == ".codebase-intelligence"
    assert policy.extra_excludes == ()
    assert policy.default_excludes == DEFAULT_EXCLUDES
    assert policy.default_excludes == (
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "build",
        "dist",
        "target",
        "vendor",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "coverage",
        ".idea",
        ".vscode",
    )
    assert policy.excluded_paths == DEFAULT_EXCLUDED_PATHS
    assert policy.excluded_paths == ("docs/codebase-intelligence",)
    assert policy.secret_patterns == DEFAULT_SECRET_PATTERNS
    assert SECRET_PATTERNS is DEFAULT_SECRET_PATTERNS
    assert "*.pem" in policy.secret_patterns
    assert "id_rsa*" in policy.secret_patterns
    assert ".env.*" in policy.secret_patterns


def test_scan_policy_is_frozen() -> None:
    policy = default_policy()
    with pytest.raises(FrozenInstanceError):
        policy.max_file_bytes = 2  # type: ignore[misc]


def test_default_policy_overrides_and_validation() -> None:
    policy = default_policy(max_file_bytes=10, include_hidden=True)
    assert policy.max_file_bytes == 10
    assert policy.include_hidden is True
    assert policy.use_gitignore is True
    assert default_policy(default_excludes=[".cache"]).default_excludes == (".cache",)
    with pytest.raises(ValueError, match="unknown ScanPolicy field"):
        default_policy(no_such_field=True)
    with pytest.raises(ValueError):
        default_policy(max_file_bytes=-1)
    with pytest.raises(TypeError):
        default_policy(max_file_bytes=True)
    with pytest.raises(ValueError):
        default_policy(index_dir_name="")
    with pytest.raises(ValueError):
        default_policy(index_dir_name="nested/dir")


def test_policy_dict_roundtrip() -> None:
    policy = default_policy(
        max_file_bytes=2048,
        follow_symlinks=True,
        use_gitignore=False,
        include_hidden=True,
        index_dir_name=".idx",
        extra_excludes=("*.log", "src/generated/"),
        default_excludes=("node_modules",),
        excluded_paths=("./docs/generated/", "cache"),
        secret_patterns=("*.pem",),
    )
    data = policy.to_dict()
    assert data["maxFileBytes"] == 2048
    assert data["followSymlinks"] is True
    assert data["useGitignore"] is False
    assert data["includeHidden"] is True
    assert data["indexDirName"] == ".idx"
    assert data["extraExcludes"] == ["*.log", "src/generated/"]
    assert data["defaultExcludes"] == ["node_modules"]
    assert data["excludedPaths"] == ["cache", "docs/generated"]
    assert data["secretPatterns"] == ["*.pem"]
    assert ScanPolicy.from_dict(data) == policy
    assert ScanPolicy.from_dict({}) == default_policy()


def test_excluded_paths_validation_and_normalization() -> None:
    policy = default_policy(excluded_paths=["docs/./generated/", "docs\\other", "cache"])
    assert policy.excluded_paths == ("cache", "docs/generated", "docs/other")
    assert default_policy(excluded_paths="docs/generated").excluded_paths == ("docs/generated",)
    assert default_policy(excluded_paths=()).excluded_paths == ()
    assert ScanPolicy.from_dict({"excludedPaths": ["b", "./a/"]}).excluded_paths == ("a", "b")
    for bad in ("/absolute/path", "../escape", "", ".", "C:/drive/path"):
        with pytest.raises(ValueError):
            default_policy(excluded_paths=[bad])


def test_generated_directory_path_excluded_but_same_basename_kept(tmp_path: Path) -> None:
    """``docs/codebase-intelligence`` is skipped; other same-named dirs are not."""

    root = tmp_path / "repo"
    generated = root / "docs" / "codebase-intelligence"
    nested_by_other_parent = root / "foo" / "codebase-intelligence"
    package_named_after_engine = root / "src" / "codebase-intelligence"
    for directory in (generated, nested_by_other_parent, package_named_after_engine):
        directory.mkdir(parents=True)
    (generated / "CONTEXT_BRIEF.md").write_text("# generated\n", encoding="utf-8")
    (generated / "overview.json").write_text("{}\n", encoding="utf-8")
    (nested_by_other_parent / "keep.md").write_text("# keep\n", encoding="utf-8")
    (package_named_after_engine / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (root / "docs" / "notes.md").write_text("# notes\n", encoding="utf-8")

    result = scan_repository(root)
    assert list(result.paths()) == [
        "docs/notes.md",
        "foo/codebase-intelligence/keep.md",
        "src/codebase-intelligence/mod.py",
    ]
    assert skip_map(result)[SKIP_GENERATED_DIR] == 1
    assert SKIP_GENERATED_DIR in result.stats.skip_map()


def test_excluded_paths_override_and_disable(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    generated = root / "docs" / "codebase-intelligence"
    custom = root / "generated"
    generated.mkdir(parents=True)
    custom.mkdir()
    (generated / "brief.md").write_text("# generated\n", encoding="utf-8")
    (custom / "art.py").write_text("x = 1\n", encoding="utf-8")

    default_scan = scan_repository(root)
    assert list(default_scan.paths()) == ["generated/art.py"]
    assert skip_map(default_scan)[SKIP_GENERATED_DIR] == 1

    custom_policy = default_policy(excluded_paths=("generated",))
    custom_scan = scan_repository(root, custom_policy)
    assert list(custom_scan.paths()) == ["docs/codebase-intelligence/brief.md"]
    assert skip_map(custom_scan)[SKIP_GENERATED_DIR] == 1

    disabled = scan_repository(root, default_policy(excluded_paths=()))
    assert list(disabled.paths()) == [
        "docs/codebase-intelligence/brief.md",
        "generated/art.py",
    ]
    assert SKIP_GENERATED_DIR not in skip_map(disabled)


def test_include_secrets_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(INCLUDE_SECRETS_ENV, raising=False)
    assert include_secrets_from_env() is False
    monkeypatch.setenv(INCLUDE_SECRETS_ENV, "1")
    assert include_secrets_from_env() is True
    for value in ("true", "TRUE", "yes", "on"):
        assert include_secrets_from_env({INCLUDE_SECRETS_ENV: value}) is True
    for value in ("", "0", "no", "false"):
        assert include_secrets_from_env({INCLUDE_SECRETS_ENV: value}) is False


# ---------------------------------------------------------------------------
# policy fingerprint
# ---------------------------------------------------------------------------
def test_policy_fingerprint_is_stable_and_sensitive(tmp_path: Path) -> None:
    policy = default_policy()
    baseline = policy_fingerprint(policy)
    assert baseline == policy_fingerprint(default_policy())
    assert baseline != policy_fingerprint(default_policy(include_hidden=True))
    assert baseline != policy_fingerprint(default_policy(excluded_paths=("generated",)))
    assert policy_fingerprint(default_policy(excluded_paths=())) != baseline
    assert policy_fingerprint(policy, ignore_files={".gitignore": "aa"}) != baseline
    assert policy_fingerprint(policy, ignore_files={".gitignore": "aa"}) != policy_fingerprint(
        policy, ignore_files={".gitignore": "bb"}
    )
    # Ordering and redundant "./" segments must not change the digest.
    first = policy_fingerprint(policy, ignore_files={"b/.gitignore": "2", ".gitignore": "1"})
    second = policy_fingerprint(
        policy, ignore_files={"./.gitignore": "1", "b/./.gitignore": "2"}
    )
    assert first == second
    root = tmp_path / "repo"
    root.mkdir()
    relative = policy_fingerprint(policy, root, {".gitignore": "aa"})
    absolute = policy_fingerprint(policy, root, {root / ".gitignore": "aa"})
    assert relative == absolute
    with pytest.raises(ValueError):
        policy_fingerprint(policy, root, {root.parent / "elsewhere.txt": "aa"})
    with pytest.raises(ValueError):
        policy_fingerprint(policy, None, {root / ".gitignore": "aa"})
    with pytest.raises(ValueError):
        policy_fingerprint(policy, ignore_files={"../escape/.gitignore": "aa"})
    with pytest.raises(ValueError, match="duplicate"):
        policy_fingerprint(policy, ignore_files=[(".gitignore", "a"), ("./.gitignore", "b")])


# ---------------------------------------------------------------------------
# gitignore matcher unit tests (independent of any fixture tree)
# ---------------------------------------------------------------------------
def _ignored_by(patterns: str, path: str, *, is_dir: bool = False, base: str = "") -> bool:
    matcher = GitIgnoreMatcher()
    matcher.add(base, patterns)
    return matcher.is_ignored(path, is_dir=is_dir)


@pytest.mark.parametrize(
    ("patterns", "path", "is_dir", "expected"),
    [
        ("*.log", "a.log", False, True),
        ("*.log", "sub/dir/a.log", False, True),
        ("*.log", "a.txt", False, False),
        ("*.log\n!keep.log", "keep.log", False, False),
        ("*.log\n!keep.log", "sub/keep.log", False, False),
        ("*.log\n!keep.log", "other.log", False, True),
        ("/root.txt", "root.txt", False, True),
        ("/root.txt", "sub/root.txt", False, False),
        ("build/", "build", True, True),
        ("build/", "build", False, False),
        ("build/", "sub/build", True, True),
        ("**/cache/", "notes/cache", True, True),
        ("**/cache/", "cache", True, True),
        ("a/**/b", "a/b", False, True),
        ("a/**/b", "a/x/b", False, True),
        ("a/**/b", "a/x/y/b", False, True),
        ("a/**/b", "a/x", False, False),
        ("a/**", "a/x/y", False, True),
        ("a/**", "a", False, False),
        ("temp-?.txt", "temp-a.txt", False, True),
        ("temp-?.txt", "temp-ab.txt", False, False),
        ("data[0-9].bin", "data3.bin", False, True),
        ("data[0-9].bin", "datax.bin", False, False),
        ("data[!0-9].bin", "datax.bin", False, True),
        ("data[!0-9].bin", "data3.bin", False, False),
        ("*.py[co]", "module.pyc", False, True),
        ("back\\*slash", "back*slash", False, True),
        ("\\#hash", "#hash", False, True),
        ("# comment only", "#hash", False, False),
        ("file ", "file", False, True),
        ("file\\ ", "file ", False, True),
        ("", "anything", False, False),
        ("\n# comment\n\n", "anything", False, False),
        ("!only-negation", "only-negation", False, False),
    ],
)
def test_gitignore_matcher_rules(
    patterns: str, path: str, is_dir: bool, expected: bool
) -> None:
    assert _ignored_by(patterns, path, is_dir=is_dir) is expected


def test_gitignore_last_match_across_nested_files() -> None:
    matcher = GitIgnoreMatcher()
    matcher.add("", "*.log\nbuild/\n")
    matcher.add("sub", "!keep.log\n")
    assert matcher.is_ignored("sub/keep.log", is_dir=False) is False
    assert matcher.is_ignored("sub/drop.log", is_dir=False) is True
    assert matcher.is_ignored("keep.log", is_dir=False) is True
    assert matcher.is_ignored("sub/build", is_dir=True) is True


def test_gitignore_nested_anchoring() -> None:
    matcher = GitIgnoreMatcher()
    matcher.add("sub", "/anchored.txt\n*.tmp\n")
    assert matcher.is_ignored("sub/anchored.txt", is_dir=False) is True
    assert matcher.is_ignored("sub/deeper/anchored.txt", is_dir=False) is False
    assert matcher.is_ignored("sub/deeper/other.tmp", is_dir=False) is True
    assert matcher.is_ignored("outside/anchored.txt", is_dir=False) is False


# ---------------------------------------------------------------------------
# fixture-tree scans
# ---------------------------------------------------------------------------
def test_gitignore_repo_default_scan() -> None:
    result = scan_fixture("gitignore-repo")
    assert list(result.paths()) == GITIGNORE_EXPECTED
    assert result.stats.files_indexed == len(GITIGNORE_EXPECTED)
    assert result.stats.directories_visited == 6
    assert result.stats.bytes_indexed == sum(item.size_bytes for item in result.files)
    skips = skip_map(result)
    assert skips[SKIP_GITIGNORE] == 10
    assert skips[SKIP_HIDDEN] == 2
    assert ".gitignore" not in result.paths()
    assert "src/nested/.gitignore" not in result.paths()
    for record in result.files:
        assert len(record.sha256) == 64
        assert record.line_count >= 1


def test_gitignore_negation_anchoring_and_pruning() -> None:
    paths = set(scan_fixture("gitignore-repo").paths())
    # negation wins per file and across nested files (last match wins)
    assert "keep.log" in paths
    assert "src/nested/important.tmp" in paths
    assert "src/nested/nested.log" in paths
    # plain ignore
    assert "debug.log" not in paths
    assert "root-only.txt" not in paths
    # anchoring: /root-only.txt is root anchored
    assert "other/root-only.txt" in paths
    # trailing slash + nested anchoring
    assert "src/generated/out.py" not in paths
    assert "src/nested/anchored.txt" not in paths
    assert "src/nested/deeper/anchored.txt" in paths
    # **/cache/ and ? and character class
    assert "notes/cache/ignored.py" not in paths
    assert "notes/temp-a.txt" not in paths
    assert "notes/temp-ab.txt" in paths
    assert "data1.bin" not in paths
    assert "datax.bin" in paths
    # parent-excluded directory cannot be re-included
    assert "blocked/include-me.py" not in paths


def test_gitignore_disabled_indexes_everything_not_excluded_by_name() -> None:
    result = scan_fixture("gitignore-repo", default_policy(use_gitignore=False))
    assert list(result.paths()) == NO_GITIGNORE_EXPECTED
    skips = skip_map(result)
    assert SKIP_GITIGNORE not in skips
    assert skips[SKIP_HIDDEN] == 2


def test_default_excludes_and_index_directory() -> None:
    result = scan_fixture("default-excludes-repo")
    assert list(result.paths()) == ["src/app.py"]
    skips = skip_map(result)
    assert skips[SKIP_DEFAULT_EXCLUDE] == 15
    assert skips[SKIP_INDEX_DIR] == 1
    assert skips[SKIP_HIDDEN] == 1
    assert skips.get(SKIP_GITIGNORE) is None


def test_include_hidden_keeps_default_excludes_and_index_dir() -> None:
    result = scan_fixture("default-excludes-repo", default_policy(include_hidden=True))
    assert list(result.paths()) == [".hidden/secret.py", "src/app.py"]
    skips = skip_map(result)
    assert skips[SKIP_DEFAULT_EXCLUDE] == 15
    assert skips[SKIP_INDEX_DIR] == 1
    assert SKIP_HIDDEN not in skips


def test_hidden_entries_skipped_by_default_but_indexed_on_request() -> None:
    default = scan_fixture("gitignore-repo")
    assert ".gitignore" not in default.paths()
    assert skip_map(default)[SKIP_HIDDEN] == 2
    inclusive = scan_fixture("gitignore-repo", default_policy(include_hidden=True))
    assert ".gitignore" in inclusive.paths()
    assert "src/nested/.gitignore" in inclusive.paths()
    assert len(inclusive.files) == len(default.files) + 2


def test_secret_names_are_filtered_by_default() -> None:
    result = scan_fixture("secrets-repo")
    assert list(result.paths()) == ["app.py", "safe.txt"]
    skips = skip_map(result)
    assert skips[SKIP_SECRET] == 9
    assert skips[SKIP_HIDDEN] == 4


def test_secret_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(INCLUDE_SECRETS_ENV, "1")
    visible = scan_fixture("secrets-repo")
    assert list(visible.paths()) == SECRETS_VISIBLE
    skips = skip_map(visible)
    assert SKIP_SECRET not in skips
    assert skips[SKIP_HIDDEN] == 4
    everything = scan_fixture("secrets-repo", default_policy(include_hidden=True))
    assert list(everything.paths()) == SECRETS_ALL
    assert skip_map(everything) == {}
    monkeypatch.setenv(INCLUDE_SECRETS_ENV, "0")
    assert list(scan_fixture("secrets-repo").paths()) == ["app.py", "safe.txt"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("id_rsa", True),
        ("ID_RSA", True),
        ("id_ed25519.pub", True),
        ("server.pem", True),
        ("SERVER.PEM", True),
        ("private.key", True),
        ("store.p12", True),
        ("identity.pfx", True),
        ("vault.kdbx", True),
        (".env", True),
        (".env.local", True),
        (".npmrc", True),
        (".netrc", True),
        ("credentials.json", True),
        ("secrets.yaml", True),
        ("app.py", False),
        ("my_secrets.txt", False),
        ("notes.md", False),
        ("env", False),
        ("key.pub", False),
    ],
)
def test_is_secret_name(name: str, expected: bool) -> None:
    assert is_secret_name(name, DEFAULT_SECRET_PATTERNS) is expected


def test_extra_excludes_cli_style_globs() -> None:
    """``--exclude`` is modelled as ``policy.extra_excludes`` (absolute globs)."""

    policy = default_policy(extra_excludes=("*.log", "src/nested/deeper/"))
    result = scan_fixture("gitignore-repo", policy)
    removed = {"keep.log", "src/nested/nested.log", "src/nested/deeper/anchored.txt"}
    assert list(result.paths()) == [item for item in GITIGNORE_EXPECTED if item not in removed]
    skips = skip_map(result)
    # Extra excludes are checked before .gitignore, so debug.log is counted here.
    assert skips[SKIP_EXTRA_EXCLUDE] == 4
    assert skips[SKIP_GITIGNORE] == 8


def test_extra_excludes_dir_only_and_path_glob(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "nested" / "deeper"
    nested.mkdir(parents=True)
    (nested / "inside.py").write_text("inside = 1\n", encoding="utf-8")
    (root / "deeper.py").write_text("y = 1\n", encoding="utf-8")
    result = scan_repository(root, default_policy(extra_excludes=("deeper/",)))
    assert list(result.paths()) == ["deeper.py"]
    assert skip_map(result)[SKIP_EXTRA_EXCLUDE] == 1


def test_containment_guard_rejects_candidate_outside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second line of defence: a candidate that resolved outside is counted."""

    from codebase_intelligence.scanner import discovery as discovery_module

    root = tmp_path / "repo"
    root.mkdir()
    (root / "real.py").write_text("real = 1\n", encoding="utf-8")
    (root / "evil.py").write_text("evil = 1\n", encoding="utf-8")
    real_is_within = discovery_module.is_within

    def guarded(inner_root: Path, candidate: Path) -> bool:
        if Path(candidate).name == "evil.py":
            return False
        return real_is_within(inner_root, candidate)

    monkeypatch.setattr(discovery_module, "is_within", guarded)
    result = scan_repository(root)
    assert list(result.paths()) == ["real.py"]
    assert skip_map(result)[SKIP_PATH_ESCAPE] == 1
    assert "evil" not in canonical_json(result.to_dict())


# ---------------------------------------------------------------------------
# oversize / binary / line counting
# ---------------------------------------------------------------------------
def test_oversize_policy_override() -> None:
    default_scan = scan_fixture("oversize-repo")
    assert list(default_scan.paths()) == ["empty.py", "keep.md", "tiny.py"]
    limited = scan_fixture("oversize-repo", default_policy(max_file_bytes=10))
    assert list(limited.paths()) == ["empty.py", "keep.md"]
    assert skip_map(limited)[SKIP_OVERSIZE] == 1


def test_default_size_limit(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "big.py").write_bytes(b"x" * 1_048_577)
    (root / "edge.py").write_bytes(b"y" * 1_048_576)
    result = scan_repository(root)
    assert list(result.paths()) == ["edge.py"]
    assert skip_map(result)[SKIP_OVERSIZE] == 1
    assert result.files[0].size_bytes == 1_048_576


def test_binary_file_skipped(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "text.py").write_text("x = 1\n", encoding="utf-8")
    (root / "blob.dat").write_bytes(b"binary\x00content")
    (root / "late_nul.txt").write_bytes(b"a" * 9000 + b"\x00")
    result = scan_repository(root)
    assert list(result.paths()) == ["late_nul.txt", "text.py"]
    assert skip_map(result)[SKIP_BINARY] == 1
    # Binary detection only inspects the first 8 KiB by contract.
    assert [item.path for item in result.files if item.path == "late_nul.txt"]


def test_empty_file_and_line_counting(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    cases = {
        "no_trailing.py": b"a\nb",
        "trailing.py": b"a\nb\n",
        "empty.py": b"",
        "crlf.py": b"a\r\nb\r\n",
    }
    for name, data in cases.items():
        (root / name).write_bytes(data)
    result = scan_repository(root)
    records = {item.path: item for item in result.files}
    assert set(records) == set(cases)
    for name, data in cases.items():
        assert records[name].sha256 == hashlib.sha256(data).hexdigest()
        assert records[name].size_bytes == len(data)
    assert records["no_trailing.py"].line_count == 2
    assert records["trailing.py"].line_count == 2
    assert records["crlf.py"].line_count == 2
    assert records["empty.py"].line_count == 0
    assert records["empty.py"].size_bytes == 0
    assert records["empty.py"].sha256 == hashlib.sha256(b"").hexdigest()
    assert records["empty.py"].language is Language.PYTHON


# ---------------------------------------------------------------------------
# unicode
# ---------------------------------------------------------------------------
def test_unicode_paths() -> None:
    result = scan_fixture("unicode-repo")
    assert list(result.paths()) == ["README.md", "docs/naïve.md", "src/日本語.py"]
    by_path = {item.path: item for item in result.files}
    assert by_path["src/日本語.py"].language is Language.PYTHON
    assert by_path["docs/naïve.md"].language is Language.MARKDOWN
    payload = canonical_json(result.to_dict())
    assert "日本語" in payload
    assert "naïve" in payload
    decoded = json.loads(payload)
    assert decoded["files"][2]["path"] == "src/日本語.py"
    # Same scan repeated must produce byte-identical canonical JSON.
    assert payload == canonical_json(scan_fixture("unicode-repo").to_dict())


# ---------------------------------------------------------------------------
# symlinks and containment
# ---------------------------------------------------------------------------
def test_symlinks_are_skipped_by_default(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "real.py").write_text("real = 1\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside content\n", encoding="utf-8")
    symlink_or_skip(outside, root / "escape.py")
    result = scan_repository(root)
    assert list(result.paths()) == ["real.py"]
    assert skip_map(result)[SKIP_SYMLINK] == 1
    assert outside.read_text(encoding="utf-8") not in canonical_json(result.to_dict())


def test_follow_symlinks_rejects_out_of_root_escape(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "real.py").write_text("real = 1\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside content\n", encoding="utf-8")
    symlink_or_skip(outside, root / "escape.py")
    result = scan_repository(root, default_policy(follow_symlinks=True))
    assert list(result.paths()) == ["real.py"]
    assert skip_map(result)[SKIP_SYMLINK_ESCAPE] == 1


def test_follow_symlinks_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "real.py").write_text("shared = 1\n", encoding="utf-8")
    symlink_or_skip(root / "real.py", root / "alias.py")
    result = scan_repository(root, default_policy(follow_symlinks=True))
    assert list(result.paths()) == ["alias.py", "real.py"]
    by_path = {item.path: item for item in result.files}
    assert by_path["alias.py"].sha256 == by_path["real.py"].sha256
    assert by_path["alias.py"].size_bytes == by_path["real.py"].size_bytes


def test_followed_symlink_directory_is_walked_once(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    real = root / "real"
    real.mkdir(parents=True)
    (real / "inner.py").write_text("inner = 1\n", encoding="utf-8")
    symlink_or_skip(real, root / "alink", is_dir=True)
    result = scan_repository(root, default_policy(follow_symlinks=True))
    assert list(result.paths()) == ["alink/inner.py"]
    assert skip_map(result)[SKIP_CYCLE] == 1


def test_symlinked_gitignore_outside_root_is_never_read(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "victim.py").write_text("victim = 1\n", encoding="utf-8")
    outside_ignore = tmp_path / "outside-ignore"
    outside_ignore.write_text("victim.py\n", encoding="utf-8")
    symlink_or_skip(outside_ignore, root / ".gitignore")
    default_result = scan_repository(root)
    assert list(default_result.paths()) == ["victim.py"]
    assert skip_map(default_result)[SKIP_SYMLINK] == 1
    followed = scan_repository(root, default_policy(follow_symlinks=True))
    assert list(followed.paths()) == ["victim.py"]
    assert skip_map(followed)[SKIP_SYMLINK_ESCAPE] == 1


# ---------------------------------------------------------------------------
# determinism and result shape
# ---------------------------------------------------------------------------
def test_repeated_scan_is_byte_identical() -> None:
    first = scan_fixture("gitignore-repo")
    second = scan_fixture("gitignore-repo")
    assert first.files == second.files
    assert first.stats == second.stats
    assert first.policy_fingerprint == second.policy_fingerprint
    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())


def test_determinism_across_checkout_locations(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    shutil.copytree(FIXTURES / "gitignore-repo", first_root)
    shutil.copytree(FIXTURES / "gitignore-repo", second_root)
    first = scan_repository(first_root)
    second = scan_repository(second_root)
    assert first.policy_fingerprint == second.policy_fingerprint
    payload = canonical_json(first.to_dict())
    assert payload == canonical_json(second.to_dict())
    assert str(tmp_path) not in payload
    assert "\\" not in payload


def test_scan_result_shape_and_stats_consistency() -> None:
    result = scan_fixture("gitignore-repo")
    assert isinstance(result, ScanResult)
    assert result.root.is_absolute()
    assert result.paths() == tuple(sorted(item.path for item in result.files))
    assert result.stats.files_indexed == len(result.files)
    assert result.stats.bytes_indexed == sum(item.size_bytes for item in result.files)
    assert result.stats.skipped == tuple(sorted(result.stats.skipped))
    assert all(count > 0 for _, count in result.stats.skipped)
    payload = result.to_dict()
    assert set(payload) == {"files", "stats", "policyFingerprint"}
    assert "root" not in payload
    assert len(result.policy_fingerprint) == 64


def test_scan_result_is_frozen() -> None:
    result = scan_fixture("gitignore-repo")
    with pytest.raises(FrozenInstanceError):
        result.files = ()  # type: ignore[misc]


def test_missing_or_invalid_root_raises_repository_error(tmp_path: Path) -> None:
    with pytest.raises(RepositoryError) as missing:
        scan_repository(tmp_path / "missing")
    assert missing.value.code == "not_a_directory"
    file_root = tmp_path / "file.txt"
    file_root.write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(RepositoryError) as not_a_directory:
        scan_repository(file_root)
    assert not_a_directory.value.code == "not_a_directory"


def test_scan_accepts_relative_root_matching_absolute(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.chdir(tmp_path)
    shutil.copytree(FIXTURES / "unicode-repo", tmp_path / "repo")
    relative = scan_repository(Path("repo"))
    absolute = scan_repository(tmp_path / "repo")
    assert relative.policy_fingerprint == absolute.policy_fingerprint
    assert canonical_json(relative.to_dict()) == canonical_json(absolute.to_dict())


def test_empty_repository() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        result = scan_repository(root)
        assert result.files == ()
        assert result.paths() == ()
        assert result.stats.files_indexed == 0
        assert result.stats.bytes_indexed == 0
        assert result.stats.directories_visited == 1
        assert len(result.policy_fingerprint) == 64
