"""Tests for the deterministic retrieval-quality gate (``cbi eval-retrieval``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from codebase_intelligence import cli
from codebase_intelligence.errors import UsageError
from codebase_intelligence.evaluation import DEFAULT_THRESHOLDS, evaluate, load_tasks
from codebase_intelligence.util import canonical_json

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "retrieval"
REPO = FIXTURES / "repo"
TASKS = FIXTURES / "eval_tasks.json"


def _write_tasks(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_tasks_bounds_and_normalizes(tmp_path: Path) -> None:
    spec = load_tasks(TASKS)
    assert spec.name == "retrieval-fixture-v2"
    assert spec.k == 10
    assert len(spec.tasks) == 21
    assert spec.thresholds == {"recallAtK": 0.90, "mrrAtK": 0.90, "ndcgAtK": 0.90}
    assert all(task.relevant for task in spec.tasks)
    task_ids = {task.id for task in spec.tasks}
    assert {
        "typescript-dashboard",
        "javascript-client",
        "go-worker",
        "rust-aggregate",
        "java-catalog",
        "c-buffer",
        "shell-deploy",
        "deployment-runbook",
        "config-budget",
        "multilingual-test",
        "chinese-dashboard",
        "identifier-render",
        "cross-language-dashboard",
    } <= task_ids

    invalid = _write_tasks(tmp_path, {"tasks": []})
    with pytest.raises(UsageError, match="non-empty tasks"):
        load_tasks(invalid)


def test_evaluate_passes_and_engine_leads_baselines(tmp_path: Path) -> None:
    payload = evaluate(REPO, TASKS, cache_dir=tmp_path / "cache")
    assert payload["ok"] is True
    assert payload["passed"] is True
    assert payload["tasks"] == 21
    assert payload["k"] == 10
    engine = payload["aggregate"]["engine"]
    assert engine["recallAtK"] >= payload["thresholds"]["recallAtK"]
    assert engine["mrrAtK"] >= payload["thresholds"]["mrrAtK"]
    assert engine["ndcgAtK"] >= payload["thresholds"]["ndcgAtK"]
    assert engine["recallAtK"] > payload["aggregate"]["path"]["recallAtK"]
    assert engine["recallAtK"] > payload["aggregate"]["symbol"]["recallAtK"]
    assert engine["mrrAtK"] > payload["aggregate"]["path"]["mrrAtK"]
    assert engine["mrrAtK"] > payload["aggregate"]["symbol"]["mrrAtK"]
    assert engine["ndcgAtK"] > payload["aggregate"]["path"]["ndcgAtK"]
    assert engine["ndcgAtK"] > payload["aggregate"]["symbol"]["ndcgAtK"]
    assert payload["checks"]
    assert all(check["passed"] for check in payload["checks"])
    rendered = canonical_json(payload)
    assert str(REPO) not in rendered
    assert "\\" not in rendered


def test_evaluate_is_deterministic_with_warm_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    first = evaluate(REPO, TASKS, cache_dir=cache)
    second = evaluate(REPO, TASKS, cache_dir=cache)
    assert canonical_json(first) == canonical_json(second)
    assert first["index"] == second["index"]
    assert first["aggregate"] == second["aggregate"]


def test_evaluate_rejects_unknown_relevant_path(tmp_path: Path) -> None:
    payload = {
        "tasks": [
            {
                "id": "bad-label",
                "query": "bounded context",
                "relevant": ["src/not-there.py"],
            }
        ]
    }
    with pytest.raises(UsageError, match="not present in the index"):
        evaluate(REPO, _write_tasks(tmp_path, payload), cache_dir=tmp_path / "cache")


def test_load_tasks_rejects_unsafe_and_bad_values(tmp_path: Path) -> None:
    base = {
        "name": "bad",
        "k": 10,
        "tasks": [{"id": "x", "query": "rank", "relevant": ["src/app/core.py"]}],
    }
    absolute = dict(base, tasks=[{"id": "x", "query": "rank", "relevant": ["/etc/passwd"]}])
    with pytest.raises(UsageError, match="repository-relative"):
        load_tasks(_write_tasks(tmp_path, absolute))
    traversal = dict(base, tasks=[{"id": "x", "query": "rank", "relevant": ["../core.py"]}])
    with pytest.raises(UsageError, match="must not escape"):
        load_tasks(_write_tasks(tmp_path, traversal))
    bad_threshold = dict(base, thresholds={"mrrAtK": 2})
    with pytest.raises(UsageError, match="threshold"):
        load_tasks(_write_tasks(tmp_path, bad_threshold))


def test_cli_eval_retrieval_json_and_failed_gate(
    tmp_path: Path, capsys: Any
) -> None:
    cache = str(tmp_path / "cache")
    code = cli.run(
        [
            "eval-retrieval",
            str(REPO),
            "--tasks",
            str(TASKS),
            "--cache-dir",
            cache,
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["command"] == "eval-retrieval"
    assert payload["passed"] is True
    assert canonical_json(payload) + "\n" == captured.out

    failing_tasks = json.loads(TASKS.read_text(encoding="utf-8"))
    failing_tasks["thresholds"] = {key: 1.0 for key in DEFAULT_THRESHOLDS}
    failing = _write_tasks(tmp_path, failing_tasks)
    code = cli.run(
        [
            "eval-retrieval",
            str(REPO),
            "--tasks",
            str(failing),
            "--cache-dir",
            cache,
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["passed"] is False
    assert not all(check["passed"] for check in payload["checks"])
