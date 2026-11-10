"""Coded errors shared by the library, CLI, MCP server and DSH bridge.

Every public entry point converts a :class:`CbiError` into a machine-readable
envelope ``{"ok": false, "error": {"code", "message", "detail"}}`` instead of a
traceback.  The error ``code`` is part of the CLI/tool contract (see
``docs/SPEC.md``), so callers may branch on it.
"""

from __future__ import annotations

from typing import Any

#: Stable error codes used across transports.
ERROR_CODES = (
    "invalid_arguments",
    "not_found",
    "not_a_directory",
    "outside_root",
    "index_failed",
    "parse_failed",
    "budget_exceeded",
    "python_unavailable",
    "internal_error",
)


class CbiError(Exception):
    """Base class for expected, user-actionable failures."""

    code = "internal_error"
    exit_code = 4

    def __init__(self, message: str, *, detail: str = "", code: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        return payload


class UsageError(CbiError):
    """Bad command-line or tool arguments."""

    code = "invalid_arguments"
    exit_code = 2


class RepositoryError(CbiError):
    """The requested repository root is missing, unreadable or out of scope."""

    code = "not_a_directory"
    exit_code = 3


class OutsideRootError(RepositoryError):
    """A path escaped the repository root (traversal or symlink escape)."""

    code = "outside_root"


class IndexError(CbiError):
    """The index could not be built, loaded or refreshed."""

    code = "index_failed"
    exit_code = 3


class ParseError(CbiError):
    """A parser adapter failed on an input in a way that must be reported."""

    code = "parse_failed"


def error_envelope(error: CbiError, *, command: str = "") -> dict[str, Any]:
    """Render the shared error envelope used by the CLI and the DSH bridge."""

    return {
        "ok": False,
        "schemaVersion": "1",
        "command": command,
        "error": error.to_dict(),
    }
