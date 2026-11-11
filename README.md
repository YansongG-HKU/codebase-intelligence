# Codebase Intelligence

**AI-native codebase understanding infrastructure for humans and AI agents.**

Codebase Intelligence turns a software repository into a navigable, queryable,
token-aware model of its structure. It helps developers and agents answer:

- What are the main components and entry points?
- Which modules, files, symbols, and interfaces depend on one another?
- What is the smallest reliable context needed for a task?
- What could be affected by a proposed change?
- How can this understanding stay current as the repository evolves?

It ships as a local-first Python engine (standard library only), a CLI, a stdio
MCP server, and a first-party [DeepSeek Harness](integrations/deepseek-harness/README.md)
plugin with six read-only, deterministic, token-budgeted tools.

## Status — v0.1.0

| Capability | Purpose | Status |
|---|---|---|
| Repository scanner | Discover files and apply ignore policies deterministically | Implemented |
| Syntax-aware parser | Extract symbols and imports (Python `ast`; heuristic adapters for JS/TS/Go/Rust/Java/C/C++/C#/Ruby/PHP/Shell) | Implemented |
| Repository map | Summarize important files and symbols under a token budget | Implemented |
| Dependency graph | Imports, inheritance, heuristic calls and references with evidence | Implemented |
| Context retrieval | Select task-relevant context within an explicit budget | Implemented |
| Retrieval quality gate | Evaluate ranking against labelled tasks and deterministic baselines | Implemented |
| Architecture reports | Generate human-readable project documentation (Markdown) and JSON | Implemented |
| Change impact | Estimate downstream impact with confidence labels | Implemented |
| MCP integration | Expose repository intelligence to AI clients over stdio | Implemented |
| DeepSeek Harness plugin | Read-only `codebase_*` tools + static prompt section | Implemented |
| DSH client panel | Right-sidebar tab + full-page fallback: browse the engine without model tokens | Implemented |
| Deterministic export | Write `docs/codebase-intelligence/` snapshot files (JSON/Markdown/Mermaid) + read-only git status | Implemented |
| Incremental indexing | Content-addressed index cache that survives edits | Implemented |
| Explorer UI | Browse saved repository, directory, file and symbol graphs with source evidence | Implemented in the Harness panel |

Everything above is covered by the test suite and, for the DSH plugin, by a real
isolated Harness run; the engine, bridge and panel were also exercised against a
real external 169-file project (see [docs/DELIVERY.md](docs/DELIVERY.md)). The
normative contract is [docs/SPEC.md](docs/SPEC.md); measured token/cache
behaviour is in [docs/BENCHMARKS.md](docs/BENCHMARKS.md); ranking quality is
measured by [docs/RETRIEVAL_EVAL.md](docs/RETRIEVAL_EVAL.md).

Open [the saved project graph](docs/codebase-intelligence/REPO_MAP.md#project-graph)
for a repository-level diagram, or load [the graph snapshot](docs/codebase-intelligence/graph.snapshot.json)
in the Harness panel. Use `cbi export .` to update the versionable files.

## Design goals

1. **Structural understanding, not blind concatenation.** Extract files, symbols,
   imports, references, and relationships instead of treating the repository as
   one giant text document.
2. **Evidence-linked output.** Every reported symbol or relationship is traceable
   to a file and source location, with a `parser` / `resolver` / `heuristic`
   label; unresolved relationships are preserved and labelled, never promoted.
3. **Token-aware context selection.** Rank and retrieve relevant context under an
   explicit token or byte budget, and say what was omitted.
4. **Incremental by design.** Re-index only changed inputs, with cache
   invalidation that can be reasoned about; never write the user's repository
   from the DSH plugin.
5. **Human- and agent-readable.** Markdown/JSON outputs, a CLI, an MCP server,
   and a native DeepSeek Harness plugin.
6. **Safe defaults.** Respect ignore rules, exclude likely secrets, never
   execute repository code, and keep all integration surfaces read-only.
7. **Language-aware, gracefully degraded.** Prefer parser-backed facts; clearly
   label heuristic or unresolved relationships.

## Quick start

Requires Python 3.11+ (the engine has **no runtime dependencies**).

```powershell
# Editable install (adds the `cbi` command); `PYTHONPATH=src` works without installing.
python -m pip install -e ".[dev]"

cbi scan .                              # deterministic discovery summary
cbi index .                             # build/refresh the local index
cbi overview . --json                   # repository shape under a token budget
cbi map . --max-tokens 1600             # ranked file/symbol map
cbi search . --query "token budget"     # files and symbols with path:line evidence
cbi eval-retrieval tests/fixtures/retrieval/repo --tasks tests/fixtures/retrieval/eval_tasks.json --json
cbi dependencies . --target src/codebase_intelligence/api.py
cbi graph . --focus "dir:src/codebase_intelligence/graph" --json   # bounded graph slice
cbi graph . --source src/codebase_intelligence/api.py --line 40    # read-only source evidence
cbi context . --task "add a new parser adapter" --max-tokens 2200
cbi impact . --files src/codebase_intelligence/api.py
cbi report . --out architecture.md      # Markdown architecture report
cbi export .                            # deterministic docs/codebase-intelligence/ snapshot
cbi export . --check                    # CI gate: exit 1 when the snapshot is stale
```

Add `--json` to any structural command for the canonical machine payload; add
`--cache-dir <path>` to keep the index cache out of the repository. Human output
is the default for `scan`, `index` and `report`.

### MCP server

```powershell
python -m codebase_intelligence.mcp .   # newline-delimited JSON-RPC 2.0 over stdio
# or: cbi mcp .
```

It exposes `codebase_overview`, `codebase_map`, `codebase_search`,
`codebase_dependencies`, `codebase_context` and `codebase_impact` with the same
payloads as the CLI and the DSH plugin.

### DeepSeek Harness plugin

See [integrations/deepseek-harness/README.md](integrations/deepseek-harness/README.md)
and [docs/DSH_PLUGIN.md](docs/DSH_PLUGIN.md). The plugin package lives in
`integrations/deepseek-harness/plugin/`, bridges to the Python engine over a
versioned JSON stdio protocol, and was verified on DSH `0.2.2-rc.1`. Besides the
six model-facing tools it ships a **right-sidebar panel** (概览/地图/搜索/依赖/上下文/生成)
with a full-page fallback, which browses the same engine without spending model
tokens and can materialize the deterministic snapshot files with an explicit
confirmation. The generation directory is excluded from scanning/indexing.

## Architecture

```text
Repository
   |
   v
Discovery & Ignore Policy        scanner/   (.gitignore subset, symlink/size/secret policy)
   |
   v
Language Detection -> Parser Adapters   parsers/ (Python ast + regex heuristics)
   |
   v
Canonical Code Model            model/     (File, Symbol, SourceSpan, Relation, Evidence)
   |
   +--> Relation Graph          graph/     (import resolution, neighborhoods, impact)
   |
   +--> Index & Cache           indexing/  (canonical JSON index, content-addressed cache)
   |
   +--> Ranking & Retrieval     retrieval/ (lexical x centrality x proximity, token budgets)
   |
   +--> Rendering & Interfaces  reporting/, cli.py (export), mcp/,
                                DSH plugin tools + right-sidebar panel
```

Facts (parser-derived declarations and imports), inferences (heuristic
relationships and ranking) and rendered views (maps, reports, context packs) are
kept separate; every payload carries the index fingerprint and the token
estimator it used.

## Repository layout

```text
src/codebase_intelligence/
  model/        canonical entities + stable ids + canonical serialization
  scanner/      discovery, ignore policy, symlink/size/secret handling
  parsers/      Python ast adapter, heuristic language adapters, dispatch
  graph/        import resolution, graph queries, conservative impact
  indexing/     index store, incremental cache, ensure_index
  retrieval/    ranking, budget fitting, task-aware context packs
  reporting/    deterministic JSON payloads + Markdown renderers
  mcp/          stdio MCP server
  api.py        shared operations used by CLI/MCP
  cli.py        `cbi` command line
integrations/deepseek-harness/
  plugin/       native DSH host (six tools + bridge), client panel (src/client,
                client.js, locale), panel/export routes, verify harness
tests/                           unit, integration, fixtures
docs/                            SPEC, DELIVERY, BENCHMARKS, EXPORT, scanner/plugin docs
scripts/bench.py                 token-cache benchmark generator
```

## Principles and boundaries

- An index is a navigational aid, **not a substitute for reading source code**
  before making changes.
- A dependency edge records its origin and confidence; unresolved edges are not
  presented as certain.
- Token estimates are estimates (`chars4-wide-v1`) and every budgeted payload
  reports the method used.
- The tool does not upload repository contents to external services.
- The DSH plugin never writes the repository, never executes project code, and
  exposes only read-only tools.

## Known limitations

- Python is the only parser-backed language; other languages use conservative
  regex extraction with honest `heuristic` labels and documented gaps.
- Call edges exist only for unambiguous same-file Python calls; cross-file calls
  are intentionally not guessed.
- `.gitignore` support is a documented subset (no git index / tracked-file view).
- Retrieval relevance is measured by the deterministic fixture gate
  ([docs/RETRIEVAL_EVAL.md](docs/RETRIEVAL_EVAL.md)); it is not a model-judged
  benchmark over arbitrary external repositories.
- The DSH panel writes files only on explicit confirmation and never runs git;
  commit/push stay manual. Custom generation directories must be passed to
  `--exclude` for commands other than the export itself.
- A standalone desktop graph UI is not implemented; the interactive drawer lives
  in the DSH panel (`cbi graph` provides the same bounded data for other clients).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before opening
a pull request. The normative implementation contract is
[docs/SPEC.md](docs/SPEC.md).

## Research references

See [docs/RESEARCH.md](docs/RESEARCH.md); this implementation borrows ideas from
Aider's repository map (ranked symbol map), Repomix (packaging/ignore/token
estimation), Tree-sitter (replaceable parser adapters), SCIP (stable symbol
identifiers), LSP (definition/reference queries) and MCP (agent transport).

## License

License selection is intentionally pending. No license has been granted yet;
until one is added, standard copyright restrictions apply.
