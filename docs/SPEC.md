# Engine & Integration Contract (v1)

Status: normative for the current implementation. Code and tests are expected to
conform to this document; when this document and code disagree, the bug is in one
of them, not a reason to ignore the contract.

This contract is the shared source of truth for parallel work. Owners may not
edit another owner's section without telling the Lead.

## 0. Scope of this delivery

Deliver, in this repository:

1. A local-first Python engine (`src/codebase_intelligence/`) that turns a
   repository into a canonical, evidence-linked structural model, persists it as
   a deterministic JSON index, and answers structural questions with explicit
   token budgets.
2. A CLI (`cbi`), a stdio MCP server, and Markdown/JSON reporting.
3. A first-party DeepSeek Harness plugin (`integrations/deepseek-harness/plugin`)
   that exposes six read-only tools to agents through a versioned JSON stdio
   bridge to the same engine. No duplicated parser/graph/ranking logic.
4. Tests, benchmarks, docs, and a real isolated-DSH acceptance run.

Non-goals: executing scanned code, uploading repository content, editing files,
IDE/language-server replacement, graph databases, a standalone desktop web
explorer outside the DSH panel.

## 1. Ownership (write scopes)

| Owner | Paths |
|---|---|
| lead | `docs/SPEC.md`, `src/codebase_intelligence/{__init__,cli,errors,util}.py`, `model/**`, `mcp/**`, `tests/test_cli.py`, `tests/test_mcp.py`, `tests/fixtures/cli/**`, `README.md`, `ROADMAP.md`, `docs/{SPEC,TOKENS,DELIVERY}.md`, root `pyproject.toml`, CI |
| scanner | `src/codebase_intelligence/scanner/**`, `tests/test_scanner.py`, `tests/test_model.py`, `tests/fixtures/scanner/**`, `docs/SCANNER_POLICY.md` |
| parser | `src/codebase_intelligence/{parsers,graph,indexing}/**`, `tests/test_{parser,graph,indexing}.py`, `tests/fixtures/parser/**` |
| retrieval | `src/codebase_intelligence/{retrieval,reporting}/**`, `tests/test_{retrieval,reporting}.py`, `tests/fixtures/retrieval/**` |
| plugin | `integrations/deepseek-harness/**` (including `plugin/**` and `docs/DSH_PLUGIN.md`), `tests/fixtures/plugin/**` |
| lead (cont.) | `src/codebase_intelligence/{api,cli}.py`, `mcp/**`, `docs/{TOKENS,DELIVERY,BENCHMARKS}.md` |

Nobody commits or pushes. The Lead integrates, verifies and reports.

## 2. Canonical model (implemented in `model/entities.py`)

Read that module first; it is code, not prose. Frozen dataclasses:

- `Language`, `SymbolKind`, `RelationType`, `EvidenceKind`, `ResolutionStatus`.
- `SourceSpan(path, start_line, end_line, start_column, end_column)` — 1-based lines.
- `FileRecord(path, language, size_bytes, sha256, line_count)` — repo-relative POSIX path.
- `SymbolRecord(id, path, name, qualified_name, kind, language, span, parent_id, signature, doc, evidence)`.
- `RelationRecord(source_id, relation_type, status, evidence, target_id, target_name, span, confidence)`.
- `ParseIssue(path, message)` — bounded, honest parser failure record.
- `ScanStats`, `CacheStats` — diagnostics only, never serialized into tool payloads.
- `IndexSnapshot(schema_version, engine_version, policy_fingerprint, files, symbols, relations, parse_issues, root)`
  with `.build(...)` (normalizes ordering), `.index_maps()`, `.public_dict()`,
  `.fingerprint()` and `.from_public_dict()`.

Stable ids: `file_id(path) == "file:<path>"`,
`symbol_id(path, kind, qualified_name, start_line) == "sym:<path>#<kind>:<qualifier>@<line>"`.
Paths are always repository-relative and POSIX (`/`), never absolute, never `..`.

Evidence rules:

- Syntax-tree extraction → `EvidenceKind.PARSER`.
- Import resolution → `EvidenceKind.RESOLVER` + `ResolutionStatus.RESOLVED|EXTERNAL|UNRESOLVED|AMBIGUOUS`.
- Regex fallback extraction → `EvidenceKind.HEURISTIC`.
- An unresolved or ambiguous edge keeps `target_id = None` (or the best candidate)
  and is never reported as a confirmed dependency.

## 3. Determinism contract (hard rule)

Every payload that reaches a user, a test snapshot or a model must be byte-stable
for the same repository content + same policy + same engine version:

1. Sort files by `path`; symbols by `(path, startLine, kind, qualifiedName)`;
   relations by `(sourceId, type, targetId, targetName, startLine)`; every derived
   list has an explicit total order (ties broken by path/id/name).
2. No timestamps, durations, wall-clock values, random ids, host names, absolute
   paths, environment values, process/pid, cache-hit flags or "generated at".
   Timing/diagnostics may appear only behind an explicit CLI flag (`--timings`,
   `--diagnostics`) and never in MCP/DSH tool payloads.
3. JSON is canonical: sorted keys, UTF-8, `(",", ":")` separators, one trailing
   newline on the CLI/stdout protocol.
4. Floating scores are rounded to at most 4 decimals.
5. `IndexSnapshot.fingerprint()` is the cache key: identical model ⇒ identical
   fingerprint; tool output includes it so repeated calls are visibly identical.

## 4. Token estimation and budgets

- `util.estimate_tokens(text)` implements `chars4-wide-v1`: every 4 ASCII chars
  count as 1 token, every non-ASCII char as 1 token, minimum 1 for non-empty
  input. It is an estimate, not a tokenizer; every budgeted payload reports
  `tokenEstimator: "chars4-wide-v1"` and `tokensEstimated`.
- Budget is a first-class input: every model-facing operation takes `maxTokens`
  (clamped to documented ranges) and must return the largest useful result that
  fits, plus explicit `omitted`/`truncated` metadata.
- Tool defaults: overview 900, map 1600, search 1200, dependencies 1200,
  context 2200, impact 1200. Hard cap per tool: 8000.
- A budgeted payload is built, measured with `estimate_tokens(canonical_json(payload))`,
  and shrunk until it fits. Never truncate mid-JSON: drop whole rows/excerpts.

## 5. Scanner (`scanner/`)

`ScanPolicy` (frozen dataclass) fields with defaults:

- `max_file_bytes = 1_048_576` (1 MiB), `follow_symlinks = False`,
  `use_gitignore = True`, `include_hidden = False`, `index_dir_name = ".codebase-intelligence"`.
- `default_excludes`: VCS/venv/build/cache dirs (`.git`, `.hg`, `.svn`, `.venv`,
  `venv`, `node_modules`, `__pycache__`, `build`, `dist`, `target`, `vendor`,
  `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `coverage`, `.idea`, `.vscode`).
- `secret_patterns`: conservative file-name globs (`*.pem`, `*.key`, `*.p12`,
  `*.pfx`, `id_rsa*`, `id_ed25519*`, `.env`, `.env.*`, `.npmrc`, `.netrc`,
  `credentials*`, `secrets*`, `*.kdbx`). Secret hits are skipped and counted;
  they never enter the index. A documented override (`CBI_INCLUDE_SECRETS=1`)
  is allowed but must be explicit and tested.
- `extra_excludes = ()`: additive CLI/tool globs (repeatable `--exclude`), matched
  case-sensitively against the basename, or against the repo-relative POSIX path
  when the pattern contains `/`; a trailing `/` matches directories only. Extra
  excludes are evaluated before `.gitignore`, are counted under skip reason
  `extra-exclude`, and are included in the policy fingerprint. They are additive:
  they cannot be negated by `.gitignore` `!` rules.
- `excluded_paths = ("docs/codebase-intelligence",)`: repository-relative POSIX
  directory prefixes that are never scanned (the deterministic export generation
  directory). Only the exact path/prefix is pruned (counted as `generated-dir`);
  unrelated directories with the same basename stay indexed. Included in the
  policy fingerprint (`excludedPaths` in `to_dict`); custom `--out` directories
  are excluded for the export's own index build and should be passed via
  `--exclude` for other commands. See [EXPORT.md](EXPORT.md).
- `.gitignore` semantics: root and nested `.gitignore` files, blank/`#` lines,
  `!` negation, trailing `/` dir-only, `/` anchoring, `**`, `*`, `?`, character
  classes, last-match-wins, parent-excluded directories not re-included.
  Document known limitations honestly in `docs/SCANNER_POLICY.md`.

Interfaces:

```python
def detect_language(path: str) -> Language
def default_policy(**overrides) -> ScanPolicy
def scan_repository(root: Path, policy: ScanPolicy | None = None) -> ScanResult
@dataclass(frozen=True) class ScanResult:
    root: Path
    files: tuple[FileRecord, ...]       # sorted by path
    stats: ScanStats                     # directories visited, skip reasons
    policy_fingerprint: str              # sha256(canonical policy + ignore digests)
```

Security: resolve the root with `strict=True`; every candidate must stay inside
it (`util.is_within`); symlinks are skipped by default and counted; oversized or
binary (NUL in first 8 KiB) files are skipped and counted; unreadable entries are
counted, never fatal.

## 6. Parsers (`parsers/`)

```python
# parsers/__init__.py
PARSER_VERSIONS: dict[Language, str]        # e.g. {"python": "ast-v1", ...}
def parser_versions_digest() -> str          # sha256(canonical_json(PARSER_VERSIONS))
def parse_file(file: FileRecord, text: str) -> ParseResult

@dataclass(frozen=True)
class ParseResult:
    symbols: tuple[SymbolRecord, ...]
    relations: tuple[RelationRecord, ...]
    issues: tuple[ParseIssue, ...]
```

- Python: standard-library `ast` adapter — module/class/function/method
  declarations, imports (`import`, `from ... import`, relative levels), class
  bases (inherits), calls resolved only when the callee is unambiguous in the
  same file (heuristic label), constants/variables at module/class level.
  Syntax errors → `ParseIssue`, never an exception.
- Heuristic adapters (regex, `EvidenceKind.HEURISTIC`): JavaScript, TypeScript,
  Go, Rust, Java, C/C++, C#, Ruby, PHP, Shell. Extract declarations and imports
  with documented limitations. No regex may crash on malformed input.
- Other languages: empty `ParseResult` with no issues (they are indexed as files
  only). Binary/oversize never reaches parsers.

## 7. Graph and import resolution (`graph/`)

`parsers` emits raw `IMPORTS` relations with `target_name`; `graph` resolves them
to file ids where safe:

- Python: dotted module → `<root>/a/b.py` or `<root>/a/b/__init__.py`; relative
  imports (`from .x`, `from ..pkg.y`) based on the importing file's package.
- JS/TS: `./x` and `../x` → `.js/.ts/.tsx/.jsx/index.*`; bare specifiers →
  `EXTERNAL`; Go: package paths → directory files (external if no local dir).
- Unresolvable stays `UNRESOLVED` with the raw target name; ambiguous (two
  candidates) → `AMBIGUOUS` and no target id.

```python
class Graph:
    def __init__(self, snapshot: IndexSnapshot) -> None
    def file_imports(self, path: str) -> tuple[str, ...]
    def file_dependents(self, path: str) -> tuple[str, ...]
    def transitive_dependents(self, path: str, *, max_depth: int = 10) -> tuple[tuple[str, int], ...]
    def symbol_neighborhood(self, symbol_id: str, *, depth: int = 1) -> tuple[dict, ...]
    def impact(self, *, files=(), symbols=(), max_results: int = 200) -> ImpactResult

@dataclass(frozen=True) class ImpactEntry:
    path: str; distance: int; confidence: str; reason: str
@dataclass(frozen=True) class ImpactSymbolEntry:
    id: str; path: str; name: str; distance: int; confidence: str
@dataclass(frozen=True) class ImpactResult:
    changed_files: tuple[str, ...]
    changed_symbols: tuple[str, ...]
    affected_files: tuple[ImpactEntry, ...]
    affected_symbols: tuple[ImpactSymbolEntry, ...]
    truncated: bool = False
```

Impact is conservative: resolved reverse file dependencies and same-file/imported
symbol references only. Each affected entry carries `confidence`
(`high` = parser/resolver fact, `medium` = heuristic call/base edge,
`low` = name coincidence) and a reason; never invent edges to look useful.

## 8. Indexing and cache (`indexing/`)

```python
def ensure_index(root: Path, policy=None, *, cache_dir: Path | None = None,
                 force: bool = False) -> IndexResult
@dataclass(frozen=True) class IndexResult:
    snapshot: IndexSnapshot
    cache: CacheStats
    index_path: Path
@dataclass(frozen=True) class CacheStats:  # already in model/entities.py
    files_reused: int; files_reparsed: int; files_removed: int; cache_hit: bool
```

- Default cache dir: `<root>/.codebase-intelligence` (gitignored by this repo's
  own `.gitignore`); the DSH plugin passes its own `cache_dir` under `DSH_HOME`
  so the user's repository is never written to.
- Files: `index.v1.json` (canonical `IndexSnapshot.public_dict()`),
  `cache.v1.json` (path → `{sizeBytes, mtimeNs, sha256, parserVersion}` plus the
  per-file `ParseResult` payload reused on cache hits), and an optional
  `serve.v1.json` sidecar containing a stat-only repository metadata stamp and
  the index identity. The sidecar enables fast serving; a missing or mismatched
  sidecar falls back to the normal incremental build, so it can never serve stale
  bytes on its own.
- Atomic writes only (temp file + `os.replace`).
- Invalidate everything when `schemaVersion`, `engineVersion`,
  `policyFingerprint` or `parser_versions_digest()` differ; otherwise reuse
  unchanged files (same size + mtime + sha256) and reparse only changed/new
  files; remove deleted files. Resolve imports during indexing; graph adjacency
  maps are built lazily on first structural query.
- `ensure_index` is deterministic: two runs on identical content produce
  identical `index.v1.json` bytes (fingerprint unchanged), even if the first run
  built and the second hit the cache. `load_served_index` may return the persisted
  snapshot without a scan when the stamp matches; it is private to `open_index`
  and always falls back to `ensure_index` on any uncertainty.
- Never execute code; treat file contents as untrusted.

## 9. Retrieval (`retrieval/`)

- `rank.py`: file/symbol scoring from (a) lexical match of the task/query over
  paths, symbol names, qualified names, signatures and docstrings; (b) symbol
  centrality (in-degree of resolved relations, normalized); (c) dependency
  proximity to explicitly named paths; (d) small bonus for entry points/modules;
  (e) file-level path coverage and documentation/config priors for paths that
  already match the query. Scores deterministic (round 4). Expose reason strings
  for ranking (bounded).
- `search(snapshot, graph, query, *, limit=20) -> tuple[SearchHit, ...]`: file
  candidates with documentation/config priority or multi-term path coverage are
  emitted in a bounded file window before the symbol stream; symbol rows are
  capped per path. This preserves symbol-first behavior for symbol-only queries
  while preventing one generated file from hiding named files.
- `budget.py`: `fit_rows(rows, measure, max_tokens) -> (kept, omitted_count)` and
  `estimate_tokens` re-export; never split a row.
- `context.py`:

```python
@dataclass(frozen=True) class ContextItem:
    path: str; start_line: int; end_line: int; kind: str; symbol: str | None
    reason: str; excerpt: str; tokens_estimated: int
@dataclass(frozen=True) class ContextPack:
    task: str; items: tuple[ContextItem, ...]; omitted: tuple[str, ...]
    tokens_estimated: int; token_estimator: str
def build_context(snapshot, graph, task: str, *, max_tokens: int = 2200,
                  path_prefix: str | None = None) -> ContextPack
```

Context selection: rank files/symbols, expand each hit into a bounded excerpt
(definition body, ≤120 lines, trimmed to fit), cite `path` + `startLine-endLine`,
drop lowest-ranked items until the measured payload fits, report omissions.

## 10. Reporting (`reporting/`)

Payload builders (all deterministic; all include the `budgets` block and never
runtime diagnostics):

```python
# reporting/__init__.py — exact integration signatures used by api.py
def overview_payload(snapshot, graph, *, max_tokens=900) -> dict
def map_payload(snapshot, graph, *, max_tokens=1600, focus=None) -> dict
def search_payload(snapshot, query, hits, *, max_tokens=1200) -> dict
def dependencies_payload(snapshot, graph, *, target, direction="both", depth=1, max_tokens=1200) -> dict
def context_payload(snapshot, pack: ContextPack, *, max_tokens=2200) -> dict
def impact_payload(snapshot, result, *, max_tokens=1200) -> dict
def markdown_map(snapshot) -> str
def markdown_report(snapshot, graph) -> str
```

`target` is already normalized to a repository-relative file path or a symbol id
(see `api._normalize_target`); report it back as `target{path}` or
`target{symbol}`. `SearchHit` and `ContextPack` are defined in `retrieval/`.
Every builder measures its own canonical JSON with `util.estimate_tokens` and
drops whole rows until the payload fits `max_tokens` (minimum useful payload is
allowed to exceed the budget only when a single row cannot fit; then it must say
so via `truncated:true`).

Payload shapes (fields may be omitted when empty, never renamed):

- `overview`: `ok, schemaVersion, command, index{schemaVersion,engineVersion,policyFingerprint,fingerprint}, repo{files,symbols,relations,languages[{language,files,symbols}],topDirectories[{path,files,symbols}]}, entryPoints[{path,symbol,kind,line}], parseIssues{count,sample[{path,message}]}, budgets{maxTokens,tokensEstimated,tokenEstimator}, truncated`
- `map`: `... index, focus, entries[{path,language,symbols[{name,kind,line,signature}]}], omitted{files,symbols}, budgets, truncated`
- `search`: `... index, query, total, results[{path,line,symbol,kind,language,score,match}], budgets, truncated`
- `dependencies`: `... index, target{path|symbol}, direction, nodes[{id,path,distance}], edges[{from,to,type,status,evidence}], budgets, truncated`
- `context`: `... index, task, items[{path,startLine,endLine,kind,symbol,reason,tokensEstimated,excerpt}], omitted[{path,reason}], budgets, truncated`
- `impact`: `... index, changed{files,symbols}, affectedFiles[{path,distance,confidence,reason}], affectedSymbols[{id,path,symbol,distance,confidence}], budgets, truncated`
- `graph`: `ok, fingerprint, snapshotSource{cache|repository|built|refreshed}, focus, relation, nodes[{id,label,kind,path,symbolKind?,line?,side?}], edges[{from,to,type,status,evidence,count,sites[{path,startLine,startColumn,endLine,endColumn}]}], breadcrumbs, totalNodes, offset, nextOffset, omittedEdges`; page is bounded to 80 nodes / 160 edges. `cbi graph --source PATH --line N` returns `ok, fingerprint, path, line, startLine, lines[]` after a hash + fingerprint check.

`markdown_map` / `markdown_report` are human-readable, bounded, cite paths+lines,
and state limitations (heuristic edges, unsupported languages).

## 11. CLI (`cli.py`)

`cbi <command> [root] [flags]`; `root` defaults to `.`. All commands accept
`--json` and `--cache-dir PATH`; `--timings`/`--diagnostics` opt into volatile
diagnostics. Errors: JSON envelope + exit code (2 usage, 3 repository/index,
4 internal). Commands:

`version`, `doctor`, `scan`, `index`, `overview`, `map`, `search`,
`dependencies`, `graph`, `context`, `impact`, `eval-retrieval`, `report`,
`export`, `mcp`.

`eval-retrieval` is a CLI-only quality gate: it reads a JSON task file of queries
and file-level relevance labels, compares the shipped ranker with path-only and
symbol-name baselines, and reports Recall@K/MRR@K/nDCG@K plus threshold checks.
It consumes no model tokens and is not part of the six model-facing tool schemas.
See [RETRIEVAL_EVAL.md](RETRIEVAL_EVAL.md).

Tool-facing commands (`overview`, `map`, `search`, `dependencies`, `context`,
`impact`) and the read-only `graph` command must be byte-stable for identical
repository content and flags, and must print exactly one canonical JSON object +
newline (no timing, no logs on stdout). Human-readable output is the default for
`scan`/`index`/`report`.
File-like arguments (`--files`, `--target`, `--focus`, `--path-prefix`) are
validated as repository-relative paths: absolute, drive-qualified, `~`-relative
or `..`-escaping values fail with `invalid_arguments` (exit 2).

## 12. MCP server (`mcp/server.py`)

`python -m codebase_intelligence.mcp` or `cbi mcp [root]`: newline-delimited
JSON-RPC 2.0 over stdio. Implement `initialize`, `notifications/initialized`,
`ping`, `tools/list`, `tools/call`; unknown methods return JSON-RPC errors.
Tools mirror the six DSH tools with the same names, schemas and payloads; the
workspace root comes from `--root`/`CBI_ROOT` (absolute, resolved, required).
Stdout carries protocol messages only; logs go to stderr; never read beyond root.

## 13. DeepSeek Harness plugin (`integrations/deepseek-harness/plugin/`)

Package `dsh-codebase-intelligence` (ESM, private, no runtime deps, `engines.dsh
>=0.2.2-rc.1`), bundle row through `cordis.patch.yml`, `inject: ['agents']`,
decorates every live/new agent (see `plugins/dsh-rea` for the proven pattern).

- Workspace root: `agent.session.header.cwd ?? agent.session.header.config.cwd ??
  agent.cwd`; fall back to `process.cwd()`. All tool paths resolve inside it.
- Six tools with the planned names: `codebase_overview`, `codebase_map`,
  `codebase_search`, `codebase_dependencies`, `codebase_context`,
  `codebase_impact`. Parameter schemas are small: shared `maxTokens`, focused
  args (`query`, `target`, `direction`, `depth`, `task`, `pathPrefix`, `files`,
  `symbols`, `focus`, `refresh`). No dynamic/defaulted values in schemas.
- Bridge: spawn the Python engine CLI (`python -m codebase_intelligence.cli ...`)
  with a resolved interpreter (config `pythonPath` → `CBI_PYTHON` →
  `DSH` managed runtimes → `python`/`python3`/`py -3`/common installs), UTF-8
  stdio, `windowsHide`, timeout (default 120 s), single JSON object response.
  Never write to the repository: pass `--cache-dir <dataDir>/indexes/<rootHash>`.
- Output: the engine JSON object itself is the tool value (`output.schema`
  object + `render` as one JSON text block). Add nothing volatile; on failure
  return `{ok:false, code, message, repair}`.
- Prompt section: one static string (≤120 words, no interpolation), registered
  per agent with `interpolate:false`; it describes when to call the tools, the
  read-only contract and that outputs are deterministic/cache-friendly.
- Cache: index cache lives under the plugin data dir; Node may memoize parsed
  payloads keyed by `(root, args, indexFingerprint)` but must never expose cache
  state in the value. Repeated identical calls must return identical bytes.
- Config row (`cordis.patch.yml`): `maxTokens` per tool, `pythonPath`,
  `dataDir`, `indexMaxFileBytes`, `tools` toggles, `promptSection` boolean.

## 14. Tests and acceptance

Per module: normal cases, edge cases, malformed input, determinism. Cross-cutting
acceptance (Lead):

1. `python -m pytest`, `python -m ruff check .` and `python -m mypy src` green.
2. Scanner: gitignore/negation/symlink/size/binary/secret/unicode/determinism.
3. Parser/graph/index: Python + heuristic fixtures, unresolved edges preserved,
   incremental rebuild after edit/delete, identical bytes on repeat.
4. Retrieval: budget respected, citations correct, ranking deterministic.
5. CLI: JSON envelope schema, exit codes, byte stability across two runs.
6. MCP: initialize/tools/list/tools/call round-trip over stdio.
7. Node tests (plugin): config, bridge (fake engine), tools, determinism,
   never-throw envelopes, workspace boundary.
8. Isolated DSH 0.2.2-rc.1 instance: plugin installs via bundle row + junction,
   `--dump-config` shows the row with clean stderr, GUI loads, a real model turn
   calls the tools, screenshot captured, graph explorer drilldown/source evidence
   renders, `--without-plugin` control run shows no tools.
9. Token/cache evidence: measured prompt-section + tool-schema token cost,
   representative tool outputs under budget, two identical calls byte-identical,
   second index build reports cache hits with no output change.
10. Docs updated: README capability matrix, ROADMAP only for verified items,
    `docs/SCANNER_POLICY.md`, `docs/DSH_PLUGIN.md`, `docs/EXPORT.md`,
    `docs/TOKENS.md`.
