# DeepSeek Harness Plugin (`dsh-codebase-intelligence`)

Status: **verified end to end against DSH 0.2.2-rc.1**: the isolated instance
boots with the bundle row, and all six tools run through the real Python engine
on the fixture repository (`node verify/bridge-smoke.mjs`: 6/6 tools, 8/8
checks). See §11 for the evidence. This document is normative for the plugin
surface: package layout, configuration, the six tools, the bridge contract, the
token footprint and the verification harness.

The plugin is a thin, read-only adapter. All scanning, parsing, graph
resolution, ranking and context packing live in the shared Python engine
(`src/codebase_intelligence/`); the plugin never re-implements them in
JavaScript.

- Package: `integrations/deepseek-harness/plugin/`
- Version: `0.1.0`
- Runtime deps: none (plain ESM, Node built-ins only)
- Installation marker: one Cordis bundle row in `cordis.patch.yml`
- Host API: `inject: ['agents']` + per-Agent decoration
- Verification harness: `plugin/verify/harness.mjs`
- Test fixture repository: `tests/fixtures/plugin/demo_repo/`

## 1. What it registers

For every live and future Agent, the plugin decorates **that Agent's scope**
with:

1. Six model-facing tools: `codebase_overview`, `codebase_map`,
   `codebase_search`, `codebase_dependencies`, `codebase_context`,
   `codebase_impact`.
2. One static system-prompt section (`interpolate: false`, 98 words) that
   describes when to call the tools, the read-only contract and the
   deterministic/cached nature of their output.
3. A client panel: a **right-sidebar tab** (`codebase-intelligence`, opened from
   the right sidebar's 开始/Start guide) plus a **full-page fallback panel** in the
   main area for DSH builds without the right-sidebar services. The panel browses
   the same engine, previews/writes the deterministic export file set, and shows
   read-only git status plus the suggested commit command. It adds **no prompt
   tokens** (no system-prompt text, no tools).

Nothing is global: another plugin's Agent scope is untouched, and a headless
profile without a tool registry simply logs a warning and stays functional. The
client half is optional: if the DSH build has no right-sidebar services the
plugin falls back to the main panel instead of failing activation.

## 2. Requirements

| Requirement | Value |
|---|---|
| Node.js | `>= 22` |
| DeepSeek Harness | `>= 0.2.2-rc.1` (declared in `engines`; exports `agents` / `agent/created` / `agent.ctx.tools.register` / `agent.ctx.systemPrompt.section`) |
| Python | `>= 3.11`, with the `codebase_intelligence` package importable |
| Disk | an index cache under `<DSH_HOME>/codebase-intelligence/` (or `config.dataDir`) |

The plugin never writes to the workspace, never executes repository code and
never sends repository content to a network service.

## 3. Installation

### 3.1 Isolated verification install (recommended for this repository)

`verify/harness.mjs` materialises a disposable DSH home and profile, links this
package in with a junction, injects the bundle row and verifies `--dump-config`
before booting. It never touches the real DSH home or the real desktop app.

```powershell
$node = 'F:\dsh插件创造\_tools\node-v24.22.2-win-x64\node.exe'
$h    = 'integrations\deepseek-harness\plugin\verify\harness.mjs'

& $node $h prepare        # home + p-cbi profile + bundle row + junction + dump-config gate
& $node $h up             # prepare + boot detached instance + HTTP health
& $node $h url            # token URL (for the browser / Playwright)
& $node $h status         # pid, port, health, activation warnings, engine probe
& $node $h restart        # identity-checked stop + fresh boot (picks up source edits)
& $node $h stop           # stop ONLY the instance this harness started
& $node $h logs           # log paths + tails
& $node $h clean [--fresh]# stop + delete logs/state (home kept unless --fresh)
```

Fixed paths: isolated home `F:\dsh插件创造\.tmp\cbi-verify-home`, profile
`p-cbi`, port **3098 only**, artifacts under `F:\dsh插件创造\_artifacts\cbi`.
Ports **52271** (DSH Web GUI) and **50823** (the real desktop app) are refused at
argv-parse time and never contacted. Every inherited `DSH_*` variable and
`ELECTRON_RUN_AS_NODE` is scrubbed before spawning.

### 3.2 Installing into another profile

A DSH profile is a `package.json` with `dsh.profile.bundles`, resolved through
Node's `node_modules` lookup from the profile directory. To install this package
from a source checkout:

```powershell
$profile = "$env:DSH_HOME\profiles\<profile-name>"

# 1. Link the package into the profile (junction on Windows; unlink it, never rm -r)
New-Item -ItemType Junction -Path "$profile\node_modules\dsh-codebase-intelligence" `
         -Target "<repo>\integrations\deepseek-harness\plugin"

# 2. Append the bundle row to dsh.profile.bundles in $profile\package.json
#    ("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app", "dsh-codebase-intelligence")

# 3. Verify the composed tree, then boot
dsh --profile <profile-name> --dump-config   # must show "# == dsh-codebase-intelligence"
dsh --profile <profile-name> --no-open --port <port>
```

The Electron desktop profile (`desktop`) is managed exclusively by the desktop
application (`dsh` refuses to boot or manage it). Install it there through the
application's plugin manager rather than the CLI.

Uninstall: remove the row from `dsh.profile.bundles`, then unlink the junction.
Do **not** delete the junction recursively — a recursive delete follows it into
this repository.

## 4. Configuration

One loader row in `cordis.patch.yml`:

```yaml
- insert:
    - id: dsh-codebase-intelligence
      name: dsh-codebase-intelligence
      config:
        maxTokens: { overview: 900, map: 1600, search: 1200, dependencies: 1200, context: 2200, impact: 1200 }
        pythonPath: ''
        corePath: ''
        dataDir: ''
        indexMaxFileBytes: 1048576
        tools: { overview: true, map: true, search: true, dependencies: true, context: true, impact: true }
        promptSection: true
        panel: true
        exportDir: docs/codebase-intelligence
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `maxTokens.<tool>` | integer | SPEC §4 table | Per-tool budget handed to the engine on every call. Plugin clamp: **200–8000**; the engine enforces its own 64–8000 clamp. |
| `pythonPath` | string | unset | Absolute path to a Python 3.11+ interpreter. Wins over every discovery step. Empty string means "use discovery". |
| `corePath` | string | unset | Directory added to `PYTHONPATH` so `python -m codebase_intelligence.cli` imports (default: `<repo>/src` when it contains the package). Empty string means "use the default or rely on a pip install". |
| `dataDir` | string | `<DSH_HOME>/codebase-intelligence` | Plugin data directory. The engine's index cache lives at `<dataDir>/indexes/<rootHash>`; the workspace itself is never written. Empty string means default. |
| `indexMaxFileBytes` | integer | `1048576` | Passed to the engine as `--max-file-bytes`. Range 1024–67108864 (bytes). |
| `tools.<tool>` | boolean | `true` | Set `false` to avoid registering that tool for new/current Agents (e.g. a profile that only needs search + context). |
| `promptSection` | boolean | `true` | Set `false` to skip the static system-prompt section. |
| `panel` | boolean | `true` | Set `false` to skip the client panel and the host `/dsh-codebase-intelligence` routes (tools keep working). |
| `exportDir` | string | `docs/codebase-intelligence` | Repository-relative generation directory for `cbi export`. Must stay inside the workspace (no absolute path, no `..`); malformed values fall back to the default with a warning. |
| `timeoutMs` (code default) | integer | `120000` | Engine call timeout, 5000–600000 ms. Not in the shipped row because the default is always correct; set it only for very large repositories. |

Environment variables read at call time (lower priority than `pythonPath`):

| Variable | Purpose |
|---|---|
| `CBI_PYTHON` | Python interpreter path (after `config.pythonPath`). |
| `CBI_PYTHONPATH` | Extra `PYTHONPATH` entries tried **before** the checkout `src/`; used for development and by the unit tests' fake engine. |
| `DSH_HOME` | Defaults the data directory and the managed-runtime search root. |

Interpreter discovery order: `config.pythonPath` → `CBI_PYTHON` →
`DSH_CBI_PYTHON` → `$DSH_HOME/dsh-runtimes/*/dependencies/python/{python.exe,bin/python3}`
→ `python` → `python3` → `py -3` → common installs (conda, `C:\Python31x`,
`%LOCALAPPDATA%\Programs\Python\...`, `/usr/bin/python3`). A candidate is accepted
only after a probe proves Python ≥ 3.11 **and** an importable
`codebase_intelligence.cli`; the result is cached until `invalidate()`.

All row values are validated and clamped. A malformed row degrades to defaults
and logs one bounded `config: ...` warning per bad value; it never prevents
activation.

## 5. Tool reference

| Tool | Required args | Optional args | Engine command |
|---|---|---|---|
| `codebase_overview` | — | `maxTokens`, `refresh` | `overview` |
| `codebase_map` | — | `focus`, `maxTokens`, `refresh` | `map` |
| `codebase_search` | `query` | `maxTokens`, `refresh` | `search` |
| `codebase_dependencies` | `target` | `direction` (`both`/`imports`/`dependents`), `depth` (1–5), `maxTokens`, `refresh` | `dependencies` |
| `codebase_context` | `task` | `pathPrefix`, `maxTokens`, `refresh` | `context` |
| `codebase_impact` | at least one of `files`/`symbols` | `maxTokens`, `refresh` | `impact` |

Semantics:

- **Workspace root** is the Agent's session cwd: `agent.session.header.cwd` →
  `header.config.cwd` → `agent.cwd` → `process.cwd()`. Every path argument must
  be repository-relative POSIX and is rejected if it is absolute, drive-letter
  or home-relative, or contains a `..` segment. This is defense in depth: the
  engine also resolves every path with strict containment checks.
- **Token budgets** are clamped by the plugin to 200–8000 and passed to the
  engine, which returns the largest useful payload that fits plus explicit
  `budgets`/`truncated` metadata. Omit `maxTokens` to use the configured
  default.
- **`refresh: true`** passes `--force` to the engine: the index is rebuilt even
  if the incremental cache is valid. Use it after out-of-band workspace edits
  the cheap memo guard cannot see (see §7).
- **Output** is the engine's canonical JSON object verbatim, rendered as one
  JSON text block. The plugin adds no timestamps, durations, cache flags, pids
  or absolute paths, so two identical calls return identical bytes.
- **Never-throw failures** use the shared envelope
  `{ok:false, code, message, repair:{action,label,detail}}`, where `code` is the
  engine code when available (`repo_error`, `index_error`, `not_found`,
  `invalid_arguments`, …) or a plugin code (`invalid_args`,
  `workspace_boundary`, `workspace_unavailable`, `engine_unavailable`,
  `engine_timeout`, `engine_invalid_json`, `engine_failed`, `failed`,
  `canceled`). Messages are bounded and path-free.

Representative payload shapes are specified in `docs/SPEC.md` §10. Example
`codebase_search` interaction (shape, not live output):

```
codebase_search {"query": "parse_file", "maxTokens": 1200}
→ {
    "ok": true,
    "index": {"schemaVersion": "1", "engineVersion": "…", "policyFingerprint": "…", "fingerprint": "…"},
    "query": "parse_file",
    "total": 2,
    "results": [{"path": "src/codebase_intelligence/parsers/__init__.py", "line": 24, "symbol": "parse_file", "kind": "function", "language": "python", "score": 0.97, "match": "name"}],
    "budgets": {"maxTokens": 1200, "tokensEstimated": 380, "tokenEstimator": "chars4-wide-v1"},
    "truncated": false
  }
```

Schema design rules (SPEC §13): small static JSON schemas, no dynamic/default
values (the schema text never changes with config), `additionalProperties:
false`, and the output projector is
`render: (_args, value) => [{type: 'text', text: JSON.stringify(value)}]`.

## 6. Bridge contract

The plugin spawns exactly:

```
<python> -m codebase_intelligence.cli <command> --json \
  --root <sessionCwd> --cache-dir <dataDir>/indexes/<rootHash> \
  --max-tokens <budget> --max-file-bytes <indexMaxFileBytes> [--force] \
  [--query Q | --focus P | --target T --direction D --depth N | --task T --path-prefix P | --files a,b --symbols x,y]
```

- UTF-8 stdio (`PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`,
  `PYTHONUNBUFFERED=1`), `windowsHide: true`, stdin closed.
- Success contract: exit 0 and exactly one canonical JSON object + newline on
  stdout. The plugin tolerates one stray non-JSON line before the object and
  otherwise fails with `engine_invalid_json` (raw stdout is never surfaced).
- Error contract: exit 2/3/4 with `{ok:false,error:{code,message}}` on stdout
  when `--json` is passed. Both that envelope and exit codes are mapped to the
  plugin's never-throw envelope.
- Timeout: `timeoutMs` (default 120 s) — the child is killed and reported as
  `engine_timeout`.
- Captured stdout/stderr is bounded at 8 MiB per stream; an over-long stream is
  reported as `engine_failed` rather than passed through.
- The plugin never parses repository content in JavaScript.

## 7. Token footprint, cache and determinism

Measured with `node scripts/footprint.mjs` (`chars4-wide-v1`, SPEC §4:
`ceil(ascii/4 + nonAscii)`, minimum 1):

| Component | Bytes | Est. tokens |
|---|---|---|
| Six tool schemas (names + descriptions + parameters, compact JSON) | 4,756 | **1,189** |
| Static prompt section | 735 | **184** |
| Total model-facing plugin overhead | 5,491 | **1,373** |

`npm run footprint` prints the JSON object (`toolCount`, `toolSchemaBytes`,
`toolSchemaTokensEstimated`, `promptSectionBytes`,
`promptSectionTokensEstimated`, `promptSectionTextHash`). The unit suite pins a
hard budget: total tool schema ≤ **2,200** estimated tokens and the prompt
section ≤ **120 words** / ≤ 300 tokens.

Cache behavior:

- **Engine index cache** — `<dataDir>/indexes/<rootHash>/`, where `rootHash` is
  the first 16 hex characters of SHA-256 over the canonicalized (realpath,
  case-folded on Windows) workspace root. The engine owns it: incremental
  reuse by size+mtime+sha256, atomic writes, and a content `index.fingerprint`
  that changes only when the model changes. The workspace is never written.
- **Plugin payload memo** — bounded to 64 entries / 6 MiB per plugin instance,
  keyed by root, tool, normalized arguments and budget. Reuse requires a complete,
  matching asynchronous stat stamp of names, sizes and timestamps. If the walk
  reaches the depth or entry limit or cannot read metadata, the request goes to
  the Python engine's incremental index. `refresh: true` also bypasses reuse.
  Cache state never appears in the tool value.
- **Determinism** — the engine payload is byte-stable for identical repository
  content + policy + engine version (SPEC §3). The plugin preserves the object
  key order it received, so `JSON.stringify(value)` in the output projector
  reproduces the engine's canonical JSON text for the same input.
- **Panel neutrality** — the client panel contributes no system-prompt text and
  no tools, so the always-on footprint above is unchanged by it. Panel requests
  go to loopback host routes and never touch the model context.

## 8. Panel and deterministic export

The client half is built from `src/client/*.js` into a single dependency-free
`client.js` (`node scripts/build-client.mjs`; `--check` fails when stale) with
generated `locale/zh.json` + `locale/en.json`.

- **Right-sidebar tab (primary).** Feature-detects the DSH right-sidebar services
  (`sidebarRightTabs` + `sidebarRight`) with optional injection, registers the
  tab type `codebase-intelligence`, its pane body (`sidebar.right.pane.tab`) and
  a 开始/Start guide entry (`sidebar.right.tab.guide.entry`) that opens the tab.
  If those services are absent the registration is skipped silently.
- **Full-page fallback (independence).** Always registers `sidebar.panellist` +
  `main`, so the plugin works on DSH builds without the right-sidebar services
  and remains usable as a full-page view.
- **Views:** 概览 / 地图 / 项目图谱 / 搜索 / 依赖 / 上下文 / 生成, Chinese by default with an
  EN toggle. The Start-guide entry is styled as a native host row (26 px icon,
  14 px title, 11 px description, 20 px radius) and the namespaced stylesheet is
  mounted globally so the row is styled before the panel opens. Bounded tables, `path:line` evidence, budget/truncation badges,
  loading/error/empty states, refresh.
- **生成 (export):** previews the eight-file bundle (`--check`), shows
  created/updated/unchanged badges, writes only after an explicit confirmation,
  then shows read-only git facts (branch, changes under the generation dir) and
  the suggested `git add … && git commit …` command with a copy button. The
  plugin **never** stages, commits or pushes.
- **Host routes:** `/dsh-codebase-intelligence/api/{state,overview,map,search,
  dependencies,context,impact,refresh,export,git}` — same-origin loopback JSON
  with the `x-dsh-codebase-intelligence: 1` header; see
  `PANEL_CONTRACT.md` §3 for the exact payloads. A headless profile registers
  none of them.
- **Interop (optional, both directions).** The Host provides an injectable
  `codebaseIntelligence` service and emits `codebase-intelligence/exported`
  after a write; the stable tab id `codebase-intelligence` and the routes let
  other plugins open the panel or read data without importing our bundle. The
  panel uses DSH theme tokens (`var(--dsw-…)`) and the shared locale service, so
  the claude-mode theme and other plugins' styling apply naturally. No hard
  dependency exists in either direction; with no plugin installed the
  engine/CLI/MCP stay fully functional, and missing collaborators only skip the
  optional integration.
- **Generated files:** `docs/codebase-intelligence/{overview.json,repo-map.json,graph.snapshot.json,
  ARCHITECTURE.generated.md,REPO_MAP.md,dependencies.mmd,CONTEXT_BRIEF.md,
  manifest.json}` — deterministic (no timestamps/absolute paths), written
  atomically, listed in `manifest.json` and excluded from scanning through the
  scanner's `excluded_paths`. The operator view is [EXPORT.md](EXPORT.md).

## 9. Verification harness

`verify/harness.mjs` (Node ≥ 22, zero dependencies) owns one disposable
instance and follows the same safety model as the other first-party plugin
harnesses on this machine:

| Item | Value |
|---|---|
| Script | `integrations/deepseek-harness/plugin/verify/harness.mjs` |
| Isolated home | `F:\dsh插件创造\.tmp\cbi-verify-home` (`DSH_HOME`) |
| Profile | `p-cbi`, created from the shipped `web` template |
| Bundle row | `<profile>\package.json` → `dsh.profile.bundles` includes `dsh-codebase-intelligence` |
| Plugin link | `<profile>\node_modules\dsh-codebase-intelligence` → junction → this package |
| Instance | `dsh web --profile p-cbi --no-open --port 3098` (detached) |
| Port | **3098 only**; 52271/50823 refused with exit 2 |
| State/logs | `F:\dsh插件创造\_artifacts\cbi\logs\` |

`prepare` verifies the composed profile with `dsh --profile p-cbi
--dump-config`:

| Check | Meaning |
|---|---|
| exit code 0 | the launcher composed the tree |
| `# == dsh-codebase-intelligence` | the bundle layer was loaded |
| `- id: dsh-codebase-intelligence` | the loader row exists |
| `name: dsh-codebase-intelligence` | the row points at this package |
| `indexMaxFileBytes: 1048576`, `promptSection: true`, `context: 2200` | row config survived composition |
| `stderr == ""` | no skipped/unresolvable bundle warnings |

`--without-plugin` boots a control profile without the row; `stop` refuses any
PID it cannot prove it started (command line + profile, or port owner);
junctions are unlinked, never recursively deleted; recursive deletes are
limited to `.tmp\cbi-verify*` and `_artifacts\cbi`.

## 10. Unit tests

No real engine and no network are required: the bridge suite spawns a fake
Python package (`codebase_intelligence/cli.py`) placed first on
`PYTHONPATH` via `CBI_PYTHONPATH`, so real spawn/probe/parse/timeout paths are
exercised against scripted success/error/invalid-JSON/timeout modes.

```powershell
cd integrations\deepseek-harness\plugin
node --test "test/unit/*.test.mjs"   # 106 tests, 0 failures (bundled Node 24.22.2)
node scripts/footprint.mjs
node --check index.js
```

Coverage: config defaults/overrides/clamping/malformed rows; exact CLI argv for
all six commands; probe discovery and `engine_unavailable`; stdout parsing
(valid, trailing noise, invalid, empty); engine error mapping; timeout kill;
tool envelopes never throwing; disabled tools; static prompt section and word
limit; workspace-root precedence; workspace-boundary rejection before spawn;
memo determinism/reuse/invalidations/refresh; footprint determinism and the
2200-token tool-schema budget; plugin decoration/disposal for live and future
Agents.

The live integration gate runs the real engine through the same bridge on the
fixture repository (`npm run smoke`, disposable cache directory, never writes
the fixture):

```powershell
cd integrations\deepseek-harness\plugin
node verify\bridge-smoke.mjs        # exit 0 pass, 1 failed check, 2 engine unavailable
node verify\bridge-smoke.mjs --root <another-repo>
```

It derives the dependency target and path prefix from the repository itself
(first entry point / first map entry / top directory), then asserts: all six
tools return `ok:true`; `overview` exposes `repo`/`index.fingerprint`; two
identical calls are byte-identical; a `refresh:true` call returns the same
fingerprint and bytes; a traversal argument is rejected with
`workspace_boundary`; empty `search` input is rejected with `invalid_args`. The
JSON report lists per-tool byte size, estimated tokens and truncation state.

### Production checks

- Git facts disable repository FSMonitor hooks and optional index writes. The
  adapter supports freshly initialized repositories, labels unavailable status,
  and only offers a copyable commit command for shell-safe paths. That command
  scopes the commit to the export directory.
  [Git configuration reference](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corefsmonitor)
- CI gates the engine with strict mypy and tests the Node 22 plugin and real
  Python bridge on Ubuntu and Windows.

### Code graph explorer

Open **项目图谱 / Code graph** in the panel. The view borrows the standard patterns
from code-navigation tools: directory-first drilldown, a stable layered chart,
typed relation lines, an inspector, and a legend instead of an opaque hairball.

- **Layout:** deterministic focus layout (incoming ← focus → outgoing) for symbols;
  DAG layers for small directory/file slices; a kind-ordered grid when there are
  no edges or too many layers. Positions are stable across renders and pages.
- **Toolbar:** back/root breadcrumbs, search-in-graph with match count and
  highlighting, relation-type filter, unresolved/heuristic visibility toggle,
  refresh, zoom controls and fit. Nodes and edges are keyboard focusable with
  Enter/Space activation; double-click drills into a directory, file or symbol.
- **Inspector:** selecting a node shows kind, path, line, in/out degree, and
  incoming/outgoing relation rows; selecting an edge highlights it on the canvas
  and opens a read-only source excerpt at the evidence line. Source excerpts
  require a matching graph fingerprint and indexed file hash.
- **Visual language:** directory/file/symbol/unresolved node tones, resolved /
  heuristic / unresolved edge tones, dashed unresolved routes, hover/selection
  emphasis, a legend, node counts and explicit omitted-edge counts. Edges are
  curved and clickable with a wide invisible hit target.
- **Bounded:** at most 80 nodes and 160 edges per page, including up to three
  evidence samples per edge; directory edges aggregate underlying import
  relationships. Graph queries are local and use no model tokens. The view has
  no new frontend dependency and the bundle stays under its 224 KiB cap.

The graph opens a saved workspace snapshot first, then a compatible
`docs/codebase-intelligence/graph.snapshot.json` from the repository. If both
are missing, it builds and saves a local snapshot once. Navigation and source
evidence reuse that snapshot after a Harness restart. Use **刷新图谱 / Refresh
graph** to pick up workspace changes. To update the files under version control,
write the export from the **生成 / Export** tab or run `cbi export .`.
The exported `REPO_MAP.md` includes the repository-level diagram.

## 11. Known limitations

- **Python engine required.** Without a Python ≥ 3.11 interpreter that can
  import `codebase_intelligence.cli`, every tool returns
  `engine_unavailable` with a repair hint; no JS fallback exists by design.
- **Engine CLI contract.** The six commands and the global flags (`--json`,
  `--root`, `--cache-dir`, `--max-tokens`, `--max-file-bytes`, `--force`) are a
  versioned contract, verified against the CLI in this repository. If the CLI
  diverges, tools fail with a structured engine error instead of guessing.
- **One workspace per session.** The root is the session cwd; there is no
  multi-root support and no way to inspect a repository outside the session
  workspace.
- **Memo scope.** The Host checks up to 4,096 entries and six directory levels,
  excluding default ignored directories. It falls back to the engine on incomplete
  coverage. Changes invisible to filesystem metadata still require `refresh: true`.
- **Python launch.** The bridge runs in the plugin directory with Python safe-path
  mode. The inspected repository is supplied separately through `--root`.
- **List arguments are comma-joined.** `codebase_impact` joins `files` and
  `symbols` into comma-separated CLI values, so a repository path containing a
  literal comma cannot be expressed.
- **Token counts are estimates.** `chars4-wide-v1` is a budgeting heuristic, not
  a tokenizer; exact model token counts differ by tokenizer.
- **Panel is web-profile only.** The client half targets the DSH web client
  (`dsh.client.platform: web`); headless profiles get the tools only, and a
  profile with `panel: false` skips the host routes as well.
- **Writes are explicit and bounded.** Only the eight fixed files under
  `exportDir` are written (atomic, confirmed in the panel); the plugin never
  deletes other files, never stages/commits/pushes, and never writes the
  workspace from the six model tools.
- **Right-sidebar services are optional.** On DSH builds without
  `sidebarRightTabs`/`sidebarRight` the plugin registers only the full-page
  fallback; the tab/guide entry and the interop `openTabIn` target then do not
  exist.
- **Custom generation directories are not globally excluded.** The default
  `docs/codebase-intelligence` is excluded from scanning by policy; a custom
  `exportDir` is excluded only for the export's own index build — pass
  `--exclude <dir>` to other commands if you need the same effect.
- **Export bundles are truncated on huge repositories.** The overview/map JSON
  are budgeted (2000/4000 estimated tokens) and `dependencies.mmd` is bounded to
  400 edges; omitted rows are reported in the payload/brief, not silently
  dropped.
- **Compatibility claim is narrow.** Only DSH `0.2.2-rc.1` has been exercised;
  `engines.dsh` declares the minimum but newer DSH releases must be re-verified
  before claiming support.
- **Heuristic parsers stay heuristic.** Tool output labels heuristic and
  unresolved edges; the plugin never promotes them, and no tool should be read
  as a complete semantic model of the repository.

## 12. Verification evidence

Recorded with the bundled Node 24.22.2 and the DSH CLI 0.2.2-rc.1 on this
machine (`F:\QuestionForAI\codebase-intelligence`):

| Gate | Command | Result |
|---|---|---|
| Syntax | `node --check index.js && node --check client.js` / `lib/*.js` / `client.js` / `scripts/*.mjs` / `verify/*.mjs` | exit 0 |
| Unit tests | `node --test "test/unit/*.test.mjs"` | **106 / 106 pass, 0 fail** (host bridge/panel/graph routes + client models/views/graph explorer) |
| Client build | `node scripts/build-client.mjs --check` | up to date (6 fragments, 201,197 bytes, 253 locale keys) |
| Footprint | `node scripts/footprint.mjs` | 1,189 + 184 = **1,373** estimated tokens (panel adds 0) |
| Dump-config | `node verify/harness.mjs prepare` | 6/6 checks, stderr `""` (row discovered) |
| Boot/health | `node verify/harness.mjs up` | healthy in ~10 s; token redeem, auth cookie, shell 200 `<title>DeepSeek Harness</title>`, no-token 401; instance stderr 0 bytes / 0 activation warnings |
| Engine probe | `prepare` fact | Python 3.13.13 found via `python`; a DSH runtime Python is used when `DSH_HOME` points at a provisioned home |
| Live bridge | `node verify/bridge-smoke.mjs` | **6/6 tools ok**, deterministic repeats, budgets respected |
| Right-sidebar panel | isolated DSH GUI | Start guide shows **打开 Codebase Intelligence**; tab `代码库情报` opens with 概览/地图/搜索/依赖/上下文/生成; header shows workspace, index fingerprint, engine status, snapshot staleness |
| 项目图谱 view | isolated DSH GUI | repository → directory → file → symbol drilldown, bounded nodes/edges, breadcrumbs, relation filter, read-only source excerpt at the evidence line; loads the published `graph.snapshot.json` before building a local snapshot |
| 生成 view | isolated DSH GUI | preview 8/8 files with badges and a dynamic `{n} / {total}` count; explicit confirm writes them; read-only git branch/status + copyable commit command; panel never runs git |
| Full-page fallback | isolated DSH GUI | left navigation icon opens the same panel full-page (right-sidebar services not required) |
| Control run | `node verify/harness.mjs dump-config --without-plugin` | row removed, no plugin layer, exit 0 |
| Export | `python -m codebase_intelligence.cli export . --json` twice + `--check` | byte-identical; second run all `unchanged`; `--check` exit 0; `cbi scan` omits `docs/codebase-intelligence/*` |
| Safety | harness refusals | non-3098 ports refused (exit 2); identity-checked stop; real desktop app untouched |

Screenshots and the full acceptance record live in
[DELIVERY.md](DELIVERY.md) and [acceptance/](acceptance/). The remaining accepted
limits are listed in §11; the panel is a web-profile feature, writes require an
explicit confirmation, and commit/push stay manual.

A headless profile registers the six tools and the prompt section only; the
panel routes and client half are skipped without failing activation.
