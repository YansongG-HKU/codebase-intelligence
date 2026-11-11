"""Incremental indexing: scan → parse (cached) → resolve → persist.

Public surface (``docs/SPEC.md`` §8)::

    from codebase_intelligence.indexing import ensure_index, index_dir

    result = ensure_index(Path("."), policy, cache_dir=Path(".../.cache"))
    result.snapshot          # populated IndexSnapshot
    result.cache             # CacheStats (diagnostics only)
    result.index_path        # Path to index.v1.json

The cache lives under ``<root>/.codebase-intelligence`` by default.  Pass an
explicit ``cache_dir`` (the DSH plugin does, under its own data directory) to
keep the scanned repository completely untouched.
"""

from codebase_intelligence.indexing.cache import (
    CACHE_VERSION,
    CacheHeader,
    CacheLoad,
    CachedEntry,
)
from codebase_intelligence.indexing.engine import (
    ENGINE_VERSION,
    IndexResult,
    ensure_index,
    index_dir,
    load_served_index,
    resolve_policy,
    resolve_root,
)
from codebase_intelligence.indexing.serving import SERVE_FILE_NAME
from codebase_intelligence.indexing.store import (
    CACHE_FILE_NAME,
    INDEX_FILE_NAME,
    atomic_write_json,
    atomic_write_text,
    read_canonical_json,
    read_json,
)

__all__ = [
    "CACHE_FILE_NAME",
    "CACHE_VERSION",
    "ENGINE_VERSION",
    "INDEX_FILE_NAME",
    "SERVE_FILE_NAME",
    "CacheHeader",
    "CacheLoad",
    "CachedEntry",
    "IndexResult",
    "atomic_write_json",
    "atomic_write_text",
    "ensure_index",
    "index_dir",
    "load_served_index",
    "read_canonical_json",
    "read_json",
    "resolve_policy",
    "resolve_root",
]
