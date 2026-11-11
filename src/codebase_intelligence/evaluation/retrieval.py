"""Deterministic file- and symbol-level retrieval benchmark metrics.

This module evaluates retrieval independently of an LLM. It measures whether
production search/ranking surfaces reviewed gold files and symbols; it does not
claim answer correctness or model-token savings.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True, slots=True)
class SymbolEvidence:
    """Reviewed source location for one gold qualified symbol."""

    qualified_name: str
    path: str
    line: int


@dataclass(frozen=True, slots=True)
class EvaluationTask:
    """One reviewed retrieval task with repository-relative gold evidence."""

    id: str
    query: str
    relevant_files: tuple[str, ...]
    relevant_symbols: tuple[str, ...] = ()
    notes: str = ""
    symbol_evidence: tuple[SymbolEvidence, ...] = ()


def _repository_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} entries must be non-empty strings")
    raw = value.strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if raw in {".", "./"} or path.is_absolute() or any(part in {".", ".."} for part in path.parts):
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
        if not isinstance(symbols, list) or any(
            not isinstance(item, str) or not item.strip() for item in symbols
        ):
            raise ValueError(f"tasks[{index}].relevantSymbols must contain non-empty strings")
        notes = row.get("notes", "")
        if not isinstance(notes, str):
            raise ValueError(f"tasks[{index}].notes must be a string")
        evidence_rows = row.get("symbolEvidence", [])
        if not isinstance(evidence_rows, list):
            raise ValueError(f"tasks[{index}].symbolEvidence must be an array")

        relevant_files = tuple(
            sorted({_repository_path(item, field=f"tasks[{index}].relevantFiles") for item in files})
        )
        relevant_symbols = tuple(sorted({item.strip() for item in symbols}))
        if len(relevant_symbols) != len(symbols):
            raise ValueError(f"tasks[{index}].relevantSymbols contains duplicate symbols")

        evidence: list[SymbolEvidence] = []
        evidence_names: set[str] = set()
        for evidence_index, item in enumerate(evidence_rows):
            if not isinstance(item, dict):
                raise ValueError(f"tasks[{index}].symbolEvidence[{evidence_index}] must be an object")
            name = item.get("qualifiedName")
            line = item.get("line")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"tasks[{index}].symbolEvidence[{evidence_index}].qualifiedName is required")
            if isinstance(line, bool) or not isinstance(line, int) or line < 1:
                raise ValueError(f"tasks[{index}].symbolEvidence[{evidence_index}].line must be a positive integer")
            evidence_path = _repository_path(
                item.get("path"), field=f"tasks[{index}].symbolEvidence[{evidence_index}].path"
            )
            if evidence_path not in relevant_files:
                raise ValueError(
                    f"tasks[{index}].symbolEvidence[{evidence_index}].path must appear in relevantFiles"
                )
            if name.strip() not in relevant_symbols:
                raise ValueError(
                    f"tasks[{index}].symbolEvidence[{evidence_index}] must reference a relevantSymbols entry"
                )
            if name.strip() in evidence_names:
                raise ValueError(f"tasks[{index}].symbolEvidence contains duplicate symbol evidence")
            evidence_names.add(name.strip())
            evidence.append(SymbolEvidence(name.strip(), evidence_path, line))

        seen_ids.add(task_id)
        tasks.append(
            EvaluationTask(
                task_id,
                query.strip(),
                relevant_files,
                relevant_symbols,
                notes,
                tuple(sorted(evidence, key=lambda item: (item.qualified_name, item.path, item.line))),
            )
        )
    return tuple(tasks)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Binary precision@k; denominator is k even when fewer results exist."""

    if k < 1:
        raise ValueError("k must be >= 1")
    gold = set(relevant)
    return sum(value in gold for value in _unique(ranked)[:k]) / k


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Binary recall@k against the complete reviewed gold set."""

    if k < 1:
        raise ValueError("k must be >= 1")
    gold = set(relevant)
    if not gold:
        raise ValueError("relevant set must not be empty")
    return sum(value in gold for value in _unique(ranked)[:k]) / len(gold)


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    """Reciprocal rank of the first relevant unique result; zero on no hit."""

    gold = set(relevant)
    for index, value in enumerate(_unique(ranked), start=1):
        if value in gold:
            return 1.0 / index
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Binary-gain nDCG@k over unique ranked values."""

    if k < 1:
        raise ValueError("k must be >= 1")
    gold = set(relevant)
    if not gold:
        raise ValueError("relevant set must not be empty")
    selected = _unique(ranked)[:k]
    dcg = sum(1.0 / math.log2(index + 2) for index, value in enumerate(selected) if value in gold)
    ideal_hits = min(len(gold), k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def _metrics_at_k(ranked: Sequence[str], relevant: Sequence[str], ks: Sequence[int]) -> dict[str, dict[str, float]]:
    return {
        str(k): {
            "precision": round(precision_at_k(ranked, relevant, k), 6),
            "recall": round(recall_at_k(ranked, relevant, k), 6),
            "ndcg": round(ndcg_at_k(ranked, relevant, k), 6),
        }
        for k in ks
    }


def _aggregate(rows: Sequence[dict[str, Any]], field: str, ks: Sequence[int]) -> dict[str, dict[str, float]]:
    return {
        str(k): {
            metric: round(
                sum(row[field][str(k)][metric] for row in rows) / len(rows), 6
            )
            for metric in ("precision", "recall", "ndcg")
        }
        for k in ks
    }


def evaluate_tasks(
    tasks: Sequence[EvaluationTask],
    retrieve_files: Callable[[str], Sequence[str]],
    *,
    retrieve_symbols: Callable[[str], Sequence[str]] | None = None,
    ks: Sequence[int] = (1, 3, 5),
) -> dict[str, Any]:
    """Evaluate injected file/symbol retrieval functions for deterministic tests."""

    if not tasks:
        raise ValueError("tasks must not be empty")
    normalized_ks = tuple(sorted(set(int(value) for value in ks)))
    if not normalized_ks or normalized_ks[0] < 1:
        raise ValueError("ks must contain positive integers")

    rows: list[dict[str, Any]] = []
    symbol_rows: list[dict[str, Any]] = []
    for task in tasks:
        ranked_files = _unique(retrieve_files(task.query))
        row: dict[str, Any] = {
            "id": task.id,
            "query": task.query,
            "relevantFiles": list(task.relevant_files),
            "retrievedFiles": list(ranked_files),
            "reciprocalRank": round(reciprocal_rank(ranked_files, task.relevant_files), 6),
            "metricsAtK": _metrics_at_k(ranked_files, task.relevant_files, normalized_ks),
        }
        if task.relevant_symbols:
            if retrieve_symbols is None:
                raise ValueError("retrieve_symbols is required for tasks with relevantSymbols")
            ranked_symbols = _unique(retrieve_symbols(task.query))
            symbol_metrics = _metrics_at_k(ranked_symbols, task.relevant_symbols, normalized_ks)
            symbol_rr = round(reciprocal_rank(ranked_symbols, task.relevant_symbols), 6)
            row.update(
                {
                    "relevantSymbols": list(task.relevant_symbols),
                    "retrievedSymbols": list(ranked_symbols),
                    "symbolEvidence": [
                        {"qualifiedName": item.qualified_name, "path": item.path, "line": item.line}
                        for item in task.symbol_evidence
                    ],
                    "symbolReciprocalRank": symbol_rr,
                    "symbolMetricsAtK": symbol_metrics,
                }
            )
            symbol_rows.append({"metrics": symbol_metrics, "reciprocalRank": symbol_rr})
        rows.append(row)

    return {
        "schemaVersion": 1,
        "evaluation": "retrieval-only",
        "taskCount": len(rows),
        "symbolTaskCount": len(symbol_rows),
        "ks": list(normalized_ks),
        "metrics": {
            "file": {
                "precision": "relevant unique files in top-k divided by k (short result lists are not padded)",
                "recall": "relevant unique files in top-k divided by the complete gold file set",
                "reciprocalRank": "1 / rank of the first relevant unique file; 0 when no hit exists",
                "ndcg": "binary-gain normalized discounted cumulative gain over unique file paths",
            },
            "symbol": {
                "precision": "relevant unique qualified symbols in top-k divided by k",
                "recall": "relevant unique qualified symbols in top-k divided by the complete gold symbol set",
                "reciprocalRank": "1 / rank of the first relevant unique qualified symbol; 0 when no hit exists",
                "ndcg": "binary-gain normalized discounted cumulative gain over unique qualified symbols",
            },
        },
        "aggregate": _aggregate(rows, "metricsAtK", normalized_ks),
        "meanReciprocalRank": round(sum(row["reciprocalRank"] for row in rows) / len(rows), 6),
        "symbolAggregate": (
            _aggregate(symbol_rows, "metrics", normalized_ks) if symbol_rows else {}
        ),
        "meanSymbolReciprocalRank": (
            round(sum(row["reciprocalRank"] for row in symbol_rows) / len(symbol_rows), 6)
            if symbol_rows else None
        ),
        "tasks": rows,
    }


def evaluate_repository(
    root: str | Path,
    tasks: Sequence[EvaluationTask],
    *,
    cache_dir: str | Path | None = None,
    ks: Sequence[int] = (1, 3, 5),
    compare_baselines: bool = False,
) -> dict[str, Any]:
    """Run reviewed tasks against the production index, search, and ranker.

    When requested, also run transparent tree-only, keyword, pack-order and
    name-only symbol-map baselines against the same snapshot and task corpus.
    """

    from codebase_intelligence import api
    from codebase_intelligence.retrieval import rank, search

    if not ks:
        raise ValueError("ks must contain at least one positive integer")
    repository = api.resolve_root(root)
    cache = api.resolve_cache_dir(cache_dir)
    indexed = api.open_index(repository, cache_dir=cache)
    graph = api.graph_for(indexed.snapshot)

    def retrieve_files(query: str) -> Sequence[str]:
        hits = search(indexed.snapshot, graph, query, limit=max(ks) * 5)
        return [hit.path for hit in hits]

    def retrieve_symbols(query: str) -> Sequence[str]:
        ranked = rank(indexed.snapshot, graph, query, limit=max(ks) * 5)
        return [item.qualified_name for item in ranked.symbols]

    report = evaluate_tasks(
        tasks,
        retrieve_files,
        retrieve_symbols=retrieve_symbols,
        ks=ks,
    )
    report["engineVersion"] = indexed.snapshot.engine_version
    report["indexFingerprint"] = indexed.snapshot.fingerprint()
    report["repository"] = repository.name

    if compare_baselines:
        from codebase_intelligence.evaluation.baselines import build_baseline_retrievers

        baselines = build_baseline_retrievers(repository, indexed.snapshot)
        file_only_tasks = tuple(
            replace(task, relevant_symbols=(), symbol_evidence=()) for task in tasks
        )
        descriptions = {
            "tree_only": "Path-token overlap only; repository file contents are not read.",
            "keyword": "Capped source-text term frequency; no symbol or graph features.",
            "pack_order": "All indexed files in deterministic path order; intentionally unranked.",
            "basic_symbol_map": "Qualified symbol-name lexical overlap only; no graph features.",
        }
        comparisons: dict[str, Any] = {}
        for key in ("tree_only", "keyword", "pack_order"):
            comparisons[key] = {
                "description": descriptions[key],
                "symbolMetrics": "not_applicable",
                "report": evaluate_tasks(file_only_tasks, baselines[key], ks=ks),
            }
        comparisons["basic_symbol_map"] = {
            "description": descriptions["basic_symbol_map"],
            "report": evaluate_tasks(
                tasks,
                baselines["basic_symbol_map_files"],
                retrieve_symbols=baselines["basic_symbol_map_symbols"],
                ks=ks,
            ),
        }
        report["baselineComparisons"] = comparisons
        report["comparisonContract"] = {
            "sameTaskSet": True,
            "sameKValues": list(sorted(set(ks))),
            "productionMethod": "graph-aware search + symbol ranker",
            "note": "Baselines are deliberately simple internal controls, not byte-for-byte reproductions of third-party tools.",
        }
    return report
