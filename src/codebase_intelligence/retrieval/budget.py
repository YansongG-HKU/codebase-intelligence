"""Token budgets and the shared deterministic payload skeleton (SPEC §3/§4).

Every model-facing answer is assembled the same way:

1. build the full payload with a placeholder ``budgets.tokensEstimated``;
2. measure it as ``estimate_tokens(canonical_json(payload))``;
3. drop whole rows (never split one) until the measured payload fits;
4. write the measured value back, so ``tokensEstimated`` is the true size of the
   bytes the caller receives.

The helpers here are shared by :mod:`codebase_intelligence.retrieval` (a context
pack is budgeted while it is built) and :mod:`codebase_intelligence.reporting`
(every tool payload).  They are dependency-free and deterministic: the only
variable input is the caller's ``maxTokens``.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence, TypeVar

from codebase_intelligence.model import IndexSnapshot
from codebase_intelligence.util import TOKEN_ESTIMATOR, canonical_json, clamp, estimate_tokens

#: Lower clamp for a requested budget.  Matches the transport-side clamp in
#: :mod:`codebase_intelligence.api`; below this the mandatory ``index`` block
#: alone can exceed the request, which is reported instead of hidden.
MIN_MAX_TOKENS = 64
#: Hard ceiling for one tool answer (SPEC §4).
MAX_TOOL_TOKENS = 8000

T = TypeVar("T")

#: Payload measurement: the exact estimator every budgeted payload reports.
MeasuredRows = Callable[[Sequence[T]], int]
MakePayload = Callable[[Sequence[T], int], dict[str, Any]]


def clamp_max_tokens(value: int | None) -> int:
    """Clamp a requested token budget into the documented range."""

    if value is None:
        return MAX_TOOL_TOKENS
    try:
        number = int(value)
    except (TypeError, ValueError):
        return MAX_TOOL_TOKENS
    return clamp(number, MIN_MAX_TOKENS, MAX_TOOL_TOKENS)


def measured_tokens(value: Any) -> int:
    """Estimate the token cost of a payload the same way budgets are measured."""

    return estimate_tokens(canonical_json(value))


def index_block(snapshot: IndexSnapshot) -> dict[str, Any]:
    """The deterministic index identity every tool payload carries (SPEC §10)."""

    return {
        "schemaVersion": snapshot.schema_version,
        "engineVersion": snapshot.engine_version,
        "policyFingerprint": snapshot.policy_fingerprint,
        "fingerprint": snapshot.fingerprint(),
    }


def budgets_block(max_tokens: int, *, tokens_estimated: int | None = None) -> dict[str, Any]:
    """Build the ``budgets`` block; the placeholder is finalized later."""

    budget = clamp_max_tokens(max_tokens)
    return {
        "maxTokens": budget,
        "tokensEstimated": budget if tokens_estimated is None else int(tokens_estimated),
        "tokenEstimator": TOKEN_ESTIMATOR,
    }


def finalize_payload(payload: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    """Measure *payload* and write the true estimate into ``budgets.tokensEstimated``."""

    budget = clamp_max_tokens(max_tokens)
    payload["budgets"] = budgets_block(budget)
    tokens = measured_tokens(payload)
    for _ in range(4):
        payload["budgets"]["tokensEstimated"] = tokens
        updated = measured_tokens(payload)
        if updated == tokens:
            break
        tokens = updated
    payload["budgets"]["tokensEstimated"] = tokens
    return payload


def fit_rows(
    rows: Sequence[T],
    measure: MeasuredRows[T],
    max_tokens: int,
) -> tuple[list[T], int]:
    """Keep the largest whole-row prefix that fits (SPEC §9/§4).

    ``measure`` receives the candidate row list (so callers can wrap it in a
    payload envelope); rows are never split.  Returns ``(kept_rows,
    omitted_count)``.
    """

    budget = clamp_max_tokens(max_tokens)
    row_list = list(rows)
    kept: list[T] = []
    if measure([]) <= budget:
        for row in row_list:
            candidate = [*kept, row]
            if measure(candidate) <= budget:
                kept = candidate
            else:
                break
    return kept, len(row_list) - len(kept)


def fit_payload(
    make_payload: MakePayload[T],
    rows: Sequence[T],
    *,
    max_tokens: int,
) -> tuple[dict[str, Any], int]:
    """Greedily fit *rows* into a payload built by ``make_payload``.

    ``make_payload(kept_rows, placeholder_tokens)`` must return the complete
    payload (including the ``budgets`` block) for the given rows, using
    ``placeholder_tokens`` as a conservative ``tokensEstimated`` value.  The
    returned payload carries the truly measured estimate and the omitted count.
    """

    budget = clamp_max_tokens(max_tokens)
    row_list = list(rows)
    kept: list[T] = []
    if measured_tokens(make_payload(kept, budget)) <= budget:
        for row in row_list:
            candidate = [*kept, row]
            if measured_tokens(make_payload(candidate, budget)) <= budget:
                kept = candidate
            else:
                break
    payload = finalize_payload(make_payload(kept, budget), budget)
    while kept and measured_tokens(payload) > budget:
        kept = kept[:-1]
        payload = finalize_payload(make_payload(kept, budget), budget)
    return payload, len(row_list) - len(kept)


def trim_sections(
    payload: dict[str, Any],
    sections: Sequence[list[Any]],
    *,
    max_tokens: int,
) -> tuple[dict[str, Any], int]:
    """Drop whole rows from the lowest-priority section first until it fits.

    Each ``sections`` entry is a mutable row list that is also referenced from
    *payload*; rows are popped from the tail (callers order them by descending
    value).  Returns ``(payload, dropped_row_count)`` and sets ``truncated``.
    """

    budget = clamp_max_tokens(max_tokens)
    payload["budgets"] = budgets_block(budget)
    dropped = 0
    for rows in sections:
        while rows and measured_tokens(payload) > budget:
            rows.pop()
            dropped += 1
    if dropped:
        payload["truncated"] = True
    return finalize_payload(payload, budget), dropped


__all__ = [
    "MAX_TOOL_TOKENS",
    "MIN_MAX_TOKENS",
    "budgets_block",
    "clamp_max_tokens",
    "estimate_tokens",
    "finalize_payload",
    "fit_payload",
    "fit_rows",
    "index_block",
    "measured_tokens",
]
