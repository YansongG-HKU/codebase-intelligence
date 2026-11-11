# Architecture report

## Summary

- files: 185
- symbols: 3926
- relations: 5585
- parser issues: 1

## Languages

- python: 90 files, 1629 symbols
- javascript: 35 files, 2251 symbols
- markdown: 31 files, 0 symbols
- other: 8 files, 0 symbols
- json: 6 files, 0 symbols
- typescript: 5 files, 21 symbols
- go: 3 files, 9 symbols
- yaml: 2 files, 0 symbols
- java: 1 files, 6 symbols
- rust: 1 files, 4 symbols
- c: 1 files, 3 symbols
- shell: 1 files, 3 symbols
- toml: 1 files, 0 symbols

## Entry points

- integrations/deepseek-harness/plugin/verify/bridge-smoke.mjs:73 function integrations.deepseek-harness.plugin.verify.bridge-smoke.main
- integrations/deepseek-harness/plugin/verify/harness.mjs:1071 function integrations.deepseek-harness.plugin.verify.harness.main
- scripts/bench.py:234 function scripts.bench.main
- src/codebase_intelligence/cli.py:568 function src.codebase_intelligence.cli.main
- src/codebase_intelligence/mcp/__main__.py:13 function src.codebase_intelligence.mcp.__main__.main
- src/codebase_intelligence/mcp/server.py:1 file entry point
- tests/fixtures/cli/demo_repo/src/demo/core.py:29 function tests.fixtures.cli.demo_repo.src.demo.core.main
- tests/fixtures/cli/demo_repo/web/index.ts:3 function tests.fixtures.cli.demo_repo.web.index.main
- tests/fixtures/parser/go/service/main.go:9 function tests.fixtures.parser.go.service.main.main
- tests/fixtures/parser/python_pkg/app.py:18 function tests.fixtures.parser.python_pkg.app.main
- ... 7 more entry points

## Dependency hubs

- `src/codebase_intelligence/util.py` - imported by 36 file(s), imports 0
- `src/codebase_intelligence/model/__init__.py` - imported by 30 file(s), imports 1
- `src/codebase_intelligence/errors.py` - imported by 18 file(s), imports 0
- `src/codebase_intelligence/__init__.py` - imported by 13 file(s), imports 1
- `integrations/deepseek-harness/plugin/lib/config.js` - imported by 10 file(s), imports 0
- `integrations/deepseek-harness/plugin/lib/util.js` - imported by 8 file(s), imports 0
- `src/codebase_intelligence/scanner/__init__.py` - imported by 6 file(s), imports 2
- `src/codebase_intelligence/mcp/server.py` - imported by 5 file(s), imports 3
- `src/codebase_intelligence/retrieval/rank.py` - imported by 5 file(s), imports 2
- `integrations/deepseek-harness/plugin/test/unit/_helpers.mjs` - imported by 5 file(s), imports 1

## Unresolved and external imports

- 296 edges kept unresolved/external (ambiguous: 2, external: 287, unresolved: 7)
- `integrations/deepseek-harness/plugin/client.js:16` imports `react` (external)
- `integrations/deepseek-harness/plugin/lib/bridge.js:21` imports `node:child_process` (external)
- `integrations/deepseek-harness/plugin/lib/bridge.js:22` imports `node:fs` (external)
- `integrations/deepseek-harness/plugin/lib/bridge.js:23` imports `node:os` (external)
- `integrations/deepseek-harness/plugin/lib/bridge.js:24` imports `node:path` (external)
- `integrations/deepseek-harness/plugin/lib/config.js:13` imports `node:os` (external)
- `integrations/deepseek-harness/plugin/lib/config.js:14` imports `node:path` (external)
- `integrations/deepseek-harness/plugin/lib/panel.js:21` imports `node:child_process` (external)
- `integrations/deepseek-harness/plugin/lib/paths.js:16` imports `node:crypto` (external)
- `integrations/deepseek-harness/plugin/lib/paths.js:17` imports `node:fs` (external)

## Parser issues

- `tests/fixtures/parser/python_pkg/broken.py` - syntax error at line 1, column 12: invalid syntax

## Confidence and evidence

- heuristic relations (regex-derived edges): 3463
- heuristic symbols (regex-derived declarations): 2297
- resolved edges are parser/resolver facts; everything else is labelled

## Limitations

- This is a structural view, not a semantic summary: declarations and files, not program behaviour.
- Symbols and relations marked `[heuristic]` come from regex adapters; they can be incomplete or mislabelled. Treat them as leads, not confirmed facts.
- Languages without an adapter are indexed as files only; their symbols are not listed here.
- Dependency edges keep their status (`resolved`, `unresolved`, `ambiguous`, `external`); unresolved relationships are not dependencies.
