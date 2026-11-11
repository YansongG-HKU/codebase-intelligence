# Retrieval-quality evaluation

`cbi eval-retrieval` measures the shipped ranking pipeline on a deterministic
file-level relevance task set and compares it with two intentionally simple
baselines. It is a CI gate, not a model benchmark: the same index, query tokens
and result ordering are used by the model-facing tools.

## Why this exists

Cost, determinism and cache behaviour are benchmarked separately in
[BENCHMARKS.md](BENCHMARKS.md). Those measurements say nothing about whether the
right files are retrieved for a task, so this gate adds a formal relevance
measurement against labelled queries. It is deliberately small, hermetic and
fast: the checked-in fixture is used by CI and no external services or models are
involved.

## Metric definitions

For each task, the top `k` distinct file paths are compared with the labelled
relevant set:

- **Recall@K** — fraction of relevant files present in the top `k`.
- **MRR@K** — reciprocal rank of the first relevant file (0 when none).
- **nDCG@K** — binary-gain discounted cumulative gain, normalised by the ideal
  ordering of the labelled set.
- **Hit rate@K** — fraction of returned rows that are relevant; useful as a
  precision-like diagnostic.
- **Mean** — arithmetic mean of each metric over all tasks, rounded to four
  decimals.

A method must be in the index to score: every labelled path is validated against
the built index, so a typo fails the command instead of silently lowering the
denominator. Paths are repository-relative and traversal/absolute labels are
rejected.

## Compared methods

| Method | Definition |
|---|---|
| `engine` | The shipped `search()`/`rank()` pipeline (lexical × centrality × proximity × entry/module bonuses). |
| `path` | Naive baseline: files whose paths contain any query term, ordered by term count then path. |
| `symbol` | Naive baseline: files containing symbol names/qualified names that match query terms. |

The baselines are reported for context; the gate itself requires the `engine`
metrics to meet the thresholds from the task file. This prevents a future change
from passing by lowering the bar through a broken baseline.

## Task file

See [tests/fixtures/retrieval/eval_tasks.json](../tests/fixtures/retrieval/eval_tasks.json)
for the checked-in fixture. Minimal shape:

```json
{
  "version": 1,
  "name": "retrieval-fixture-v1",
  "k": 10,
  "thresholds": {"recallAtK": 0.85, "mrrAtK": 0.85, "ndcgAtK": 0.85},
  "tasks": [
    {
      "id": "bounded-context",
      "query": "bounded context pack token budget",
      "relevant": ["src/app/core.py", "src/app/model.py"]
    }
  ]
}
```

Limits: at most 100 tasks, 20 relevant paths per task, 500 characters per query
and 5–20 for `k`. Unknown fields are ignored; malformed values fail with
`invalid_arguments` (exit 2). A failing threshold returns the structured payload
and exit 1, so CI can archive it.

## Current fixture result

Command:

```powershell
$env:PYTHONPATH='src'
python -m codebase_intelligence.cli eval-retrieval `
  tests/fixtures/retrieval/repo `
  --tasks tests/fixtures/retrieval/eval_tasks.json --json
```

Result on the checked-in fixture (8 tasks, `k=10`):

| Method | Recall@K | MRR@K | nDCG@K |
|---|---:|---:|---:|
| **engine** | **0.9375** | **1.0000** | **0.9450** |
| path-only baseline | 0.3125 | 0.3750 | 0.3123 |
| symbol-name baseline | 0.8750 | 0.8125 | 0.8105 |

Gate thresholds: Recall 0.85, MRR 0.85, nDCG 0.85 → **pass**.

The engine's lead over the path-only baseline is large; the symbol-name baseline
is intentionally strong on this small fixture because most relevance is attached
to named Python symbols. The fixture is a regression gate, not a claim about
generalisation to arbitrary external repositories.

## CI and local use

The `clean-checkout acceptance` CI job runs the same command with a temporary
cache after reinstalling the engine and verifying the export snapshot. Locally:

```powershell
python -m pytest -q tests/test_evaluation.py
cbi eval-retrieval tests/fixtures/retrieval/repo `
  --tasks tests/fixtures/retrieval/eval_tasks.json --json
```

To evaluate a real repository, point the positional root at it and provide a task
file with repository-relative labels:

```powershell
cbi eval-retrieval /path/to/repo --tasks /path/to/tasks.json --cache-dir /tmp/cbi-eval --json
```

No model tokens are consumed by the evaluation; it uses the same local index as
`cbi search`/`cbi context`.
