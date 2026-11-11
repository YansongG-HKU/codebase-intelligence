# Retrieval-quality evaluation

`cbi eval-retrieval` measures the shipped ranking pipeline on deterministic
file-level relevance tasks and compares it with two intentionally simple
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

## Expanded fixture (v2)

The checked-in fixture at
[tests/fixtures/retrieval/eval_tasks.json](../tests/fixtures/retrieval/eval_tasks.json)
now contains **21 tasks** over a small multilingual repository:

| Dimension | Covered values |
|---|---|
| Languages | Python, JavaScript, TypeScript, Go, Rust, Java, C, Shell, Markdown, YAML |
| Task families | code/symbol lookup, file/path lookup, docs/runbook, config, tests, shell automation, cross-language, Chinese natural language |
| Query styles | natural language, identifiers (`renderDashboard`), path fragments, multi-relevant tasks |
| Thresholds | Recall@K 0.90, MRR@K 0.90, nDCG@K 0.90 |
| `k` | 10 |

Example shape:

```json
{
  "version": 1,
  "name": "retrieval-fixture-v2",
  "k": 10,
  "thresholds": {"recallAtK": 0.90, "mrrAtK": 0.90, "ndcgAtK": 0.90},
  "tasks": [
    {
      "id": "typescript-dashboard",
      "query": "dashboard render TypeScript component",
      "relevant": ["web/dashboard.ts"]
    }
  ]
}
```

Limits: at most 100 tasks, 20 relevant paths per task, 500 characters per query
and 5–20 for `k`. Unknown fields are ignored; malformed values fail with
`invalid_arguments` (exit 2). A failing threshold returns the structured payload
and exit 1, so CI can archive it.

## Checked-in fixture result

Command:

```powershell
$env:PYTHONPATH='src'
python -m codebase_intelligence.cli eval-retrieval `
  tests/fixtures/retrieval/repo `
  --tasks tests/fixtures/retrieval/eval_tasks.json --json
```

Result on the checked-in fixture (21 tasks, `k=10`):

| Method | Recall@K | MRR@K | nDCG@K |
|---|---:|---:|---:|
| **engine** | **0.9762** | **1.0000** | **0.9790** |
| path-only baseline | 0.7143 | 0.6905 | 0.6699 |
| symbol-name baseline | 0.8810 | 0.8571 | 0.8365 |

Gate thresholds: Recall 0.90, MRR 0.90, nDCG 0.90 → **pass**; the engine leads
both baselines on all three aggregate metrics.

## Real-repository calibration (2026-11-11)

A local external copy of `dsh-sci-plot` was used as a calibration target because
it is a real mixed-language project already used in the delivery acceptance:

- 169 indexed files, 3,188 symbols, 3,961 relations; 6 indexed languages
  (Python, JavaScript, Markdown, JSON, YAML, plus file-only other assets).
- 15-task file (kept out of this repository because it labels an external
  workspace), `k=10`, same metrics and the same path/symbol baselines.
- Calibration threshold was 0.85 for each aggregate metric.

Observed data after the ranker update:

| Method | Recall@K | MRR@K | nDCG@K |
|---|---:|---:|---:|
| engine | 0.9333 | 0.9333 | 0.8952 |
| path-only baseline | 0.9000 | 0.9000 | 0.8871 |
| symbol-name baseline | 0.7667 | 0.6333 | 0.6452 |

**Calibration result: passed** (all three engine metrics at or above 0.85, and
the engine now leads both baselines on all three aggregate metrics).

For comparison, the same calibration before the ranker change scored engine
0.7333 / 0.4744 / 0.5026; the fix added:

1. **File-level candidate window.** Documentation/config or multi-term path
   hits are returned ahead of a long symbol stream, with a bounded file window.
2. **File-level aggregation.** A path candidate records its matched query terms
   and gains a coverage bonus when its filename names multiple terms. Symbol
   rows are capped per path so one generated file cannot fill the page.
3. **Path/doc prior and priority cutoff.** Documentation/config paths get a
   small prior after a lexical match; a low-scoring path is only promoted when
   it is competitive with the best symbol (ratio 0.33), preventing config/JSON
   noise from crowding out code files.
4. **Per-file symbol cap** (2 rows) plus the larger internal candidate window.

Remaining partial tasks after the update: `palette-theme` and `plot-registry`
recall 0.5 (the second relevant file is below the top-10), `panel-contract`
MRR 0.5 (`engine/CONTRACT.md` ranks before `docs/PANEL-CONTRACT.md`), and
`engine-service` MRR 0.5 (a test file ranks before `lib/engine.js`). The
previous zero-hit tasks (`design-doc`, `panel-contract`, `demo-catalog`) and
`engine-service` now all have non-zero recall; `panel-contract` and
`engine-service` still need ranking work to move their first relevant item to
rank 1.

This is recorded as calibration data, not hidden by lowering the fixture gate.
The fixture labels, 0.90 thresholds and evaluation metric definitions were not
changed; only ranker behavior changed.

## CI and local use

The `clean-checkout acceptance` CI job runs the checked-in command with a
temporary cache after reinstalling the engine and verifying the export snapshot.
Locally:

```powershell
python -m pytest -q tests/test_evaluation.py
cbi eval-retrieval tests/fixtures/retrieval/repo `
  --tasks tests/fixtures/retrieval/eval_tasks.json --json
```

To evaluate a real repository, point the positional root at it and provide a
task file with repository-relative labels:

```powershell
cbi eval-retrieval /path/to/repo --tasks /path/to/tasks.json `
  --cache-dir /tmp/cbi-eval --json
```

No model tokens are consumed by the evaluation; it uses the same local index as
`cbi search`/`cbi context`.

## Not included in this change

A large-monorepo performance/memory benchmark is **not** part of this round. The
calibration target is 169 files; scale work remains open on the roadmap.
