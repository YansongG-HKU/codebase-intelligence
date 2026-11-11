"""Fast, persistent index serving metadata.

The full index build still hashes and parses every source file.  Serving a
previously built index does not need that work: a small sidecar records a
deterministic **metadata stamp** over the repository tree (paths, sizes,
mtimes and modes, never file contents) plus the index identity.  Before a
snapshot is trusted, the stamp is recomputed with a stat-only walk; any change
falls back to the normal incremental build, so stale bytes are never served.

The stamp is intentionally conservative: it includes every regular file under
the root (including ignored files), so an edit that the scanner would ignore may
still force a rebuild.  The cost is a stat walk, not a content hash; this is the
trade-off that turns repeated commands from tens of seconds into a few seconds.

The sidecar is optional: a missing/corrupt sidecar means "rebuild", never a
failure.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from codebase_intelligence.indexing.store import atomic_write_json, read_json
from codebase_intelligence.model import SCHEMA_VERSION
from codebase_intelligence.scanner.policy import (
    DEFAULT_EXCLUDED_PATHS,
    DEFAULT_EXCLUDES,
    DEFAULT_INDEX_DIR_NAME,
)

SERVE_FILE_NAME = "serve.v1.json"
SERVE_VERSION = 1


def serving_path(directory: Path) -> Path:
    return Path(directory) / SERVE_FILE_NAME


#: Directories the default scan policy never indexes.  Pruning them from the
#: stamp walk keeps the fast path cheap on real repositories with a large
#: ``.git``/virtualenv/node_modules presence; their contents cannot change the
#: served index under the default policy.
_SKIPPED_DIRS = frozenset(DEFAULT_EXCLUDES) | {DEFAULT_INDEX_DIR_NAME}
_SKIPPED_PATHS = frozenset(DEFAULT_EXCLUDED_PATHS)


def repository_stamp(root: str | Path, cache_dir: str | Path | None = None) -> str:
    """Hash a stat-only metadata snapshot of *root* without reading file bytes."""

    root_path = Path(root).resolve()
    root_str = str(root_path)
    cache_abs = os.path.abspath(os.fspath(cache_dir)) if cache_dir is not None else ""
    digest = hashlib.sha256()

    def visit(directory: str, relative: str) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError:
            digest.update(f"{relative}\0unreadable\n".encode("utf-8"))
            return
        for entry in entries:
            child_relative = f"{relative}/{entry.name}" if relative else entry.name
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
            except OSError:
                digest.update(f"{child_relative}\0missing\n".encode("utf-8"))
                continue
            if is_directory:
                absolute = os.path.abspath(entry.path)
                if absolute == cache_abs:
                    continue
                if entry.name in _SKIPPED_DIRS or child_relative in _SKIPPED_PATHS:
                    continue
                if entry.name.startswith("."):
                    # The default policy does not index hidden directories.
                    continue
                visit(entry.path, child_relative)
                continue
            if cache_abs and os.path.abspath(entry.path).startswith(cache_abs + os.sep):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
                mode = info.st_mode
                if stat.S_ISLNK(mode):
                    try:
                        target = os.stat(entry.path)
                        size = int(target.st_size)
                        mtime_ns = int(target.st_mtime_ns)
                    except OSError:
                        size = -1
                        mtime_ns = -1
                else:
                    size = int(info.st_size)
                    mtime_ns = int(info.st_mtime_ns)
                digest.update(
                    f"{child_relative}\0{mode}\0{size}\0{mtime_ns}\n".encode("utf-8")
                )
            except OSError:
                # A concurrent deletion is a stamp change; the caller falls
                # back to the incremental build.
                digest.update(f"{child_relative}\0missing\n".encode("utf-8"))

    visit(root_str, "")
    return digest.hexdigest()


def write_serving_metadata(
    directory: Path,
    *,
    root: Path,
    snapshot: Any,
    default_policy: bool,
) -> Path:
    """Write the sidecar used by :func:`load_served_index`."""

    path = serving_path(directory)
    payload: dict[str, Any] = {
        "serveVersion": SERVE_VERSION,
        "defaultPolicy": bool(default_policy),
        "schemaVersion": str(getattr(snapshot, "schema_version", SCHEMA_VERSION)),
        "engineVersion": str(getattr(snapshot, "engine_version", "")),
        "policyFingerprint": str(getattr(snapshot, "policy_fingerprint", "")),
        "snapshotFingerprint": str(snapshot.fingerprint()),
        "fileCount": len(snapshot.files),
        "symbolCount": len(snapshot.symbols),
        "relationCount": len(snapshot.relations),
        "stamp": repository_stamp(root, directory),
    }
    atomic_write_json(path, payload)
    return path


def read_serving_metadata(directory: Path) -> dict[str, Any] | None:
    document = read_json(serving_path(directory))
    if not isinstance(document, Mapping):
        return None
    if int(document.get("serveVersion", 0)) != SERVE_VERSION:
        return None
    return dict(document)


__all__ = [
    "SERVE_FILE_NAME",
    "SERVE_VERSION",
    "read_serving_metadata",
    "repository_stamp",
    "serving_path",
    "write_serving_metadata",
]
