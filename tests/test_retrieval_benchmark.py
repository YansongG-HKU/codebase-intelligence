from __future__ import annotations

import json
from pathlib import Path

import pytest

from codebase_intelligence.evaluation import (
    EvaluationTask,
    evaluate_tasks,
    load_task_set,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "bench" / "retrieval_tasks.v1.json"


def test_precision_recall_and_rr_use_unique_ranked_paths() -> None:
    ranked = ["a.py", "a.py", "b.py", "c.py"]
    gold = {"b.py", "c.py"}
    assert precision_at_k(ranked, gold, 2) == 0.5
    assert recall_at_k(ranked, gold, 2) == 0.5
    assert reciprocal_rank(ranked, gold) == 0.5


def test_ndcg_matches_hand_calculated_binary_gain() -> None:
    # Relevant result at rank 2: DCG = 1/log2(3); ideal DCG@3 = 1 + 1/log2(3).
    expected = (1 / 1.584962500721156) / (1 + 1 / 1.584962500721156)
    assert ndcg_at_k(["noise.py", "gold.py", "other.py"], {"gold.py"}, 3) == pytest.approx(expected)


def test_metrics_handle_no_hits_and_short_result_lists() -> None:
    assert precision_at_k(["noise.py"], {"gold.py"}, 5) == 0.0
    assert recall_at_k(["noise.py"], {"gold.py"}, 5) == 0.0
    assert reciprocal_rank(["noise.py"], {"gold.py"}) == 0.0
    assert ndcg_at_k(["noise.py"], {"gold.py"}, 5) == 0.0


@pytest.mark.parametrize("k", [0, -1])
def test_metrics_reject_non_positive_k(k: int) -> None:
    with pytest.raises(ValueError, match="k must be >= 1"):
        precision_at_k([], {"a.py"}, k)


def test_task_loader_validates_schema_and_normalizes_gold_paths(tmp_path: Path) -> None:
    payload = {
        "schemaVersion": 1,
        "tasks": [
            {
                "id": "one",
                "query": "find entry",
                "relevantFiles": ["src\\app.py", "src/app.py"],
                "relevantSymbols": ["app.main"],
            }
        ],
    }
    source = tmp_path / "tasks.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    tasks = load_task_set(source)
    assert tasks == (EvaluationTask("one", "find entry", ("src/app.py",), ("app.main",), ""),)


@pytest.mark.parametrize("bad_path", ["../outside.py", "/etc/passwd", "C:\\secret.py"])
def test_task_loader_rejects_paths_outside_repository(tmp_path: Path, bad_path: str) -> None:
    source = tmp_path / "tasks.json"
    source.write_text(
        json.dumps({"schemaVersion": 1, "tasks": [{"id": "bad", "query": "x", "relevantFiles": [bad_path]}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="repository-relative"):
        load_task_set(source)


def test_task_loader_rejects_empty_gold_set_and_duplicate_ids(tmp_path: Path) -> None:
    source = tmp_path / "tasks.json"
    source.write_text(
        json.dumps({"schemaVersion": 1, "tasks": [{"id": "bad", "query": "x", "relevantFiles": []}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-empty array"):
        load_task_set(source)
    source.write_text(
        json.dumps({
            "schemaVersion": 1,
            "tasks": [
                {"id": "same", "query": "one", "relevantFiles": ["a.py"]},
                {"id": "same", "query": "two", "relevantFiles": ["b.py"]}
            ],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate task id"):
        load_task_set(source)


def test_evaluate_tasks_aggregates_deterministically() -> None:
    tasks = (
        EvaluationTask("one", "first", ("a.py",)),
        EvaluationTask("two", "second", ("c.py",)),
    )
    results = {"first": ["a.py", "b.py"], "second": ["b.py", "c.py"]}
    retrieve = lambda query: results[query]
    first = evaluate_tasks(tasks, retrieve, ks=(1, 2))
    second = evaluate_tasks(tasks, retrieve, ks=(2, 1, 1))
    assert first == second
    assert first["taskCount"] == 2
    assert first["aggregate"]["1"]["recall"] == 0.5
    assert first["meanReciprocalRank"] == 0.75


def test_default_task_set_is_non_empty_and_versioned() -> None:
    tasks = load_task_set(TASKS)
    assert len(tasks) >= 4
    assert all(task.relevant_files for task in tasks)
