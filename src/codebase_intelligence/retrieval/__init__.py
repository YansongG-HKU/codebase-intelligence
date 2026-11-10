"""Task-aware retrieval primitives: ranking, search and budgeted context packs.

Public surface (``docs/SPEC.md`` §9)::

    from codebase_intelligence.retrieval import build_context, search, fit_rows

Everything here is deterministic for identical index content + query + budgets.
"""

from __future__ import annotations

from codebase_intelligence.retrieval.budget import (
    MAX_TOOL_TOKENS,
    MIN_MAX_TOKENS,
    budgets_block,
    clamp_max_tokens,
    estimate_tokens,
    finalize_payload,
    fit_payload,
    fit_rows,
    index_block,
    measured_tokens,
    trim_sections,
)
from codebase_intelligence.retrieval.context import (
    MAX_EXCERPT_LINES,
    ContextItem,
    ContextPack,
    Omission,
    build_context,
    context_payload_dict,
    fit_context,
)
from codebase_intelligence.retrieval.paths import is_under_prefix, normalize_repo_prefix
from codebase_intelligence.retrieval.rank import (
    RankResult,
    RankedFile,
    RankedSymbol,
    SearchHit,
    rank,
    search,
)

__all__ = [
    "MAX_EXCERPT_LINES",
    "MAX_TOOL_TOKENS",
    "MIN_MAX_TOKENS",
    "ContextItem",
    "ContextPack",
    "Omission",
    "RankResult",
    "RankedFile",
    "RankedSymbol",
    "SearchHit",
    "budgets_block",
    "build_context",
    "clamp_max_tokens",
    "context_payload_dict",
    "estimate_tokens",
    "finalize_payload",
    "fit_context",
    "fit_payload",
    "fit_rows",
    "index_block",
    "is_under_prefix",
    "measured_tokens",
    "normalize_repo_prefix",
    "rank",
    "search",
    "trim_sections",
]
