# Vision

## Problem
AI coding agents often begin with incomplete repository awareness. They repeatedly inspect directory trees, search for symbols, open files, and reconstruct relationships. Humans joining an unfamiliar codebase face the same orientation cost.

A raw repository dump can provide broad exposure but is expensive, noisy, difficult to keep current, and weak at representing relationships. A static architecture diagram is readable but often stale and disconnected from source evidence.

## Vision
Create a local-first, continuously refreshable repository intelligence layer that converts source code into a compact, evidence-linked structural model. Humans and agents can query that model to orient themselves, retrieve task-relevant context, and reason about potential change impact.

## Primary users
- AI coding agents that need repository context before planning or editing.
- Developers onboarding to unfamiliar or large codebases.
- Maintainers reviewing cross-module changes.
- Engineering teams maintaining architecture documentation.

## Non-goals for the initial release
- Replacing IDEs, debuggers, compilers, or language servers.
- Claiming complete semantic understanding across every language.
- Automatically modifying source code.
- Sending private code to a hosted service.
- Building a general-purpose vector database or autonomous coding agent.

## Success measures
- Time and tokens required to answer standardized repository-understanding tasks.
- Precision/recall of extracted symbols and dependency edges on fixture repositories.
- Context retrieval relevance under fixed budgets.
- Incremental indexing correctness after controlled changes.
- Reproducibility and source traceability of generated reports.
