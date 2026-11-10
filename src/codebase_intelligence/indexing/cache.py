"""Incremental parse cache: ``cache.v1.json``.

The cache lets :func:`codebase_intelligence.indexing.ensure_index` reparse only
new or changed files.  It is deliberately a *derived* document:

* the whole cache is invalidated when the schema version, engine version, scan
  policy fingerprint or :func:`~codebase_intelligence.parsers.parser_versions_digest`
  changes (``docs/SPEC.md`` §8);
* a single file entry is reused only when size, ``mtime_ns``, **and** sha256 all
  match the freshly scanned :class:`FileRecord`, so a rewritten file with the
  same mtime cannot serve stale symbols;
* the cached per-file ``ParseResult`` payload is validated defensively when
  loaded — a corrupt or hand-edited cache degrades to a full rebuild instead of
  poisoning the index.

Cache contents are never exposed in tool payloads; only aggregate counters from
:class:`~codebase_intelligence.model.entities.CacheStats` reach diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from codebase_intelligence.indexing.store import (
    CACHE_FILE_NAME,
    atomic_write_json,
    read_canonical_json,
)
from codebase_intelligence.model import (
    SCHEMA_VERSION,
    FileRecord,
    ParseIssue,
    RelationRecord,
    SymbolRecord,
)
from codebase_intelligence.parsers import (
    ParseResult,
    parser_version_for,
    parser_versions_digest,
)

#: Version of the cache document layout (not the model schema version).
CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class CacheHeader:
    """Identity fields that must match for a cache to be reusable at all."""

    cache_version: int
    schema_version: str
    engine_version: str
    policy_fingerprint: str
    parser_versions_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cacheVersion": self.cache_version,
            "schemaVersion": self.schema_version,
            "engineVersion": self.engine_version,
            "policyFingerprint": self.policy_fingerprint,
            "parserVersionsDigest": self.parser_versions_digest,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CacheHeader | None":
        try:
            return cls(
                cache_version=int(data["cacheVersion"]),
                schema_version=str(data["schemaVersion"]),
                engine_version=str(data["engineVersion"]),
                policy_fingerprint=str(data["policyFingerprint"]),
                parser_versions_digest=str(data["parserVersionsDigest"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class CachedEntry:
    """One reusable file entry: identity triple + parser version + result."""

    size_bytes: int
    mtime_ns: int
    sha256: str
    parser_version: str
    result: ParseResult

    def is_reusable_for(self, record: FileRecord, mtime_ns: int) -> bool:
        return (
            self.size_bytes == record.size_bytes
            and self.mtime_ns == int(mtime_ns)
            and self.sha256 == record.sha256
            and self.parser_version == parser_version_for(record.language)
        )


@dataclass(frozen=True, slots=True)
class CacheLoad:
    """Outcome of loading one cache document."""

    header_valid: bool
    entries: dict[str, CachedEntry]


def cache_header(*, engine_version: str, policy_fingerprint: str) -> CacheHeader:
    return CacheHeader(
        cache_version=CACHE_VERSION,
        schema_version=SCHEMA_VERSION,
        engine_version=str(engine_version),
        policy_fingerprint=str(policy_fingerprint),
        parser_versions_digest=parser_versions_digest(),
    )


# ---------------------------------------------------------------------------
# Per-file payload (de)serialization
# ---------------------------------------------------------------------------
def parse_result_payload(result: ParseResult) -> dict[str, Any]:
    return {
        "symbols": [symbol.to_dict() for symbol in result.symbols],
        "relations": [relation.to_dict() for relation in result.relations],
        "issues": [issue.to_dict() for issue in result.issues],
    }


def parse_result_from_payload(payload: Any, *, path: str) -> ParseResult | None:
    """Validate and decode one cached ``ParseResult`` (``None`` when corrupt)."""

    if not isinstance(payload, Mapping):
        return None
    try:
        symbols = tuple(
            SymbolRecord.from_dict(item) for item in payload.get("symbols", ())
        )
        relations = tuple(
            RelationRecord.from_dict(item) for item in payload.get("relations", ())
        )
        issues = tuple(ParseIssue.from_dict(item) for item in payload.get("issues", ()))
    except (KeyError, TypeError, ValueError):
        return None
    # The cache belongs to exactly one file; reject cross-file smuggling.
    for symbol in symbols:
        if symbol.path != path:
            return None
    for relation in relations:
        if relation.span is not None and relation.span.path != path:
            return None
    for issue in issues:
        if issue.path != path:
            return None
    return ParseResult(symbols=symbols, relations=relations, issues=issues)


def entry_payload(
    record: FileRecord,
    mtime_ns: int,
    result: ParseResult,
) -> dict[str, Any]:
    """Build one cache entry document for *record* and its parse result."""

    return {
        "sizeBytes": int(record.size_bytes),
        "mtimeNs": int(mtime_ns),
        "sha256": record.sha256,
        "parserVersion": parser_version_for(record.language),
        "parse": parse_result_payload(result),
    }


def _entry_from_payload(path: str, raw: Any) -> CachedEntry | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        size_bytes = int(raw["sizeBytes"])
        mtime_ns = int(raw["mtimeNs"])
        sha256 = str(raw["sha256"])
        parser_version = str(raw.get("parserVersion", ""))
    except (KeyError, TypeError, ValueError):
        return None
    result = parse_result_from_payload(raw.get("parse"), path=path)
    if result is None:
        return None
    return CachedEntry(
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        sha256=sha256,
        parser_version=parser_version,
        result=result,
    )


# ---------------------------------------------------------------------------
# Whole-document load/write
# ---------------------------------------------------------------------------
def build_cache_document(
    header: CacheHeader, entries: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    document = header.to_dict()
    document["files"] = {path: entries[path] for path in sorted(entries)}
    return document


def load_cache(path: Path, expected: CacheHeader) -> CacheLoad:
    """Load the cache at *path*; anything unexpected means "rebuild". """

    document = read_canonical_json(Path(path))
    if not isinstance(document, Mapping):
        return CacheLoad(header_valid=False, entries={})
    header = CacheHeader.from_dict(document)
    if header is None or header != expected:
        return CacheLoad(header_valid=False, entries={})
    raw_files = document.get("files")
    if not isinstance(raw_files, Mapping):
        return CacheLoad(header_valid=True, entries={})
    entries: dict[str, CachedEntry] = {}
    for raw_path, raw_entry in raw_files.items():
        entry = _entry_from_payload(str(raw_path), raw_entry)
        if entry is not None:
            entries[str(raw_path)] = entry
    return CacheLoad(header_valid=True, entries=entries)


def write_cache(
    cache_dir: Path, header: CacheHeader, entries: Mapping[str, Mapping[str, Any]]
) -> Path:
    """Atomically write the cache document and return its path."""

    path = Path(cache_dir) / CACHE_FILE_NAME
    atomic_write_json(path, build_cache_document(header, entries))
    return path


__all__ = [
    "CACHE_VERSION",
    "CacheHeader",
    "CacheLoad",
    "CachedEntry",
    "build_cache_document",
    "cache_header",
    "entry_payload",
    "load_cache",
    "parse_result_from_payload",
    "parse_result_payload",
    "write_cache",
]
