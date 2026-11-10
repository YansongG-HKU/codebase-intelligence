# Codebase Intelligence

**AI-native codebase understanding infrastructure for humans and AI agents.**

Codebase Intelligence turns a software repository into a navigable, queryable, token-aware model of its structure. It helps developers and agents answer:

- What are the main components and entry points?
- Which modules, files, symbols, and interfaces depend on one another?
- What is the smallest reliable context needed for a task?
- What could be affected by a proposed change?
- How can this understanding stay current as the repository evolves?

The project is inspired by useful ideas from repository maps, syntax-aware code parsing, code intelligence indexes, and AI context-packaging tools. It aims to combine these capabilities behind a reproducible, tool-agnostic interface.

## Design goals

1. **Structural understanding, not blind concatenation.** Extract files, symbols, imports, references, and relationships instead of treating the repository as one giant text document.
2. **Evidence-linked output.** Every reported symbol or relationship should be traceable to a file and source location.
3. **Token-aware context selection.** Rank and retrieve relevant context under an explicit token or byte budget.
4. **Incremental by design.** Re-index only changed inputs where safe, while detecting when a full rebuild is required.
5. **Human- and agent-readable.** Provide Markdown/JSON outputs, a CLI, an MCP server, and a native DeepSeek Harness (DSH) plugin.
6. **Safe defaults.** Respect ignore rules, avoid secrets, never execute repository code during indexing, and make data collection boundaries explicit.
7. **Language-aware, gracefully degraded.** Prefer parser-backed facts; clearly label heuristic or unresolved relationships.

## Planned capabilities

| Capability | Purpose | Status |
|---|---|---|
| Repository scanner | Discover files and apply ignore policies | Planned |
| Syntax-aware parser | Extract symbols and imports | Planned |
| Repository map | Summarize important files and symbols | Planned |
| Dependency graph | Represent imports, references, and calls with evidence | Planned |
| Context retrieval | Select task-relevant context within a budget | Planned |
| Architecture reports | Generate human-readable project documentation | Planned |
| Change impact | Estimate downstream impact of proposed edits | Planned |
| MCP integration | Expose repository intelligence to AI clients | Planned |
| DeepSeek Harness plugin | Native DSH tools, configuration, lifecycle, and distribution | Planned |
| Incremental indexing | Keep the index synchronized with Git changes | Planned |
| Explorer UI | Browse graph and source evidence interactively | Planned |

## Architecture (target)

```text
Repository
   |
   v
Discovery & Ignore Policy
   |
   v
Language Detection -> Parser Adapters
   |                      |
   +----------------------+
              |
              v
      Canonical Code Model
       /       |        \
      v        v         v
  Symbol DB  Relation   Source
             Graph      Evidence
       \       |        /
        v      v       v
        Ranking & Retrieval
                 |
        +--------+---------+
        |        |         |
       CLI     Reports    MCP
                         DSH Plugin
```

The canonical model separates **facts** (parser-derived declarations and imports), **inferences** (heuristic relationships and ranking), and **rendered views** (maps, reports, and context packs). This distinction is essential for trustworthy results.

## Repository layout

```text
src/codebase_intelligence/
  scanner/       # file discovery and ignore policy
  parsers/       # language-specific parser adapters
  model/         # canonical entities and relationships
  graph/         # graph construction and queries
  indexing/      # persistence and incremental updates
  retrieval/     # task-aware context selection
  reporting/     # Markdown and JSON renderers
  mcp/           # MCP server integration
integrations/
  deepseek-harness/ # native DSH plugin adapter and packaging
tests/
docs/
examples/
```

## Quick start

The implementation is under active design. Installation and CLI commands will be documented once the first executable MVP is merged. See [the roadmap](docs/ROADMAP.md) and [the architecture](docs/ARCHITECTURE.md).

## Principles and boundaries

- An index is a navigational aid, **not a substitute for reading source code** before making changes.
- A dependency edge must record its origin and confidence; unresolved edges must not be presented as certain.
- Token estimates are estimates and should identify the tokenizer or approximation used.
- The tool must not upload repository contents to external services by default.
- Public documentation and examples must not contain private source code, credentials, customer data, or internal project details.

## Research references

See [RESEARCH.md](docs/RESEARCH.md) for the initial landscape and the distinction between adjacent tools and the proposed system. See [the DeepSeek Harness integration](integrations/deepseek-harness/README.md) for the native plugin workstream.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before opening a pull request.

## License

License selection is intentionally pending. No license has been granted yet; until one is added, standard copyright restrictions apply.
