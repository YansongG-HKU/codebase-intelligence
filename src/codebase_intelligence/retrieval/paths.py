"""Repository-relative path helpers shared by retrieval and reporting.

Tool inputs such as ``pathPrefix``/``focus`` are untrusted: they must never be
able to point outside the repository, and echo values in payloads must stay
repository-relative and POSIX (SPEC §3).  Invalid input is a user error
(:class:`codebase_intelligence.errors.UsageError`), never a silent empty result.
"""

from __future__ import annotations

import re

from codebase_intelligence.errors import UsageError
from codebase_intelligence.util import to_posix

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def normalize_repo_prefix(value: str | None, *, field: str = "pathPrefix") -> str | None:
    """Normalize a user-supplied path prefix to ``a/b`` form (or ``None``).

    ``None``/empty/``.`` mean "no prefix".  Absolute paths, drive letters and
    ``..`` segments are rejected: they would escape the repository root.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise UsageError(f"{field} must be a string")
    raw = to_posix(value.strip())
    if not raw or raw in (".", "./"):
        return None
    if raw.startswith("/") or _DRIVE_PREFIX.match(raw):
        raise UsageError(f"{field} must be a repository-relative path")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise UsageError(f"{field} must not escape the repository root")
    if not parts:
        return None
    return "/".join(parts)


def is_under_prefix(path: str, prefix: str | None) -> bool:
    """True when *path* is the prefix itself or sits below it."""

    if prefix is None:
        return True
    return path == prefix or path.startswith(prefix + "/")


__all__ = ["is_under_prefix", "normalize_repo_prefix"]
