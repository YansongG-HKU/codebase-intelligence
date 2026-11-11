"""Deterministic evaluation gates for shipped retrieval behaviour."""

from codebase_intelligence.evaluation.retrieval import (
    DEFAULT_THRESHOLDS,
    EvalSpec,
    EvalTask,
    evaluate,
    load_tasks,
)

__all__ = ["DEFAULT_THRESHOLDS", "EvalSpec", "EvalTask", "evaluate", "load_tasks"]
