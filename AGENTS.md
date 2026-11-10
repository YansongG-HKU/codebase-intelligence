# Agent Instructions

## Mission
Build Codebase Intelligence as a reliable, privacy-conscious, language-aware system for repository structure analysis and task-aware context retrieval.

## Before changing code
1. Read README.md and the relevant architecture/design documents.
2. Inspect the current implementation and tests; do not assume the roadmap describes shipped behavior.
3. Identify the smallest change that satisfies the task.
4. Preserve the distinction between parser-backed facts, heuristics, and generated summaries.

## Engineering rules
- Python-first for the initial MVP; keep language adapters replaceable.
- Use typed, explicit data models for files, symbols, source spans, and graph edges.
- Every extracted fact must retain source path and location where available.
- Never silently convert an unresolved relationship into a confirmed dependency.
- Respect .gitignore and project-specific ignore configuration; avoid indexing binary files and generated/vendor directories by default.
- Do not execute code from scanned repositories.
- Do not transmit repository content to remote services unless a future feature explicitly opts in and documents the data flow.
- Make output deterministic where practical.
- Add tests for normal cases, edge cases, malformed inputs, and security-sensitive behavior.
- Keep dependencies minimal and justify new runtime dependencies.
- Avoid premature microservices, distributed infrastructure, and mandatory hosted components.

## Token and context rules
- Report the estimation method and tokenizer when known.
- Enforce explicit context budgets.
- Prefer relevant definitions and dependency neighborhoods over arbitrary truncation.
- Keep source excerpts bounded and cite their paths/line ranges.
- Never claim that a compact map fully represents source semantics.

## Security and privacy
- Treat repository contents as untrusted input.
- Defend against path traversal and symlink escapes.
- Exclude likely secrets and sensitive files by default, with documented overrides.
- Do not add real credentials, private repository contents, or customer information to this public repository.

## Delivery
- Run relevant tests and static checks.
- Document limitations and unsupported languages.
- Update docs when behavior or public interfaces change.
- Use focused commits and descriptive pull requests.


## DeepSeek Harness integration
- Maintain a first-party DSH plugin as a supported product deliverable, not an example-only integration.
- Keep the DSH adapter thin; core parsing, graph, ranking, and context logic belongs in the shared engine.
- Follow the official DSH/Cordis plugin package conventions and verify them against the exact supported DSH release before relying on an API.
- Declare compatibility explicitly; never claim a DSH version is supported without install and runtime smoke tests.
- Default all DSH-exposed repository operations to read-only. Any future write/apply operation requires a separate explicit approval and policy design.
- Keep DSH-specific dependencies and compatibility shims isolated from the core Python package.
