"""Dependency graph: import resolution and structural queries.

Typical use (``docs/SPEC.md`` §7)::

    from codebase_intelligence.graph import Graph

    graph = Graph(snapshot)
    graph.file_imports("pkg/app.py")
    graph.transitive_dependents("pkg/helpers.py", max_depth=3)
    graph.impact(files=["pkg/helpers.py"], max_results=50)

The graph resolves raw parser ``IMPORTS`` relations against the snapshot's file
set; every attempted import carries ``EvidenceKind.RESOLVER`` and one of the
four resolution statuses, and unresolved/ambiguous imports are preserved with
their raw target name instead of being promoted to dependencies.
"""

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
from codebase_intelligence.graph.queries import Graph
from codebase_intelligence.graph.resolve import (
    build_go_directory_index,
    build_python_module_index,
    detect_source_roots,
    python_module_aliases,
    python_module_name,
    resolve_imports,
)

__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "Graph",
    "GraphIndex",
    "ImpactEntry",
    "ImpactResult",
    "ImpactSymbolEntry",
    "build_go_directory_index",
    "build_graph_index",
    "build_python_module_index",
    "confidence_rank",
    "detect_source_roots",
    "python_module_aliases",
    "python_module_name",
    "resolve_imports",
]
