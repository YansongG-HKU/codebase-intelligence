"""Frozen scan policy: what repository discovery includes, skips and counts.

A :class:`ScanPolicy` is part of the cache contract.  It is immutable so one
policy instance can be shared by the scanner, the indexer and the CLI without
any risk of a component silently changing what gets indexed.

:func:`policy_fingerprint` hashes the policy fields together with the digests of
the ``.gitignore`` files that were actually consulted while walking.  A
repository whose ignore rules changed is therefore re-indexed even when its
included file contents did not change.  The absolute repository root is
deliberately **not** part of the hash: identical trees scanned from different
directories yield the same fingerprint and the same canonical index bytes
(see ``docs/SPEC.md`` section 3).

Secret filtering is on by default.  The single documented opt-out is the
environment variable ``CBI_INCLUDE_SECRETS=1`` (see
:func:`include_secrets_from_env`); it must be set explicitly and is never
implied by a policy override.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from codebase_intelligence.util import canonical_json, sha256_text, to_posix

#: Default upper bound for one indexed file: 1 MiB.
DEFAULT_MAX_FILE_BYTES = 1_048_576

#: Default directory holding the engine cache; never scanned.
DEFAULT_INDEX_DIR_NAME = ".codebase-intelligence"

#: Directory names skipped at any depth by default (VCS, venv, build, caches).
DEFAULT_EXCLUDES: tuple[str, ...] = (
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

#: Repo-relative directory paths skipped by default.
#:
#: ``cbi export`` generates its deterministic artifact bundle into this
#: directory, so it must never be scanned or indexed: otherwise the index would
#: depend on whether an export already happened and repeated exports could never
#: be byte-identical.  Unlike :data:`DEFAULT_EXCLUDES` this is an exact
#: repo-relative path: only ``docs/codebase-intelligence`` (at the repository
#: root) is skipped, while an unrelated same-named directory such as
#: ``src/codebase-intelligence/`` stays indexed.
DEFAULT_EXCLUDED_PATHS: tuple[str, ...] = ("docs/codebase-intelligence",)

#: Conservative file-name globs for likely secrets.  Matching is
#: case-insensitive and applies to the basename only.
DEFAULT_SECRET_PATTERNS: tuple[str, ...] = (
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    ".env",
    ".env.*",
    ".npmrc",
    ".netrc",
    "credentials*",
    "secrets*",
    "*.kdbx",
)

#: Backwards-friendly alias.
SECRET_PATTERNS: tuple[str, ...] = DEFAULT_SECRET_PATTERNS

#: Environment variable that explicitly opts into indexing secret-named files.
INCLUDE_SECRETS_ENV = "CBI_INCLUDE_SECRETS"

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})


def _normalize_excluded_paths(values: Iterable[str] | str) -> tuple[str, ...]:
    """Normalize repo-relative excluded directory paths (fail closed).

    Entries are converted to POSIX form, empty/``.`` segments are dropped, and
    the result is sorted and de-duplicated so the policy fingerprint does not
    depend on the order the caller used.  Absolute paths, ``..`` escapes and
    drive/stream separators are rejected instead of being silently repaired.
    """

    raw_values: Iterable[str] = (values,) if isinstance(values, str) else values
    normalized: list[str] = []
    for raw in raw_values:
        text = to_posix(str(raw)).strip()
        if not text:
            raise ValueError("excluded_paths entries must not be empty")
        if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
            raise ValueError(f"excluded_paths entries must be repo-relative: {raw!r}")
        parts = [part for part in text.split("/") if part not in ("", ".")]
        if not parts:
            raise ValueError("excluded_paths entries must name a directory")
        if any(part == ".." for part in parts):
            raise ValueError(f"excluded_paths entries must not escape the root: {raw!r}")
        normalized.append("/".join(parts))
    return tuple(sorted(set(normalized)))


@dataclass(frozen=True, slots=True)
class ScanPolicy:
    """Immutable input describing one repository scan.

    Attributes:
        max_file_bytes: Files strictly larger than this are skipped and counted.
        follow_symlinks: When ``False`` (the default) every symlink is skipped.
            When ``True`` a symlink is followed only if it resolves to a path
            still inside the scanned root.
        use_gitignore: Honor root and nested ``.gitignore`` files.
        include_hidden: Include dot-files and dot-directories (default: no).
        index_dir_name: Cache directory name; always skipped, at any depth.
        extra_excludes: Caller-supplied ignore globs (for example the CLI
            ``--exclude`` flag).  Patterns are matched case-sensitively against
            the basename, or against the repo-relative POSIX path when the
            pattern contains ``/``; a trailing ``/`` restricts the pattern to
            directories.  Extra excludes always win (independent of
            ``.gitignore`` negation).
        default_excludes: Directory names skipped at any depth.
        excluded_paths: Repo-relative POSIX directory paths skipped exactly at
            that path (and everything below it).  Entries are normalized
            (``/`` separators, no ``.``/``..`` segments, sorted, de-duplicated);
            absolute paths and ``..`` escapes are rejected.  The default is the
            ``cbi export`` generation directory, which must never feed back into
            the index.
        secret_patterns: Basename globs of likely-secret files, skipped and
            counted unless :data:`INCLUDE_SECRETS_ENV` is set explicitly.
    """

    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    follow_symlinks: bool = False
    use_gitignore: bool = True
    include_hidden: bool = False
    index_dir_name: str = DEFAULT_INDEX_DIR_NAME
    extra_excludes: tuple[str, ...] = ()
    default_excludes: tuple[str, ...] = DEFAULT_EXCLUDES
    excluded_paths: tuple[str, ...] = DEFAULT_EXCLUDED_PATHS
    secret_patterns: tuple[str, ...] = DEFAULT_SECRET_PATTERNS

    def __post_init__(self) -> None:
        if isinstance(self.max_file_bytes, bool) or not isinstance(self.max_file_bytes, int):
            raise TypeError("max_file_bytes must be an int")
        if self.max_file_bytes < 0:
            raise ValueError("max_file_bytes must be >= 0")
        if not isinstance(self.index_dir_name, str) or not self.index_dir_name:
            raise ValueError("index_dir_name must be a non-empty string")
        if "/" in self.index_dir_name or "\\" in self.index_dir_name:
            raise ValueError("index_dir_name must be a single path segment")
        object.__setattr__(
            self, "extra_excludes", tuple(str(item) for item in self.extra_excludes)
        )
        object.__setattr__(
            self, "default_excludes", tuple(str(item) for item in self.default_excludes)
        )
        object.__setattr__(
            self, "excluded_paths", _normalize_excluded_paths(self.excluded_paths)
        )
        object.__setattr__(
            self, "secret_patterns", tuple(str(item) for item in self.secret_patterns)
        )

    def to_dict(self) -> dict[str, Any]:
        """Deterministic camelCase representation (used for the fingerprint)."""

        return {
            "maxFileBytes": self.max_file_bytes,
            "followSymlinks": self.follow_symlinks,
            "useGitignore": self.use_gitignore,
            "includeHidden": self.include_hidden,
            "indexDirName": self.index_dir_name,
            "extraExcludes": list(self.extra_excludes),
            "defaultExcludes": list(self.default_excludes),
            "excludedPaths": list(self.excluded_paths),
            "secretPatterns": list(self.secret_patterns),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScanPolicy":
        """Inverse of :meth:`to_dict`; missing fields fall back to defaults."""

        defaults = cls()
        return cls(
            max_file_bytes=int(data.get("maxFileBytes", defaults.max_file_bytes)),
            follow_symlinks=bool(data.get("followSymlinks", defaults.follow_symlinks)),
            use_gitignore=bool(data.get("useGitignore", defaults.use_gitignore)),
            include_hidden=bool(data.get("includeHidden", defaults.include_hidden)),
            index_dir_name=str(data.get("indexDirName", defaults.index_dir_name)),
            extra_excludes=tuple(
                str(item) for item in data.get("extraExcludes", defaults.extra_excludes)
            ),
            default_excludes=tuple(
                str(item) for item in data.get("defaultExcludes", defaults.default_excludes)
            ),
            excluded_paths=tuple(
                str(item) for item in data.get("excludedPaths", defaults.excluded_paths)
            ),
            secret_patterns=tuple(
                str(item) for item in data.get("secretPatterns", defaults.secret_patterns)
            ),
        )


def default_policy(**overrides: Any) -> ScanPolicy:
    """Return the documented default policy with optional field overrides.

    Unknown field names raise :class:`ValueError` instead of being ignored, so a
    typo cannot silently fall back to a different scan behaviour.
    """

    known = {field.name for field in fields(ScanPolicy)}
    unknown = sorted(set(overrides) - known)
    if unknown:
        raise ValueError(f"unknown ScanPolicy field(s): {', '.join(unknown)}")
    return ScanPolicy(**overrides)


def include_secrets_from_env(environ: Mapping[str, str] | None = None) -> bool:
    """True when ``CBI_INCLUDE_SECRETS`` explicitly opts into secret files.

    Accepted truthy values are ``1`` (documented canonical form), ``true``,
    ``yes`` and ``on``, case-insensitively.  Anything else (including an unset
    variable) leaves secret filtering enabled.
    """

    env = os.environ if environ is None else environ
    return env.get(INCLUDE_SECRETS_ENV, "").strip().casefold() in _TRUTHY_VALUES


def policy_fingerprint(
    policy: ScanPolicy,
    root: Path | None = None,
    ignore_files: Mapping[str, str] | Iterable[tuple[str | Path, str]] = (),
) -> str:
    """Hash a policy plus the digests of the ignore files it consulted.

    Args:
        policy: The active scan policy.
        root: Optional repository root.  Only used to relativize absolute
            ignore-file paths; it is never serialized, so fingerprints do not
            depend on where the repository is checked out.
        ignore_files: Mapping (or iterable of pairs) of repo-relative
            ``.gitignore`` path to sha256 hex digest of its bytes.

    Returns:
        ``sha256(canonical_json(payload))`` where the payload contains the
        policy fields and the sorted ignore-file digests.
    """

    pairs: dict[str, str] = {}
    items: Iterable[tuple[str | Path, str]]
    if isinstance(ignore_files, Mapping):
        items = ignore_files.items()
    else:
        items = ignore_files
    for ignore_path, digest in items:
        relative = _normalize_ignore_path(ignore_path, root)
        if relative in pairs:
            raise ValueError(f"duplicate ignore file digest for {relative!r}")
        pairs[relative] = str(digest)
    payload = {
        "policy": policy.to_dict(),
        "ignoreFiles": [
            {"path": relative, "sha256": pairs[relative]} for relative in sorted(pairs)
        ],
    }
    return sha256_text(canonical_json(payload))


def _normalize_ignore_path(path: str | Path, root: Path | None) -> str:
    """Normalize an ignore-file reference to a safe repo-relative POSIX string."""

    raw = to_posix(str(path))
    candidate = Path(raw)
    if candidate.is_absolute():
        if root is None:
            raise ValueError("absolute ignore-file paths require an explicit root")
        root_path = Path(root)
        relative: Path | None
        try:
            relative = candidate.relative_to(root_path)
        except ValueError:
            try:
                relative = candidate.resolve().relative_to(root_path.resolve())
            except (OSError, ValueError):
                raise ValueError(
                    f"ignore file {raw!r} is outside root {to_posix(str(root_path))!r}"
                ) from None
        raw = to_posix(str(relative))
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"ignore file path escapes root: {to_posix(str(path))!r}")
        parts.append(part)
    if not parts:
        raise ValueError("ignore file path must not be empty")
    return "/".join(parts)
