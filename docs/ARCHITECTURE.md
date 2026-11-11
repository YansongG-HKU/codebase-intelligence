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

Compatibility is explicit: declare the supported DSH version range in package metadata and test exact versions. The implemented release is verified on the installed `0.2.2-rc.1` (the original planning target `0.2.1-rc.3` is superseded by what runs on the machine); the adapter stays isolated and compatibility evidence is recorded in [DELIVERY.md](DELIVERY.md).

See [DeepSeek Harness integration](../integrations/deepseek-harness/README.md).

## Implementation status (v0.1.0)

The shipped implementation follows this architecture with the following concrete
choices, all covered by tests:

- **No runtime dependencies.** Parsing uses the standard-library `ast` module for
  Python; other languages use conservative regex adapters with explicit
  `heuristic` evidence. Parser adapters sit behind a dispatch boundary so a
  Tree-sitter implementation can replace them without touching the canonical model.
- **Canonical JSON index instead of a database.** `indexing/` persists
  `index.v1.json` + `cache.v1.json` (atomic writes, canonical bytes,
  content-addressed reuse) plus an optional stat-only `serve.v1.json` sidecar.
  Serving validates the repository metadata stamp and decodes the persisted index
  without rescanning; any mismatch falls back to the incremental build. Storage
  stays behind `ensure_index`/`IndexResult`, so SQLite or a graph database can be
  evaluated later without changing callers.
- **Import-level graph.** Relations carry evidence (`parser`/`resolver`/
  `heuristic`), resolution status (`resolved`/`unresolved`/`ambiguous`/`external`)
  and confidence; unresolved edges are preserved. Python CALLS edges are emitted
  only for unambiguous same-file calls; cross-file calls are intentionally not
  guessed.
- **Retrieval** combines lexical match, resolved in-degree centrality, explicit
  path proximity, entry/module bonuses, and file-level path coverage/doc-config
  priors; a bounded file window is emitted before the symbol stream and symbol
  rows are capped per path. Every budgeted payload reports its measured size,
  the `chars4-wide-v1` estimator, and what was omitted.
- **Integration transports**: CLI (`cbi`), stdio MCP server, and a DSH plugin that
  drives the CLI over a versioned JSON stdio bridge. All three share `api.py` and
  return the same payloads.
- Large-monorepo benchmarks pass their unchanged budgets; retrieval relevance is covered
  by the deterministic fixture gate in [RETRIEVAL_EVAL.md](RETRIEVAL_EVAL.md).
