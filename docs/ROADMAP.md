# Roadmap

This roadmap describes intended work, not shipped functionality. Status changes only after implementation and verification.

## Phase 0 — Foundation
- [ ] Define product requirements and non-goals.
- [ ] Establish canonical data model and JSON schema.
- [ ] Define scanner ignore, symlink, and size policies.
- [ ] Create representative fixture repositories and evaluation tasks.
- [ ] Establish CI, linting, typing, and test conventions.

## Phase 1 — Useful local MVP
- [ ] Repository scanner with deterministic output.
- [ ] Initial Python parser adapter.
- [ ] Extract files, modules, classes, functions, imports, and source spans.
- [ ] Generate repository tree and symbol map.
- [ ] Export machine-readable JSON and human-readable Markdown.
- [ ] Provide token/character estimates with explicit methodology.
- [ ] Add CLI commands for scan, map, and report.

## Phase 2 — Relationship intelligence
- [ ] Resolve local imports for supported languages.
- [ ] Build typed dependency graph with evidence and unresolved edges.
- [ ] Add graph queries and neighborhood exploration.
- [ ] Add change-impact prototype with conservative confidence labels.

## Phase 3 — Task-aware context
- [ ] Task query interface.
- [ ] Ranking and token-budget selection.
- [ ] Source excerpts with path and line citations.
- [ ] Benchmark retrieval quality against baseline strategies.

## Phase 4 — Agent integration
- [ ] MCP server exposing repository map, symbol lookup, graph traversal, and context retrieval.
- [ ] Document integration patterns for common coding agents.
- [ ] Add safe read-only defaults and explicit repository scope.

## Phase 5 — Scale and usability
- [ ] Incremental indexing.
- [ ] Multi-language adapter expansion.
- [ ] Interactive graph explorer.
- [ ] Large monorepo performance and memory benchmarks.

## Release gates
A phase is complete only when tests, documented limitations, reproducible examples, and acceptance criteria are satisfied. Do not mark roadmap items complete merely because a design document exists.
