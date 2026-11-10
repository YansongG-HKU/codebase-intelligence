# Scanner policy

Status: implemented in `src/codebase_intelligence/scanner/`. This document is the
human-readable contract for repository discovery; `docs/SPEC.md` §5 is the
normative one. If the two disagree, that is a bug in one of them.

The scanner turns a repository directory into a deterministic tuple of
`FileRecord` facts (path, language, byte size, sha256, line count) plus bounded
diagnostics. It reads bytes only: it never imports, evaluates or executes
scanned code, never writes to the repository, and never reads outside the
resolved repository root.

## API

```python
from codebase_intelligence.scanner import (
    ScanPolicy, ScanResult, default_policy, detect_language,
    policy_fingerprint, scan_repository,
)

result = scan_repository(root, default_policy())
result.files                 # tuple[FileRecord, ...] sorted by repo-relative path
result.paths()               # same order, just the path strings
result.stats                 # ScanStats: files/bytes/directories + sorted skip counters
result.policy_fingerprint    # sha256 over policy + consulted .gitignore digests
result.to_dict()             # deterministic payload; excludes the absolute root
```

`scan_repository()` raises `RepositoryError` (`code="not_a_directory"`) when the
root is missing or not a directory. Everything else (unreadable file, unreadable
`.gitignore`, broken symlink, race between `stat` and `open`) is counted in
`ScanStats.skipped` and scanning continues.

## Defaults

`default_policy()` returns `ScanPolicy()`:

| Field | Default | Meaning |
|---|---|---|
| `max_file_bytes` | `1048576` (1 MiB) | Files strictly larger are skipped and counted. |
| `follow_symlinks` | `False` | Symlinks are skipped and counted. |
| `use_gitignore` | `True` | Root and nested `.gitignore` files are honored. |
| `include_hidden` | `False` | Dot-files and dot-directories are skipped (`hidden`). |
| `index_dir_name` | `".codebase-intelligence"` | Cache directory; skipped anywhere in the tree. |
| `extra_excludes` | `()` | Caller-supplied ignore globs (CLI `--exclude`); absolute, independent of `.gitignore` negation. |
| `default_excludes` | VCS/venv/build/cache dir names | Directory names skipped at any depth. |
| `excluded_paths` | `("docs/codebase-intelligence",)` | Exact repo-relative directories skipped (the `cbi export` generation directory). |
| `secret_patterns` | conservative filename globs | Likely-secret files are skipped and counted. |

`default_excludes`, in order: `.git`, `.hg`, `.svn`, `.venv`, `venv`,
`node_modules`, `__pycache__`, `build`, `dist`, `target`, `vendor`,
`.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `coverage`, `.idea`, `.vscode`.
These are **directory names** matched at any depth (a regular file named
`build` is not excluded).

`excluded_paths` are **repo-relative directory paths**, not names: an exact
match (or a path below it) is pruned, so the default entry skips
`docs/codebase-intelligence/` (where `cbi export` writes its deterministic
artifact bundle) while an unrelated `src/codebase-intelligence/` or
`foo/codebase-intelligence/` stays indexed. Entries are normalized in
`ScanPolicy.__post_init__` (`/` separators, no `.`/`..` segments, sorted and
de-duplicated); absolute paths and `..` escapes raise `ValueError` instead of
being repaired. Set `excluded_paths=()` to index the generation directory.

`secret_patterns`, matched case-insensitively against the basename only:
`*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `.env`, `.env.*`,
`.npmrc`, `.netrc`, `credentials*`, `secrets*`, `*.kdbx`.

Policies are frozen dataclasses: build variants with
`default_policy(max_file_bytes=4096, include_hidden=True)` (unknown field names
raise `ValueError`; `ScanPolicy` is hashable and safe to share). `to_dict()` /
`ScanPolicy.from_dict()` are available for serialization; the JSON keys are
camelCase (`maxFileBytes`, `followSymlinks`, `useGitignore`, `includeHidden`,
`indexDirName`, `extraExcludes`, `defaultExcludes`, `excludedPaths`,
`secretPatterns`).

## Skip precedence

Each directory entry is classified once. The first matching rule wins, which
also defines the `ScanStats.skipped` bucket the entry lands in:

| # | Check | Skip reason |
|---|---|---|
| 1 | Symlink (unless `follow_symlinks=True`) | `symlink` |
| 2 | Directory path in `excluded_paths` | `generated-dir` |
| 3 | Directory name in `default_excludes` | `default-exclude` |
| 4 | Directory name equals `index_dir_name` | `index-dir` |
| 5 | Hidden name (dot prefix) and `include_hidden=False` | `hidden` |
| 6 | Matches an `extra_excludes` glob (CLI `--exclude`) | `extra-exclude` |
| 7 | Ignored by the active `.gitignore` matcher | `gitignore` |
| 8 | File basename matches `secret_patterns` | `secret` |
| 9 | Candidate resolves outside the root | `path-escape` |
| 10 | Size greater than `max_file_bytes` | `oversize` |
| 11 | NUL byte in the first 8 KiB | `binary` |
| 12 | `OSError` while stat'ing/opening/reading | `unreadable` |
| 13 | Directory already visited via a symlink/junction | `cycle` |
| 14 | Entry is a FIFO/socket/device/other special file | `unsupported-entry` |
| — | Symlink target missing / unreadable | `symlink-broken` |
| — | Followed symlink resolves outside the root | `symlink-escape` |

`hidden` is a dot-prefix convention only; platform-specific hidden attributes
are not consulted (deterministic across platforms). The scanner still *reads* a
root or nested `.gitignore` when `use_gitignore=True` even though the file
itself is hidden and therefore not indexed by default.

## `.gitignore` subset

The matcher implements a documented subset of git's `wildmatch`; it is not a
full git implementation.

Supported:

- root and nested `.gitignore` files, evaluated relative to the directory that
  contains them; rules from ancestor files apply first, deeper files last;
- blank lines and `#` comments (a backslash escapes them: `\#`, `\!`);
- `!` negation — last matching rule wins, including across nested files;
- trailing `/` restricts the rule to directories (`build/` ignores the
  directory named `build` anywhere);
- any other `/`, or a leading `/`, anchors the rule to the ignore file's
  directory (`/root-only.txt` does not match `sub/root-only.txt`);
- `*` and `?` never cross `/`; character classes with ranges and negation
  (`data[0-9].bin`, `data[!0-9].bin`, `*.py[co]`);
- `**` as a whole path segment: `**/cache/` (any depth), `a/**/b` (zero or more
  directories), `a/**` (everything inside `a`, not `a` itself);
- unescaped trailing spaces are stripped; a backslash-escaped trailing space is
  literal; backslash escapes any special character.

Deliberate semantics that match git:

- a path whose parent directory is excluded cannot be re-included — the walker
  prunes ignored directories, so `!blocked/include-me.py` after `blocked/` has
  no effect;
- `.gitignore` files inside an ignored directory are never read;
- rules are case-sensitive on every platform (git's `core.ignoreCase` behaviour
  is not emulated).

Not supported (honest limitations): `core.excludesFile` / global gitignore,
`.git/info/exclude`, `.gitignore` from a parent directory outside the scanned
root, `.gitmodules`/submodule handling, POSIX character classes such as
`[[:alpha:]]`, `{a,b}` brace expansion, and escaped trailing-slash edge cases.
Patterns are matched against repo-relative POSIX paths.

Example:

```gitignore
# build output
build/
dist/
**/cache/
*.log
!keep.log            # re-included (last match wins)
/root-only.txt       # anchored to the repository root
temp-?.txt           # exactly one character before ".txt"
data[0-9].bin        # character class
blocked/
!blocked/keep.py     # NO EFFECT: blocked/ is pruned before it is evaluated
```

## Extra excludes (`--exclude`)

Callers may add ignore globs the repository itself does not declare, for example
`cbi scan . --exclude "*.tmp" --exclude "private/"`. They are modelled as the
`extra_excludes` policy tuple and are absolute excludes: `.gitignore` `!`
negation cannot re-include a path matched by them (they are evaluated before the
gitignore matcher; matched entries are counted as `extra-exclude`).

- a pattern without `/` matches the basename at any depth (`*.log`, `cache`);
- a pattern containing `/` matches the whole repo-relative path
  (`docs/generated/*`, `src/vendor/`); `*` then spans `/` as in `fnmatch`;
- a trailing `/` restricts the pattern to directories (`cache/` prunes the
  directory, it does not hide a file named `cache`);
- backslashes are normalized to `/`; matching is case-sensitive on every
  platform.

These are Python `fnmatch` globs, not gitignore wildmatch: `**` has no special
meaning and a character class such as `[0-9]` is supported only as `fnmatch`
supports it. Use `.gitignore` for git-compatible patterns. `extra_excludes` is
part of the policy fingerprint, so changing it invalidates the index cache.

## Secret filtering and the explicit override

Secret-named files never enter the index by default: they are skipped
(`secret`) and counted. Matching is case-insensitive on the basename
(`SERVER.PEM` matches `*.pem`).

The only override is the environment variable `CBI_INCLUDE_SECRETS=1`
(truthy values: `1`, `true`, `yes`, `on`, case-insensitive). It is explicit by
design — no policy field silently disables secret filtering — and it is read by
`scan_repository()` at scan time, so every process must opt in independently.
Hidden files still require `include_hidden=True`:

```bash
CBI_INCLUDE_SECRETS=1 python -m codebase_intelligence.cli scan . --json   # non-hidden secrets included
CBI_INCLUDE_SECRETS=1 ... # plus include_hidden=True to also see .env/.npmrc
```

Limitation: this is a filename heuristic, not content detection. A secret in
`config.py` or `notes.txt` is indexed; a PEM in `cert.txt` (not matching a
pattern) is indexed. `secret_patterns` can be overridden per policy.

## Security model

- The root is resolved with `Path.resolve(strict=True)` and must be a directory.
- Symlinks are skipped and counted by default. With `follow_symlinks=True` the
  resolved target must still be inside the resolved root (`util.is_within`);
  escaping links are counted as `symlink-escape` and never read.
- Every candidate file is resolved and re-checked against the root before it is
  opened; directories are checked before descending. Windows junctions are
  followed by `resolve()` and therefore caught by the same containment check
  (`path-escape`).
- Symlinked `.gitignore` files are subject to the same rules: a link pointing
  outside the root is never read, so ignore rules cannot be smuggled in from
  outside the repository.
- Cycles in followed directory links are detected via resolved-path keys
  (`cycle`) so a scan always terminates; a linked directory is walked at most
  once (the first path encountered in sorted order wins, which keeps output
  deterministic).
- Files are read once: an 8 KiB head for binary detection, then streaming
  sha256 and line counting. `line_count` counts `\n` plus a final unterminated
  line (`""` → 0, `"a\nb"` → 2, `"a\nb\n"` → 2, `"a\r\nb\r\n"` → 2).
- Only the first 8 KiB are inspected for NUL bytes; a NUL byte later in a file
  is treated as text (documented trade-off between cost and completeness).
- Unreadable entries and ignore files are counted, never fatal.

## Determinism

Same repository content + same policy + same engine version ⇒ byte-identical
`ScanResult.to_dict()` and identical `policy_fingerprint`:

- `files` are sorted by repo-relative POSIX `path` (`/` separators, never
  absolute, never `..`);
- skip counters are sorted by reason; only non-zero buckets are reported;
- no timestamps, durations, host names, absolute paths, environment values or
  process data are serialized (`ScanResult.to_dict()` explicitly omits `root`);
- `policy_fingerprint` = `sha256(canonical_json({policy, ignoreFiles}))` where
  `ignoreFiles` is the sorted list of `{path, sha256}` for every `.gitignore`
  actually consulted. The absolute root is not hashed, so scanning the same
  tree from a different checkout directory yields the same fingerprint. A
  changed `.gitignore` changes the fingerprint even if the included files did
  not change, which forces the index cache to rebuild. If `use_gitignore` is
  `False`, no ignore digests are part of the fingerprint.

`ScanStats` is diagnostics only: it never appears in model-facing tool payloads
(see `docs/SPEC.md` §3). `directories_visited` includes the root and counts
directories actually descended into (ignored directories are pruned and not
counted as visited).

## Language detection

`detect_language(path)` is a conservative extension table (see
`scanner/discovery.py`), not a content classifier; unknown extensions and
extension-less names map to `Language.OTHER`. Ambiguous choices are documented:
`.h` → C, `.scss`/`.sass`/`.less` → CSS, `.jsonc`/`.jsonl` → JSON,
`.mdx` → Markdown; Ruby/shell special names (`Rakefile`, `Gemfile`,
`.bashrc`, ...) are recognized. Windows path separators are accepted.

## Known limitations

- No git index integration: untracked files are scanned unless ignored by a
  `.gitignore` file; ignored files are not distinguished as tracked/untracked.
- Hidden = dot prefix only (see above).
- Ignore files larger than `max_file_bytes` are truncated when read (their
  digest covers the truncated bytes).
- `.gitignore` in a hidden directory is not read when `include_hidden=False`
  because the directory is pruned first (git behaves differently only for
  explicitly added hidden paths).
- Symlink-following mode can index the same content under two paths (the link
  and, if visited first, only once); this is documented instead of deduplicated
  so the result stays deterministic.
- Text encoding is not validated: non-UTF-8 but NUL-free files are indexed
  with a byte-level sha256 and line count; parser adapters handle decoding
  errors later.
- Pathological `.gitignore` patterns are compiled to regular expressions; a
  pathological repository-controlled pattern can be slower than native git.
  Scans stay bounded by `max_file_bytes` and by the root boundary.
