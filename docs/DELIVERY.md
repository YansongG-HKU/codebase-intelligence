# Delivery Evidence — v0.1.0

This document records what shipped, how it was verified, the measured token/cache
behaviour, and what remains open. It is the acceptance record for the end-to-end
Codebase Intelligence delivery: engine + CLI + MCP + DSH plugin (tools **and**
right-sidebar panel) + deterministic export.

## What shipped

| Area | Deliverable |
|---|---|
| Engine | `src/codebase_intelligence/` — canonical model, deterministic scanner (now with generation-dir exclusion), Python `ast` + heuristic parsers, import-resolution graph, incremental content-addressed index, budgeted retrieval/context, JSON/Markdown reporting |
| Interfaces | `cbi` CLI (14 commands incl. `export` and `graph`), stdio MCP server, shared `api.py` operations |
| DSH plugin (host) | `integrations/deepseek-harness/plugin/` — `dsh-codebase-intelligence` 0.1.0, six read-only tools, static prompt section, Python JSON-stdio bridge, panel/export/graph host routes, git read-only facts, isolated verify harness |
| DSH plugin (client) | Right-sidebar tab `codebase-intelligence` + full-page fallback panel (Chinese default / EN toggle), seven views (概览/地图/项目图谱/搜索/依赖/上下文/生成), interactive bounded graph explorer with read-only source evidence, explicit-confirm export writer, read-only git status + copyable commit command; built from `src/client/*.js` into a single dependency-free `client.js` |
| Export | `cbi export` deterministic eight-file snapshot under `docs/codebase-intelligence/` (including `graph.snapshot.json`); `--check` CI gate; generated dir excluded from scanning |
| Tests | 408 Python tests + 106 Node tests (plugin host + panel + client + graph explorer), fixtures for scanner/parser/retrieval/CLI/plugin/export/graph |
| Docs | `docs/SPEC.md`, `docs/SCANNER_POLICY.md`, `docs/EXPORT.md`, `docs/DSH_PLUGIN.md`, `docs/TOKENS.md`, `docs/BENCHMARKS.md`, plugin `PANEL_CONTRACT.md`, updated README/ROADMAP/ARCHITECTURE/integration README |
| Bench | `scripts/bench.py` regenerates token/cache evidence; `bench/results.json` holds raw numbers |
| CI | `.github/workflows/ci.yml` — Python lint, strict `mypy src`, tests, deterministic `cbi export --check` and CLI smoke + Node 22 plugin checks on Ubuntu and Windows (syntax, client build `--check`, 106 unit tests, Python bridge smoke, footprint) + a dedicated clean-checkout acceptance job that reinstalls the project, verifies fixtures/snapshot, packs and installs the plugin tarball, and runs the plugin gates |

Generated snapshot files, benchmark evidence and acceptance screenshots are part
of the delivered commit; the final `cbi export . --check` gate passes. The plugin
itself never stages, commits or pushes; repository commit and push remain manual.

## Verification evidence

### Automated suites

| Check | Command | Result |
|---|---|---|
| Python tests | `python -m pytest -q` | **408 passed, 7 skipped** (symlink creation is not permitted on this Windows host; POSIX CI executes those paths, containment is additionally covered by active guard tests) |
| Python lint | `python -m ruff check .` | clean |
| Python types | `python -m mypy src` | strict, clean (38 source files) |
| Plugin unit tests | `cd integrations/deepseek-harness/plugin && node --test "test/unit/*.test.mjs"` | **106 passed, 0 failed** (host bridge/panel/graph routes + client models/views/graph explorer) |
| Plugin check chain | `npm run check` | syntax + `client.js` + `build-client --check` + harness/scripts syntax, clean |
| Client build freshness | `node scripts/build-client.mjs --check` | up to date (6 fragments, **201,197 bytes**, **253 locale keys**) |
| Always-on footprint | `node scripts/footprint.mjs` | tool schema **1189** est. tokens / prompt **184** est. tokens — unchanged by the panel |
| Live bridge smoke | `node verify/bridge-smoke.mjs` | six tools OK against the real engine; deterministic repeats; budgets respected |
| Export determinism | `cbi export . --json` twice + `--check` | byte-identical, second run all `unchanged`, `--check` exit 0 |
| Scan exclusion | `cbi scan . --json --list-files` | no `docs/codebase-intelligence/*` entries; `generated-dir` skip counted |
| Token/cache bench | `python scripts/bench.py --root . --plugin-dir integrations/deepseek-harness/plugin` | all six operations within budget, deterministic, warm cache hit (see `docs/BENCHMARKS.md`) |

### Real-project validation (external repository)

The engine and the plugin were exercised against a real, non-fixture project
(`dsh-sci-plot`, a Python/JS plotting tool: 169 indexed files, 3,188 symbols,
3,961 relations; tested as a workspace copy without `.git`):

| Check | Result |
|---|---|
| `cbi index` cold → warm | full parse, then all files reused from the content-addressed cache; schema/policy/fingerprint stable |
| six CLI operations | all six within budget, deterministic on repeat, no absolute paths or host details in payloads |
| CLI edge cases | `--out` escape rejected (exit 2), unknown files in the generation directory preserved, tampered artifact detected by `--check` (exit 1) and repaired, incremental edit/delete/`--force` counts correct, MCP unknown-tool and invalid-args paths structured |
| `cbi export` | 8/8 files deterministic (including `graph.snapshot.json`), second run all `unchanged`, `--check` exit 0; panel and CLI agree on index fingerprint `f92177d2292b` |
| DSH bridge smoke | `verify/bridge-smoke.mjs --root <copy>`: six tools returned valid JSON, budgets respected, `errors=[]`; a CJK + space workspace path also passed |
| DSH panel (real project) | new session in an isolated workspace pointing at the project: header shows `copy-sciplot`, `f92177d2292b`, engine available; 概览 numbers match the CLI (169 files / 3,188 symbols / 3,961 relations, 6 languages, 8 directories, 2 entry points); 生成 shows 8/8 `无变化` and `快照最新`; the no-git copy renders `当前工作区不是 git 仓库` without breaking; no non-network console errors (the only console errors logged were reconnect noise after the test server was stopped) |
| Graph explorer (real project) | 项目图谱 starts from the saved repository graph, uses a deterministic layered/grid layout, and supports node inspection, in-graph search/highlighting, relation-type and unresolved-edge filters, zoom/fit, breadcrumbs and keyboard activation; `engine` → `engine/build_demo_catalog.py` → symbol drilldown lists resolved `contains`/`calls` edges with evidence and opens a read-only source excerpt at `engine/build_demo_catalog.py:23`; no model turn or token cost |

### Isolated DSH 0.2.2-rc.1 acceptance

Performed with the bundled Node 24.22.2 + `_tools/dsh-cli` (DSH 0.2.2-rc.1) in a
disposable `DSH_HOME` (`F:\dsh插件创造\.tmp\cbi-verify-home`), profile `p-cbi`,
plugin junctioned into the profile, port 3098 only, real desktop app untouched:

| Step | Result |
|---|---|
| `harness prepare` | profile created from the web template, bundle row added, junction correct |
| `--dump-config` | 6/6 checks: exit 0, `# == dsh-codebase-intelligence` layer header, row id/name/config, stderr empty |
| `--without-plugin` control | row removed, no layer — proves the row activates the plugin |
| `harness up` | healthy boot (~10 s); health 4/4 (token redeem, auth cookie, shell 200, no-token 401); instance stderr 0 bytes / 0 activation warnings |
| Real model turn (DeepSeek-V4.1-Flash, High) | model called the six `codebase_*` tools across two turns; reported files/symbols/relations, `path:line` context hits and impact lists |
| Right-sidebar panel | Start guide shows **打开 Codebase Intelligence**; clicking opens the `代码库情报` right tab; 概览 renders file/symbol/relation counts, language and directory tables, entry points and parse issues; panel header shows workspace basename, index fingerprint, engine status and snapshot staleness |
| 项目图谱 view | graph tab renders a bounded, deterministic repository graph (80 nodes / 160 edges per page) with focus/layered/grid layouts, node/edge inspector, search-in-graph, relation/status filters, legend, zoom/fit, keyboard activation and read-only source excerpts; the published `graph.snapshot.json` is read first, so browsing after a restart needs no index build; a refresh rebuilds and saves one local snapshot |
| 生成 view | preview shows 8/8 files with create/update/unchanged badges, a dynamic count and manifest fingerprint; explicit confirm writes the eight files; view then shows 已写入, snapshot freshness and read-only git facts (branch, `?? docs/codebase-intelligence/`, copyable `git add … && git commit …` command). The panel never runs git |
| Full-page fallback | left navigation icon opens the same panel as a full-page view (independence from the right-sidebar services) |
| Prompt/cache neutrality | panel adds no tools and no system-prompt text; tool schemas/prompt footprint unchanged; no model turn is needed to browse |
| Safety | non-3098 ports refused (exit 2); identity-checked stop; instance stopped cleanly |

Screenshots (kept in [docs/acceptance/](acceptance/)):

- [Right-sidebar Start guide — native-style plugin entry (light)](acceptance/cbi-guide-entry.png)
- [Right-sidebar Start guide — native-style plugin entry (dark)](acceptance/cbi-guide-entry-dark.png)
- [Right-sidebar panel — overview](acceptance/cbi-panel-overview.png)
- [Right-sidebar panel — eight-file export preview](acceptance/cbi-panel-export-8.png)
- [Right-sidebar panel — interactive graph explorer](acceptance/cbi-panel-graph.png)
- [Full-page fallback panel](acceptance/cbi-panel-main.png)
- [Real project — 概览 (169 files, fingerprint `f92177d2292b`)](acceptance/cbi-real-overview.png)
- [Real project — 生成 (8/8 unchanged, workspace without git)](acceptance/cbi-real-generate.png)
- [Real project — 项目图谱 drilldown](acceptance/cbi-real-graph.png)
- [Turn 1 — six-tool real model turn](acceptance/cbi-acceptance-turn1.png)
- [Token usage — 63,352 tok, 70% cache hit](acceptance/cbi-acceptance-usage.png)
- [Full conversation](acceptance/cbi-acceptance-conversation.png)

Detailed visual acceptance record: [Start-guide style acceptance](acceptance/GUIDE_STYLE.md)
(native row target measurements, before/after and the live-page computed styles).

### Export and interop acceptance

- Generated files (default `docs/codebase-intelligence/`): `overview.json`,
  `repo-map.json`, `graph.snapshot.json`, `ARCHITECTURE.generated.md`, `REPO_MAP.md`,
  `dependencies.mmd`, `CONTEXT_BRIEF.md`, `manifest.json` — one index build,
  deterministic bytes, no timestamps or absolute paths, manifest hashes covering
  the other seven files.
- The graph bundle is fully local: `graph.snapshot.json` stores files, symbols and
  evidence locations without signatures/docstrings/source text; the panel loads
  it first, falls back to a local workspace snapshot, and can explicitly refresh
  it. Source excerpts are read-only, hash-checked and require a matching graph
  fingerprint. No model turn or prompt tokens are involved.
- `--check` writes nothing and exits 0 only when the snapshot is current; a
  second run on the unchanged tree reports every file `unchanged`.
- The generation directory is pruned from scans through the scanner's
  `excluded_paths` (skip reason `generated-dir`); same-basename directories under
  other paths stay indexed.
- Write safety: `--out` must stay inside the workspace (absolute/`..`/symlink
  escapes rejected, exit 2); only the fixed file names are written, atomically;
  other files are never deleted.
- Interop: `codebaseIntelligence` Host service provided for other plugins,
  `codebase-intelligence/exported` event after a write, stable tab id/routes, DSH
  theme tokens and shared locale; missing collaborators only skip the optional
  integration (verified by the 106 headless plugin tests and the fallback panel).

### Token and cache measurements

Always-on (static) DSH footprint: **1373 estimated tokens** (1189 tool schema +
184 prompt section). The panel adds **0 prompt tokens** (no tools, no prompt
text). MCP tool catalogue: 903 estimated tokens.

Per-operation payloads on this repository (all within budget, byte-identical on
repeat): see [docs/BENCHMARKS.md](BENCHMARKS.md) for the current numbers.

Isolated session usage (from the DSH UI, model turns only):

- Turn 1: 27.7K tokens, 43% cache hit (cold prefix).
- After turn 2: 63,352 tokens total — 43,776 cache-read, 18,592 uncached input,
  984 output, **70% cumulative cache hit**. Derived second-turn hit rate ≈ 90%:
  the static tool/prompt prefix and previous turns are reused.
- Index cache: cold build reparses every file; warm build reuses all of them,
  `cacheHit=true`, identical public payload/fingerprint.

Budget-fitting renderers previously re-hashed the whole snapshot for every row
dropped: `IndexSnapshot.fingerprint()` ran 68 times per map payload on the real
project, and each call canonicalized the full model. The fingerprint is now
memoized per snapshot (the value and every payload byte are unchanged; a
regression test pins exactly one computation). Controlled measurement against
the same cached 169-file snapshot: map payload **5,763 ms → 52 ms** (111×),
overview **88.5 ms → 16.5 ms**, and `cbi export --check` on the real project
**11.5 s → ~1.3–1.6 s**. Wall-clock values depend on host load; the ratios were
measured in one process against one snapshot.

Method and invariants: [docs/TOKENS.md](TOKENS.md). Raw markers:
[docs/BENCHMARKS.md](BENCHMARKS.md), `bench/results.json`.

## Reproduce

```powershell
# Engine + tests
python -m pytest -q
python -m ruff check .
python -m codebase_intelligence.cli overview . --json
python -m codebase_intelligence.cli export . --json
python -m codebase_intelligence.cli export . --check    # exit 0 when current

# Benchmarks
$env:PYTHONPATH = "src"
python scripts/bench.py --root . --plugin-dir integrations/deepseek-harness/plugin `
  --json-out bench/results.json --markdown-out docs/BENCHMARKS.md

# Plugin unit tests + client build
cd integrations/deepseek-harness/plugin
node --test "test/unit/*.test.mjs"
node scripts/build-client.mjs --check
node scripts/footprint.mjs

# Isolated DSH acceptance (path details in docs/DSH_PLUGIN.md; port 3098 only)
node verify/harness.mjs up --json
node verify/harness.mjs url      # open in a browser: 开始 → 打开 Codebase Intelligence
node verify/harness.mjs stop
```

## Known limitations and open items

- Python is the only parser-backed language; the other ten adapters are
  regex-level with `heuristic` labels and documented gaps (no cross-file symbol
  resolution; some languages only import declarations).
- Call edges exist only for unambiguous same-file Python calls; cross-file calls
  are intentionally not guessed.
- `.gitignore` is a documented subset; there is no git-index/tracked-file view.
  `mypy strict` now runs in CI (`mypy src`) and is clean locally (38 source files).
- Retrieval quality is measured for cost/determinism/cache, not yet by a formal
  relevance benchmark against baselines.
- The DSH panel targets the web profile; headless profiles get the tools only.
  Writes require an explicit panel confirmation; the plugin never stages,
  commits or pushes. Custom generation directories are excluded only for the
  export's own index build — pass `--exclude <dir>` to other commands.
- The client bundle is 201,197 B (≈196.5 KiB) against the 224 KiB contract cap;
  adding UI copy still needs care.
- The graph explorer renders at most 80 nodes / 160 edges per page and reads a
  graph snapshot up to 64 MiB; the exported snapshot grows with repository size
  (≈2.5–4.5 MiB for the repositories tested here).
- Real-project timing numbers come from one Windows host and move with machine
  load; the controlled before/after fingerprint figures are the stable evidence.
  The real-project run is acceptance evidence, not part of CI (CI uses the
  checked-in fixtures to stay fast and hermetic).
- `impact` rejects absolute, `..`-escaping and home-relative file paths (exit 2);
  unknown but in-workspace file paths are ignored by design (conservative blast
  radius) rather than guessed.
- DSH compatibility is verified only for `0.2.2-rc.1` (developer preview channel
  can break plugin APIs; re-run the harness before claiming another version).
- Symlink tests skip on this Windows host because symlink creation is not
  permitted; the containment guard is still covered.
