"""Deterministic retrieval-quality evaluation against named baselines.

This module is intentionally independent of the reporting layer: it uses the
same ``Retrieval.rank/search`` path as the model-facing tools, measures file-level
relevance with binary labels, and returns a canonical, bounded payload suitable
for a CLI gate.  No timestamps, absolute paths or volatile measurements are
included in the payload.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codebase_intelligence import api
from codebase_intelligence.errors import UsageError
from codebase_intelligence.retrieval.rank import query_terms, rank, search
from codebase_intelligence.util import bounded_text, canonical_json

MAX_TASKS = 100
MAX_RELEVANT = 20
MAX_QUERY_CHARS = 500
MAX_K = 20
MIN_K = 5
DEFAULT_K = 10
MAX_EVIDENCE_PATHS = 10

#: Defaults keep the gate honest without over-fitting a single fixture.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "recallAtK": 0.80,
    "mrrAtK": 0.80,
    "ndcgAtK": 0.75,
}


@dataclass(frozen=True, slots=True)
class EvalTask:
    """One file-level relevance task loaded from the task file."""

    id: str
    query: str
    relevant: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvalSpec:
    """Validated task-file contents plus the gate configuration."""

    name: str
    k: int
    thresholds: dict[str, float]
    tasks: tuple[EvalTask, ...]


def _normalize_label(raw: Any, *, task_id: str) -> str:
    value = str(raw or "").strip().replace("\\", "/")
    if not value:
        raise UsageError(f"task {task_id!r} has an empty relevant path")
    if value.startswith("/") or value.startswith("//") or (
        len(value) >= 2 and value[1] == ":"
    ):
        raise UsageError(f"task {task_id!r} relevant path must be repository-relative: {value!r}")
    if any(part == ".." for part in value.split("/")):
        raise UsageError(f"task {task_id!r} relevant path must not escape the repository: {value!r}")
    return value


def load_tasks(path: str | Path) -> EvalSpec:
    """Load and validate a deterministic task file.

    Every unknown field is ignored; known fields are bounded and type-checked so a
    malformed task file fails with a usage error rather than producing a
    misleading score.
    """

    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise UsageError(f"task file not found: {file_path}") from error
    except (OSError, UnicodeError, ValueError) as error:
        raise UsageError(f"cannot read task file {file_path}: {error}") from error
    if not isinstance(raw, dict):
        raise UsageError("task file must be a JSON object")
    raw_tasks = raw.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise UsageError("task file must contain a non-empty tasks array")
    if len(raw_tasks) > MAX_TASKS:
        raise UsageError(f"task file contains more than {MAX_TASKS} tasks")

    raw_k = raw.get("k", DEFAULT_K)
    if not isinstance(raw_k, int) or isinstance(raw_k, bool) or not MIN_K <= raw_k <= MAX_K:
        raise UsageError(f"k must be an integer between {MIN_K} and {MAX_K}")
    raw_thresholds = raw.get("thresholds", {})
    if not isinstance(raw_thresholds, dict):
        raise UsageError("thresholds must be an object")
    thresholds = dict(DEFAULT_THRESHOLDS)
    for key, default in DEFAULT_THRESHOLDS.items():
        value = raw_thresholds.get(key, default)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 <= value <= 1.0:
            raise UsageError(f"threshold {key!r} must be a number between 0 and 1")
        thresholds[key] = float(value)

    tasks: list[EvalTask] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_tasks):
        if not isinstance(item, dict):
            raise UsageError(f"task #{index + 1} must be an object")
        task_id = str(item.get("id") or f"task-{index + 1}").strip()
        if not task_id or task_id in seen_ids:
            raise UsageError(f"task ids must be unique and non-empty: {task_id!r}")
        seen_ids.add(task_id)
        query = bounded_text(str(item.get("query") or "").strip(), MAX_QUERY_CHARS)
        if not query:
            raise UsageError(f"task {task_id!r} has an empty query")
        raw_relevant = item.get("relevant")
        if not isinstance(raw_relevant, list) or not raw_relevant:
            raise UsageError(f"task {task_id!r} must have a non-empty relevant array")
        if len(raw_relevant) > MAX_RELEVANT:
            raise UsageError(f"task {task_id!r} has more than {MAX_RELEVANT} relevant paths")
        relevant = tuple(
            sorted({_normalize_label(value, task_id=task_id) for value in raw_relevant})
        )
        if not relevant:
            raise UsageError(f"task {task_id!r} has no relevant paths")
        tasks.append(EvalTask(id=task_id, query=query, relevant=relevant))

    name = str(raw.get("name") or file_path.stem).strip() or file_path.stem
    return EvalSpec(name=bounded_text(name, 120), k=raw_k, thresholds=thresholds, tasks=tuple(tasks))


def _order_paths(paths: list[str], k: int) -> tuple[str, ...]:
    """Deduplicate while preserving order and keep the first ``k`` paths."""

    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
        if len(ordered) >= k:
            break
    return tuple(ordered)


def _path_baseline(snapshot: Any, terms: tuple[str, ...], k: int) -> tuple[str, ...]:
    """Naive path-token baseline: files whose paths contain query terms."""

    scores: dict[str, int] = {}
    for file in snapshot.files:
        lowered = file.path.lower()
        score = sum(1 for term in terms if term in lowered)
        if score > 0:
            scores[file.path] = score
    ordered = sorted(scores, key=lambda path: (-scores[path], path))
    return _order_paths(ordered, k)


def _symbol_baseline(snapshot: Any, terms: tuple[str, ...], k: int) -> tuple[str, ...]:
    """Naive symbol-name baseline: symbol matches rolled up to their file."""

    scores: dict[str, int] = {}
    for symbol in snapshot.symbols:
        lowered = f"{symbol.name} {symbol.qualified_name}".lower()
        score = sum(1 for term in terms if term in lowered)
        if score > 0:
            scores[symbol.path] = max(scores.get(symbol.path, 0), score)
    ordered = sorted(scores, key=lambda path: (-scores[path], path))
    return _order_paths(ordered, k)


def _engine_baseline(snapshot: Any, graph: Any, query: str, k: int) -> tuple[str, ...]:
    """The shipped search order, deduplicated to file paths."""

    hits = search(snapshot, graph, query, limit=max(k * 4, 20))
    paths = [hit.path for hit in hits]
    # Include ranked files without a symbol hit as a deterministic fallback.  The
    # search API intentionally reports symbol rows first; file-level evaluation
    # must not silently lose a file that only matched its path.
    ranked = rank(snapshot, graph, query)
    paths.extend(item.path for item in ranked.files)
    paths.extend(item.path for item in ranked.symbols)
    return _order_paths(paths, k)


def _metrics(order: tuple[str, ...], relevant: frozenset[str], k: int) -> dict[str, float]:
    top = order[:k]
    hits = [1.0 if path in relevant else 0.0 for path in top]
    recall = sum(hits) / len(relevant) if relevant else 0.0
    first = next((index + 1 for index, hit in enumerate(hits) if hit), 0)
    mrr = 1.0 / first if first else 0.0
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(len(relevant), k)))
    ndcg = dcg / ideal if ideal else 0.0
    return {
        "recallAtK": round(recall, 4),
        "mrrAtK": round(mrr, 4),
        "ndcgAtK": round(ndcg, 4),
        "hitRateAtK": round(sum(hits) / max(1, len(top)), 4),
    }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def evaluate(
    root: str | Path,
    tasks_path: str | Path,
    *,
    cache_dir: str | Path | None = None,
    policy: Any = None,
) -> dict[str, Any]:
    """Evaluate the shipped ranker on a validated task file.

    The returned payload is deterministic and bounded.  The gate passes only when
    every configured engine threshold is met; the baseline scores are reported for
    context, not used to weaken the gate.
    """

    spec = load_tasks(tasks_path)
    result = api.open_index(Path(root), cache_dir=Path(cache_dir) if cache_dir else None, policy=policy)
    snapshot = result.snapshot
    graph = api.graph_for(snapshot)
    files_by_path = {file.path for file in snapshot.files}

    per_task: list[dict[str, Any]] = []
    engine_metrics: list[dict[str, float]] = []
    path_metrics: list[dict[str, float]] = []
    symbol_metrics: list[dict[str, float]] = []
    for task in spec.tasks:
        unknown = [path for path in task.relevant if path not in files_by_path]
        if unknown:
            raise UsageError(
                f"task {task.id!r} labels paths not present in the index: {', '.join(unknown[:5])}"
            )
        relevant = frozenset(task.relevant)
        # Use the documented query-term tokenizer for the path/symbol baselines so
        # comparison is fair and independent of ad-hoc splitting.
        terms = query_terms(task.query)
        engine_order = _engine_baseline(snapshot, graph, task.query, spec.k)
        path_order = _path_baseline(snapshot, terms, spec.k)
        symbol_order = _symbol_baseline(snapshot, terms, spec.k)
        engine_score = _metrics(engine_order, relevant, spec.k)
        path_score = _metrics(path_order, relevant, spec.k)
        symbol_score = _metrics(symbol_order, relevant, spec.k)
        engine_metrics.append(engine_score)
        path_metrics.append(path_score)
        symbol_metrics.append(symbol_score)
        per_task.append(
            {
                "id": task.id,
                "query": task.query,
                "relevant": list(task.relevant),
                "methods": {
                    "engine": {
                        "paths": list(engine_order[:MAX_EVIDENCE_PATHS]),
                        "metrics": engine_score,
                    },
                    "path": {
                        "paths": list(path_order[:MAX_EVIDENCE_PATHS]),
                        "metrics": path_score,
                    },
                    "symbol": {
                        "paths": list(symbol_order[:MAX_EVIDENCE_PATHS]),
                        "metrics": symbol_score,
                    },
                },
            }
        )

    aggregate = {
        "engine": {key: _mean([item[key] for item in engine_metrics]) for key in DEFAULT_THRESHOLDS},
        "path": {key: _mean([item[key] for item in path_metrics]) for key in DEFAULT_THRESHOLDS},
        "symbol": {key: _mean([item[key] for item in symbol_metrics]) for key in DEFAULT_THRESHOLDS},
    }
    checks = [
        {
            "metric": metric,
            "value": aggregate["engine"][metric],
            "threshold": spec.thresholds[metric],
            "passed": aggregate["engine"][metric] >= spec.thresholds[metric],
        }
        for metric in DEFAULT_THRESHOLDS
    ]
    passed = all(item["passed"] for item in checks)
    payload: dict[str, Any] = {
        "ok": True,
        "command": "eval-retrieval",
        "schemaVersion": snapshot.schema_version,
        "engineVersion": snapshot.engine_version,
        "name": spec.name,
        "k": spec.k,
        "tasks": len(spec.tasks),
        "thresholds": spec.thresholds,
        "aggregate": aggregate,
        "checks": checks,
        "passed": passed,
        "baselineBest": {
            "recallAtK": max(aggregate["path"]["recallAtK"], aggregate["symbol"]["recallAtK"]),
            "mrrAtK": max(aggregate["path"]["mrrAtK"], aggregate["symbol"]["mrrAtK"]),
            "ndcgAtK": max(aggregate["path"]["ndcgAtK"], aggregate["symbol"]["ndcgAtK"]),
        },
        "index": api.index_block(snapshot),
        "results": per_task,
    }
    # Fail loudly on non-canonical payload data rather than silently emitting
    # duplicate/NaN fields from future changes.
    canonical_json(payload)
    return payload


__all__ = ["DEFAULT_THRESHOLDS", "EvalSpec", "EvalTask", "evaluate", "load_tasks"]
