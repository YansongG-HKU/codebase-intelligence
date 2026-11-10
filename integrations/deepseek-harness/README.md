# DeepSeek Harness Integration

**Status: implemented and verified on DSH `0.2.2-rc.1`.**

This directory contains the first-party native plugin for
[DeepSeek Harness](https://github.com/deepseek-ai/DeepSeek-Harness). The plugin
makes Codebase Intelligence available inside DSH sessions through six read-only,
deterministic, token-budgeted tools. The standalone engine remains independently
usable through the CLI and the MCP server; the plugin is a thin adapter over it.

See [../../docs/DSH_PLUGIN.md](../../docs/DSH_PLUGIN.md) for the full operator
manual (install, configuration, tool reference, footprint, troubleshooting).

## Product contract

The integration is a maintained deliverable, not a one-off example. It:

- installs as a normal Cordis bundle row and appears through the DSH plugin loader;
- exposes focused, read-only model-facing tools;
- uses the shared Codebase Intelligence engine (Python CLI over a versioned JSON
  stdio bridge) for scanning, parsing, graph queries, ranking and context
  selection — no duplicated analysis logic in JavaScript;
- respects the active workspace (`agent.session.header.cwd`) and rejects paths
  outside it;
- returns bounded outputs with source paths and line ranges;
- labels inferred or unresolved relationships (`heuristic`, `unresolved`,
  `ambiguous`, `external`);
- never writes the repository (index cache lives under `DSH_HOME`), never
  executes project code, and never uploads source content.

## Tools

| Tool | Purpose | Default budget | Default |
|---|---|---|---|
| `codebase_overview` | Repository shape: files/symbols/relations, languages, top directories, entry points, index fingerprint | 900 tokens | Read-only |
| `codebase_map` | Compact ranked file/symbol map, optional path focus | 1600 tokens | Read-only |
| `codebase_search` | Search files and symbols with path:line evidence | 1200 tokens | Read-only |
| `codebase_dependencies` | Imports/dependents neighborhood with status and evidence labels | 1200 tokens | Read-only |
| `codebase_context` | Task-aware excerpts with path:line citations under a token budget | 2200 tokens | Read-only |
| `codebase_impact` | Conservative affected files/symbols with confidence labels | 1200 tokens | Read-only |

Every tool returns the engine's canonical JSON object as one text block. The
payloads contain no timestamps, absolute paths, durations or cache flags, and are
byte-identical for identical inputs (prompt-cache friendly).

## Client panel and deterministic export

The plugin also ships a client half (web profile): a **right-sidebar tab**
(`codebase-intelligence`, opened from the right sidebar's 开始/Start guide) plus a
**full-page fallback** panel for builds without the right-sidebar services. It
browses the same engine with no model-token cost (概览 / 地图 / 搜索 / 依赖 /
上下文 / 生成) and can materialize the deterministic snapshot:

- `cbi export` writes eight files under `docs/codebase-intelligence/`
  (`overview.json`, `repo-map.json`, `ARCHITECTURE.generated.md`, `REPO_MAP.md`,
  `dependencies.mmd`, `CONTEXT_BRIEF.md`, `manifest.json`); the panel previews
  them, writes only after an explicit confirmation, then shows read-only git
  branch/status and a copyable `git add … && git commit …` command.
- The plugin never stages, commits or pushes; commit/push stay manual.
- Generated files are deterministic (no timestamps/absolute paths) and the
  generation directory is excluded from scanning/indexing.
- The panel adds no tools and no system-prompt text, so the always-on footprint
  (1,189 tool-schema + 184 prompt estimated tokens) is unchanged.

Interoperability is optional in both directions: the Host provides an injectable
`codebaseIntelligence` service and emits `codebase-intelligence/exported`; the
stable tab id and loopback routes let other plugins open the panel or read data
without importing this package. Theme tokens and the shared locale service keep
the panel visually consistent with the claude-mode theme and other plugins, and
missing collaborators only skip the optional integration. The normative
contract is [plugin/PANEL_CONTRACT.md](plugin/PANEL_CONTRACT.md).

## Package layout

```text
plugin/
  package.json        dsh-codebase-intelligence (ESM, zero runtime deps)
  cordis.patch.yml    one bundle row with compact config defaults
  index.js            per-agent decoration: tools + static prompt section; panel routes
  lib/                config, paths, prompt, bridge, service, tools, panel, util
  src/client/         readable client sources (collapsed into client.js)
  client.js           single dependency-free DSH client bundle (panel + fallback)
  locale/             generated zh/en dictionaries
  scripts/footprint.mjs   measured always-on token footprint
  scripts/build-client.mjs  client build + --check
  test/unit/          94 node:test cases (host + panel routes + client; no engine)
  verify/harness.mjs  isolated DSH instance harness (prepare/dump-config/boot/...)
  verify/bridge-smoke.mjs  six tools against the real engine on fixture repos
```

## Compatibility policy

Initial target: **DSH 0.2.2-rc.1** (the release installed on the target machine),
declared in `package.json` `engines.dsh`. DSH is in developer preview and can
introduce breaking changes, so the adapter stays isolated in this directory and
is verified through an isolated-instance harness rather than assumed from package
metadata.

Compatibility matrix:

| DSH | Node | Plugin | Result |
|---|---|---|---|
| 0.2.2-rc.1 | 24.22.2 | 0.1.0 | Verified: dump-config row, isolated boot, health, real model turn, six tools, right-sidebar panel + full-page fallback, confirmed export write, read-only git facts |

Before claiming a new DSH version: inspect that release's plugin cookbook and
official examples, install into a clean profile, verify activation and tool
registration, execute every tool against a disposable fixture repository, and
verify disable/uninstall and failure diagnostics. Record the evidence here.

## Install (source checkout)

```powershell
# 1. Register the bundle row in a DSH profile and junction the package into it.
#    The isolated harness does exactly this for verification:
cd integrations/deepseek-harness/plugin
& $node verify/harness.mjs prepare        # isolated home + profile p-cbi + junction
& $node verify/harness.mjs dump-config     # asserts the row is present, stderr clean

# 2. For a real profile, junction the package and add the bundle name:
#    %DSH_HOME%\profiles\<profile>\node_modules\dsh-codebase-intelligence -> this directory
#    add "dsh-codebase-intelligence" to dsh.profile.bundles in that profile's package.json
```

The plugin resolves the Python engine from `CBI_PYTHON`/`pythonPath` and
`<repo>/src` (or the pip-installed package), resolves the workspace from the
agent session cwd, and stores its index cache under
`<DSH_HOME>/codebase-intelligence/indexes/<rootHash>`.

## Security requirements

- Workspace-scoped access only; the plugin rejects paths outside the session cwd.
- No execution of scanned repository code.
- Exclude likely secrets and generated/vendor content by default (engine policy).
- Enforce output-size and token budgets at the tool boundary.
- No external upload or telemetry containing source contents.
- All tools are read-only; the plugin never writes the repository.
- Repository text and tool output are untrusted data, never instructions.

## References

- [Official DeepSeek Harness repository](https://github.com/deepseek-ai/DeepSeek-Harness)
- [Official package cookbook](https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/cookbook/adding-a-package.md)
- [Official plugin release notes](https://github.com/deepseek-ai/DeepSeek-Harness/releases)
