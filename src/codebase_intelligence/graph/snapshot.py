"""Persist the graph independently of the index used by live tools."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from codebase_intelligence import ENGINE_VERSION
from codebase_intelligence.errors import RepositoryError
from codebase_intelligence.indexing.engine import ensure_index, index_dir
from codebase_intelligence.indexing.store import atomic_write_json, read_json
from codebase_intelligence.model import SCHEMA_VERSION, IndexSnapshot
from codebase_intelligence.scanner import ScanPolicy, policy_fingerprint
from codebase_intelligence.util import is_within, sha256_text

GRAPH_FILE_NAME = "graph.snapshot.json"
GRAPH_DIRECTORY = "docs/codebase-intelligence"
MAX_REPOSITORY_GRAPH_BYTES = 64 * 1024 * 1024


def graph_snapshot(snapshot: IndexSnapshot) -> IndexSnapshot:
    """Keep the fields needed for navigation without docs or source snippets."""
    return IndexSnapshot(
        schema_version=snapshot.schema_version,
        engine_version=snapshot.engine_version,
        policy_fingerprint=snapshot.policy_fingerprint,
        root=snapshot.root,
        files=snapshot.files,
        symbols=tuple(replace(symbol, signature=None, doc=None) for symbol in snapshot.symbols),
        relations=snapshot.relations,
    )


def snapshot_document(snapshot: IndexSnapshot, policy: ScanPolicy) -> dict[str, Any]:
    return {"scanSettings": policy_fingerprint(policy), "graph": snapshot.public_dict()}


def _read_published(root: Path) -> Any:
    path = root / GRAPH_DIRECTORY / GRAPH_FILE_NAME
    try:
        if not is_within(root, path) or not path.is_file():
            return None
        with path.open("rb") as handle:
            raw = handle.read(MAX_REPOSITORY_GRAPH_BYTES + 1)
        return json.loads(raw) if len(raw) <= MAX_REPOSITORY_GRAPH_BYTES else None
    except (OSError, ValueError, RecursionError):
        return None


def _decode(document: Any, root: Path, settings: str) -> IndexSnapshot | None:
    if not isinstance(document, dict) or document.get("scanSettings") != settings:
        return None
    data = document.get("graph")
    if (
        not isinstance(data, dict)
        or data.get("schemaVersion") != SCHEMA_VERSION
        or data.get("engineVersion") != ENGINE_VERSION
        or not all(isinstance(data.get(key), list) for key in ("files", "symbols", "relations", "parseIssues"))
    ):
        return None
    try:
        snapshot = IndexSnapshot.from_public_dict(data, root=str(root))
        return snapshot if data.get("fingerprint") == snapshot.fingerprint() else None
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return None


def open_graph_snapshot(
    root: Path,
    policy: ScanPolicy,
    cache_dir: Path | None,
    *,
    refresh: bool = False,
    force: bool = False,
) -> tuple[IndexSnapshot, str]:
    """Read a saved graph or build once. Only an explicit refresh replaces it."""
    settings = policy_fingerprint(policy)
    workspace = sha256_text(str(root) + "\n" + settings)
    local = index_dir(root, policy, cache_dir=cache_dir) / f"graph-{workspace}.v1.json"
    if not (refresh or force):
        try:
            cached = _decode(read_json(local), root, settings)
        except RecursionError:
            cached = None
        if cached is not None:
            return cached, "cache"
        published = _decode(_read_published(root), root, settings)
        if published is not None:
            return published, "repository"

    index = ensure_index(root, policy, cache_dir=cache_dir, force=force)
    snapshot = graph_snapshot(index.snapshot)
    try:
        atomic_write_json(local, snapshot_document(snapshot, policy))
    except OSError as exc:
        raise RepositoryError("could not save the workspace graph snapshot") from exc
    return snapshot, "refreshed" if refresh or force else "built"
