# Research Landscape

This is an initial orientation document, not an exhaustive or final comparative study. Claims about upstream tools should be checked against their current documentation before implementation decisions.

## Adjacent projects and standards

### Aider — Repository Map
Aider's repository map is a strong reference for compact structural context: extract important code symbols and use relationships/ranking to fit a concise map into a model context. Study its ranking strategy, token budgeting, and task-conditioned inclusion.

### Repomix
Repomix packages repository content into model-friendly formats and provides useful ideas for filtering, output formats, token estimation, and integration. It is a complementary content-packaging approach rather than a complete substitute for a persistent semantic index.

### Tree-sitter
Tree-sitter provides incremental concrete syntax trees and broad language grammar support. It is a candidate parsing foundation, but grammar availability and extraction quality vary by language. Evaluate parser maturity and maintenance before adopting adapters.

### SCIP
SCIP is a code intelligence protocol/index format for representing symbol and relationship information across languages. Evaluate it as an interoperability input/output layer rather than assuming every repository already has complete SCIP indexes.

### Language Server Protocol (LSP)
LSP provides editor-oriented language intelligence such as definitions, references, and symbols. Existing language servers may provide higher-quality semantic resolution than custom static heuristics for supported languages.

### Model Context Protocol (MCP)
MCP is a standard interface for exposing tools and resources to AI clients. It is a delivery/integration layer, not the underlying code analysis engine.

## Proposed differentiation
- One canonical, evidence-linked model across parser adapters.
- Clear separation of syntax facts, semantic resolutions, and heuristic inferences.
- Explicit confidence and unresolved-edge handling.
- Task-aware context selection with measurable retrieval quality.
- Local-first operation and privacy-preserving defaults.
- Incremental refresh with reproducible snapshots.
- Interoperability with JSON, SCIP, and MCP where useful.

## Questions to validate
1. Which language should be the first fully supported language, based on representative user repositories?
2. Should Tree-sitter be the baseline parser, with language-server/SCIP enrichment as optional providers?
3. What ranking features outperform simple lexical search and graph centrality on real coding tasks?
4. What is the smallest useful graph schema that avoids false semantic precision?
5. How should token estimation behave across different model tokenizers?
6. How can incremental updates remain correct after renames, generated files, and configuration changes?

## Evaluation requirement
Benchmark against at least: raw directory listing, keyword search, repository packing, and a basic symbol map. Measure answer quality, retrieval relevance, latency, index size, and token consumption under fixed tasks and budgets.


## Production follow-up

Sourcegraph uses SCIP for precise navigation and search when a precise index
is unavailable. Evaluate an optional reader for **prebuilt local SCIP indexes**
against the existing resolver and lexical baseline. Compare definition and
reference precision on fixed tasks, preserve evidence provenance, and keep the
local engine usable when an index is absent or stale.
[Sourcegraph precise navigation](https://sourcegraph.com/docs/code-navigation/precise-code-navigation)

The current lexical implementation reuses Python's standard-library
`functools.cache` only within a query. On Windows with Python 3.13 and a synthetic
80-file, 6,480-symbol snapshot, path-score calls fell from 6,560 to 80 and median
ranking time from 289.57 to 221.43 ms (nine measured runs). The cache keeps no
repository state between queries. [Issue #11](https://github.com/YansongG-HKU/codebase-intelligence/issues/11)
