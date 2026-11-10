"""Reporting layer: deterministic JSON payloads and bounded Markdown (SPEC §10).

This package is the only place that turns engine state into model-facing
answers.  It never writes to the repository, never executes scanned code and
never emits volatile fields (timestamps, durations, absolute paths, cache state).
"""

from __future__ import annotations

from codebase_intelligence.reporting.markdown import (
    markdown_map,
    markdown_report,
)
from codebase_intelligence.reporting.payloads import (
    DEFAULT_TOKENS,
    context_payload,
    dependencies_payload,
    entry_point_rows,
    impact_payload,
    map_payload,
    overview_payload,
    search_payload,
)

__all__ = [
    "DEFAULT_TOKENS",
    "context_payload",
    "dependencies_payload",
    "entry_point_rows",
    "impact_payload",
    "map_payload",
    "markdown_map",
    "markdown_report",
    "overview_payload",
    "search_payload",
]
