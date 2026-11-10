# Export: deterministic repository artifacts

Status: implemented in `src/codebase_intelligence/export.py` and exposed as
`cbi export`. Normative sources: `integrations/deepseek-harness/plugin/PANEL_CONTRACT.md`
§1/§2 (file set and CLI payload) and `docs/SPEC.md` §3/§4/§10/§11 (determinism,
budgets, reporting, CLI). This document is the operator-facing description.

`cbi export` renders one fixed, repository-local documentation snapshot from a
**single** index build and writes it into a generation directory. The DSH
right-sidebar panel calls the same command (`--check` for a preview, a normal
run for the write) over the host bridge, so the panel never owns a second
renderer and the CLI, the MCP server and the panel stay consistent.

```bash
cbi export [root] --out docs/codebase-intelligence [--json] [--check]
           [--cache-dir DIR] [--force] [--max-file-bytes N] [--exclude GLOB]...
```

`root` defaults to `.`; `--out` is always **repository-relative** and defaults
to `docs/codebase-intelligence`. `--max-file-bytes`, `--exclude` and
`--include-hidden` affect the one index build only.

## Generated file set

| File | Content | Budget / bound |
|---|---|---|
| `overview.json` | `reporting.overview_payload` — counts, languages, top directories, entry points | 2000 estimated tokens |
| `repo-map.json` | `reporting.map_payload` — ranked files with bounded symbol lists | 4000 estimated tokens |
| `ARCHITECTURE.generated.md` | `reporting.markdown_report` — architecture report with `path:line` citations | 16 000 chars |
| `REPO_MAP.md` | `reporting.markdown_map` — compact structural map | 12 000 chars |
| `dependencies.mmd` | Mermaid `graph LR` over **resolved** import edges between indexed files | ≤ 400 edges |
| `CONTEXT_BRIEF.md` | Orientation brief: snapshot identity, language mix, entry points, top modules by resolved in-degree, files with the most declarations, how to query, limitations | bounded sections |
| `manifest.json` | `{schemaVersion, engineVersion, policyFingerprint, fingerprint, outDir, files[{path, bytes, sha256}]}` for the six files above | written last |

Every path inside a generated file is a repository-relative POSIX path
(`/` separators, never absolute, never `..`). `manifest.json` is written last
and lists every other generated file (not itself); `manifestFingerprint` in the
CLI payload is the sha256 of the manifest bytes.

`dependencies.mmd` renders only `resolved` `imports` relations whose source and
target are both indexed files. Unresolved/ambiguous/external edges are never
drawn as dependencies; their count appears in one header comment. Nodes are
labelled with repository-relative paths (quoted and HTML-escaped), numbered in
sorted path order, and the header carries the index fingerprint.

## Determinism

Two runs over unchanged repository content with the same flags produce
byte-identical files:

- the index is built **once** with `indexing.ensure_index` and every artifact is
  rendered from that one snapshot (no per-file re-indexing, no drift between
  JSON and Markdown);
- JSON is canonical (`util.canonical_json`: sorted keys, no insignificant
  whitespace) plus exactly one trailing newline; Markdown/Mermaid are UTF-8 with
  LF line endings;
- every list has an explicit total order (sorted paths/names, sorted edges,
  sorted manifest entries, node ids in sorted path order);
- no timestamps, durations, host names, absolute paths, environment values,
  process ids, cache counters or random ids are rendered.

`--check` builds the index exactly like a write run (using the cache where
possible), renders the same bytes and compares them with the files on disk.

## `--check` and exit codes

`--check` writes nothing (it does not even create the generation directory) and
reports the per-file plan: `created`, `updated` or `unchanged`.

| Exit | Meaning |
|---|---|
| `0` | Success; with `--check`: all seven files exist with identical bytes |
| `1` | `--check` only: something is missing or stale |
| `2` | Usage error (bad path, bad flag, unknown arguments) |
| `3` | Repository/index error (missing root, unwritable target, symlink escape) |
| `4` | Internal error |

`--json` prints exactly one canonical JSON object plus a newline, in both modes:

```json
{"ok": true, "schemaVersion": "1", "command": "export", "check": false,
 "outDir": "docs/codebase-intelligence",
 "index": {"schemaVersion": "1", "engineVersion": "0.1.0",
           "policyFingerprint": "…", "fingerprint": "…"},
 "files": [{"path": "docs/codebase-intelligence/overview.json",
            "status": "created", "bytes": 0, "sha256": "…"}],
 "manifestFingerprint": "…", "stale": false}
```

`stale` is `true` only when the bundle on disk differs from the freshly rendered
bundle at the end of the command: in `--check` that is the pass/fail signal; a
successful write always returns `false`. Errors use the shared envelope
(`{"ok": false, "error": {"code", "message"}}`).

## Write safety

- `--out` must stay inside the resolved workspace root. Absolute paths, `..`
  segments, drive letters, control characters and symlinked path components are
  refused (`invalid_arguments` / `outside_root`); the resolved directory is
  re-checked for containment before anything is written.
- Only the seven fixed file names are ever written below `outDir`; nothing is
  ever deleted, renamed or written elsewhere. Other files in the generation
  directory (for example an operator note) are left alone.
- Writes are atomic: each changed file goes to a `mkstemp` temporary file in
  the same directory and is moved into place with `os.replace`. Unchanged files
  are not opened for writing at all, so their mtime is preserved.
- A target that is a directory, a symlink or another non-regular file is
  reported as an error instead of being overwritten.
- `--check` never writes and never creates the generation directory.

## Generation-directory exclusion

`docs/codebase-intelligence` is the export generation directory and is part of
the default scan policy as an exact repo-relative path
(`ScanPolicy.excluded_paths`, skip reason `generated-dir` in
`src/codebase_intelligence/scanner/discovery.py`). It is therefore absent from
`cbi scan`, `cbi index`, `cbi overview` and the `overview`/`map` tool payloads
without any extra flag, and a second export cannot index the files the first
export wrote. Unlike a bare basename exclude, an unrelated
`src/codebase-intelligence/` package stays indexed.

For a custom `--out` path, the export adds that directory to its **own** index
build's excludes, so repeated exports stay deterministic; plain `cbi scan`
commands do not know about the custom path (add `--exclude "<dir>/"` there if
you want the same behaviour). See `docs/SCANNER_POLICY.md` for the policy field
and its precedence.

## Library API

```python
from codebase_intelligence import export

result = export.build_export(
    repo_root,
    out="docs/codebase-intelligence",  # repository-relative
    cache_dir=cache_dir,               # avoids writing inside the repository
    check=True,                        # preview only
)
result.to_payload()          # exact CLI/panel JSON payload
result.files                 # ExportFile(path, status, bytes, sha256)
result.index                 # {schemaVersion, engineVersion, policyFingerprint, fingerprint}
result.manifest_fingerprint  # sha256 of manifest.json bytes
result.stale                 # bool
```

Renderers are pure and reusable: `render_bundle`, `render_context_brief` and
`render_dependencies_mermaid` take an `IndexSnapshot` (plus a graph for the
report payloads) and return bytes/text for tests and other hosts.

## Limitations

- Structural view only: declarations and edges, not behaviour; heuristic
  (regex-adapter) symbols and relations are labelled and may be incomplete.
- The JSON artifacts are budgeted like every tool payload, so very large
  repositories are represented by truncated, explicitly-marked rows rather
  than a complete dump.
- `dependencies.mmd` is bounded to 400 edges and omits unresolved/external
  edges by design; the JSON reports keep the full relation set.
- The snapshot is only as fresh as the last export; the panel preview
  (`--check`) is what tells you whether a refresh is needed.
- The command never stages, commits or pushes git changes; committing the
  generated directory is an operator decision.
- Symlink-refusal tests are skipped where the platform forbids symlink
  creation (for example unprivileged Windows).
