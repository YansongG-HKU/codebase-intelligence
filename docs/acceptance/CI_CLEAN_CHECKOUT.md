# Clean-checkout CI acceptance

Date: 2026-11-11 (Windows host; GitHub Actions Ubuntu/Windows runners)

Goal: prove the pushed commit can be reproduced from a fresh checkout, including
the fixture data, deterministic export snapshot and the plugin's package
installation path, rather than relying only on the local working tree.

## Run

- Verified commit: `ba3fc803880854fae27791d38c7117271bf17f11`
- Workflow run: [CI #43004226280](https://github.com/YansongG-HKU/codebase-intelligence/actions/runs/43004226280)
- Jobs: **clean-checkout acceptance**, **python**, **dsh-plugin (ubuntu-latest)**,
  **dsh-plugin (windows-latest)** — all `success`.

The workflow now uses `actions/checkout@v7`, `actions/setup-python@v7` and
`actions/setup-node@v7`; the previous Node.js 20 deprecation warnings are gone.

## What the clean-checkout job covers

1. `actions/checkout@v7`; no local files are reused.
2. `python -m pip install -e ".[dev]"` with the pinned Ruff 0.15.22.
3. `pytest` — the scanner/parser/retrieval/CLI/export/graph fixture suite.
4. `cbi export . --check` — the committed eight-file snapshot must be current.
5. `cbi overview tests/fixtures/cli/demo_repo --json` plus budget/fingerprint
   assertions — fixture CLI smoke.
6. `cbi eval-retrieval tests/fixtures/retrieval/repo --tasks
   tests/fixtures/retrieval/eval_tasks.json` — retrieval-quality gate with
   Recall@K/MRR@K/nDCG@K thresholds.
7. `python scripts/bench_monorepo.py --synthetic-files 200 --check` — fast
   monorepo benchmark-harness smoke.
8. `npm pack --pack-destination "$RUNNER_TEMP"` then `npm install` of the
   tarball into a temporary project; asserts `client.js`, `cordis.patch.yml` and
   `locale/zh.json` are present in the installed package.
9. Plugin gates on the same clean checkout: `npm run check`, `npm test`,
   `npm run smoke`, `npm run footprint`.
10. `git diff --exit-code` / tracked-status check — the checks must not dirty the
   checkout.

The existing `python` job also runs the export check now; the pinned-action
matrix keeps the engine and plugin independently covered on both operating
systems.

## Reproducible local equivalent

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
cbi export . --check
cbi overview tests/fixtures/cli/demo_repo --json
cbi eval-retrieval tests/fixtures/retrieval/repo `
  --tasks tests/fixtures/retrieval/eval_tasks.json --json
python scripts/bench_monorepo.py --synthetic-files 200 --repeat 1 `
  --json-out "$env:TEMP/monorepo-smoke.json" --check

cd integrations/deepseek-harness/plugin
npm run check
npm test
npm run smoke
npm run footprint
```

The CI-only addition is the tarball install step; on Windows PowerShell the same
pack/install sequence is:

```powershell
npm pack --pack-destination $env:TEMP
npm install --no-package-lock --ignore-scripts "$env:TEMP\dsh-codebase-intelligence-0.1.0.tgz"
node -e "require('dsh-codebase-intelligence/package.json')"
```

## Remaining notes

- The Linux runner still emits the informational `ubuntu-latest` → Ubuntu 26
  migration annotation (not a failure).
- The dedicated plugin tests also run against the real Python bridge on both
  runners; local Windows has the expected 7 skips for symlink-creation tests,
  while the Linux job executes those paths.
