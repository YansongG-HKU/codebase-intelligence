"""Deterministic, read-only repository discovery.

The scanner is the only component that walks the user's file system, so it is
also the component that enforces the security boundary described in
``docs/SPEC.md`` section 5:

* the root is resolved with ``strict=True`` and must be a directory,
* every candidate is resolved and must stay inside the resolved root
  (traversal and symlink/junction escapes are rejected, never read),
* symlinks are skipped by default and counted; following them is an explicit
  opt-in that still enforces the containment rule,
* files are read exactly once (head for the binary check, then streaming
  sha256 + line count), never executed and never imported,
* every failure (unreadable entry, unreadable ignore file) is counted in
  :class:`~codebase_intelligence.model.entities.ScanStats`, never fatal.

Output is deterministic: files are sorted by repo-relative POSIX path, skip
counters are sorted by reason, the absolute root is excluded from
:meth:`ScanResult.to_dict`, and the policy fingerprint hashes only policy fields
plus relative ``.gitignore`` paths and digests.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from codebase_intelligence.errors import RepositoryError
from codebase_intelligence.model import FileRecord, Language, ScanStats
from codebase_intelligence.scanner.gitignore import GitIgnoreMatcher
from codebase_intelligence.scanner.policy import (
    ScanPolicy,
    default_policy,
    include_secrets_from_env,
    policy_fingerprint,
)
from codebase_intelligence.util import is_within, sha256_bytes, to_posix

#: How many leading bytes are inspected for binary content (NUL byte).
_HEAD_BYTES = 8192

#: Streaming read size while hashing one candidate file.
_CHUNK_BYTES = 1 << 20

# -- stable skip-reason codes (diagnostics only, documented in SCANNER_POLICY) --
SKIP_GENERATED_DIR = "generated-dir"
SKIP_DEFAULT_EXCLUDE = "default-exclude"
SKIP_INDEX_DIR = "index-dir"
SKIP_HIDDEN = "hidden"
SKIP_EXTRA_EXCLUDE = "extra-exclude"
SKIP_GITIGNORE = "gitignore"
SKIP_SECRET = "secret"
SKIP_SYMLINK = "symlink"
SKIP_SYMLINK_ESCAPE = "symlink-escape"
SKIP_SYMLINK_BROKEN = "symlink-broken"
SKIP_OVERSIZE = "oversize"
SKIP_BINARY = "binary"
SKIP_UNREADABLE = "unreadable"
SKIP_PATH_ESCAPE = "path-escape"
SKIP_CYCLE = "cycle"
SKIP_UNSUPPORTED_ENTRY = "unsupported-entry"

#: Every skip reason discovery can emit, in precedence order.
SKIP_REASONS: tuple[str, ...] = (
    SKIP_SYMLINK,
    SKIP_SYMLINK_ESCAPE,
    SKIP_SYMLINK_BROKEN,
    SKIP_GENERATED_DIR,
    SKIP_DEFAULT_EXCLUDE,
    SKIP_INDEX_DIR,
    SKIP_HIDDEN,
    SKIP_EXTRA_EXCLUDE,
    SKIP_GITIGNORE,
    SKIP_SECRET,
    SKIP_PATH_ESCAPE,
    SKIP_OVERSIZE,
    SKIP_BINARY,
    SKIP_UNREADABLE,
    SKIP_CYCLE,
    SKIP_UNSUPPORTED_ENTRY,
)

_EXTENSION_LANGUAGES: dict[str, Language] = {
    "py": Language.PYTHON,
    "pyi": Language.PYTHON,
    "pyw": Language.PYTHON,
    "js": Language.JAVASCRIPT,
    "mjs": Language.JAVASCRIPT,
    "cjs": Language.JAVASCRIPT,
    "jsx": Language.JAVASCRIPT,
    "ts": Language.TYPESCRIPT,
    "tsx": Language.TYPESCRIPT,
    "mts": Language.TYPESCRIPT,
    "cts": Language.TYPESCRIPT,
    "go": Language.GO,
    "rs": Language.RUST,
    "java": Language.JAVA,
    "c": Language.C,
    "h": Language.C,
    "cpp": Language.CPP,
    "cc": Language.CPP,
    "cxx": Language.CPP,
    "c++": Language.CPP,
    "hpp": Language.CPP,
    "hh": Language.CPP,
    "hxx": Language.CPP,
    "h++": Language.CPP,
    "cs": Language.CSHARP,
    "rb": Language.RUBY,
    "php": Language.PHP,
    "phtml": Language.PHP,
    "sh": Language.SHELL,
    "bash": Language.SHELL,
    "zsh": Language.SHELL,
    "ksh": Language.SHELL,
    "fish": Language.SHELL,
    "html": Language.HTML,
    "htm": Language.HTML,
    "xhtml": Language.HTML,
    "css": Language.CSS,
    "scss": Language.CSS,
    "sass": Language.CSS,
    "less": Language.CSS,
    "json": Language.JSON,
    "jsonc": Language.JSON,
    "jsonl": Language.JSON,
    "yaml": Language.YAML,
    "yml": Language.YAML,
    "toml": Language.TOML,
    "md": Language.MARKDOWN,
    "markdown": Language.MARKDOWN,
    "mdx": Language.MARKDOWN,
    "sql": Language.SQL,
}

_SPECIAL_FILENAMES: dict[str, Language] = {
    "rakefile": Language.RUBY,
    "gemfile": Language.RUBY,
    "podfile": Language.RUBY,
    "vagrantfile": Language.RUBY,
    "capfile": Language.RUBY,
    "berksfile": Language.RUBY,
    ".bashrc": Language.SHELL,
    ".bash_profile": Language.SHELL,
    ".bash_login": Language.SHELL,
    ".profile": Language.SHELL,
    ".zshrc": Language.SHELL,
    ".zshenv": Language.SHELL,
    ".zprofile": Language.SHELL,
    ".kshrc": Language.SHELL,
}


@dataclass(frozen=True, slots=True)
class ScanResult:
    """One completed scan of one repository root.

    Attributes:
        root: Canonical absolute root that was scanned.  Deliberately absent
            from :meth:`to_dict` so payloads are location-independent.
        files: Indexed file facts, sorted by ``path``.
        stats: Discovery counters (diagnostics only, never tool payloads).
        policy_fingerprint: Cache key for policy + consulted ignore files.
    """

    root: Path
    files: tuple[FileRecord, ...]
    stats: ScanStats
    policy_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        """Deterministic, absolute-path-free representation (for tests/CLI)."""

        return {
            "files": [item.to_dict() for item in self.files],
            "stats": self.stats.to_dict(),
            "policyFingerprint": self.policy_fingerprint,
        }

    def paths(self) -> tuple[str, ...]:
        """Indexed repo-relative POSIX paths in canonical order."""

        return tuple(item.path for item in self.files)


def detect_language(path: str) -> Language:
    """Detect the language of *path* from its basename extension.

    This is intentionally a conservative extension table, not a content
    classifier: a wrong guess is worse than ``Language.OTHER``.  Ambiguous
    extensions are documented in ``docs/SCANNER_POLICY.md`` (for example ``.h``
    is treated as C and ``.scss`` as CSS).
    """

    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1].lower()
    if not name:
        return Language.OTHER
    special = _SPECIAL_FILENAMES.get(name)
    if special is not None:
        return special
    dot = name.rfind(".")
    if dot <= 0:
        return Language.OTHER
    return _EXTENSION_LANGUAGES.get(name[dot + 1 :], Language.OTHER)


def is_secret_name(name: str, patterns: tuple[str, ...]) -> bool:
    """Case-insensitive basename glob match against the secret patterns."""

    lowered = name.casefold()
    return any(fnmatchcase(lowered, pattern.casefold()) for pattern in patterns)


def matches_extra_excludes(
    rel_path: str,
    name: str,
    *,
    is_dir: bool,
    patterns: tuple[str, ...],
) -> bool:
    """Match caller-supplied ignore globs (CLI ``--exclude``).

    Patterns are case-sensitive (deterministic across platforms).  A pattern
    without ``/`` matches the basename; one with ``/`` matches the whole
    repo-relative POSIX path.  A trailing ``/`` restricts the pattern to
    directories.  These excludes are absolute: ``.gitignore`` negation cannot
    re-include them.
    """

    for raw_pattern in patterns:
        pattern = to_posix(raw_pattern)
        dir_only = pattern.endswith("/")
        if dir_only:
            pattern = pattern[:-1]
        if not pattern:
            continue
        if dir_only and not is_dir:
            continue
        if "/" in pattern:
            if fnmatchcase(rel_path, pattern):
                return True
        elif fnmatchcase(name, pattern):
            return True
    return False


def matches_excluded_path(rel_path: str, paths: tuple[str, ...]) -> bool:
    """Match a directory against the exact repo-relative ``excluded_paths``.

    Unlike :data:`~codebase_intelligence.scanner.policy.DEFAULT_EXCLUDES` (which
    matches a directory *name* at any depth) these entries are full repository
    paths, so ``docs/codebase-intelligence`` is skipped at the repository root
    while an unrelated ``src/codebase-intelligence/`` stays indexed.  A path is
    excluded when it equals an entry or lies inside one.
    """

    normalized = to_posix(rel_path)
    for entry in paths:
        if not entry:
            continue
        if normalized == entry or normalized.startswith(entry + "/"):
            return True
    return False


def scan_repository(root: Path, policy: ScanPolicy | None = None) -> ScanResult:
    """Walk *root* once and return its deterministic :class:`ScanResult`.

    Raises:
        RepositoryError: The root does not exist or is not a directory.
    """

    active_policy = policy if policy is not None else default_policy()
    requested = Path(root)
    try:
        root_resolved = requested.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepositoryError(f"repository root does not exist: {requested}") from exc
    if not root_resolved.is_dir():
        raise RepositoryError(f"repository root is not a directory: {requested}")
    scanner = _Scanner(root=root_resolved, policy=active_policy)
    files = scanner.run()
    skipped = tuple(
        sorted((reason, count) for reason, count in scanner.skip.items() if count > 0)
    )
    stats = ScanStats(
        files_indexed=len(files),
        bytes_indexed=sum(item.size_bytes for item in files),
        directories_visited=scanner.directories_visited,
        skipped=skipped,
    )
    fingerprint = policy_fingerprint(active_policy, root_resolved, scanner.ignore_digests)
    return ScanResult(
        root=root_resolved,
        files=tuple(files),
        stats=stats,
        policy_fingerprint=fingerprint,
    )


class _Scanner:
    """Mutable per-scan state; one instance per :func:`scan_repository` call."""

    def __init__(self, *, root: Path, policy: ScanPolicy) -> None:
        self.root = root
        self.policy = policy
        self.include_secrets = include_secrets_from_env()
        self.files: list[FileRecord] = []
        self.skip: dict[str, int] = {}
        self.directories_visited = 0
        self.ignore_digests: dict[str, str] = {}
        self._visited_dirs: set[str] = set()

    # -- driver ------------------------------------------------------------
    def run(self) -> list[FileRecord]:
        matcher = GitIgnoreMatcher()
        if self.policy.use_gitignore:
            self._load_ignore_file(self.root, "", matcher)
        self._visited_dirs.add(_dir_key(self.root))
        self._walk(self.root, "", matcher)
        self.files.sort(key=lambda item: item.path)
        return self.files

    def _walk(self, directory: Path, rel_dir: str, matcher: GitIgnoreMatcher) -> None:
        self.directories_visited += 1
        try:
            with os.scandir(directory) as iterator:
                names = sorted(entry.name for entry in iterator)
        except OSError:
            self._count_skip(SKIP_UNREADABLE)
            return
        for name in names:
            self._consider(directory / name, name, rel_dir, matcher)

    def _consider(
        self, abs_path: Path, name: str, rel_dir: str, matcher: GitIgnoreMatcher
    ) -> None:
        rel_path = f"{rel_dir}/{name}" if rel_dir else name
        try:
            entry_stat = os.lstat(abs_path)
        except OSError:
            self._count_skip(SKIP_UNREADABLE)
            return
        mode = entry_stat.st_mode
        is_symlink = stat.S_ISLNK(mode)
        is_dir = stat.S_ISDIR(mode)
        is_file = stat.S_ISREG(mode)
        if is_symlink:
            if not self.policy.follow_symlinks:
                self._count_skip(SKIP_SYMLINK)
                return
            try:
                target = abs_path.resolve(strict=True)
            except (OSError, RuntimeError):
                self._count_skip(SKIP_SYMLINK_BROKEN)
                return
            if not is_within(self.root, target):
                self._count_skip(SKIP_SYMLINK_ESCAPE)
                return
            try:
                target_stat = os.stat(abs_path)
            except OSError:
                self._count_skip(SKIP_UNREADABLE)
                return
            is_dir = stat.S_ISDIR(target_stat.st_mode)
            is_file = stat.S_ISREG(target_stat.st_mode)
            if not (is_dir or is_file):
                self._count_skip(SKIP_UNSUPPORTED_ENTRY)
                return
        if is_dir:
            self._consider_directory(abs_path, name, rel_path, matcher)
        elif is_file:
            self._consider_file(abs_path, name, rel_path, matcher)
        else:
            self._count_skip(SKIP_UNSUPPORTED_ENTRY)

    def _consider_directory(
        self, abs_path: Path, name: str, rel_path: str, matcher: GitIgnoreMatcher
    ) -> None:
        if matches_excluded_path(rel_path, self.policy.excluded_paths):
            self._count_skip(SKIP_GENERATED_DIR)
            return
        if name in self.policy.default_excludes:
            self._count_skip(SKIP_DEFAULT_EXCLUDE)
            return
        if name == self.policy.index_dir_name:
            self._count_skip(SKIP_INDEX_DIR)
            return
        if not self.policy.include_hidden and name.startswith("."):
            self._count_skip(SKIP_HIDDEN)
            return
        if matches_extra_excludes(
            rel_path, name, is_dir=True, patterns=self.policy.extra_excludes
        ):
            self._count_skip(SKIP_EXTRA_EXCLUDE)
            return
        if self.policy.use_gitignore and matcher.is_ignored(rel_path, is_dir=True):
            self._count_skip(SKIP_GITIGNORE)
            return
        if not is_within(self.root, abs_path):
            self._count_skip(SKIP_PATH_ESCAPE)
            return
        try:
            resolved = abs_path.resolve(strict=True)
        except (OSError, RuntimeError):
            self._count_skip(SKIP_UNREADABLE)
            return
        key = _dir_key(resolved)
        if key in self._visited_dirs:
            self._count_skip(SKIP_CYCLE)
            return
        self._visited_dirs.add(key)
        if self.policy.use_gitignore:
            self._load_ignore_file(abs_path, rel_path, matcher)
        self._walk(abs_path, rel_path, matcher)

    def _consider_file(
        self, abs_path: Path, name: str, rel_path: str, matcher: GitIgnoreMatcher
    ) -> None:
        if not self.policy.include_hidden and name.startswith("."):
            self._count_skip(SKIP_HIDDEN)
            return
        if matches_extra_excludes(
            rel_path, name, is_dir=False, patterns=self.policy.extra_excludes
        ):
            self._count_skip(SKIP_EXTRA_EXCLUDE)
            return
        if self.policy.use_gitignore and matcher.is_ignored(rel_path, is_dir=False):
            self._count_skip(SKIP_GITIGNORE)
            return
        if not self.include_secrets and is_secret_name(name, self.policy.secret_patterns):
            self._count_skip(SKIP_SECRET)
            return
        if not is_within(self.root, abs_path):
            self._count_skip(SKIP_PATH_ESCAPE)
            return
        try:
            file_stat = os.stat(abs_path)
        except OSError:
            self._count_skip(SKIP_UNREADABLE)
            return
        if file_stat.st_size > self.policy.max_file_bytes:
            self._count_skip(SKIP_OVERSIZE)
            return
        try:
            record, reason = self._read_file(abs_path, rel_path)
        except OSError:
            self._count_skip(SKIP_UNREADABLE)
            return
        if record is None:
            self._count_skip(reason or SKIP_UNREADABLE)
            return
        self.files.append(record)

    # -- reading -----------------------------------------------------------
    def _read_file(self, path: Path, rel_path: str) -> tuple[FileRecord | None, str | None]:
        """Read *path* once: binary head check, streaming sha256 and line count."""

        with open(path, "rb") as handle:
            head = handle.read(_HEAD_BYTES)
            if b"\x00" in head:
                return None, SKIP_BINARY
            digest = hashlib.sha256(head)
            size = len(head)
            newlines = head.count(b"\n")
            last_byte = head[-1:] if head else b""
            while True:
                chunk = handle.read(_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > self.policy.max_file_bytes:
                    return None, SKIP_OVERSIZE
                digest.update(chunk)
                newlines += chunk.count(b"\n")
                last_byte = chunk[-1:]
        line_count = newlines + (1 if size and last_byte != b"\n" else 0)
        return (
            FileRecord(
                path=rel_path,
                language=detect_language(rel_path),
                size_bytes=size,
                sha256=digest.hexdigest(),
                line_count=line_count,
            ),
            None,
        )

    def _load_ignore_file(
        self, directory: Path, rel_dir: str, matcher: GitIgnoreMatcher
    ) -> None:
        """Load ``directory/.gitignore`` into *matcher* without escaping the root."""

        path = directory / ".gitignore"
        rel_path = f"{rel_dir}/.gitignore" if rel_dir else ".gitignore"
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return
        except OSError:
            self._count_skip(SKIP_UNREADABLE)
            return
        if stat.S_ISLNK(info.st_mode):
            # Symlink skip/escape diagnostics are produced by _consider() when
            # the entry itself is visited; do not double count them here.
            if not self.policy.follow_symlinks:
                return
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                return
            if not is_within(self.root, resolved):
                return
            try:
                info = os.stat(path)
            except OSError:
                self._count_skip(SKIP_UNREADABLE)
                return
        if not stat.S_ISREG(info.st_mode):
            return
        try:
            with open(path, "rb") as handle:
                data = handle.read(self.policy.max_file_bytes)
        except OSError:
            self._count_skip(SKIP_UNREADABLE)
            return
        self.ignore_digests[rel_path] = sha256_bytes(data)
        matcher.add(rel_dir, data.decode("utf-8", errors="replace"))

    # -- diagnostics -------------------------------------------------------
    def _count_skip(self, reason: str) -> None:
        self.skip[reason] = self.skip.get(reason, 0) + 1


def _dir_key(path: Path) -> str:
    """Platform-normalized key for visited-directory cycle detection."""

    return os.path.normcase(str(path))
