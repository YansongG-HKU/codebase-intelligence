"""Incremental index construction (``docs/SPEC.md`` §8).

``ensure_index`` is the only way the engine builds an index.  It

1. resolves the repository root and scans it with the (frozen) scan policy;
2. reuses cached per-file :class:`~codebase_intelligence.parsers.ParseResult`
   payloads when ``(size, mtime_ns, sha256, parserVersion)`` all match;
3. reparses new/changed files, drops deleted ones, and rebuilds symbols and
   import relations from the per-file results;
4. resolves imports with the graph resolver and normalizes the
   :class:`~codebase_intelligence.model.entities.IndexSnapshot`;
5. atomically writes ``index.v1.json`` and ``cache.v1.json`` under the cache
   directory (never under the repository when ``cache_dir`` is passed).

The function is deterministic: two runs over identical repository content with
the same policy and engine version produce identical ``index.v1.json`` bytes and
the same :meth:`IndexSnapshot.fingerprint`, whether the second run hit the cache
or not.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from codebase_intelligence import __version__
from codebase_intelligence.errors import IndexError as CbiIndexError
from codebase_intelligence.errors import RepositoryError
from codebase_intelligence.graph import resolve_imports
from codebase_intelligence.indexing.cache import (
    CacheHeader,
    cache_header,
    entry_payload,
    load_cache,
    write_cache,
)
from codebase_intelligence.indexing.serving import (
    read_serving_metadata,
    repository_stamp,
    write_serving_metadata,
)
from codebase_intelligence.indexing.store import (
    INDEX_FILE_NAME,
    atomic_write_json,
    read_json,
)
from codebase_intelligence.model import SCHEMA_VERSION
from codebase_intelligence.model import (
    CacheStats,
    FileRecord,
    IndexSnapshot,
    ParseIssue,
    RelationRecord,
    SymbolRecord,
)
from codebase_intelligence.parsers import ParseResult, parse_file
from codebase_intelligence.util import bounded_text, is_within

if TYPE_CHECKING:
    from codebase_intelligence.scanner import ScanPolicy, ScanResult

#: Engine version serialized into every index (cache invalidation input).
ENGINE_VERSION = __version__

#: ParseIssue messages are bounded (SPEC §6) even for I/O failures.
_MAX_ISSUE_MESSAGE_CHARS = 300


@dataclass(frozen=True, slots=True)
class IndexResult:
    """One completed incremental index build."""

    snapshot: IndexSnapshot
    cache: CacheStats
    index_path: Path


#: Process-local serving cache.  The key includes the metadata stamp, so a
#: changed working tree can never reuse an old snapshot in the same process.
_SERVED_CACHE: OrderedDict[tuple[str, str, str], IndexResult] = OrderedDict()
_SERVED_CACHE_LIMIT = 2


# ---------------------------------------------------------------------------
# Root / policy plumbing
# ---------------------------------------------------------------------------
def resolve_root(root: str | os.PathLike[str]) -> Path:
    """Resolve *root* strictly and prove it is an existing directory."""

    requested = Path(root)
    try:
        resolved = requested.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepositoryError(f"repository root does not exist: {requested}") from exc
    if not resolved.is_dir():
        raise RepositoryError(f"repository root is not a directory: {requested}")
    return resolved


def _scanner_api() -> tuple[Callable[..., ScanPolicy], Callable[[Path, ScanPolicy | None], ScanResult]]:
    """Load the scanner lazily (keeps indexing importable during bootstrap)."""

    from codebase_intelligence.scanner import default_policy, scan_repository

    return default_policy, scan_repository


def resolve_policy(policy: ScanPolicy | None = None) -> ScanPolicy:
    if policy is not None:
        return policy
    default_policy, _scan_repository = _scanner_api()
    return default_policy()


def index_dir(
    root: str | os.PathLike[str],
    policy: Any = None,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Directory holding ``index.v1.json`` / ``cache.v1.json`` for *root*.

    An explicit ``cache_dir`` wins (that is how the DSH plugin keeps the user's
    repository read-only); otherwise the policy's index directory name is used
    under the resolved root.
    """

    if cache_dir is not None:
        return Path(cache_dir).expanduser().resolve(strict=False)
    active_policy = resolve_policy(policy)
    base = resolve_root(root)
    return base / active_policy.index_dir_name


# ---------------------------------------------------------------------------
# Per-file parsing
# ---------------------------------------------------------------------------
def _issue(record: FileRecord, message: str) -> ParseIssue:
    return ParseIssue(
        path=record.path, message=bounded_text(message, _MAX_ISSUE_MESSAGE_CHARS)
    )


def _parse_record(root: Path, record: FileRecord, max_file_bytes: int) -> ParseResult:
    """Read one indexed file and parse it, converting I/O problems to issues."""

    candidate = root / record.path
    if not is_within(root, candidate):
        return ParseResult(
            issues=(_issue(record, "file skipped: path escapes the repository root"),)
        )
    try:
        with open(candidate, "rb") as handle:
            data = handle.read(max_file_bytes + 1)
    except OSError as exc:
        return ParseResult(
            issues=(_issue(record, f"file skipped: unreadable ({type(exc).__name__})"),)
        )
    if len(data) > max_file_bytes:
        return ParseResult(
            issues=(_issue(record, "file skipped: grew beyond the scan policy size limit"),)
        )
    # Repository content is untrusted: decode defensively, never execute.
    text = data.decode("utf-8", errors="replace")
    return parse_file(record, text)


def _mtime_ns(root: Path, record: FileRecord) -> int:
    try:
        return int((root / record.path).stat().st_mtime_ns)
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Index build
# ---------------------------------------------------------------------------
def ensure_index(
    root: str | os.PathLike[str],
    policy: Any = None,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
    force: bool = False,
) -> IndexResult:
    """Build or incrementally refresh the index for *root*.

    Args:
        root: Repository root (resolved strictly; must exist and be a directory).
        policy: ``ScanPolicy``; defaults to the documented scanner policy.
        cache_dir: Where ``index.v1.json`` / ``cache.v1.json`` live.  When
            omitted, ``<root>/<policy.index_dir_name>`` is used.
        force: Ignore (and replace) any existing cache and reparse every file.

    Raises:
        RepositoryError: The root is missing or is not a directory.
        IndexError: The index could not be written.

    The returned ``result.snapshot`` excludes the absolute root only from
    serialized payloads; ``snapshot.root`` keeps it for in-process callers.
    """

    root_path = resolve_root(root)
    active_policy = resolve_policy(policy)
    default_policy, scan_repository = _scanner_api()
    policy_is_default = active_policy == default_policy()
    try:
        scan = scan_repository(root_path, active_policy)
    except CbiIndexError:
        raise
    except RepositoryError:
        raise
    except Exception as exc:  # noqa: BLE001 - wrap unexpected scanner failures
        raise CbiIndexError(f"repository scan failed: {exc}") from exc

    directory = index_dir(root_path, active_policy, cache_dir=cache_dir)
    index_path = directory / INDEX_FILE_NAME
    header: CacheHeader = cache_header(
        engine_version=ENGINE_VERSION,
        policy_fingerprint=scan.policy_fingerprint,
    )

    loaded = load_cache(directory / "cache.v1.json", header)
    reusable = loaded.header_valid and not force
    current_paths = {file.path for file in scan.files}
    removed = (
        len(set(loaded.entries) - current_paths) if (loaded.header_valid and not force) else 0
    )

    parsed: dict[str, ParseResult] = {}
    entry_payloads: dict[str, dict[str, Any]] = {}
    files_reused = 0
    files_reparsed = 0
    max_file_bytes = int(getattr(active_policy, "max_file_bytes", 1_048_576))
    for record in scan.files:
        mtime_ns = _mtime_ns(root_path, record)
        cached = loaded.entries.get(record.path) if reusable else None
        if cached is not None and cached.is_reusable_for(record, mtime_ns):
            result = cached.result
            files_reused += 1
        else:
            result = _parse_record(root_path, record, max_file_bytes)
            files_reparsed += 1
        parsed[record.path] = result
        entry_payloads[record.path] = entry_payload(record, mtime_ns, result)

    symbols: list[SymbolRecord] = []
    raw_relations: list[RelationRecord] = []
    parse_issues: list[ParseIssue] = []
    for file in scan.files:
        result = parsed[file.path]
        symbols.extend(result.symbols)
        raw_relations.extend(result.relations)
        parse_issues.extend(result.issues)

    # Import resolution is rebuilt on every run (cheap) and is deterministic.
    resolved_relations = resolve_imports(scan.files, raw_relations)
    snapshot = IndexSnapshot.build(
        engine_version=ENGINE_VERSION,
        policy_fingerprint=scan.policy_fingerprint,
        root=str(root_path),
        files=scan.files,
        symbols=symbols,
        relations=resolved_relations,
        parse_issues=parse_issues,
    )

    try:
        atomic_write_json(index_path, snapshot.public_dict())
        write_cache(directory, header, entry_payloads)
        # The sidecar is optional for correctness (a missing sidecar simply
        # forces the normal build next time), but it is what enables fast
        # serving.  Do not fail an otherwise valid index if the sidecar cannot
        # be written on a read-only cache filesystem.
        try:
            write_serving_metadata(
                directory,
                root=root_path,
                snapshot=snapshot,
                default_policy=policy_is_default,
            )
        except OSError:
            pass
    except OSError as exc:
        raise CbiIndexError(f"failed to write index under {directory}: {exc}") from exc

    cache_stats = CacheStats(
        files_reused=files_reused,
        files_reparsed=files_reparsed,
        files_removed=removed,
        cache_hit=bool(loaded.header_valid and not force and files_reparsed == 0),
    )
    return IndexResult(snapshot=snapshot, cache=cache_stats, index_path=index_path)


def load_served_index(
    root: str | os.PathLike[str],
    *,
    cache_dir: str | os.PathLike[str] | None = None,
    policy: Any = None,
) -> IndexResult | None:
    """Return a previously built snapshot when the repository stamp matches.

    This is the serving path: it performs a stat-only stamp walk and a JSON
    decode, but never scans/hashes/parses source files and never rebuilds the
    graph.  A missing sidecar, any metadata change or a malformed index returns
    ``None`` so the caller falls back to :func:`ensure_index`.
    """

    # A caller-supplied scan policy can change the indexed file set; the fast
    # path deliberately only serves the default policy.
    if policy is not None:
        return None
    try:
        root_path = resolve_root(root)
        directory = index_dir(root_path, None, cache_dir=cache_dir)
        metadata = read_serving_metadata(directory)
        if metadata is None:
            return None
        if (
            str(metadata.get("engineVersion", "")) != ENGINE_VERSION
            or str(metadata.get("schemaVersion", "")) != SCHEMA_VERSION
            or metadata.get("defaultPolicy") is not True
        ):
            return None
        stamp = repository_stamp(root_path, directory)
        if stamp != metadata.get("stamp"):
            return None
        key = (str(root_path), str(directory), stamp)
        cached = _SERVED_CACHE.get(key)
        if cached is not None:
            _SERVED_CACHE.move_to_end(key)
            return cached
        document = read_json(directory / INDEX_FILE_NAME)
        if not isinstance(document, dict):
            return None
        expected_fingerprint = str(metadata.get("snapshotFingerprint", ""))
        if not expected_fingerprint or document.get("fingerprint") != expected_fingerprint:
            return None
        if document.get("policyFingerprint") != metadata.get("policyFingerprint"):
            return None
        if (
            int(metadata.get("fileCount", -1)) != len(document.get("files", ()))
            or int(metadata.get("symbolCount", -1)) != len(document.get("symbols", ()))
            or int(metadata.get("relationCount", -1)) != len(document.get("relations", ()))
        ):
            return None
        snapshot = IndexSnapshot.from_public_dict(
            document,
            root=str(root_path),
            fingerprint=expected_fingerprint,
        )
        result = IndexResult(
            snapshot=snapshot,
            cache=CacheStats(
                files_reused=len(snapshot.files),
                files_reparsed=0,
                files_removed=0,
                cache_hit=True,
            ),
            index_path=directory / INDEX_FILE_NAME,
        )
        _SERVED_CACHE[key] = result
        _SERVED_CACHE.move_to_end(key)
        while len(_SERVED_CACHE) > _SERVED_CACHE_LIMIT:
            _SERVED_CACHE.popitem(last=False)
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return None


__all__ = [
    "ENGINE_VERSION",
    "IndexResult",
    "ensure_index",
    "index_dir",
    "load_served_index",
    "resolve_policy",
    "resolve_root",
]
