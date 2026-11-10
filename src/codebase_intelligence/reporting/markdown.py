"""Bounded, human-readable Markdown renderers (SPEC 10).

``markdown_map`` and ``markdown_report`` are for humans (CLI ``report`` and PR
notes): they cite ``path:line`` for every claim, stay within documented size
bounds, contain no timestamps/paths outside the repository, and state their
limitations honestly - heuristic parser output, unsupported languages and
unresolved/ambiguous edges are never presented as confirmed facts.
"""

from __future__ import annotations

from typing import Any

from codebase_intelligence.model import (
    EvidenceKind,
    FileRecord,
    IndexSnapshot,
    SymbolRecord,
    RelationType,
    ResolutionStatus,
    SourceSpan,
)
from codebase_intelligence.reporting.payloads import entry_point_rows
from codebase_intelligence.util import bounded_text

MAX_MAP_FILES = 60
MAX_MAP_SYMBOLS_PER_FILE = 10
MAX_MAP_CHARS = 12_000
MAX_REPORT_CHARS = 16_000
MAX_REPORT_ROWS = 10
MAX_MAP_DIRECTORIES = 10
MAX_MAP_ENTRY_POINTS = 10
MAX_ISSUE_ROWS = 8
MAX_SIGNATURE_CHARS = 110
MAX_MESSAGE_CHARS = 200

LIMITATIONS = (
    "- This is a structural view, not a semantic summary: declarations and files, "
    "not program behaviour.",
    "- Symbols and relations marked `[heuristic]` come from regex adapters; they can "
    "be incomplete or mislabelled. Treat them as leads, not confirmed facts.",
    "- Languages without an adapter are indexed as files only; their symbols are not "
    "listed here.",
    "- Dependency edges keep their status (`resolved`, `unresolved`, `ambiguous`, "
    "`external`); unresolved relationships are not dependencies.",
)


def _sorted_files(snapshot: IndexSnapshot) -> list[FileRecord]:
    return sorted(snapshot.files, key=lambda item: item.path)


def _sorted_symbols(snapshot: IndexSnapshot) -> list[SymbolRecord]:
    return sorted(
        snapshot.symbols,
        key=lambda item: (item.path, item.span.start_line, item.kind.value, item.qualified_name),
    )


def _clip(text: str, limit: int) -> str:
    return bounded_text(str(text), limit)


def _symbol_line(symbol: Any) -> str:
    signature = ""
    if symbol.signature:
        signature = f" `{_clip(symbol.signature, MAX_SIGNATURE_CHARS)}`"
    evidence = " [heuristic]" if symbol.evidence is EvidenceKind.HEURISTIC else ""
    return (
        f"- {symbol.path}:{symbol.span.start_line} {symbol.kind.value} "
        f"{symbol.qualified_name}{signature}{evidence}"
    )


def _entry_point_line(row: dict[str, Any]) -> str:
    symbol = row.get("symbol")
    if symbol:
        return f"- {row['path']}:{row['line']} {row['kind']} {symbol}"
    return f"- {row['path']}:{row['line']} file entry point"


def _join_bounded(lines: list[str], limit: int) -> str:
    """Join lines while keeping the rendered document under ``limit`` characters."""

    rendered = "\n".join(lines).rstrip() + "\n"
    if len(rendered) <= limit:
        return rendered
    kept: list[str] = []
    note = "- ... truncated: document size bound reached."
    size = 0
    for line in lines:
        size += len(line) + 1
        if size + len(note) + 1 > limit:
            break
        kept.append(line)
    return "\n".join([*kept, note]).rstrip() + "\n"


def _directory_of(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "."


def _relation_path(relation: Any) -> str:
    span = relation.span
    if isinstance(span, SourceSpan) and span.path:
        return span.path
    source = str(relation.source_id or "")
    if source.startswith("file:"):
        return source[len("file:") :]
    if source.startswith("sym:"):
        remainder = source[len("sym:") :]
        head, _, _rest = remainder.partition("#")
        return head
    return ""


# ---------------------------------------------------------------------------
# markdown_map
# ---------------------------------------------------------------------------
def markdown_map(snapshot: IndexSnapshot) -> str:
    """Compact structural map of the repository (bounded, cited, deterministic)."""

    files = _sorted_files(snapshot)
    symbols = _sorted_symbols(snapshot)
    symbols_by_file: dict[str, list[Any]] = {}
    for symbol in symbols:
        symbols_by_file.setdefault(symbol.path, []).append(symbol)

    directories: dict[str, dict[str, int]] = {}
    for file in files:
        entry = directories.setdefault(_directory_of(file.path), {"files": 0, "symbols": 0})
        entry["files"] += 1
    for symbol in symbols:
        entry = directories.setdefault(_directory_of(symbol.path), {"files": 0, "symbols": 0})
        entry["symbols"] += 1
    directory_rows = sorted(
        directories.items(), key=lambda item: (-item[1]["files"], -item[1]["symbols"], item[0])
    )

    entry_points = entry_point_rows(snapshot)

    lines: list[str] = [
        "# Repository map",
        "",
        f"- files: {len(files)}",
        f"- symbols: {len(symbols)}",
        f"- relations: {len(snapshot.relations)}",
        f"- parser issues: {len(snapshot.parse_issues)}",
        "",
        "## Top directories",
        "",
    ]
    for directory, value in directory_rows[:MAX_MAP_DIRECTORIES]:
        lines.append(f"- {directory}: {value['files']} files, {value['symbols']} symbols")
    if len(directory_rows) > MAX_MAP_DIRECTORIES:
        lines.append(f"- ... {len(directory_rows) - MAX_MAP_DIRECTORIES} more directories")

    lines.extend(["", "## Entry points", ""])
    if entry_points:
        for row in entry_points[:MAX_MAP_ENTRY_POINTS]:
            lines.append(_entry_point_line(row))
        if len(entry_points) > MAX_MAP_ENTRY_POINTS:
            lines.append(f"- ... {len(entry_points) - MAX_MAP_ENTRY_POINTS} more entry points")
    else:
        lines.append("- none detected by the name heuristic")

    lines.extend(["", "## Files", ""])
    for index, file in enumerate(files):
        if index >= MAX_MAP_FILES:
            lines.append(f"- ... {len(files) - MAX_MAP_FILES} more files (map file bound reached)")
            break
        file_symbols = symbols_by_file.get(file.path, ())
        lines.append(f"### {file.path} ({file.language.value}, {file.line_count} lines)")
        lines.append("")
        if not file_symbols:
            lines.append(
                "- no declarations extracted (unsupported language or file-only index entry)"
            )
        for symbol in file_symbols[:MAX_MAP_SYMBOLS_PER_FILE]:
            lines.append(_symbol_line(symbol))
        remaining = len(file_symbols) - MAX_MAP_SYMBOLS_PER_FILE
        if remaining > 0:
            lines.append(f"- ... {remaining} more symbols in this file")
        lines.append("")

    unsupported = sum(1 for file in files if not symbols_by_file.get(file.path))
    lines.extend(["## Limitations", ""])
    lines.extend(LIMITATIONS)
    lines.append(f"- Files without extracted declarations in this index: {unsupported}.")
    if snapshot.parse_issues:
        lines.append(
            f"- Parser issues recorded: {len(snapshot.parse_issues)} (run `cbi index --json`)."
        )
    return _join_bounded(lines, MAX_MAP_CHARS)


# ---------------------------------------------------------------------------
# markdown_report
# ---------------------------------------------------------------------------
def _safe_graph_paths(graph: Any, method_name: str, path: str) -> tuple[str, ...]:
    method = getattr(graph, method_name, None)
    if not callable(method):
        return ()
    try:
        values = method(path)
    except Exception:  # noqa: BLE001 - the report must render even with a broken graph
        return ()
    return tuple(item for item in values or () if isinstance(item, str) and item)


def _language_rows(snapshot: IndexSnapshot) -> list[tuple[str, int, int]]:
    stats: dict[str, list[int]] = {}
    for file in _sorted_files(snapshot):
        stats.setdefault(file.language.value, [0, 0])[0] += 1
    for symbol in _sorted_symbols(snapshot):
        stats.setdefault(symbol.language.value, [0, 0])[1] += 1
    rows = [(language, value[0], value[1]) for language, value in stats.items()]
    rows.sort(key=lambda row: (-row[1], -row[2], row[0]))
    return rows


def markdown_report(snapshot: IndexSnapshot, graph: Any) -> str:
    """Architecture report: what the index contains and how far to trust it."""

    files = _sorted_files(snapshot)
    symbols = _sorted_symbols(snapshot)
    lines: list[str] = [
        "# Architecture report",
        "",
        "## Summary",
        "",
        f"- files: {len(files)}",
        f"- symbols: {len(symbols)}",
        f"- relations: {len(snapshot.relations)}",
        f"- parser issues: {len(snapshot.parse_issues)}",
    ]

    lines.extend(["", "## Languages", ""])
    for language, file_count, symbol_count in _language_rows(snapshot):
        lines.append(f"- {language}: {file_count} files, {symbol_count} symbols")

    entry_points = entry_point_rows(snapshot)
    lines.extend(["", "## Entry points", ""])
    if entry_points:
        for row in entry_points[:MAX_REPORT_ROWS]:
            lines.append(_entry_point_line(row))
        if len(entry_points) > MAX_REPORT_ROWS:
            lines.append(f"- ... {len(entry_points) - MAX_REPORT_ROWS} more entry points")
    else:
        lines.append("- none detected by the name heuristic")

    hubs: list[tuple[str, int, int]] = []
    for file in files:
        dependents = _safe_graph_paths(graph, "file_dependents", file.path)
        imports = _safe_graph_paths(graph, "file_imports", file.path)
        hubs.append((file.path, len(dependents), len(imports)))
    hubs.sort(key=lambda row: (-row[1], -row[2], row[0]))
    lines.extend(["", "## Dependency hubs", ""])
    for path, dependent_count, import_count in hubs[:MAX_REPORT_ROWS]:
        if dependent_count == 0 and import_count == 0:
            continue
        lines.append(f"- `{path}` - imported by {dependent_count} file(s), imports {import_count}")
    if all(dependent_count == 0 and import_count == 0 for _, dependent_count, import_count in hubs):
        lines.append("- no resolved import edges in this index")

    unresolved = sorted(
        (
            relation
            for relation in snapshot.relations
            if relation.relation_type is RelationType.IMPORTS
            and relation.status is not ResolutionStatus.RESOLVED
        ),
        key=lambda relation: (
            _relation_path(relation),
            relation.span.start_line if relation.span else 0,
            relation.status.value,
            relation.target_name or relation.target_id or "",
        ),
    )
    lines.extend(["", "## Unresolved and external imports", ""])
    if unresolved:
        by_status: dict[str, int] = {}
        for relation in unresolved:
            by_status[relation.status.value] = by_status.get(relation.status.value, 0) + 1
        summary = ", ".join(
            f"{status}: {count}" for status, count in sorted(by_status.items())
        )
        lines.append(f"- {len(unresolved)} edges kept unresolved/external ({summary})")
        for relation in unresolved[:MAX_REPORT_ROWS]:
            path = _relation_path(relation)
            line = relation.span.start_line if relation.span else 1
            target = _clip(relation.target_name or relation.target_id or "?", MAX_MESSAGE_CHARS)
            lines.append(f"- `{path}:{line}` imports `{target}` ({relation.status.value})")
    else:
        lines.append("- none: every import in this index was resolved")

    issues = sorted(snapshot.parse_issues, key=lambda item: (item.path, item.message))
    lines.extend(["", "## Parser issues", ""])
    if issues:
        for issue in issues[:MAX_ISSUE_ROWS]:
            lines.append(f"- `{issue.path}` - {_clip(issue.message, MAX_MESSAGE_CHARS)}")
        if len(issues) > MAX_ISSUE_ROWS:
            lines.append(f"- ... {len(issues) - MAX_ISSUE_ROWS} more parser issues")
    else:
        lines.append("- none recorded")

    heuristic_relations = sum(
        1 for relation in snapshot.relations if relation.evidence is EvidenceKind.HEURISTIC
    )
    heuristic_symbols = sum(
        1 for symbol in symbols if symbol.evidence is EvidenceKind.HEURISTIC
    )
    lines.extend(["", "## Confidence and evidence", ""])
    lines.append(f"- heuristic relations (regex-derived edges): {heuristic_relations}")
    lines.append(f"- heuristic symbols (regex-derived declarations): {heuristic_symbols}")
    lines.append("- resolved edges are parser/resolver facts; everything else is labelled")

    lines.extend(["", "## Limitations", ""])
    lines.extend(LIMITATIONS)
    return _join_bounded(lines, MAX_REPORT_CHARS)


__all__ = ["MAX_MAP_CHARS", "MAX_REPORT_CHARS", "markdown_map", "markdown_report"]
