"""High-level engine operations shared by the CLI, MCP server and tests.

The CLI and the MCP server must answer exactly the same questions with exactly
the same payloads, so both call these functions instead of re-implementing the
pipeline.  The DSH plugin drives the CLI over a JSON stdio bridge and therefore
inherits the same behaviour.

Everything that reaches a model is deterministic (``docs/SPEC.md`` §3): no
timestamps, absolute paths, durations or cache state.  Diagnostics-only values
are exposed through explicit keyword arguments used by the CLI behind flags.
"""

from __future__ import annotations

import re
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from codebase_intelligence.errors import RepositoryError, UsageError
from codebase_intelligence.model import SCHEMA_VERSION, IndexSnapshot
from codebase_intelligence.util import TOKEN_ESTIMATOR, canonical_json, estimate_tokens

if TYPE_CHECKING:
    from codebase_intelligence.graph import Graph
    from codebase_intelligence.indexing import IndexResult
    from codebase_intelligence.scanner import ScanPolicy

#: Default and hard-cap token budgets for the six model-facing operations.
DEFAULT_TOOL_TOKENS: dict[str, int] = {
    "overview": 900,
    "map": 1600,
    "search": 1200,
    "dependencies": 1200,
    "context": 2200,
    "impact": 1200,
}
MAX_TOOL_TOKENS = 8000


# ---------------------------------------------------------------------------
# Root / policy / index plumbing
# ---------------------------------------------------------------------------
def resolve_root(path: str | PathLike[str] | None, *, must_exist: bool = True) -> Path:
    """Resolve a repository root and prove it is an existing directory."""

    raw = Path(path) if path not in (None, "") else Path(".")
    try:
        root = raw.expanduser().resolve(strict=must_exist)
    except OSError as exc:
        raise RepositoryError(f"cannot resolve repository root {raw}: {exc}") from exc
    if must_exist and not root.is_dir():
        raise RepositoryError(f"repository root is not a directory: {root}")
    return root


def resolve_cache_dir(cache_dir: str | PathLike[str] | None) -> Path | None:
    if cache_dir in (None, ""):
        return None
    return Path(cache_dir).expanduser().resolve(strict=False)


def build_policy(
    *,
    max_file_bytes: int | None = None,
    excludes: Sequence[str] | None = None,
    include_hidden: bool = False,
) -> ScanPolicy:
    """Build a :class:`ScanPolicy` from CLI/tool flags (defaults from SPEC §5)."""

    from codebase_intelligence.scanner import default_policy

    overrides: dict[str, Any] = {"include_hidden": include_hidden}
    if max_file_bytes is not None:
        if max_file_bytes < 1:
            raise UsageError("--max-file-bytes must be a positive integer")
        overrides["max_file_bytes"] = int(max_file_bytes)
    if excludes:
        overrides["extra_excludes"] = tuple(str(item) for item in excludes)
    return default_policy(**overrides)


def open_index(
    root: Path,
    *,
    cache_dir: Path | None = None,
    force: bool = False,
    policy: ScanPolicy | None = None,
) -> IndexResult:
    """Build or refresh the index for ``root`` (incremental unless ``force``)."""

    from codebase_intelligence.indexing import ensure_index

    if policy is None:
        policy = build_policy()
    return ensure_index(root, policy, cache_dir=cache_dir, force=force)


def graph_for(snapshot: IndexSnapshot) -> Graph:
    from codebase_intelligence.graph import Graph

    return Graph(snapshot)


def index_block(snapshot: IndexSnapshot) -> dict[str, Any]:
    """The deterministic index identity shared by every tool payload."""

    return {
        "schemaVersion": snapshot.schema_version,
        "engineVersion": snapshot.engine_version,
        "policyFingerprint": snapshot.policy_fingerprint,
        "fingerprint": snapshot.fingerprint(),
    }


def _language_summary(snapshot: IndexSnapshot) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, int]] = {}
    for file in snapshot.files:
        entry = stats.setdefault(file.language.value, {"files": 0, "symbols": 0})
        entry["files"] += 1
    for symbol in snapshot.symbols:
        entry = stats.setdefault(symbol.language.value, {"files": 0, "symbols": 0})
        entry["symbols"] += 1
    return [
        {"language": language, "files": value["files"], "symbols": value["symbols"]}
        for language, value in sorted(stats.items())
    ]


# ---------------------------------------------------------------------------
# CLI-only payloads (scan / index)
# ---------------------------------------------------------------------------
def scan_payload(root: Path, *, policy: Any = None) -> dict[str, Any]:
    from codebase_intelligence.scanner import scan_repository

    result = scan_repository(root, policy)
    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "command": "scan",
        "policyFingerprint": result.policy_fingerprint,
        "files": [item.to_dict() for item in result.files],
        "stats": result.stats.to_dict(),
    }


def index_payload(
    root: Path,
    *,
    cache_dir: Path | None = None,
    force: bool = False,
    policy: Any = None,
    diagnostics: bool = False,
) -> dict[str, Any]:
    result = open_index(root, cache_dir=cache_dir, force=force, policy=policy)
    snapshot = result.snapshot
    payload: dict[str, Any] = {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "command": "index",
        "index": index_block(snapshot),
        "repo": {
            "files": snapshot.file_count(),
            "symbols": snapshot.symbol_count(),
            "relations": snapshot.relation_count(),
            "languages": _language_summary(snapshot),
        },
        "parseIssues": {
            "count": len(snapshot.parse_issues),
            "sample": [issue.to_dict() for issue in snapshot.parse_issues[:5]],
        },
    }
    if diagnostics:
        payload["diagnostics"] = {
            "cache": result.cache.to_dict(),
            "indexPath": str(result.index_path),
        }
    return payload


# ---------------------------------------------------------------------------
# Six model-facing operations
# ---------------------------------------------------------------------------
def _clamp_tokens(value: int | None, operation: str) -> int:
    default = DEFAULT_TOOL_TOKENS[operation]
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise UsageError(f"maxTokens must be an integer, got {value!r}") from exc
    return max(64, min(MAX_TOOL_TOKENS, number))


def run_overview(
    root: Path, *, cache_dir: Path | None = None, max_tokens: int | None = None, force: bool = False
) -> dict[str, Any]:
    from codebase_intelligence import reporting

    budget = _clamp_tokens(max_tokens, "overview")
    result = open_index(root, cache_dir=cache_dir, force=force)
    graph = graph_for(result.snapshot)
    return reporting.overview_payload(result.snapshot, graph, max_tokens=budget)


def run_map(
    root: Path,
    *,
    cache_dir: Path | None = None,
    max_tokens: int | None = None,
    focus: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from codebase_intelligence import reporting

    budget = _clamp_tokens(max_tokens, "map")
    result = open_index(root, cache_dir=cache_dir, force=force)
    graph = graph_for(result.snapshot)
    return reporting.map_payload(result.snapshot, graph, max_tokens=budget, focus=focus)


def run_search(
    root: Path,
    query: str,
    *,
    cache_dir: Path | None = None,
    max_tokens: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from codebase_intelligence import reporting, retrieval

    if not isinstance(query, str) or not query.strip():
        raise UsageError("query must be a non-empty string")
    budget = _clamp_tokens(max_tokens, "search")
    result = open_index(root, cache_dir=cache_dir, force=force)
    graph = graph_for(result.snapshot)
    hits = retrieval.search(result.snapshot, graph, query.strip(), limit=20)
    return reporting.search_payload(result.snapshot, query.strip(), hits, max_tokens=budget)


def _normalize_target(snapshot: IndexSnapshot, target: str) -> str:
    """Resolve ``target`` to a repository-relative path or a symbol id."""

    value = (target or "").strip().replace("\\", "/")
    if not value:
        raise UsageError("target must be a file path or symbol name")
    files_by_path, symbols_by_id, symbols_by_file = snapshot.index_maps()
    if value in files_by_path:
        return value
    if value in symbols_by_id:
        return value
    by_name = [symbol for symbol in snapshot.symbols if symbol.name == value]
    if len(by_name) == 1:
        return by_name[0].id
    by_qualified = [symbol for symbol in snapshot.symbols if symbol.qualified_name == value]
    if len(by_qualified) == 1:
        return by_qualified[0].id
    if len(by_name) > 1 or len(by_qualified) > 1:
        raise UsageError(
            f"target {value!r} is ambiguous; pass a repository-relative file path or a symbol id",
        )
    raise UsageError(f"target {value!r} was not found in the index")


def run_dependencies(
    root: Path,
    target: str,
    *,
    direction: str = "both",
    depth: int = 1,
    cache_dir: Path | None = None,
    max_tokens: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from codebase_intelligence import reporting

    if direction not in {"both", "imports", "dependents"}:
        raise UsageError("direction must be one of both|imports|dependents")
    if depth < 1 or depth > 5:
        raise UsageError("depth must be between 1 and 5")
    budget = _clamp_tokens(max_tokens, "dependencies")
    result = open_index(root, cache_dir=cache_dir, force=force)
    snapshot = result.snapshot
    graph = graph_for(snapshot)
    resolved = _normalize_target(snapshot, target)
    return reporting.dependencies_payload(
        snapshot,
        graph,
        target=resolved,
        direction=direction,
        depth=int(depth),
        max_tokens=budget,
    )


def run_context(
    root: Path,
    task: str,
    *,
    max_tokens: int | None = None,
    path_prefix: str | None = None,
    cache_dir: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from codebase_intelligence import reporting, retrieval

    if not isinstance(task, str) or not task.strip():
        raise UsageError("task must be a non-empty string")
    budget = _clamp_tokens(max_tokens, "context")
    result = open_index(root, cache_dir=cache_dir, force=force)
    graph = graph_for(result.snapshot)
    pack = retrieval.build_context(
        result.snapshot,
        graph,
        task.strip(),
        max_tokens=budget,
        path_prefix=path_prefix,
    )
    return reporting.context_payload(result.snapshot, pack)


def _validate_impact_file(raw: str) -> str:
    """Normalize one impact file path and reject workspace escapes.

    ``impact`` is the only structural command where a user-supplied file path is
    not looked up in the index first, so a traversal or absolute path would
    otherwise be silently ignored while looking like a valid request.
    """

    value = str(raw).strip().replace("\\", "/")
    if value in {"", ".", "./", "~"} or value.startswith("~/"):
        raise UsageError(f"impact file path must name a file inside the workspace: {raw!r}")
    if value.startswith("/") or value.startswith("//") or re.match(r"^[A-Za-z]:", value):
        raise UsageError(f"impact file path must be repository-relative: {raw!r}")
    parts = [part for part in value.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise UsageError(f"impact file path must not escape the workspace: {raw!r}")
    return "/".join(parts)


def run_impact(
    root: Path,
    *,
    files: Iterable[str] = (),
    symbols: Iterable[str] = (),
    max_tokens: int | None = None,
    cache_dir: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from codebase_intelligence import reporting

    file_list = [_validate_impact_file(item) for item in files if item and str(item).strip()]
    symbol_list = [item.strip() for item in symbols if item and item.strip()]
    if not file_list and not symbol_list:
        raise UsageError("impact requires at least one file or symbol")
    budget = _clamp_tokens(max_tokens, "impact")
    result = open_index(root, cache_dir=cache_dir, force=force)
    graph = graph_for(result.snapshot)
    impact = graph.impact(files=file_list, symbols=symbol_list, max_results=200)
    return reporting.impact_payload(result.snapshot, impact, max_tokens=budget)


def report_markdown(
    root: Path, *, cache_dir: Path | None = None, force: bool = False
) -> str:
    from codebase_intelligence import reporting

    result = open_index(root, cache_dir=cache_dir, force=force)
    graph = graph_for(result.snapshot)
    return reporting.markdown_report(result.snapshot, graph)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
def doctor_payload() -> dict[str, Any]:
    import platform
    import sys

    from codebase_intelligence import __version__

    payload: dict[str, Any] = {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "command": "doctor",
        "engine": {"version": __version__, "schemaVersion": SCHEMA_VERSION},
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "defaults": {
            "maxFileBytes": 1_048_576,
            "tokenEstimator": TOKEN_ESTIMATOR,
            "toolTokens": dict(sorted(DEFAULT_TOOL_TOKENS.items())),
            "maxToolTokens": MAX_TOOL_TOKENS,
        },
        "modules": {},
    }
    for name in ("scanner", "parsers", "graph", "indexing", "retrieval", "reporting"):
        try:
            __import__(f"codebase_intelligence.{name}")
            payload["modules"][name] = "available"
        except Exception as exc:  # noqa: BLE001 - diagnostics must never crash
            payload["modules"][name] = f"unavailable: {exc}"
    return payload


def token_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach the measured size of a payload (diagnostics only)."""

    text = canonical_json(payload)
    return {
        "bytes": len(text.encode("utf-8")),
        "chars": len(text),
        "tokensEstimated": estimate_tokens(text),
        "tokenEstimator": TOKEN_ESTIMATOR,
    }
