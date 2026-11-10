# Architecture

## Architectural stance
The system is a local-first pipeline with replaceable language adapters and deterministic intermediate representations. The first release should be a modular Python package and CLI, not a distributed service.

## Pipeline
1. **Discovery** — enumerate eligible files, normalize paths, detect language, apply ignore and size policies.
2. **Parsing** — use language-aware parsers where available to extract declarations, imports, exports, and source spans.
3. **Normalization** — map parser output into a canonical model independent of any one parser.
4. **Relationship analysis** — resolve imports and selected symbol references; preserve unresolved edges and confidence.
5. **Indexing** — persist metadata and graph data locally; support rebuild and incremental update.
6. **Ranking/retrieval** — rank files and symbols for a task query and select context under a budget.
7. **Rendering/interfaces** — emit JSON, Markdown, CLI output, and later MCP resources/tools.

## Canonical entities
- Repository
- File
- Symbol (module, class, function, method, interface, type, constant)
- SourceSpan (path, start/end line and optional columns)
- Relation (imports, defines, calls, references, inherits, implements, contains)
- Evidence (parser, resolver, heuristic, user-provided)
- IndexSnapshot

## Relation quality
Each relation should include:
- source and target identifiers (target may be unresolved),
- relation type,
- evidence source,
- source span,
- confidence or resolution status,
- parser/resolver version where useful.

Do not conflate lexical co-occurrence with a call edge. Do not infer runtime behavior solely from static syntax.

## Persistence
Initial storage should be simple and local (for example SQLite plus JSON export). Keep storage behind an interface so alternatives can be evaluated later. Avoid selecting a graph database before benchmarks demonstrate a need.

## Incremental indexing
Use Git status/diff and file fingerprints to identify changed inputs. Recompute affected files and relationships where safe. Fall back to a full rebuild when parser versions, configuration, ignore policy, or schema changes invalidate prior results.

## Context retrieval
Inputs: task query, repository index, explicit budget, optional path constraints.
Outputs: ranked file/symbol evidence and bounded source excerpts.
Ranking should combine lexical relevance, symbol centrality, dependency proximity, recency/change context, and explicit user constraints. The scoring formula must be measurable and configurable.

## Security boundaries
Treat scanned code as untrusted. Do not import or execute project modules. Normalize paths, constrain reads to the repository root, handle symlinks explicitly, and exclude sensitive/generated content by default.


## Product integrations

The core engine remains independent of any one agent harness. Integrations are adapters over stable, versioned core operations rather than separate implementations of parsing or ranking.

### DeepSeek Harness (DSH)

The project will maintain a first-party native DSH plugin alongside the standalone CLI/library and MCP interface. The plugin should expose a small, read-only set of model-facing operations: repository overview/map, symbol and file lookup, dependency neighborhood, task-aware context pack, and conservative change-impact preview.

The DSH adapter must use the official Cordis/DSH plugin contracts and package conventions for the targeted release. It must not duplicate parser, graph, or ranking logic. Initially, evaluate a bounded local bridge from the TypeScript plugin to the core engine (for example, a versioned JSON stdio protocol or local service); choose only after checking DSH process, filesystem, subprocess, and sandbox APIs. Do not assume a shell command is permitted merely because a tool is available.

Compatibility is explicit: declare the supported DSH version range in package metadata and test exact versions, starting with the user's target `0.2.1-rc.3`. DSH is in developer preview and can introduce breaking changes, so keep the adapter isolated and maintain compatibility tests.

See [DeepSeek Harness integration](../integrations/deepseek-harness/README.md).
