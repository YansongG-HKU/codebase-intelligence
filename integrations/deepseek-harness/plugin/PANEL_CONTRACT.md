# Panel & Export Contract (v1)

Normative for the L2 delivery: `cbi export`, the DSH host panel routes, the
client right-sidebar panel, and plugin interoperability. The Lead owns this
file; the `export-core` (Python) and `client-panel` (JS) owners implement
against it.

Design constraints (do not break):

- The panel never enters the model context. It must not change the six tool
  schemas or the static prompt section; tool payloads stay byte-identical.
- All writes are explicit, confirmed, inside the session workspace, and limited
  to the generation directory (`docs/codebase-intelligence/` by default).
- Generated files are deterministic: no timestamps, no absolute paths, stable
  ordering. Re-running an unchanged repository produces no diff.
- The generated directory is excluded from scanning/indexing.
- Missing collaborators degrade gracefully: no hard dependency on the right
  sidebar services, on any other plugin, or on the DSH version's slot set.

## 1. Generation directory and file set

Default `<root>/docs/codebase-intelligence/` (configurable). Fixed file set:

| File | Content |
|---|---|
| `overview.json` | `cbi overview --json` payload with `budgets.maxTokens` set to the fixed export budget (2000) |
| `repo-map.json` | `cbi map --json` payload (budget 4000) |
| `graph.snapshot.json` | Portable graph snapshot for layered browsing |
| `ARCHITECTURE.generated.md` | `cbi report` Markdown |
| `REPO_MAP.md` | `reporting.markdown_map` output and top-level Mermaid graph |
| `dependencies.mmd` | Mermaid `graph LR` of resolved IMPORTS edges among indexed files (bounded: ≤400 edges, deterministic order; unresolved/external edges omitted with a comment) |
| `CONTEXT_BRIEF.md` | Agent-facing orientation brief: entry points, top modules by centrality, language mix, key files, how to query the tools, limitations |
| `manifest.json` | `{schemaVersion, engineVersion, policyFingerprint, fingerprint, files:[{path, bytes, sha256}], outDir}` — no time, no root path |

`manifest.json` is written last and lists every other generated file (not
itself). All paths inside generated files are repository-relative POSIX paths.

## 2. `cbi export` CLI

```
cbi export [root] --out docs/codebase-intelligence --json [--check]
           [--cache-dir DIR] [--force] [--max-file-bytes N] [--exclude GLOB]...
```

- Default: build the index, render the bundle, write changed files atomically
  (`tmp` + `os.replace`), leave unchanged files untouched.
- `--check`: write nothing; report per-file status. Exit code `0` when every
  file exists with identical bytes, `1` when anything is missing/stale, `2`
  usage, `3` repository/index error, `4` internal.
- JSON payload (`--json`, both modes):

```json
{"ok": true, "schemaVersion": "1", "command": "export", "check": false,
 "outDir": "docs/codebase-intelligence",
 "index": {"schemaVersion": "1", "engineVersion": "0.1.0",
           "policyFingerprint": "…", "fingerprint": "…"},
 "files": [{"path": "docs/codebase-intelligence/overview.json",
            "status": "created|updated|unchanged", "bytes": 0,
            "sha256": "…"}],
 "manifestFingerprint": "…", "stale": false}
```

- Strict safety: `--out` must resolve inside the workspace root; refuse
  absolute/`..`/symlink escapes; only write the fixed file names; never delete
  other files; never write outside `outDir`.
- `--check` must work without an existing index (it builds the index like a
  normal call, using the cache when possible).

## 3. Host panel routes

Registered through `ctx.inject(['webServer'])` exactly like
`dsh-security-selftest/lib/panel.js`: one `webServer.register({kind:'prefix',
path:'/dsh-codebase-intelligence', handler})`. Every request must carry
`x-dsh-codebase-intelligence: 1`, a loopback `Host`, and a matching `Origin`
when present; every response is JSON with `no-store`. Bodies ≤ 1 MiB.

Git status is read-only with optional index writes and FSMonitor disabled.
When Git status is unavailable, `available` is false. `command` is null when
status is unavailable or the export path is unsafe to paste into a shell.

Workspace root resolution: `sessionId` query/body → live agent session cwd
(`agent.session.header.cwd`). An omitted ID uses the latest live registration.
An explicit unknown or disposed ID, or no live session, returns
`{ok:false, code:'workspace_unavailable'}`.

| Route | Method | Result `data` |
|---|---|---|
| `/api/state?session=` | GET | `{root, repo, languages, entryPoints, index, exports:{outDir, files, stale}, git:{branch, dirty, exportChanges, command}, engine:{available, pythonVersion}}` |
| `/api/graph?session=&focus=&offset=&relation=` | GET | bounded slice of the saved graph and graph fingerprint |
| `/api/graph?session=&source=&line=&fingerprint=` | GET | indexed, bounded source excerpt, or 409 if the graph or source changed |
| `/api/graph` | POST | refresh the session workspace graph in the local cache |
| `/api/overview?session=&maxTokens=` | GET | engine overview payload |
| `/api/map?session=&maxTokens=&focus=` | GET | engine map payload |
| `/api/search?session=&query=&maxTokens=` | GET | engine search payload |
| `/api/dependencies?session=&target=&direction=&depth=&maxTokens=` | GET | engine dependencies payload |
| `/api/context?session=&task=&maxTokens=&pathPrefix=` | GET | engine context payload |
| `/api/impact?session=&files=a,b&symbols=&maxTokens=` | GET | engine impact payload |
| `/api/refresh` | POST `{session}` | `{ok:true, data:{index}}` (force reindex) |
| `/api/export?session=` | GET | `--check` plan: `{outDir, files, stale, manifestFingerprint, git}` |
| `/api/export` | POST `{session, confirm:true}` | write: `{outDir, files, manifestFingerprint, git}` |
| `/api/git?session=` | GET | `{branch, dirty, exportChanges:[...], command}` |

`git` objects are produced host-side with `git rev-parse --abbrev-ref HEAD`
and `git status --porcelain -- <outDir>`; `command` is the suggested
`git add <outDir> && git commit -m "docs: refresh codebase intelligence snapshot"`.
The host never stages/commits/pushes.

Error envelope: `{ok:false, code, message, repair?}` with the shared codes
(`invalid_arguments`, `workspace_unavailable`, `not_found`, `engine_unavailable`,
`export_failed`, `too_large`, `failed`). Route handlers never throw.

## 4. Client panel

Package half (`dsh.client` in `package.json`): static `client.js` built from
`src/client/*.js` fragments by `scripts/build-client.mjs` (concat in filename
order) plus generated `locale/zh.json` / `locale/en.json`. React comes from
`require("react")`; the loader entry is
`window.__ModuleLoader__.load({ id: "dsh-codebase-intelligence", factory: (require) => { … } })`.

Required surfaces:

1. **Right-sidebar tab (primary).** Feature-detect `sidebarRightTabs` +
   `sidebarRight` via optional `ctx.inject([...])`:
   - `ctx.sidebarRightTabs.register({id: 'codebase-intelligence', kind: 'codebase-intelligence', multiple: false, title: () => t('panel.title')})`
   - `ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({name:'sidebar.right.pane.tab', key:'codebase-intelligence', locale: NS}, PanelComponent))`
     (component receives `sessionId` in standard props; requests include it)
   - `ctx.slots.inject('sidebar.right.tab.guide.entry', …)` registering a
     button that calls `ctx.sidebarRight.openTabIn(sessionId, 'codebase-intelligence')`
     (appears in the right sidebar's 开始/Start guide).
   - Do not register these when the services are absent; activation must never fail.
2. **Fallback full panel (independence).** Always register
   `sidebar.panellist` (id `codebase-intelligence`, order 26, label from locale)
   + `main` slot so the plugin works on DSH builds without the right sidebar
   services (and as a full-page view).
3. **Views (Chinese default, en fallback):** 概览 / 地图 / 项目图谱 / 搜索 / 依赖 / 上下文 / 生成.
   - Every data view renders bounded JSON-derived tables, `path:line` citations,
     budget/truncated markers, loading/error/empty states, refresh button.
   - 项目图谱: deterministic focus/layered/grid layout, node/edge inspector,
     in-graph search and highlighting, relation/status filters, zoom/fit,
     legend, keyboard activation, read-only source excerpts, and explicit
     node/edge/page bounds (80 nodes / 160 edges per page).
   - 生成: export file checklist (all eight), preview (`--check`) with
     created/updated/unchanged badges, explicit 写入 button (confirm),
     then git branch/status, changed files under the generation dir, and a
     copyable commit command. Never run git.
   - Header shows workspace root basename, index fingerprint (short), engine
     availability, and a language toggle (中文/EN via `ctx.locale`).
4. **Styling:** namespaced class names (`cbi-*`), no global CSS, no CSS
   variables overridden. Use DSH theme tokens (`var(--dsw-*)`) with safe
   fallbacks so the claude-mode theme and other themes style the panel
   correctly without any hard dependency.
5. **No prompt surface:** the client adds no system prompt text and no model
   tools; `scripts/footprint.mjs` numbers must not change.
6. **Headless tests** (`test/unit/client.test.mjs`): evaluate `client.js` in a
   vm with `__ModuleLoader__`/react stubs; assert `__test__` helpers, graph
   model/layout helpers, the eight export file names, zh/en dictionary
   completeness, view order, API URL builders (header/prefix/session), and
   build `--check` freshness. The client bundle cap is 224 KiB.

## 5. Interoperability (organic, optional, both directions)

- **Provide** (server): `ctx.reflect.provide('codebaseIntelligence', api)` with
  `{version, overview(sessionId), exportPreview(sessionId), exportWrite(sessionId),
  resolveRoot(sessionId)}`; other Host plugins can optionally inject it.
- **Provide** (client): the stable tab id `codebase-intelligence` and the
  documented host routes let any plugin open the panel or read data without
  importing our bundle.
- **Emit/consume events** (optional): `ctx.emit('codebase-intelligence/exported', payload)`
  after a successful write; no listener is required.
- **Theme/locale composition:** use DSH theme tokens and the shared locale
  service; never fork or override another plugin's styling.
- **Absent collaborators:** if `sidebarRightTabs`/`sidebarRight` are missing →
  fallback full panel; if `theme` is missing → CSS fallbacks; if another plugin
  is absent → no effect; our plugin absent → the engine/CLI/MCP remain fully
  functional.
- **No hard dependency:** package manifest, activation and tests must pass with
  only the DSH core services present.

## 6. Acceptance

1. `cbi export` deterministic: two runs byte-identical; `--check` exit 0;
   no timestamps/absolute paths; manifest hashes match files; generated dir
   absent from `cbi scan`/`overview` file lists.
2. Write safety: `--out` outside root / `..` / symlink refused; only the fixed
   files written; unchanged files untouched.
3. Host routes: same-origin gate (403 without header), JSON errors, workspace
   resolution via session, export preview/write, git status + commit command.
4. Client: right-sidebar tab opens in the isolated DSH instance with a real
   screenshot; the 开始 guide entry opens it; fallback main panel is registered;
   panel renders overview/search/context/export and writes the eight files;
   git status + command shown; no console errors.
5. Independence: with the right-sidebar services stubbed away the client still
   registers the fallback panel; plugin unit tests pass without the engine.
6. No prompt-surface change: tool schema footprint and static prompt section
   unchanged; six tool payloads byte-identical after the panel lands.
