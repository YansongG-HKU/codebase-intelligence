# Clean-clone reproducibility acceptance

Date: 2026-11-11 (Windows 11, Python 3.13.13, Node 24.14.1, Git for Windows)
Scope: prove that a fresh clone of the current worktree can install and pass the
full test chain, then fix the two known clone-only failures (ignored fixtures and
line-ending drift) without touching the graph interaction logic, the always-on
token footprint (1373 estimated tokens) or the version (0.1.0).

## Constraints used in this verification

- The 57 pre-existing uncommitted graph/UI changes were preserved. This turn only
  adds `.gitattributes`, fixture files and the line-ending/snapshot normalization
  required by the fix.
- No commit was created in the delivery repository and nothing was pushed.
- To obtain a *clean clone of the fixed worktree* while the delivery repo remains
  uncommitted, a disposable scratch repository was created under
  `F:\dsh插件创造\.tmp\cbi-clone-repro\` and deleted after the run. The scratch
  commit is verification scaffolding only; it is not part of the delivery repo.

## Pre-fix baseline

A clean temporary clone was built from the current worktree content (tracked +
untracked non-ignored files only, so ignored fixture data was absent) and its
default Windows checkout was left untouched:

```powershell
# scratch snapshot of the current worktree, then a real clean clone
git init; git add -A; git commit -m "temporary pre-fix verification snapshot"
git clone <scratch> pre-clean

python -m venv --system-site-packages .venv
.\.venv\Scripts\python -m pip install -e . --no-deps
cd integrations/deepseek-harness/plugin
npm install
npm test
npm run check
cd ../..
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m codebase_intelligence.cli export . --check --json
```

Observed results (logs under the temporary verification directory, removed after
the run):

| Command | Exit | Observed |
|---|---|---|
| `pytest -q` | **1** | `5 failed, 403 passed, 7 skipped` |
| `npm test` | 0 | 105 passed |
| `npm run check` | 0 | client artifacts up to date |
| `cbi export . --check` | **1** | `stale=true`, all 8 files `updated`, manifest `bdc6c369628c…` |

Failing tests:

```text
tests/test_scanner.py::test_gitignore_repo_default_scan - KeyError: 'gitignore'
tests/test_scanner.py::test_gitignore_disabled_indexes_everything_not_excluded_by_name
tests/test_scanner.py::test_default_excludes_and_index_directory - assert 6 == 15
tests/test_scanner.py::test_include_hidden_keeps_default_excludes_and_index_dir
tests/test_scanner.py::test_extra_excludes_cli_style_globs - assert 3 == 4
```

Evidence and root-cause hypotheses:

```powershell
git ls-tree -r --name-only HEAD -- tests/fixtures/scanner/default-excludes-repo | wc -l
# 8 tracked files in the pre-fix clone; the local worktree has 18
git check-ignore -v tests/fixtures/scanner/default-excludes-repo/build/out.py
# .gitignore:8:build/
git ls-files --eol AGENTS.md
# i/lf  w/crlf
```

1. **Ignored fixture data was never committed.** 21 files under
   `tests/fixtures/scanner/` and `tests/fixtures/cli/` are ignored by the root
   `.gitignore` (or nested fixture ignore files) but are required by scanner
   tests. A clean clone therefore sees 8 instead of 18 files in
   `default-excludes-repo` and the scanner assertions fail. A nested
   `tests/fixtures/scanner/default-excludes-repo/.git/config` was also counted
   as one default-excluded directory; Git cannot commit a path below `.git`.
2. **The export snapshot hashes working-tree bytes, but the repository had no
   `.gitattributes`.** Local worktree line endings were mixed (10 CRLF files,
   the rest LF), while Windows Git checks out CRLF by default. The committed
   eight-file snapshot can never match every checkout, so
   `cbi export . --check` reports every file stale even though the committed
   snapshot is internally consistent.

## Fixes applied (working tree only, no commit)

- Added `.gitattributes` with `* text=auto eol=lf` and binary overrides for
  images and archives, so a fresh clone always checks text out as LF.
- Force-added the 21 ignored fixture files with `git add -f`. Replaced the
  uncommittable nested `.git/config` fixture dependency with a tracked
  `.hg/config` fixture directory (also a default-excluded name), preserving the
  expected default-exclude count of 15; removed the stray nested `.git` fixture
  from the worktree.
- Normalized 17 CRLF/mixed tracked text files to LF and regenerated the
  eight-file `docs/codebase-intelligence/` snapshot. No graph interaction source
  changed: the text of `03-models.js`, `04-panel.js`, `01-styles.js`,
  `00-head.js` and `05-apply.js` is byte-identical after normalizing CRLF to LF.
- Re-ran Python/Node tests and the export check in the delivery worktree.
- To test a clean clone of the fixed state without creating a delivery commit, a
  second disposable scratch repository was built from the fixed worktree and
  cloned with the default Windows Git configuration. The installed dependencies
  and Node cache live only inside the disposable clone.

## Post-fix clean clone

```powershell
git clone <temporary-fixed-scratch> fixed-clean
cd fixed-clean
git status --short -b          # clean
git ls-files --eol AGENTS.md   # i/lf  w/lf  attr/text=auto eol=lf
python -m venv --system-site-packages .venv
.\.venv\Scripts\python -m pip install -e . --no-deps
cd integrations/deepseek-harness/plugin
npm install --no-package-lock  # package-lock.json would be an untracked change
npm test
npm run check
cd ../..
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m codebase_intelligence.cli export . --check --json
```

Recorded results:

| Command | Exit | Result |
|---|---|---|
| install (venv + `pip install -e . --no-deps`) | 0 | editable engine installed |
| `npm install --no-package-lock` | 0 | no untracked lockfile |
| `pytest -q` | **0** | **408 passed, 7 skipped** |
| `npm test` | **0** | **105 passed, 0 failed** |
| `npm run check` | **0** | client artifacts up to date (`199,470 B`, 253 locale keys) |
| `cbi export . --check` | **0** | `check=true`, `stale=false`, all eight files present |
| `node scripts/footprint.mjs` | 0 | tool schema 1189 + prompt 184 = **1373** est. tokens |

Clone checks: clean `git status`, `i/lf w/lf` checkout for text files, ignored
fixture files present, nested `.git` fixture absent, `.hg/config` present.

## Before / after comparison

| Check | Clean clone before fix | Clean clone after fix |
|---|---|---|
| `pytest -q` | exit 1, 5 failed / 403 passed / 7 skipped | exit 0, 408 passed / 7 skipped |
| `npm test` | exit 0, 105 passed | exit 0, 105 passed |
| `npm run check` | exit 0 | exit 0 |
| `cbi export . --check` | exit 1, stale (manifest `bdc6c369628c…`) | exit 0, fresh |
| Text checkout | default CRLF (`w/crlf`) | LF (`w/lf`, `.gitattributes`) |
| Ignored fixture data | absent from clone | 21 files force-added + `.hg` substitute |
| Graph interaction logic | baseline | unchanged (LF-normalized text identical) |
| Always-on footprint | 1373 est. tokens | 1373 est. tokens |
| Version | 0.1.0 | 0.1.0 |

## Remaining risks

- The fix is present only in the uncommitted working tree and staged fixture
  entries; the delivery still has no commit and nothing was pushed. The
  disposable scratch commits used for clone verification are not delivery
  history.
- `npm install` *without* `--no-package-lock` creates `package-lock.json`, which
  makes `cbi export . --check` stale until it is removed, committed or ignored.
  The verification uses `--no-package-lock`.
- The nested `.git/config` fixture cannot be tracked by Git; the tracked
  `.hg/config` replacement keeps the expected default-exclude count, but anyone
  who reintroduces a local nested `.git` directory will see the count change.
- The graph snapshot is repository-sized (about 4.8 MB for this tree) and the
  panel still bounds a page to 80 nodes / 160 edges.
- Python/Node installs in clean clones need network access for `pip install -e`
  (only build backend/editable metadata) and npm metadata; the test commands
  themselves are offline.
- The prior remote-clone issue with `github.com:443` and the API-push workaround
  is unchanged; this verification intentionally did not push.

> Follow-up note: after this clone verification, the Start-guide entry was
> styled to match the native host row and an extra Node test was added; the Node
> suite is now 106 tests. This does not change the fixture/line-ending fix. The
> export snapshot was regenerated for this working-tree state; before the next
> commit, repeat the clean-clone gate.
