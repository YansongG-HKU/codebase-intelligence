# Large-monorepo performance and memory benchmark

This benchmark measures the end-to-end engine commands — not just the ranking
function — on large repositories. It records scale, wall-clock time, Python
allocation peaks, payload sizes, token estimates and deterministic repeats. The
timings are volatile evidence and never enter model-facing JSON payloads.

## Source and scale recording

`scripts/bench_monorepo.py` supports two explicit source modes:

- **`--root <MONOREPO_ROOT>`** benchmarks an existing checkout read-only; the
  index cache must be outside that repository (`--cache-dir` is recommended).
  The run below used a local working checkout labelled **`quantAlpha`** at
  git commit `9af63b21d8a7230215eb6c5900e3a26eaaea50f1` (clean worktree).
- **`--synthetic-files 5000`** generates a deterministic Python-only monorepo
  in a temporary directory (50 modules per package, one import/class/function
  per module). The source is the generator in the same script, so the command
  is fully reproducible on any machine; the JSON records the generator command.

Every result records:

- files, symbols, relations, source bytes and index-cache bytes;
- per-language file/symbol counts;
- engine/schema version, Python version and platform;
- cold/warm index time and Python-traced peak allocation;
- per-operation median/min/max time, peak allocation, payload bytes, estimated
  tokens and whether repeated calls produced identical JSON.

Memory is measured with Python's `tracemalloc` (engine allocations), not full
process RSS. The operation timings include opening and validating the index for
each command, which is the real CLI/bridge cost.

## Serving changes measured here (2026-11-11)

The accepted baseline (`3fbe4d0`) rescanned and hashed the repository on every
`open_index` call, decoded/rebuilt the index model and eagerly built the graph.
The optimized path adds:

- a `serve.v1.json` sidecar containing a deterministic, **stat-only** metadata
  stamp (paths, sizes, mtimes and modes) and the index identity;
- a fast serving loader that recomputes the stamp and decodes the persisted
  `index.v1.json` without scanning, hashing or reparsing source files; any stamp
  mismatch falls back to the normal incremental build, so stale bytes are never
  served;
- lazy `Graph` construction (import resolution and adjacency maps are built on
  first structural access, not in `Graph.__init__`) and process-local graph reuse;
- process-local snapshot reuse and a pure lexical-token warm-up so repeated
  commands in one serving process do not pay the same setup cost twice. The
  token warm-up does not change ranking output or scores.

## Reproduce

Synthetic 5,000-file monorepo:

```powershell
$env:PYTHONPATH='src'
python scripts/bench_monorepo.py --synthetic-files 5000 --repeat 2 `
  --json-out bench/monorepo-synthetic.json `
  --markdown-out docs/MONOREPO_BENCHMARK.md --check
```

Real local monorepo (read-only; cache outside the repository):

```powershell
$env:PYTHONPATH='src'
python scripts/bench_monorepo.py --root <MONOREPO_ROOT> `
  --source-label quantAlpha --cache-dir <TEMP_CACHE> --repeat 2 `
  --json-out bench/monorepo-quantAlpha.json `
  --markdown-out docs/MONOREPO_BENCHMARK.md --check
```

The CI `clean-checkout acceptance` job runs a fast 200-file synthetic smoke
with `--check` to keep the harness itself tested.

## Results (2026-11-11, Windows 11, Python 3.13)

Raw artifacts: [synthetic](../bench/monorepo-synthetic.json),
[synthetic baseline](../bench/monorepo-synthetic-baseline.json),
[quantAlpha](../bench/monorepo-quantAlpha.json),
[quantAlpha baseline](../bench/monorepo-quantAlpha-baseline.json).

### Synthetic monorepo — 5,000 files / 20,000 symbols / 19,999 relations

Source bytes 1,237,177; index cache 36,505,908 bytes (including the serving
sidecar); Python-only.

| Phase | Before | After | After Python peak |
|---|---:|---:|---:|
| Cold index | 49.70 s | 50.88 s | 103.98 MB |
| Warm index | 32.68 s | **2.81 s** | 64.00 MB |
| overview | 34.95 s | **0.75 s** | 2.18 MB |
| map | 34.46 s | **0.81 s** | 5.41 MB |
| search | 39.89 s | **1.55 s** | 2.38 MB |
| dependencies | 35.20 s | **0.78 s** | 7.81 MB |
| context | 38.80 s | **1.64 s** | 2.38 MB |
| impact | 35.70 s | **0.40 s** | 0.09 MB |
| symbol-neighborhood | 34.22 s | **0.45 s** | 2.25 MB |

All payloads were deterministic across repeats within the same index and are
byte-identical to the baseline payloads.

### Real monorepo — `quantAlpha` 5,670 indexed files / 52,929 symbols / 104,857 relations

Source bytes 65,229,285; index cache 168,417,258 bytes (including the serving
sidecar). Language mix: Python (2,001 files / 37,136 symbols), TypeScript
(923 / 14,402), JavaScript (191 / 1,174), Shell (15 / 217), Markdown (515),
JSON (1,636), plus HTML/CSS/SQL/TOML/YAML/other file-only assets.

| Phase | Before | After | After Python peak |
|---|---:|---:|---:|
| Cold index | 229.67 s | 176.05 s | 637.99 MB |
| Warm index | 129.28 s | **10.53 s** | 401.33 MB |
| overview | 127.89 s | **1.32 s** | 6.39 MB |
| map | 116.31 s | **1.01 s** | 7.56 MB |
| search | 147.84 s | **3.99 s** | 6.28 MB |
| dependencies | 93.53 s | **1.51 s** | 22.00 MB |
| context | 102.55 s | **4.19 s** | 6.40 MB |
| impact | 99.20 s | **0.58 s** | 0.79 MB |
| symbol-neighborhood | 90.15 s | **0.73 s** | 5.59 MB |

The "before" column is a fresh baseline run at `3fbe4d0` on the same host (the
committed older baseline recorded 221.72 s cold / 110.73 s warm and 62–113 s
operations). Payloads remained bounded (431–8,219 bytes, 133–2,055 estimated
tokens), deterministic, and byte-identical to the baseline payloads.

## Gate result

The benchmark **passes every unchanged default budget** on both sources:

- cold index 300 s — real 176.05 s, synthetic 50.88 s;
- warm index 60 s — real 10.53 s, synthetic 2.81 s;
- per-operation 5–10 s — real 0.58–4.19 s, synthetic 0.40–1.64 s;
- peak memory 1,024 MB — real max 637.99 MB, synthetic max 103.98 MB.

The dominant recurring cost is now the one-time persisted index decode (and the
lazy graph build when an operation needs structure); source scanning/hashing and
eager graph construction no longer happen on every command. A brand-new OS
process still decodes the persisted `index.v1.json` once (the serving stamp
avoids the scan/hash, not the decode), while long-lived serving processes reuse
the in-process snapshot, graph and lexical cache. The benchmark is recorded as
passing rather than having its budgets relaxed.

## Related evidence

- Retrieval-quality gate and real-repository calibration:
  [RETRIEVAL_EVAL.md](RETRIEVAL_EVAL.md)
- Token/cache benchmark: [BENCHMARKS.md](BENCHMARKS.md)
- CI clean-checkout acceptance: [acceptance/CI_CLEAN_CHECKOUT.md](acceptance/CI_CLEAN_CHECKOUT.md)
