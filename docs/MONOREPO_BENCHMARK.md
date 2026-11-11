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
process RSS. The operation timings include loading and validating the index for
each command, which is the real CLI/bridge cost.

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
  --source-label quantAlpha --cache-dir <TEMP_CACHE> --repeat 1 `
  --json-out bench/monorepo-quantAlpha.json `
  --markdown-out docs/MONOREPO_BENCHMARK.md --check
```

The CI `clean-checkout acceptance` job runs a fast 200-file synthetic smoke
with `--check` to keep the harness itself tested.

## Results (2026-11-11, Windows 11, Python 3.13)

### Synthetic monorepo — 5,000 files / 20,000 symbols / 19,999 relations

Source bytes 1,237,177; index cache 36,505,514 bytes; Python-only.

| Phase | Time | Python peak |
|---|---:|---:|
| Cold index | 49.70 s | 103.97 MB |
| Warm index | 32.68 s | 119.36 MB |
| overview | 34.95 s | 119.74 MB |
| map | 34.46 s | 119.37 MB |
| search | 39.89 s | 121.20 MB |
| dependencies | 35.20 s | 119.37 MB |
| context | 38.80 s | 119.36 MB |
| impact | 35.70 s | 119.37 MB |
| symbol-neighborhood | 34.22 s | 119.37 MB |

All payloads were deterministic across repeats within the same index.

### Real monorepo — `quantAlpha` 5,670 indexed files / 52,929 symbols / 104,857 relations

Source bytes 65,229,285; index cache 168,416,863 bytes. Language mix: Python
(2,001 files / 37,136 symbols), TypeScript (923 / 14,402), JavaScript (191 /
1,174), Shell (15 / 217), Markdown (515), JSON (1,636), plus HTML/CSS/SQL/TOML/
YAML/other file-only assets.

| Phase | Time | Python peak |
|---|---:|---:|
| Cold index | 221.72 s | 637.97 MB |
| Warm index | 110.73 s | 753.09 MB |
| overview | 113.30 s | 753.43 MB |
| map | 93.16 s | 753.09 MB |
| search | 97.88 s | 753.09 MB |
| dependencies | 63.04 s | 753.09 MB |
| context | 75.01 s | 753.10 MB |
| impact | 62.51 s | 753.09 MB |
| symbol-neighborhood | 62.13 s | 753.10 MB |

All payloads were deterministic across repeated calls; payloads remained
bounded (431–8,219 bytes, 133–2,055 estimated tokens).

## Gate result

The benchmark **fails its default performance budgets** on both sources:

- cold index budget 300 s — real run 221.7 s (pass), synthetic 49.7 s (pass);
- warm index budget 60 s — real 110.7 s and synthetic 32.7 s (real fails);
- per-operation budgets 5–10 s — every operation on both sources exceeds the
  budget (34–113 s);
- peak-memory budget 1,024 MB — both runs pass (max 753 MB on the real repo).

The dominant cost is per-command index loading/validation and graph construction;
warm index time (110.7 s) is already larger than the operation budgets. This is a
real production-scale signal, not a fixture issue: index persistence and a
serving path that avoids reloading/rebuilding the full graph per command are the
next optimization targets. The benchmark is recorded as failing rather than
having its budgets relaxed.

## Related evidence

- Retrieval-quality gate and real-repository calibration:
  [RETRIEVAL_EVAL.md](RETRIEVAL_EVAL.md)
- Token/cache benchmark: [BENCHMARKS.md](BENCHMARKS.md)
- CI clean-checkout acceptance: [acceptance/CI_CLEAN_CHECKOUT.md](acceptance/CI_CLEAN_CHECKOUT.md)
