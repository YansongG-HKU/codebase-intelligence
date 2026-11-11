# Roadmap

This roadmap describes intended work, not shipped functionality. Status changes
only after implementation and verification. Items marked `[x]` are covered by the
test suite and the acceptance evidence in [DELIVERY.md](DELIVERY.md); where an
item is only partially met, the note says exactly what remains.

## Current status (v0.1.0)

Phase 1 (local MVP), Phase 2 (relationship intelligence), Phase 3's first three
items (task-aware context), Phase 4's core integration deliverables
(MCP server + first-party DSH plugin), the interactive graph explorer and the
eight-file deterministic export are implemented and verified. Phase 0 typing and
the deterministic retrieval-quality gate are enforced in CI; large-monorepo
performance/memory benchmarks remain open.

## Phase 0 — Foundation
- [x] Define product requirements and non-goals. (README, VISION.md)
- [x] Establish canonical data model and canonical JSON contract. (model/entities.py, SPEC §2/§10)
- [x] Define scanner ignore, symlink, and size policies. (docs/SCANNER_POLICY.md)
- [x] Create representative fixture repositories and evaluation tasks. (tests/fixtures/**; deterministic cost/determinism evaluation in scripts/bench.py)
- [x] Establish CI, linting, typing, and test conventions. (CI + ruff + strict `mypy src` + pytest shipped in `.github/workflows/ci.yml`; Node plugin checks run on Ubuntu and Windows)

## Phase 1 — Useful local MVP
- [x] Repository scanner with deterministic output.
- [x] Initial Python parser adapter.
- [x] Extract files, modules, classes, functions, imports, and source spans.
- [x] Generate repository tree and symbol map.
- [x] Export machine-readable JSON and human-readable Markdown.
- [x] Provide token/character estimates with explicit methodology (`chars4-wide-v1`).
- [x] Add CLI commands for scan, map, and report.

## Phase 2 — Relationship intelligence
- [x] Resolve local imports for supported languages (Python incl. `src/` layouts, JS/TS relative imports, Go directories).
- [x] Build typed dependency graph with evidence and unresolved edges.
- [x] Add graph queries and neighborhood exploration.
- [x] Add change-impact prototype with conservative confidence labels.

## Phase 3 — Task-aware context
- [x] Task query interface.
- [x] Ranking and token-budget selection.
- [x] Source excerpts with path and line citations.
- [x] Benchmark retrieval relevance against baseline strategies. (`cbi eval-retrieval` file-level Recall@K/MRR@K/nDCG@K against path-only and symbol-name baselines on a 21-task multilingual fixture; external 169-file calibration recorded in [RETRIEVAL_EVAL.md](RETRIEVAL_EVAL.md) now passes after file-level/prior ranker work); cost/determinism/cache remain in [BENCHMARKS.md](BENCHMARKS.md)

## Phase 4 — Agent integration
- [x] MCP server exposing repository map, symbol lookup, graph traversal, and context retrieval.
- [x] First-party native DeepSeek Harness plugin with model-facing read-only tools.
- [x] Define a versioned, local bridge between the DSH adapter and core engine (JSON stdio CLI protocol).
- [x] Declare and test DSH compatibility, starting with 0.2.2-rc.1 (the release installed on the target machine; 0.2.1-rc.3 was the original planning target and is superseded).
- [x] Publish DSH installation, configuration, upgrade, and troubleshooting instructions. (docs/DSH_PLUGIN.md, integrations/deepseek-harness/README.md)
- [x] Document integration patterns for other coding agents. (generic stdio MCP server; SPEC §12)
- [x] Add safe read-only defaults and explicit repository scope.

## Phase 5 — Scale and usability
- [x] Incremental indexing.
- [x] Multi-language adapter expansion (heuristic/regex adapters for JS/TS/Go/Rust/Java/C/C++/C#/Ruby/PHP/Shell; Python is parser-backed).
- [x] Right-sidebar client panel + deterministic `cbi export` snapshot (L2: browse without model tokens, explicit write, read-only git status; full-page fallback when the right sidebar services are absent).
- [x] Interactive graph explorer. (saved `graph.snapshot.json` + bounded panel explorer: directory → file → symbol, relation filter, pagination, read-only source evidence; max 80 nodes / 160 edges per page)
- [ ] Large monorepo performance and memory benchmarks.

## Release gates
A phase is complete only when tests, documented limitations, reproducible
examples, and acceptance criteria are satisfied. Do not mark roadmap items
complete merely because a design document exists.

Current release gate status: `pytest` 416 passed / 7 skipped (symlink tests
unavailable on the Windows host), `ruff` clean, strict `mypy src` clean,
plugin `node --test` 106 passed, the fixture retrieval-quality gate passes,
isolated DSH 0.2.2-rc.1 install + real model
turn + right-sidebar panel + graph explorer + deterministic eight-file export
verified, plus a real-project run on an external 169-file repository (engine CLI,
MCP/bridge smoke, panel, JSON-stdio bridge, graph drilldown). See
[DELIVERY.md](DELIVERY.md).
