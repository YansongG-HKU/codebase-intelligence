# Plugin test fixture (synthetic repository)

`demo_repo/` is a tiny, deterministic Python package used by the DeepSeek
Harness plugin integration checks. It exists so the engine can be exercised
against a known repository shape without depending on this repository's own
contents.

- `app/` — an importable package: `__init__`, `models`, `util`, `services`, `main`.
  `services.py` imports `models`/`util`, `main.py` imports `services`/`util`, and
  `util.py` imports `models`, so resolved import edges are guaranteed.
- `tests/test_app.py` — one import of `app.services` plus pure-function tests.
- `.gitignore` — excludes generated Python artifacts (exercises ignore handling).

Properties the checks rely on:

- deterministic content (static files, no timestamps or absolute paths);
- tiny (7 files, < 6 KiB) so a cold index is fast;
- no secrets and no binary files;
- every symbol is discoverable by `ast` (classes, functions, methods, docstrings).

Do not add generated files or change the import graph without updating
`docs/DSH_PLUGIN.md` (integration evidence).
