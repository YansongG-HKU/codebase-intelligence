"""Persistence helpers for the local JSON index and its cache.

The index is a plain canonical-JSON document: byte-stable for identical
repository content and policy (``docs/SPEC.md`` §3/§8).  Writes are atomic
(temp file in the destination directory + :func:`os.replace`), so a crash can
never leave a half-written index that the next run would trust.

The two files are:

* ``index.v1.json`` — canonical :meth:`IndexSnapshot.public_dict`;
* ``cache.v1.json`` — per-file incremental-cache document (see ``cache.py``).

Nothing in this module writes outside the directory it is handed, and it never
imports or executes scanned code.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from codebase_intelligence.util import canonical_json

#: Canonical index document written by :func:`ensure_index`.
INDEX_FILE_NAME = "index.v1.json"
#: Incremental cache document (parse results keyed by file path).
CACHE_FILE_NAME = "cache.v1.json"

#: File mode for freshly written JSON files (owner read/write only).
_FILE_MODE = 0o600


def atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically (temp file + ``os.replace``)."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, _FILE_MODE)
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    """Atomically write *value* as canonical JSON plus one trailing newline."""

    atomic_write_text(path, canonical_json(value) + "\n")


def read_json(path: Path) -> Any | None:
    """Read one JSON document; missing or malformed files return ``None``.

    A corrupt cache or index must never crash the engine: it is simply rebuilt.
    """

    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def read_canonical_json(path: Path) -> Any | None:
    """Read JSON only when the file is byte-canonical (cache validation aid)."""

    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    try:
        canonical = canonical_json(value) + "\n"
    except (TypeError, ValueError):
        return None
    if canonical != text:
        return None
    return value


__all__ = [
    "CACHE_FILE_NAME",
    "INDEX_FILE_NAME",
    "atomic_write_json",
    "atomic_write_text",
    "read_canonical_json",
    "read_json",
]
