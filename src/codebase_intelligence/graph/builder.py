"""Derived graph indexes built once per :class:`~codebase_intelligence.graph.Graph`.

Building the indexes is cheap (files + one relation pass) and deterministic:
the same :class:`IndexSnapshot` always yields the same dictionaries, which is
what makes repeated tool calls byte-identical (``docs/SPEC.md`` §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from codebase_intelligence.graph.resolve import resolve_imports, source_path_from_id
from codebase_intelligence.model import (
    FileRecord,
    IndexSnapshot,
    RelationRecord,
    RelationType,
    ResolutionStatus,
    SymbolRecord,
)


@dataclass(frozen=True)
class GraphIndex:
    """Resolved relations plus the adjacency maps graph queries need."""

    snapshot: IndexSnapshot
    relations: tuple[RelationRecord, ...]
    files_by_path: dict[str, FileRecord]
    symbols_by_id: dict[str, SymbolRecord]
    symbols_by_path: dict[str, tuple[SymbolRecord, ...]]
    symbols_by_name: dict[str, tuple[SymbolRecord, ...]]
    imports_by_path: dict[str, tuple[str, ...]]
    dependents_by_path: dict[str, tuple[str, ...]]
    symbol_relations: dict[str, tuple[RelationRecord, ...]]


def _group_symbols(symbols: Iterable[SymbolRecord]) -> dict[str, tuple[SymbolRecord, ...]]:
    grouped: dict[str, list[SymbolRecord]] = {}
    for symbol in symbols:
        grouped.setdefault(symbol.path, []).append(symbol)
    return {path: tuple(sorted(items, key=lambda item: item.id)) for path, items in grouped.items()}


def _group_symbol_relations(
    relations: Iterable[RelationRecord],
) -> dict[str, tuple[RelationRecord, ...]]:
    grouped: dict[str, list[RelationRecord]] = {}

    def add(key: str, relation: RelationRecord) -> None:
        grouped.setdefault(key, []).append(relation)

    for relation in relations:
        if relation.source_id.startswith("sym:"):
            add(relation.source_id, relation)
        if relation.target_id and relation.target_id.startswith("sym:"):
            if relation.target_id != relation.source_id:
                add(relation.target_id, relation)
    return {
        key: tuple(sorted(items, key=lambda item: (item.span.start_line if item.span else 0, item.source_id, item.target_id or "")))
        for key, items in grouped.items()
    }


def _import_adjacency(
    relations: Iterable[RelationRecord], files_by_path: dict[str, FileRecord]
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    imports: dict[str, set[str]] = {}
    dependents: dict[str, set[str]] = {}
    for relation in relations:
        if (
            relation.relation_type is not RelationType.IMPORTS
            or relation.status is not ResolutionStatus.RESOLVED
        ):
            continue
        source_path = source_path_from_id(relation.source_id)
        target_path = source_path_from_id(relation.target_id or "")
        if source_path is None or target_path is None:
            continue
        if source_path not in files_by_path or target_path not in files_by_path:
            # Never expose an edge that points outside the indexed model.
            continue
        imports.setdefault(source_path, set()).add(target_path)
        dependents.setdefault(target_path, set()).add(source_path)
    return (
        {path: tuple(sorted(targets)) for path, targets in imports.items()},
        {path: tuple(sorted(sources)) for path, sources in dependents.items()},
    )


def build_graph_index(snapshot: IndexSnapshot) -> GraphIndex:
    """Resolve imports and build every adjacency map used by graph queries."""

    files_by_path = {file.path: file for file in snapshot.files}
    symbols_by_id = {symbol.id: symbol for symbol in snapshot.symbols}
    relations = resolve_imports(snapshot.files, snapshot.relations)
    imports_by_path, dependents_by_path = _import_adjacency(relations, files_by_path)
    return GraphIndex(
        snapshot=snapshot,
        relations=relations,
        files_by_path=files_by_path,
        symbols_by_id=symbols_by_id,
        symbols_by_path=_group_symbols(snapshot.symbols),
        symbols_by_name=_group_symbols_by_name(snapshot.symbols),
        imports_by_path=imports_by_path,
        dependents_by_path=dependents_by_path,
        symbol_relations=_group_symbol_relations(relations),
    )


def _group_symbols_by_name(
    symbols: Iterable[SymbolRecord],
) -> dict[str, tuple[SymbolRecord, ...]]:
    grouped: dict[str, list[SymbolRecord]] = {}
    for symbol in symbols:
        grouped.setdefault(symbol.name, []).append(symbol)
    return {name: tuple(sorted(items, key=lambda item: item.id)) for name, items in grouped.items()}


__all__ = ["GraphIndex", "build_graph_index"]
