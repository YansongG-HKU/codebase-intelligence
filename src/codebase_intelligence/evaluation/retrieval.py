"""Deterministic retrieval-only benchmark metrics and task loading.

This module deliberately evaluates retrieval independently of an LLM. It
measures whether the production search pipeline surfaces reviewed gold files;
it does not claim answer correctness or model-token savings.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True, slots=True)
class EvaluationTask:
    """One reviewed retrieval task with repository-relative gold evidence."""

    id: str
    query: str
    relevant_files: tuple[str, ...]
    relevant_symbols: tuple[str, ...] = ()
    notes: str = ""


def _repository_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} entries must be non-empty strings")
    raw = value.strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise ValueError(f"{field} entries must be normalized repository-relative paths: {value!r}")
    if raw.startswith("~") or ":" in path.parts[0]:
        raise ValueError(f"{field} entries must be repository-relative paths: {value!r}")
    return path.as_posix()


def load_task_set(path: str | Path) -> tuple[EvaluationTask, ...]:
    """Load and validate a version-1 retrieval task JSON document."""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load benchmark task set {source}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("task set must be an object with schemaVersion: 1")
    rows = payload.get("tasks")
    if not isinstance(rows, list) or not rows:
        raise ValueError("task set must contain a non-empty tasks array")

    tasks: list[EvaluationTask] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"tasks[{index}] must be an object")
        task_id = row.get("id")
        query = row.get("query")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(f"tasks[{index}].id must be a non-empty string")
        if task_id in seen_ids:
            raise ValueError(f"duplicate task id: {task_id}")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"tasks[{index}].query must be a non-empty string")
        files = row.get("relevantFiles")
        if not isinstance(files, list) or not files:
            raise ValueError(f"tasks[{index}].relevantFiles must be a non-empty array")
        symbols = row.get("relevantSymbols", [])
        if not isinstance(symbols, list):
            raise ValueError(f"tasks[{index}].relevantSymbols must be an array")
        notes = row.get("notes", "")
        if not isinstance(notes, str):
            raise ValueError(f"tasks[{index}].notes must be a string")
        relevant_files = tuple(sorted({_repository_path(item, field=f"tasks[{index}].relevantFiles") for item in files}))
        relevant_symbols = tuple(sorted({item.strip() for item in symbols if isinstance(item, str) and item.strip()}))
        if len(relevant_symbols) != len([item for item in symbols if isinstance(item, str) and item.strip()]):
            raise ValueError(f"tasks[{index}].relevantSymbols contains duplicate symbols")
        seen_ids.add(task_id)
        tasks.append(EvaluationTask(task_id, query.strip(), relevant_files, relevant_symbols, notes))
    return tuple(tasks)


def _unique_paths(paths: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return tuple(ordered)


def precision_at_k(ranked_paths: Sequence[str], relevant_paths: Iterable[str], k: int) -> float:
    """Binary file precision@k; denominator is always k, including short lists."""

    if k < 1:
        raise ValueError("k must be >= 1")
    relevant = set(relevant_paths)
    selected = _unique_paths(ranked_paths)[:k]
    return sum(path in relevant for path in selected) / k


def recall_at_k(ranked_paths: Sequence[str], relevant_paths: Iterable[str], k: int) -> float:
    """Binary file recall@k against the complete reviewed gold set."""

    if k < 1:
        raise ValueError("k must be >= 1")
    relevant = set(relevant_paths)
    if not relevant:
        raise ValueError("relevant_paths must not be empty")
    selected = _unique_paths(ranked_paths)[:k]
    return sum(path in relevant for path in selected) / len(relevant)


def reciprocal_rank(ranked_paths: Sequence[str], relevant_paths: Iterable[str]) -> float:
    """Reciprocal rank of the first relevant unique file; zero when no hit exists."""

    relevant = set(relevant_paths)
    for index, path in enumerate(_unique_paths(ranked_paths), start=1):
        if path in relevant:
            return 1.0 / index
    return 0.0


def ndcg_at_k(ranked_paths: Sequence[str], relevant_paths: Iterable[str], k: int) -> float:
    """Binary-gain nDCG@k with an ideal ranking over all relevant files."""

    if k < 1:
        raise ValueError("k must be >= 1")
    relevant = set(relevant_paths)
    if not relevant:
        raise ValueError("relevant_paths must not be empty")
    selected = _unique_paths(ranked_paths)[:k]
    dcg = sum(1.0 / math.log2(index + 2) for index, path in enumerate(selected) if path in relevant)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def evaluate_tasks(
    tasks: Sequence[EvaluationTask],
    retrieve: Callable[[str], Sequence[str]],
    *,
    ks: Sequence[int] = (1, 3, 5),
) -> dict[str, Any]:
    """Evaluate a supplied retrieval function, enabling deterministic unit tests."""

    if not tasks:
        raise ValueError("tasks must not be empty")
    normalized_ks = tuple(sorted(set(int(value) for value in ks)))
    if not normalized_ks or normalized_ks[0] < 1:
        raise ValueError("ks must contain positive integers")
    rows: list[dict[str, Any]] = []
    for task in tasks:
        ranked = _unique_paths(retrieve(task.query))
        metrics: dict[str, dict[str, float]] = {}
        for k in normalized_ks:
            metrics[str(k)] = {
                "precision": round(precision_at_k(ranked, task.relevant_files, k), 6),
                "recall": round(recall_at_k(ranked, task.relevant_files, k), 6),
                "ndcg": round(ndcg_at_k(ranked, task.relevant_files, k), 6),
            }
        rows.append(
            {
                "id": task.id,
                "query": task.query,
                "relevantFiles": list(task.relevant_files),
                "retrievedFiles": list(ranked),
                "reciprocalRank": round(reciprocal_rank(ranked, task.relevant_files), 6),
                "metricsAtK": metrics,
            }
        )
    aggregate: dict[str, dict[str, float]] = {}
    for k in normalized_ks:
        key = str(k)
        aggregate[key] = {
            metric: round(sum(row["metricsAtK"][key][metric] for row in rows) / len(rows), 6)
            for metric in ("precision", "recall", "ndcg")
        }
    return {
        "schemaVersion": 1,
        "evaluation": "retrieval-only",
        "taskCount": len(rows),
        "ks": list(normalized_ks),
        "metrics": {
            "precision": "relevant unique files in top-k divided by k (short result lists are not padded)",
            "recall": "relevant unique files in top-k divided by the complete gold file set",
            "reciprocalRank": "1 / rank of the first relevant unique file; 0 when no hit exists",
            "ndcg": "binary-gain normalized discounted cumulative gain over unique files",
        },
        "aggregate": aggregate,
        "meanReciprocalRank": round(sum(row["reciprocalRank"] for row in rows) / len(rows), 6),
        "tasks": rows,
    }


def evaluate_repository(
    root: str | Path,
    tasks: Sequence[EvaluationTask],
    *,
    cache_dir: str | Path | None = None,
    ks: Sequence[int] = (1, 3, 5),
) -> dict[str, Any]:
    """Run reviewed tasks against the production index and search implementation."""

    from codebase_intelligence import api
    from codebase_intelligence.retrieval import search

    repository = api.resolve_root(root)
    cache = api.resolve_cache_dir(cache_dir)
    indexed = api.open_index(repository, cache_dir=cache)
    graph = api.graph_for(indexed.snapshot)

    def retrieve(query: str) -> Sequence[str]:
        hits = search(indexed.snapshot, graph, query, limit=max(ks) * 5)
        return [hit.path for hit in hits]

    report = evaluate_tasks(tasks, retrieve, ks=ks)
    report["engineVersion"] = indexed.snapshot.engine_version
    report["indexFingerprint"] = indexed.snapshot.fingerprint()
    report["repository"] = repository.name
    return report
