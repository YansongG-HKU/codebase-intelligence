"""Evaluation helpers for reproducible repository-understanding benchmarks."""

from codebase_intelligence.evaluation.retrieval import (
    EvaluationTask,
    SymbolEvidence,
    evaluate_repository,
    evaluate_tasks,
    load_task_set,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

__all__ = [
    "EvaluationTask",
    "SymbolEvidence",
    "evaluate_repository",
    "evaluate_tasks",
    "load_task_set",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
]
