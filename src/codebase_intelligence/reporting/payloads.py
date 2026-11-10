"""Deterministic JSON payload builders for the six model-facing operations.

Every builder follows the same contract (``docs/SPEC.md`` §3/§4/§10):

* the payload carries the ``index`` block built from the snapshot itself, so two
  runs on identical content return identical bytes;
* every list has an explicit total order;
* the answer is measured with the shared token estimator and shrunk by dropping
  whole rows until it fits; ``truncated`` and omitted counts say what was lost;
* nothing volatile (timestamps, durations, absolute paths, cache state) leaks in.

These builders never import :mod:`codebase_intelligence.api` (the integration
layer imports them) and never import :mod:`codebase_intelligence.graph` at module
load time: the documented Graph/ImpactResult APIs are consumed structurally.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from codebase_intelligence.errors import UsageError
from codebase_intelligence.model import (
    FileRecord,
    IndexSnapshot,
    SymbolRecord,
    RelationType,
    SymbolKind,
    file_id,
)
from codebase_intelligence.model.entities import SCHEMA_VERSION
from codebase_intelligence.retrieval.budget import (
    budgets_block,
    clamp_max_tokens,
    finalize_payload,
    index_block,
    measured_tokens,
)
from codebase_intelligence.retrieval.context import ContextPack, context_payload_dict
from codebase_intelligence.retrieval.paths import is_under_prefix, normalize_repo_prefix
from codebase_intelligence.retrieval.rank import SearchHit
from codebase_intelligence.util import bounded_text, to_posix

#: Tool defaults from SPEC §4 (callers may pass an explicit budget instead).
DEFAULT_TOKENS: dict[str, int] = {
    "overview": 900,
    "map": 1600,
    "search": 1200,
    "dependencies": 1200,
    "context": 2200,
    "impact": 1200,
}

MAX_LANGUAGE_ROWS = 24
MAX_TOP_DIRECTORIES = 8
MAX_ENTRY_POINTS = 10
MAX_PARSE_ISSUE_SAMPLES = 5
MAX_PARSE_ISSUE_CHARS = 300
MAX_SIGNATURE_CHARS = 120
MAX_QUERY_ECHO_CHARS = 200
MAX_EDGE_TARGET_CHARS = 160
MAX_SYMBOLS_PER_ENTRY = 12
MAX_EDGE_ROWS = 320

_ENTRY_SYMBOL_NAMES = ("main", "run")
_ENTRY_SYMBOL_KINDS = (SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CLASS)
#: Conventional entry-point file names (SPEC 10 reporting heuristic).
_ENTRY_FILE_BASENAMES = frozenset(
    {
        "__main__.py",
        "main.py",
        "cli.py",
        "app.py",
        "server.py",
        "manage.py",
        "main.go",
        "main.rs",
    }
)
#: Module barrels are only entry points when they declare a ``main`` symbol.
_ENTRY_INDEX_BASENAMES = frozenset({"index.ts", "index.tsx", "index.js", "index.jsx"})
_DIRECTIONS = ("both", "imports", "dependents")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _envelope(command: str, snapshot: IndexSnapshot) -> dict[str, Any]:
    return {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "command": command,
        "index": index_block(snapshot),
    }


def _sorted_files(snapshot: IndexSnapshot) -> list[FileRecord]:
    return sorted(snapshot.files, key=lambda item: item.path)


def _sorted_symbols(snapshot: IndexSnapshot) -> list[SymbolRecord]:
    return sorted(
        snapshot.symbols,
        key=lambda item: (item.path, item.span.start_line, item.kind.value, item.qualified_name),
    )


def _clip(text: str, limit: int) -> str:
    return bounded_text(str(text), limit)


def _language_rows(snapshot: IndexSnapshot) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, int]] = {}
    for file in _sorted_files(snapshot):
        entry = stats.setdefault(file.language.value, {"files": 0, "symbols": 0})
        entry["files"] += 1
    for symbol in _sorted_symbols(snapshot):
        entry = stats.setdefault(symbol.language.value, {"files": 0, "symbols": 0})
        entry["symbols"] += 1
    return [
        {"language": language, "files": value["files"], "symbols": value["symbols"]}
        for language, value in sorted(stats.items())
    ]


def _directory_of(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "."


def _top_directory_rows(snapshot: IndexSnapshot) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, int]] = {}
    for file in _sorted_files(snapshot):
        entry = stats.setdefault(_directory_of(file.path), {"files": 0, "symbols": 0})
        entry["files"] += 1
    for symbol in _sorted_symbols(snapshot):
        entry = stats.setdefault(_directory_of(symbol.path), {"files": 0, "symbols": 0})
        entry["symbols"] += 1
    rows = [
        {"path": path, "files": value["files"], "symbols": value["symbols"]}
        for path, value in sorted(
            stats.items(), key=lambda item: (-item[1]["files"], -item[1]["symbols"], item[0])
        )
    ]
    return rows


def _is_top_level(symbol: Any, symbols_by_id: dict[str, Any]) -> bool:
    """Top-level declaration: no parent, or owned directly by a module/package.

    Parser adapters model top-level functions as children of their module symbol,
    so "parentId is null" alone would find nothing on a real index; a module owner
    is still a top-level declaration.  A class-owned method is not.
    """

    if symbol.parent_id is None:
        return True
    parent = symbols_by_id.get(symbol.parent_id)
    return parent is not None and parent.kind in (SymbolKind.MODULE, SymbolKind.PACKAGE)


def entry_point_rows(snapshot: IndexSnapshot) -> list[dict[str, Any]]:
    """One shared deterministic entry-point heuristic for every report.

    Tier 1: top-level function/method/class symbols named ``main`` (``run`` only
    when no ``main`` exists).  Tier 2: conventional entry files
    (``__main__.py``, ``main.py``, ``cli.py``, ``app.py``, ``server.py``,
    ``manage.py``, ``main.go``, ``main.rs``), with ``index.ts/js`` accepted only
    when the file declares a ``main`` symbol.  Each row is
    ``{path, symbol, kind, line}`` sorted by path.  This is a heuristic, not a
    claim about program execution.
    """

    symbols_by_id = {symbol.id: symbol for symbol in snapshot.symbols}
    symbols = _sorted_symbols(snapshot)
    symbols_by_path: dict[str, list[Any]] = {}
    for symbol in symbols:
        symbols_by_path.setdefault(symbol.path, []).append(symbol)

    rows: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for name in _ENTRY_SYMBOL_NAMES:
        found = [
            symbol
            for symbol in symbols
            if symbol.name == name
            and symbol.kind in _ENTRY_SYMBOL_KINDS
            and _is_top_level(symbol, symbols_by_id)
        ]
        if not found:
            continue
        for symbol in found:
            rows.append(
                {
                    "path": symbol.path,
                    "symbol": symbol.qualified_name or symbol.name,
                    "kind": symbol.kind.value,
                    "line": symbol.span.start_line,
                }
            )
            seen_paths.add(symbol.path)
        break  # main wins; run is only considered when there is no main

    for file in _sorted_files(snapshot):
        if file.path in seen_paths:
            continue
        base = file.path.rsplit("/", 1)[-1]
        if base in _ENTRY_FILE_BASENAMES:
            named = [
                symbol
                for symbol in symbols_by_path.get(file.path, ())
                if symbol.name in _ENTRY_SYMBOL_NAMES
            ]
            if named:
                symbol = named[0]
                rows.append(
                    {
                        "path": file.path,
                        "symbol": symbol.qualified_name or symbol.name,
                        "kind": symbol.kind.value,
                        "line": symbol.span.start_line,
                    }
                )
            else:
                rows.append({"path": file.path, "symbol": None, "kind": "file", "line": 1})
            seen_paths.add(file.path)
        elif base in _ENTRY_INDEX_BASENAMES:
            named = [
                symbol for symbol in symbols_by_path.get(file.path, ()) if symbol.name == "main"
            ]
            if not named:
                continue
            symbol = named[0]
            rows.append(
                {
                    "path": file.path,
                    "symbol": symbol.qualified_name or symbol.name,
                    "kind": symbol.kind.value,
                    "line": symbol.span.start_line,
                }
            )
            seen_paths.add(file.path)

    rows.sort(key=lambda row: (row["path"], row["line"], row["symbol"] or "", row["kind"]))
    return rows


def _issue_rows(snapshot: IndexSnapshot) -> list[dict[str, str]]:
    issues = sorted(snapshot.parse_issues, key=lambda item: (item.path, item.message))
    return [
        {"path": issue.path, "message": _clip(issue.message, MAX_PARSE_ISSUE_CHARS)}
        for issue in issues
    ]


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------
def overview_payload(snapshot: IndexSnapshot, graph: Any, *, max_tokens: int = 900) -> dict[str, Any]:
    """Repository overview: counts, languages, top directories, entry points."""

    del graph  # the overview shape is purely snapshot-derived
    budget = clamp_max_tokens(max_tokens)
    languages = _language_rows(snapshot)
    directories = _top_directory_rows(snapshot)
    entry_points = entry_point_rows(snapshot)
    issues = _issue_rows(snapshot)

    language_rows = languages[:MAX_LANGUAGE_ROWS]
    directory_rows = directories[:MAX_TOP_DIRECTORIES]
    entry_rows = entry_points[:MAX_ENTRY_POINTS]
    sample_rows = issues[:MAX_PARSE_ISSUE_SAMPLES]

    payload = _envelope("overview", snapshot)
    payload["repo"] = {
        "files": len(snapshot.files),
        "symbols": len(snapshot.symbols),
        "relations": len(snapshot.relations),
        "languages": language_rows,
        "topDirectories": directory_rows,
    }
    payload["entryPoints"] = entry_rows
    payload["parseIssues"] = {"count": len(issues), "sample": sample_rows}
    payload["truncated"] = False
    payload = _fit_counted_sections(
        payload,
        [
            ("directories", len(directories), directory_rows),
            ("entryPoints", len(entry_points), entry_rows),
            ("parseIssues", len(issues), sample_rows),
            ("languages", len(languages), language_rows),
        ],
        max_tokens=budget,
    )
    return payload


# ---------------------------------------------------------------------------
# map
# ---------------------------------------------------------------------------
def map_payload(
    snapshot: IndexSnapshot,
    graph: Any,
    *,
    max_tokens: int = 1600,
    focus: str | None = None,
) -> dict[str, Any]:
    """Compact structural map of files and their bounded symbol lists."""

    del graph  # the map shape is structural, not dependency-aware
    budget = clamp_max_tokens(max_tokens)
    prefix = normalize_repo_prefix(focus, field="focus") if focus is not None else None
    files = [file for file in _sorted_files(snapshot) if is_under_prefix(file.path, prefix)]
    symbols_by_file: dict[str, list[Any]] = {}
    for symbol in _sorted_symbols(snapshot):
        symbols_by_file.setdefault(symbol.path, []).append(symbol)
    total_symbols = sum(len(symbols_by_file.get(file.path, ())) for file in files)

    entries: list[dict[str, Any]] = []
    for file in files:
        symbols = symbols_by_file.get(file.path, ())
        rows: list[dict[str, Any]] = []
        for symbol in symbols[:MAX_SYMBOLS_PER_ENTRY]:
            row: dict[str, Any] = {
                "name": symbol.name,
                "kind": symbol.kind.value,
                "line": symbol.span.start_line,
            }
            if symbol.signature:
                row["signature"] = _clip(symbol.signature, MAX_SIGNATURE_CHARS)
            rows.append(row)
        entries.append({"path": file.path, "language": file.language.value, "symbols": rows})

    def make(kept: Sequence[dict[str, Any]], placeholder: int) -> dict[str, Any]:
        kept_symbols = sum(len(entry["symbols"]) for entry in kept)
        omitted_files = len(files) - len(kept)
        omitted_symbols = total_symbols - kept_symbols
        payload = _envelope("map", snapshot)
        payload["focus"] = prefix
        payload["entries"] = list(kept)
        payload["omitted"] = {"files": omitted_files, "symbols": omitted_symbols}
        payload["budgets"] = budgets_block(budget, tokens_estimated=placeholder)
        payload["truncated"] = bool(omitted_files or omitted_symbols)
        return payload

    kept: list[dict[str, Any]] = []
    if measured_tokens(make(kept, budget)) <= budget:
        for entry in entries:
            candidate = [*kept, entry]
            if measured_tokens(make(candidate, budget)) <= budget:
                kept = candidate
                continue
            if not kept:
                trimmed = _trim_entry_to_fit(entry, budget, make)
                if trimmed is not None:
                    kept = [trimmed]
            break

    payload = finalize_payload(make(kept, budget), budget)
    while kept and measured_tokens(payload) > budget:
        kept = kept[:-1]
        payload = finalize_payload(make(kept, budget), budget)
    return payload


def _trim_entry_to_fit(
    entry: dict[str, Any],
    budget: int,
    make: Any,
) -> dict[str, Any] | None:
    symbols = list(entry["symbols"])
    for keep in range(len(symbols) - 1, 0, -1):
        trimmed = {**entry, "symbols": symbols[:keep]}
        if measured_tokens(make([trimmed], budget)) <= budget:
            return trimmed
    return None


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def search_payload(
    snapshot: IndexSnapshot,
    query: str,
    hits: Sequence[SearchHit],
    *,
    max_tokens: int = 1200,
) -> dict[str, Any]:
    """Bounded lexical search results with scores and match evidence."""

    budget = clamp_max_tokens(max_tokens)
    rows = [
        {
            "path": hit.path,
            "line": int(hit.line),
            "symbol": hit.symbol,
            "kind": hit.kind,
            "language": hit.language,
            "score": round(float(hit.score), 4),
            "match": _clip(hit.match, 80),
        }
        for hit in hits
    ]
    total = len(rows)
    payload = _envelope("search", snapshot)
    payload["query"] = _clip(str(query).strip(), MAX_QUERY_ECHO_CHARS)
    payload["total"] = total
    payload["results"] = rows
    payload["truncated"] = False
    payload = _fit_counted_sections(payload, [("results", total, rows)], max_tokens=budget)
    return payload


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------
def _normalize_target_path(value: str) -> str:
    raw = to_posix(str(value or "").strip())
    while raw.startswith("./"):
        raw = raw[2:]
    return raw


def _normalize_target(snapshot: IndexSnapshot, target: str) -> tuple[str | None, Any]:
    """Return ``(path, symbol_record)`` — exactly one of them is set."""

    files_by_path, symbols_by_id, _ = snapshot.index_maps()
    value = str(target or "").strip()
    if not value:
        raise UsageError("target must be a repository-relative file path or a symbol id")
    if value in symbols_by_id:
        symbol = symbols_by_id[value]
        return symbol.path, symbol
    normalized = _normalize_target_path(value)
    if normalized in files_by_path or value in files_by_path:
        return normalized if normalized in files_by_path else value, None
    raise UsageError(f"target {value!r} was not found in the index")


def _graph_paths(graph: Any, method_name: str, path: str) -> tuple[str, ...]:
    method = getattr(graph, method_name, None)
    if not callable(method):
        return ()
    try:
        values = method(path)
    except (KeyError, ValueError, TypeError):
        return ()
    return tuple(item for item in values or () if isinstance(item, str) and item)


def _walk_files(
    graph: Any,
    start: str,
    direction: str,
    depth: int,
    known: Mapping[str, Any],
) -> dict[str, int]:
    distances: dict[str, int] = {start: 0}
    frontier = [start]
    for level in range(1, depth + 1):
        next_frontier: list[str] = []
        for path in frontier:
            neighbors: list[str] = []
            if direction in ("imports", "both"):
                neighbors.extend(_graph_paths(graph, "file_imports", path))
            if direction in ("dependents", "both"):
                neighbors.extend(_graph_paths(graph, "file_dependents", path))
            for neighbor in sorted(set(neighbors)):
                if neighbor in known and neighbor not in distances:
                    distances[neighbor] = level
                    next_frontier.append(neighbor)
        frontier = sorted(set(next_frontier))
        if not frontier:
            break
    return distances


def _edge_row(relation: Any) -> dict[str, Any]:
    target = relation.target_id or relation.target_name or ""
    return {
        "from": relation.source_id,
        "to": _clip(target, MAX_EDGE_TARGET_CHARS),
        "type": relation.relation_type.value,
        "status": relation.status.value,
        "evidence": relation.evidence.value,
    }


def _file_edges(
    snapshot: IndexSnapshot,
    node_paths: Sequence[str],
    direction: str,
) -> list[dict[str, Any]]:
    node_ids = {file_id(path) for path in node_paths}
    rows: list[dict[str, Any]] = []
    for relation in snapshot.relations:
        if relation.relation_type is not RelationType.IMPORTS:
            continue
        source_in = relation.source_id in node_ids
        target_in = bool(relation.target_id) and relation.target_id in node_ids
        if direction == "imports":
            include = source_in and (relation.target_id is None or target_in)
        elif direction == "dependents":
            include = target_in and source_in
        else:
            include = (source_in and (relation.target_id is None or target_in)) or (
                target_in and source_in
            )
        if include:
            rows.append(_edge_row(relation))
    return rows


def _symbol_edges(snapshot: IndexSnapshot, symbol_id_value: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relation in snapshot.relations:
        if relation.source_id == symbol_id_value or relation.target_id == symbol_id_value:
            rows.append(_edge_row(relation))
    return rows


def _dedupe_edges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        key = (
            str(row["from"]),
            str(row["to"]),
            str(row["type"]),
            str(row["status"]),
            str(row["evidence"]),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    unique.sort(key=lambda row: (row["from"], row["to"], row["type"], row["status"], row["evidence"]))
    return unique


def dependencies_payload(
    snapshot: IndexSnapshot,
    graph: Any,
    *,
    target: str,
    direction: str = "both",
    depth: int = 1,
    max_tokens: int = 1200,
) -> dict[str, Any]:
    """Dependency neighborhood with honest status/evidence labels on every edge."""

    budget = clamp_max_tokens(max_tokens)
    if direction not in _DIRECTIONS:
        raise UsageError("direction must be one of both|imports|dependents")
    try:
        traversal_depth = int(depth)
    except (TypeError, ValueError) as exc:
        raise UsageError(f"depth must be an integer, got {depth!r}") from exc
    traversal_depth = max(1, min(10, traversal_depth))
    files_by_path, _symbols_by_id, _ = snapshot.index_maps()
    target_path, symbol = _normalize_target(snapshot, target)
    assert target_path is not None  # _normalize_target guarantees a path

    distances = _walk_files(graph, target_path, direction, traversal_depth, files_by_path)
    node_paths = sorted(distances)

    nodes: list[dict[str, Any]] = []
    if symbol is not None:
        nodes.append({"id": symbol.id, "path": symbol.path, "distance": 0})
    focus_id = symbol.id if symbol is not None else ""
    for path in node_paths:
        nodes.append({"id": file_id(path), "path": path, "distance": distances[path]})
    nodes.sort(
        key=lambda row: (
            row["distance"],
            0 if focus_id and row["id"] == focus_id else 1,
            row["path"],
            row["id"],
        )
    )

    edges = _file_edges(snapshot, node_paths, direction)
    if symbol is not None:
        edges.extend(_symbol_edges(snapshot, symbol.id))
    unique_edges = _dedupe_edges(edges)
    edges = unique_edges[:MAX_EDGE_ROWS]

    payload = _envelope("dependencies", snapshot)
    payload["target"] = {"symbol": symbol.id} if symbol is not None else {"path": target_path}
    payload["direction"] = direction
    payload["depth"] = traversal_depth
    payload["nodes"] = nodes
    payload["edges"] = edges
    payload["truncated"] = False
    payload = _fit_counted_sections(
        payload,
        [("edges", len(unique_edges), edges), ("nodes", len(nodes), nodes)],
        max_tokens=budget,
    )
    return payload


def _fit_counted_sections(
    payload: dict[str, Any],
    sections: Sequence[tuple[str, int, list[Any]]],
    *,
    max_tokens: int,
) -> dict[str, Any]:
    """Trim counted sections (first entry = lowest priority) and report omissions.

    Each section is ``(payload_key, total_row_count, mutable_row_list)`` where the
    list object is referenced from *payload*.  Rows are popped from the tail;
    ``omitted`` receives the per-section dropped counts and ``truncated`` is set
    when anything was dropped (or kept from an earlier flag, e.g. a graph cap).
    """

    budget = clamp_max_tokens(max_tokens)
    totals = {name: int(total) for name, total, _rows in sections}
    payload["omitted"] = {name: 0 for name, _total, _rows in sections}
    payload["budgets"] = budgets_block(budget)

    def recount() -> bool:
        omitted = {name: totals[name] - len(rows) for name, _total, rows in sections}
        payload["omitted"] = omitted
        dropped = any(value > 0 for value in omitted.values())
        if dropped:
            payload["truncated"] = True
        return dropped

    def drop_one() -> bool:
        for _name, _total, rows in sections:
            if rows:
                rows.pop()
                return True
        return False

    while measured_tokens(payload) > budget and drop_one():
        recount()
    recount()
    finalize_payload(payload, budget)
    while measured_tokens(payload) > budget and drop_one():
        recount()
        finalize_payload(payload, budget)
    return payload


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------
def context_payload(
    snapshot: IndexSnapshot,
    pack: ContextPack,
    *,
    max_tokens: int = 2200,
) -> dict[str, Any]:
    """Render a :class:`ContextPack`, re-budgeted to ``max_tokens``.

    The excerpt selection already happened in ``build_context``; this only drops
    lowest-ranked whole items when the caller asks for a smaller budget and
    re-measures the final payload.
    """

    return context_payload_dict(snapshot, pack, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# impact
# ---------------------------------------------------------------------------
def _field(value: Any, names: Sequence[str], default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return ()


def _int_field(value: Any, names: Sequence[str], default: int) -> int:
    raw = _field(value, names, default)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default


def impact_payload(
    snapshot: IndexSnapshot,
    result: Any,
    *,
    max_tokens: int = 1200,
) -> dict[str, Any]:
    """Conservative change-impact preview from :class:`graph.ImpactResult`."""

    budget = clamp_max_tokens(max_tokens)
    changed_files = sorted(
        {
            _normalize_target_path(str(item))
            for item in _as_sequence(_field(result, ("changed_files", "changedFiles", "files"), ()))
            if str(item).strip()
        }
    )
    changed_symbols = sorted(
        {str(item) for item in _as_sequence(_field(result, ("changed_symbols", "changedSymbols", "symbols"), ())) if str(item).strip()}
    )

    file_rows: list[dict[str, Any]] = []
    for entry in _as_sequence(_field(result, ("affected_files", "affectedFiles"), ())):
        path = _field(entry, ("path",), None)
        if not path:
            continue
        file_rows.append(
            {
                "path": _normalize_target_path(str(path)),
                "distance": _int_field(entry, ("distance",), 1),
                "confidence": str(_field(entry, ("confidence",), "low")),
                "reason": _clip(str(_field(entry, ("reason",), "")), 160),
            }
        )
    file_rows.sort(key=lambda row: (row["distance"], row["path"], row["confidence"], row["reason"]))

    symbol_rows: list[dict[str, Any]] = []
    for entry in _as_sequence(_field(result, ("affected_symbols", "affectedSymbols"), ())):
        path = _field(entry, ("path",), None)
        name = _field(entry, ("name", "symbol", "qualified_name", "qualifiedName"), None)
        symbol_entry_id = _field(entry, ("id", "symbol_id", "symbolId"), None)
        if not path or (not name and not symbol_entry_id):
            continue
        symbol_rows.append(
            {
                "id": str(symbol_entry_id) if symbol_entry_id else "",
                "path": _normalize_target_path(str(path)),
                "symbol": str(name) if name else "",
                "distance": _int_field(entry, ("distance",), 1),
                "confidence": str(_field(entry, ("confidence",), "low")),
            }
        )
    symbol_rows.sort(
        key=lambda row: (row["distance"], row["path"], row["symbol"], row["confidence"], row["id"])
    )

    payload = _envelope("impact", snapshot)
    payload["changed"] = {"files": changed_files, "symbols": changed_symbols}
    payload["affectedFiles"] = file_rows
    payload["affectedSymbols"] = symbol_rows
    payload["truncated"] = bool(_field(result, ("truncated",), False))
    payload = _fit_counted_sections(
        payload,
        [
            ("affectedSymbols", len(symbol_rows), symbol_rows),
            ("affectedFiles", len(file_rows), file_rows),
        ],
        max_tokens=budget,
    )
    return payload


__all__ = [
    "DEFAULT_TOKENS",
    "MAX_SYMBOLS_PER_ENTRY",
    "context_payload",
    "dependencies_payload",
    "entry_point_rows",
    "impact_payload",
    "map_payload",
    "overview_payload",
    "search_payload",
]
