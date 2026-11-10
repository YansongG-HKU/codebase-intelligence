# dsh-codebase-intelligence

First-party [DeepSeek Harness](https://github.com/deepseek-ai/DeepSeek-Harness)
plugin for Codebase Intelligence.

It provides:

- six read-only, deterministic, token-budgeted model tools — `codebase_overview`,
  `codebase_map`, `codebase_search`, `codebase_dependencies`, `codebase_context`,
  `codebase_impact` — plus one static system-prompt section;
- a web client panel: right-sidebar tab `codebase-intelligence` with a full-page
  fallback (概览 / 地图 / 搜索 / 依赖 / 上下文 / 生成), which browses the local Python
  engine without spending model tokens;
- a deterministic export writer (`cbi export`) for `docs/codebase-intelligence/`
  with explicit-confirm writes and read-only git facts (the plugin never stages,
  commits or pushes).

Install, configuration, tool reference, token footprint and the isolated
verification harness are documented in
[`../../docs/DSH_PLUGIN.md`](../../../docs/DSH_PLUGIN.md); the acceptance evidence is
in [`../../docs/DELIVERY.md`](../../../docs/DELIVERY.md) and the panel route/UI
contract in [`PANEL_CONTRACT.md`](PANEL_CONTRACT.md).

Quick checks:

```powershell
cd integrations/deepseek-harness/plugin
npm test          # 95 headless unit tests (host + panel routes + client)
npm run check     # syntax + client build freshness
npm run footprint # measured always-on token cost
node verify/harness.mjs up   # isolated DSH instance on port 3098
```

The plugin is a maintained deliverable; keep the Python engine version and the
DSH compatibility claim in sync when changing `engines.dsh`.
