"""Graph queries: imports, dependents, symbol neighborhoods and impact.

The :class:`Graph` object wraps an immutable :class:`IndexSnapshot`.  Imports are
resolved once in :meth:`Graph.__init__` (via :func:`resolve_imports`), so a graph
built from a raw parser snapshot and a graph built from an already-resolved one
behave identically.

Queries are conservative by contract (``docs/SPEC.md`` §7):

* ``file_imports`` / ``file_dependents`` expose only *resolved* file edges;
* ``transitive_dependents`` walks reverse import edges, cycle-safe;
* ``symbol_neighborhood`` reports relation-backed neighbors with direction,
  status, evidence and confidence;
* ``impact`` combines the resolved reverse-import closure with symbol-level
  edges and clearly labels heuristic/call/base claims as ``medium`` and pure
  name coincidence as ``low``.  It never invents an edge to look useful.

All returned sequences are sorted deterministically.
"""

from __future__ import annotations

from typing import Any, Iterable

from codebase_intelligence.graph.builder import GraphIndex, build_graph_index
from codebase_intelligence.graph.model import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    ImpactEntry,
    ImpactResult,
    ImpactSymbolEntry,
    confidence_rank,
)
from codebase_intelligence.graph.resolve import source_path_from_id
from codebase_intelligence.model import (
    EvidenceKind,
    IndexSnapshot,
    RelationRecord,
    RelationType,
    SymbolRecord,
)
from codebase_intelligence.util import to_posix

#: Safety valve for reverse-dependency and neighborhood walks.
MAX_TRAVERSAL_DEPTH = 10
#: Hard cap on ``impact`` entries per list even if the caller passes more.
MAX_IMPACT_RESULTS = 1_000
#: Relations whose target *name* can be matched to a changed symbol heuristically.
_HEURISTIC_NAME_EDGES = (RelationType.CALLS, RelationType.INHERITS, RelationType.IMPLEMENTS)


def _normalize_repo_path(raw: object) -> str:
    value = to_posix(str(raw)).strip()
    while value.startswith("./"):
        value = value[2:]
    return value


class Graph:
    """Structural queries over one indexed snapshot."""

    def __init__(self, snapshot: IndexSnapshot) -> None:
        self.snapshot = snapshot
        self._index: GraphIndex = build_graph_index(snapshot)

    # -- resolved relations exposed for reporting -------------------------
    @property
    def relations(self) -> tuple[RelationRecord, ...]:
        """Resolved relations (resolver evidence for every attempted import)."""

        return self._index.relations

    @property
    def files_by_path(self) -> dict[str, object]:
        """Read-only view of the files map; callers must not mutate it."""

        return dict(self._index.files_by_path)

    @property
    def symbols_by_id(self) -> dict[str, SymbolRecord]:
        """Read-only view of the symbol map; callers must not mutate it."""

        return dict(self._index.symbols_by_id)

    # -- file-level import queries -----------------------------------------
    def file_imports(self, path: str) -> tuple[str, ...]:
        """Resolved imports of ``path`` (target file paths), sorted."""

        return self._index.imports_by_path.get(_normalize_repo_path(path), ())

    def file_dependents(self, path: str) -> tuple[str, ...]:
        """Files that directly import ``path`` (resolved edges only), sorted."""

        return self._index.dependents_by_path.get(_normalize_repo_path(path), ())

    def transitive_dependents(
        self, path: str, *, max_depth: int = 10
    ) -> tuple[tuple[str, int], ...]:
        """Reverse-dependency closure of ``path`` as ``(dependent, distance)``.

        Breadth-first from ``path`` so every reported distance is the shortest
        one; cycles are visited once.  Sorted by ``(distance, path)``.
        """

        start = _normalize_repo_path(path)
        if start not in self._index.files_by_path:
            return ()
        try:
            depth_limit = int(max_depth)
        except (TypeError, ValueError):
            depth_limit = 10
        depth_limit = max(1, min(depth_limit, MAX_TRAVERSAL_DEPTH))
        visited: set[str] = {start}
        distances: dict[str, int] = {}
        frontier: list[str] = [start]
        for distance in range(1, depth_limit + 1):
            next_frontier: list[str] = []
            for current in frontier:
                for dependent in self._index.dependents_by_path.get(current, ()):
                    if dependent in visited:
                        continue
                    visited.add(dependent)
                    distances[dependent] = distance
                    next_frontier.append(dependent)
            if not next_frontier:
                break
            frontier = next_frontier
        return tuple(sorted(distances.items(), key=lambda item: (item[1], item[0])))

    # -- symbol-level queries -----------------------------------------------
    def symbol_neighborhood(self, symbol_id: str, *, depth: int = 1) -> tuple[dict[str, Any], ...]:
        """Relation-backed neighborhood of one symbol, up to ``depth`` hops.

        Each entry is a deterministic dict with ``id``, ``path``, ``symbol``,
        ``kind``, ``distance``, ``direction``, ``relation``, ``status``,
        ``evidence``, ``confidence`` and ``targetName``.  Unresolved outgoing
        relations appear with ``id=None`` and the raw target name.
        """

        if symbol_id not in self._index.symbols_by_id:
            return ()
        try:
            depth_limit = int(depth)
        except (TypeError, ValueError):
            depth_limit = 1
        depth_limit = max(1, min(depth_limit, MAX_TRAVERSAL_DEPTH))
        entries: dict[tuple[Any, ...], dict[str, Any]] = {}
        visited: set[str] = {symbol_id}
        frontier: list[str] = [symbol_id]
        for distance in range(1, depth_limit + 1):
            next_frontier: list[str] = []
            for current in frontier:
                for relation in self._index.symbol_relations.get(current, ()):
                    if relation.source_id == current:
                        direction = "out"
                        neighbor_id = relation.target_id
                    else:
                        direction = "in"
                        neighbor_id = relation.source_id
                    neighbor = (
                        self._index.symbols_by_id.get(neighbor_id) if neighbor_id else None
                    )
                    key = (
                        distance,
                        direction,
                        neighbor_id or relation.target_name or "",
                        relation.relation_type.value,
                        relation.source_id,
                    )
                    if key not in entries:
                        entries[key] = {
                            "id": neighbor.id if neighbor else None,
                            "path": neighbor.path if neighbor else _symbol_path(current),
                            "symbol": neighbor.name if neighbor else relation.target_name,
                            "kind": neighbor.kind.value if neighbor else None,
                            "distance": distance,
                            "direction": direction,
                            "relation": relation.relation_type.value,
                            "status": relation.status.value,
                            "evidence": relation.evidence.value,
                            "confidence": round(relation.confidence, 4),
                            "targetName": relation.target_name,
                        }
                    if neighbor is not None and neighbor.id not in visited:
                        visited.add(neighbor.id)
                        next_frontier.append(neighbor.id)
            if not next_frontier:
                break
            frontier = next_frontier
        return tuple(entries[key] for key in sorted(entries))

    # -- impact --------------------------------------------------------------
    def impact(
        self,
        *,
        files: Iterable[str] = (),
        symbols: Iterable[str] = (),
        max_results: int = 200,
    ) -> ImpactResult:
        """Conservative blast radius for changed files and/or symbols.

        ``files`` are repository-relative POSIX paths; ``symbols`` may be symbol
        ids or (unambiguous) symbol names.  Unknown inputs are ignored instead
        of guessed.  Each list is capped at ``max_results``; ``truncated`` says
        whether anything was dropped.
        """

        try:
            limit = int(max_results)
        except (TypeError, ValueError):
            limit = 200
        limit = max(1, min(limit, MAX_IMPACT_RESULTS))
        changed_symbol_ids = self._resolve_changed_symbols(symbols)
        changed_files_set: set[str] = set()
        for raw in files:
            path = _normalize_repo_path(raw)
            if path in self._index.files_by_path:
                changed_files_set.add(path)
        for symbol_id in changed_symbol_ids:
            symbol = self._index.symbols_by_id.get(symbol_id)
            if symbol is not None:
                changed_files_set.add(symbol.path)
        changed_files = tuple(sorted(changed_files_set))
        changed_symbols = tuple(sorted(changed_symbol_ids))
        if not changed_files and not changed_symbols:
            return ImpactResult()

        affected = self._affected_files(changed_files, limit)
        affected_files, files_truncated = affected
        affected_symbols, symbols_truncated = self._affected_symbols(
            changed_files, changed_symbols, limit
        )
        return ImpactResult(
            changed_files=changed_files,
            changed_symbols=changed_symbols,
            affected_files=affected_files,
            affected_symbols=affected_symbols,
            truncated=files_truncated or symbols_truncated,
        )

    def _resolve_changed_symbols(self, symbols: Iterable[str]) -> set[str]:
        resolved: set[str] = set()
        for raw in symbols:
            value = str(raw).strip()
            if not value:
                continue
            if value in self._index.symbols_by_id:
                resolved.add(value)
                continue
            matches = self._index.symbols_by_name.get(value, ())
            if len(matches) == 1:
                resolved.add(matches[0].id)
                continue
            qualified = [
                symbol
                for symbol in self.snapshot.symbols
                if symbol.qualified_name == value
            ]
            if len(qualified) == 1:
                resolved.add(qualified[0].id)
        return resolved

    def _affected_files(
        self, changed_files: tuple[str, ...], limit: int
    ) -> tuple[tuple[ImpactEntry, ...], bool]:
        distances: dict[str, int] = {}
        visited: set[str] = set(changed_files)
        frontier: list[str] = list(changed_files)
        for distance in range(1, MAX_TRAVERSAL_DEPTH + 1):
            next_frontier: list[str] = []
            for current in frontier:
                for dependent in self._index.dependents_by_path.get(current, ()):
                    if dependent in visited:
                        continue
                    visited.add(dependent)
                    distances[dependent] = distance
                    next_frontier.append(dependent)
            if not next_frontier:
                break
            frontier = next_frontier
        entries: list[ImpactEntry] = []
        for path, distance in sorted(distances.items(), key=lambda item: (item[1], item[0])):
            if distance <= 1:
                reason = "direct reverse import dependency (resolved)"
            else:
                reason = f"transitive reverse import dependency at depth {distance} (resolved)"
            entries.append(
                ImpactEntry(
                    path=path,
                    distance=distance,
                    confidence=CONFIDENCE_HIGH,
                    reason=reason,
                )
            )
        truncated = len(entries) > limit
        return (tuple(entries[:limit]), truncated)

    def _changed_symbol_names(self, changed_symbols: tuple[str, ...]) -> list[SymbolRecord]:
        names: list[SymbolRecord] = []
        for symbol_id in changed_symbols:
            symbol = self._index.symbols_by_id.get(symbol_id)
            if symbol is not None:
                names.append(symbol)
        return names

    def _affected_symbols(
        self,
        changed_files: tuple[str, ...],
        changed_symbols: tuple[str, ...],
        limit: int,
    ) -> tuple[tuple[ImpactSymbolEntry, ...], bool]:
        changed_file_set = set(changed_files)
        changed_ids = set(changed_symbols)
        changed_name_set = {symbol.name for symbol in self._changed_symbol_names(changed_symbols)}
        candidates: dict[str, tuple[str, str, int]] = {}

        def consider(
            source: SymbolRecord,
            *,
            confidence: str,
            reason: str,
            distance: int = 1,
            exclude_changed_files: bool = True,
        ) -> None:
            if source.id in changed_ids:
                return
            if exclude_changed_files and source.path in changed_file_set:
                return
            previous = candidates.get(source.id)
            if previous is None or confidence_rank(confidence) > confidence_rank(previous[0]):
                candidates[source.id] = (confidence, reason, distance)

        # (a) resolved symbol edges pointing at a changed symbol.  Same-file
        # dependents count here: a symbol passed explicitly is a symbol-level
        # change even though its file is part of the file-closure seed set.
        for symbol_id in changed_symbols:
            changed_symbol = self._index.symbols_by_id.get(symbol_id)
            if changed_symbol is None:
                continue
            for relation in self._index.symbol_relations.get(symbol_id, ()):
                if relation.target_id != symbol_id or relation.source_id == symbol_id:
                    continue
                source = self._index.symbols_by_id.get(relation.source_id)
                if source is None:
                    continue
                if relation.evidence is EvidenceKind.HEURISTIC:
                    confidence = CONFIDENCE_MEDIUM
                else:
                    confidence = CONFIDENCE_HIGH
                consider(
                    source,
                    confidence=confidence,
                    reason=(
                        f"{confidence}-confidence {relation.relation_type.value} edge to "
                        f"changed symbol {changed_symbol.name!r}"
                    ),
                    exclude_changed_files=False,
                )

        # (b) resolved symbol edges pointing into a changed file (from elsewhere).
        if changed_file_set:
            for relation in self._index.relations:
                target_id = relation.target_id
                if not target_id or not target_id.startswith("sym:"):
                    continue
                if target_id in changed_ids:
                    continue
                target = self._index.symbols_by_id.get(target_id)
                if target is None or target.path not in changed_file_set:
                    continue
                source = self._index.symbols_by_id.get(relation.source_id)
                if source is None or source.path in changed_file_set:
                    continue
                if relation.evidence is EvidenceKind.HEURISTIC:
                    confidence = CONFIDENCE_MEDIUM
                else:
                    confidence = CONFIDENCE_HIGH
                consider(
                    source,
                    confidence=confidence,
                    reason=(
                        f"{confidence}-confidence {relation.relation_type.value} edge into "
                        f"changed file {target.path!r}"
                    ),
                )

        # (c) unresolved heuristic call/base edges whose raw name matches a
        # changed symbol.  These are explicitly ``medium``: the parser saw a
        # call/base with that name but could not bind it to a symbol.
        if changed_name_set:
            for relation in self._index.relations:
                if (
                    relation.relation_type not in _HEURISTIC_NAME_EDGES
                    or relation.target_id is not None
                    or not relation.target_name
                    or relation.target_name not in changed_name_set
                ):
                    continue
                source = self._index.symbols_by_id.get(relation.source_id)
                if source is None:
                    continue
                consider(
                    source,
                    confidence=CONFIDENCE_MEDIUM,
                    reason=(
                        f"unresolved {relation.relation_type.value} edge names changed symbol "
                        f"{relation.target_name!r} (heuristic)"
                    ),
                    exclude_changed_files=False,
                )

        # (d) pure name coincidence: low confidence, clearly labelled.
        if changed_name_set:
            for name in sorted(changed_name_set):
                for symbol in self._index.symbols_by_name.get(name, ()):
                    consider(
                        symbol,
                        confidence=CONFIDENCE_LOW,
                        reason=f"same symbol name {name!r} (name coincidence, unverified)",
                    )

        entries = [
            ImpactSymbolEntry(
                id=symbol_id,
                path=self._index.symbols_by_id[symbol_id].path,
                name=self._index.symbols_by_id[symbol_id].name,
                distance=distance,
                confidence=confidence,
            )
            for symbol_id, (confidence, _reason, distance) in candidates.items()
        ]
        entries.sort(key=lambda entry: (entry.distance, entry.path, entry.id))
        truncated = len(entries) > limit
        return (tuple(entries[:limit]), truncated)


def _symbol_path(symbol_id: str) -> str:
    """Recover the repository path encoded in a symbol id (never absolute)."""

    if not symbol_id.startswith("sym:"):
        return ""
    remainder = symbol_id[len("sym:") :]
    path, _, _ = remainder.partition("#")
    return path


__all__ = ["Graph", "MAX_IMPACT_RESULTS", "MAX_TRAVERSAL_DEPTH", "source_path_from_id"]
