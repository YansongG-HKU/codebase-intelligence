# Retrieval Evaluation

## Purpose and scope

The retrieval benchmark measures whether the production retrieval pipeline ranks reviewed, task-relevant repository files near the top. It is deliberately separate from model-answer evaluation.

It does **not** yet prove:
- that an LLM answers the task correctly;
- that context contains every required implementation detail;
- exact token savings under a native model tokenizer;
- broad generalization across languages and large repositories.

The initial task set is a small deterministic smoke corpus over `tests/fixtures/retrieval/repo`. It validates the evaluation mechanism, not product-level retrieval quality. Expand the corpus and independently review gold evidence before making comparative claims.

## Run

From the repository root:

```bash
python scripts/eval_retrieval.py
python scripts/eval_retrieval.py --root tests/fixtures/retrieval/repo --k 1 3 5
python scripts/eval_retrieval.py --json-out /tmp/retrieval-evaluation.json
```

The runner uses the production index and `codebase_intelligence.retrieval.search`; it does not reimplement ranking and makes no model/API/network calls.

## Task-set schema

The versioned JSON file `bench/retrieval_tasks.v1.json` contains:
- `schemaVersion`: currently `1`;
- `tasks[].id`: unique stable task identifier;
- `tasks[].query`: the exact retrieval query;
- `tasks[].relevantFiles`: non-empty gold set of repository-relative file paths;
- `tasks[].relevantSymbols`: optional reviewed set of qualified symbol names;
- `tasks[].symbolEvidence`: optional objects with `qualifiedName`, repository-relative `path`, and positive `line`;
- `tasks[].notes`: reviewer rationale/source evidence notes.

Gold paths are normalized and must not be absolute, contain parent traversal, or point outside the evaluated repository. Add tasks only after reviewing the source and recording why each gold file is relevant. Do not use private repositories or proprietary code in the public corpus.

## Metrics

For each task and each requested K:
- **Precision@K**: relevant unique retrieved files in the first K positions divided by K. A short result list is not padded.
- **Recall@K**: relevant unique retrieved files in the first K positions divided by the full gold file set.
- **nDCG@K**: binary-gain normalized discounted cumulative gain over unique file paths.
- **Reciprocal rank**: reciprocal position of the first relevant unique file, or zero if no relevant file is retrieved.

When a task has `relevantSymbols`, the runner separately reports the same four metrics over qualified symbol names returned by the production ranker. File and symbol denominators are never mixed. Tasks without symbol gold evidence are excluded from symbol aggregates; `symbolTaskCount` records the evaluated subset. Source locations in `symbolEvidence` are reviewer provenance, not an assertion that every parser adapter resolves symbols semantically.

Aggregate values are macro averages across tasks. Duplicate paths are de-duplicated while preserving first rank. Ties inherit the deterministic order of the production search implementation.

## Interpretation

- Compare systems at matched K and matched task sets.
- Do not compare scores when the gold-set policy or task prompts differ.
- A high precision score with low recall may indicate overly narrow context.
- A high recall score with poor precision may indicate noisy context.
- File-level metrics do not score model answer quality or token cost per correct answer. Symbol-level metrics measure exact qualified-name retrieval; they do not prove runtime call correctness. Source-line evidence is retained as gold provenance but line-span accuracy is not yet scored.
- Token cost currently uses the documented `chars4-wide-v1` estimator where reported; it is not a native tokenizer.

## Next evaluation layers

1. Add multi-repository tasks and language-diverse fixtures.
2. Add baseline runners: tree-only, keyword search, full pack, basic symbol map, and graph-aware retrieval.
3. Measure native tokenizer usage for selected model families.
4. Evaluate downstream model answers for correctness, groundedness, and unsupported claims.
5. Score source-line evidence correctness and report variance/confidence intervals where repeated evaluations are used.
