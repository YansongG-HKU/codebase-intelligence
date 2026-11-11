"""Benchmark scan/index and retrieval operations on a large repository.

Two source modes are supported and both are explicit in the output:

* ``--root PATH`` benchmarks an existing monorepo read-only (the cache lives
  outside the repository unless ``--cache-dir`` is supplied);
* ``--synthetic-files N`` generates a deterministic synthetic Python monorepo
  in a temporary directory, so the command is reproducible on any machine.

The JSON/markdown artifacts record the source label, indexed scale, engine and
Python version, wall-clock medians, Python-traced peak allocations, payload
sizes/token estimates and deterministic-repeat results. Timings are volatile
evidence by design; they never enter the model-facing JSON payloads.

Run with the package importable (``PYTHONPATH=src`` or an editable install):

    python scripts/bench_monorepo.py --root <MONOREPO_ROOT> \
        --source-label local-monorepo --json-out bench/monorepo.json \
        --markdown-out docs/MONOREPO_BENCHMARK.md

    python scripts/bench_monorepo.py --synthetic-files 5000 \
        --json-out bench/monorepo-synthetic.json \
        --markdown-out docs/MONOREPO_BENCHMARK.md
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import statistics
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codebase_intelligence import ENGINE_VERSION, api
from codebase_intelligence.model import SCHEMA_VERSION
from codebase_intelligence.util import TOKEN_ESTIMATOR, canonical_json, estimate_tokens

DEFAULT_LIMITS: dict[str, float] = {
    "coldIndexSeconds": 300.0,
    "warmIndexSeconds": 60.0,
    "overviewSeconds": 5.0,
    "mapSeconds": 10.0,
    "searchSeconds": 5.0,
    "dependenciesSeconds": 5.0,
    "contextSeconds": 10.0,
    "impactSeconds": 5.0,
    "peakMemoryMB": 1024.0,
}


def _git_metadata(root: Path) -> dict[str, Any]:
    """Best-effort source provenance for a real checkout (no path in output)."""

    def run(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(root), *args],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

    try:
        commit = run("rev-parse", "HEAD")
        dirty = bool(run("status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        return {}
    return {"gitCommit": commit, "gitDirty": dirty}


def _timed(fn: Callable[[], Any]) -> tuple[Any, float, float]:
    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = fn()
    finally:
        elapsed = (time.perf_counter() - started) * 1000.0
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return result, elapsed, peak / (1024 * 1024)


def _synthetic_repository(root: Path, files: int) -> None:
    """Create a deterministic Python-only monorepo with ``files`` modules."""

    for index in range(files):
        package = root / "packages" / f"pkg{index // 50:03d}"
        package.mkdir(parents=True, exist_ok=True)
        previous = index - 1
        imports = []
        if previous >= 0:
            imports.append(
                f"from packages.pkg{previous // 50:03d}.module_{previous:05d} import Symbol{previous}"
            )
        lines = [
            f'"""Synthetic module {index}."""',
            "",
            *imports,
            "",
            f"class Symbol{index}:",
            f'    """Synthetic class {index}."""',
            f"    value = {index}",
            "",
            f"def build_{index}(items):",
            f'    """Build synthetic item set {index}."""',
            "    return list(items)",
        ]
        (package / f"module_{index:05d}.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scale(snapshot: Any, cache_dir: Path) -> dict[str, Any]:
    languages: dict[str, dict[str, int]] = {}
    for file in snapshot.files:
        entry = languages.setdefault(file.language.value, {"files": 0, "symbols": 0})
        entry["files"] += 1
    for symbol in snapshot.symbols:
        entry = languages.setdefault(symbol.language.value, {"files": 0, "symbols": 0})
        entry["symbols"] += 1
    cache_bytes = sum(
        path.stat().st_size for path in cache_dir.rglob("*") if path.is_file()
    )
    return {
        "files": len(snapshot.files),
        "symbols": len(snapshot.symbols),
        "relations": len(snapshot.relations),
        "sourceBytes": sum(file.size_bytes for file in snapshot.files),
        "indexCacheBytes": cache_bytes,
        "languages": [
            {"language": language, **entry}
            for language, entry in sorted(languages.items())
        ],
    }


def _operation_rows(
    root: Path,
    cache_dir: Path,
    snapshot: Any,
    repeat: int,
) -> list[dict[str, Any]]:
    python_files = [item.path for item in snapshot.files if item.path.endswith(".py")]
    target_file = python_files[0] if python_files else (snapshot.files[0].path if snapshot.files else "")
    target_symbols = [item.id for item in snapshot.symbols if item.path == target_file]
    target_symbol = target_symbols[0] if target_symbols else ""

    operations: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("overview", lambda: api.run_overview(root, cache_dir=cache_dir)),
        ("map", lambda: api.run_map(root, cache_dir=cache_dir)),
        ("search", lambda: api.run_search(root, "token budget context", cache_dir=cache_dir)),
        (
            "dependencies",
            lambda: api.run_dependencies(root, target_file, cache_dir=cache_dir),
        ),
        ("context", lambda: api.run_context(root, "add a parser adapter", cache_dir=cache_dir)),
        ("impact", lambda: api.run_impact(root, files=[target_file] if target_file else [], cache_dir=cache_dir)),
    ]
    if target_symbol:
        operations.append(
            (
                "symbol-neighborhood",
                lambda: api.run_dependencies(root, target_symbol, cache_dir=cache_dir),
            )
        )

    rows: list[dict[str, Any]] = []
    for name, runner in operations:
        payload, elapsed, peak = _timed(runner)
        payload_bytes = len(canonical_json(payload).encode("utf-8"))
        samples = [elapsed]
        peaks = [peak]
        deterministic = True
        for _ in range(max(1, repeat) - 1):
            repeated, repeat_elapsed, repeat_peak = _timed(runner)
            samples.append(repeat_elapsed)
            peaks.append(repeat_peak)
            deterministic = deterministic and canonical_json(repeated) == canonical_json(payload)
        rows.append(
            {
                "operation": name,
                "seconds": round(statistics.median(samples) / 1000.0, 4),
                "secondsMin": round(min(samples) / 1000.0, 4),
                "secondsMax": round(max(samples) / 1000.0, 4),
                "peakMemoryMB": round(max(peaks), 2),
                "payloadBytes": payload_bytes,
                "tokensEstimated": estimate_tokens(canonical_json(payload)),
                "tokenEstimator": TOKEN_ESTIMATOR,
                "deterministic": deterministic,
            }
        )
    return rows


def _markdown(payload: dict[str, Any]) -> str:
    source = payload["source"]
    scale = payload["scale"]
    lines = [
        "# Large monorepo performance/memory benchmark",
        "",
        "Generated by `python scripts/bench_monorepo.py`; timings are volatile "
        "evidence and never enter model-facing payloads.",
        "",
        "## Source and scale",
        "",
        f"- Source: **{source['label']}** (`{source['mode']}`)",
        f"- Engine/schema: `{payload['engineVersion']}` / `{payload['schemaVersion']}`",
        f"- Python: `{payload['environment']['python']}` on `{payload['environment']['platform']}`",
        f"- Files: **{scale['files']}**, symbols: **{scale['symbols']}**, "
        f"relations: **{scale['relations']}**",
        f"- Indexed bytes: **{scale['sourceBytes']}**, index cache bytes: "
        f"**{scale['indexCacheBytes']}**",
        "- Languages: " + ", ".join(
            f"{item['language']} ({item['files']} files/{item['symbols']} symbols)"
            for item in scale["languages"]
        ),
        "",
        "## Results",
        "",
        "| Operation | Median s | Min s | Max s | Peak MB | Bytes | Est. tokens | Deterministic |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload["operations"]:
        lines.append(
            f"| {row['operation']} | {row['seconds']:.4f} | {row['secondsMin']:.4f} | "
            f"{row['secondsMax']:.4f} | {row['peakMemoryMB']:.2f} | {row['payloadBytes']} | "
            f"{row['tokensEstimated']} | {str(row['deterministic']).lower()} |"
        )
    lines += [
        "",
        f"- Cold index: **{payload['coldIndex']['seconds']:.4f}s**, peak "
        f"**{payload['coldIndex']['peakMemoryMB']:.2f} MB**",
        f"- Warm index: **{payload['warmIndex']['seconds']:.4f}s**, peak "
        f"**{payload['warmIndex']['peakMemoryMB']:.2f} MB**",
        f"- Gate: **{'pass' if payload['passed'] else 'fail'}**",
        "",
        "Thresholds: " + ", ".join(
            f"`{key} <= {value:g}`" for key, value in payload["thresholds"].items()
        ),
        "",
        "## Reproduce",
        "",
        "```powershell",
        "python scripts/bench_monorepo.py --synthetic-files 5000 `",
        "  --json-out bench/monorepo-synthetic.json `",
        "  --markdown-out docs/MONOREPO_BENCHMARK.md --check",
        "```",
        "",
        "For a local monorepo, replace `--synthetic-files 5000` with "
        "`--root <MONOREPO_ROOT> --source-label <label> --cache-dir <TEMP_CACHE>`.",
        "",
    ]
    return "\n".join(lines)


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    temporary: tempfile.TemporaryDirectory[str] | None = None
    temporary_cache: tempfile.TemporaryDirectory[str] | None = None
    if args.synthetic_files:
        temporary = tempfile.TemporaryDirectory(prefix="cbi-monorepo-")
        root = Path(temporary.name)
        _synthetic_repository(root, args.synthetic_files)
        source = {
            "mode": "synthetic",
            "label": args.source_label or f"synthetic-{args.synthetic_files}-files",
            "filesRequested": args.synthetic_files,
            "generator": f"scripts/bench_monorepo.py --synthetic-files {args.synthetic_files}",
        }
        cache_dir = root / ".cbi-benchmark-cache"
    else:
        if not args.root:
            raise SystemExit("either --root or --synthetic-files is required")
        root = api.resolve_root(args.root)
        source = {
            "mode": "real",
            "label": args.source_label or root.name,
            "filesRequested": None,
            **_git_metadata(root),
        }
        if args.cache_dir:
            cache_dir = Path(args.cache_dir)
        else:
            temporary_cache = tempfile.TemporaryDirectory(prefix="cbi-benchmark-cache-")
            cache_dir = Path(temporary_cache.name)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        cold_result, cold_seconds, cold_peak = _timed(
            lambda: api.open_index(root, cache_dir=cache_dir, force=True)
        )
        warm_result, warm_seconds, warm_peak = _timed(
            lambda: api.open_index(root, cache_dir=cache_dir, force=False)
        )
        snapshot = warm_result.snapshot
        operations = _operation_rows(root, cache_dir, snapshot, args.repeat)
        results = {
            "engineVersion": ENGINE_VERSION,
            "schemaVersion": SCHEMA_VERSION,
            "source": source,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "scale": _scale(snapshot, cache_dir),
            "coldIndex": {
                "seconds": round(cold_seconds / 1000.0, 4),
                "peakMemoryMB": round(cold_peak, 2),
                "cacheHit": cold_result.cache.cache_hit,
            },
            "warmIndex": {
                "seconds": round(warm_seconds / 1000.0, 4),
                "peakMemoryMB": round(warm_peak, 2),
                "cacheHit": warm_result.cache.cache_hit,
            },
            "operations": operations,
            "thresholds": DEFAULT_LIMITS,
            "passed": False,
        }
        checks = [
            cold_seconds / 1000.0 <= DEFAULT_LIMITS["coldIndexSeconds"],
            warm_seconds / 1000.0 <= DEFAULT_LIMITS["warmIndexSeconds"],
            cold_peak <= DEFAULT_LIMITS["peakMemoryMB"],
            warm_peak <= DEFAULT_LIMITS["peakMemoryMB"],
        ]
        check_names = ["coldIndexSeconds", "warmIndexSeconds", "coldPeakMemoryMB", "warmPeakMemoryMB"]
        operation_keys = {
            "overview": "overviewSeconds",
            "map": "mapSeconds",
            "search": "searchSeconds",
            "dependencies": "dependenciesSeconds",
            "context": "contextSeconds",
            "impact": "impactSeconds",
        }
        for row in operations:
            key = operation_keys.get(row["operation"])
            if key:
                checks.append(row["seconds"] <= DEFAULT_LIMITS[key])
                check_names.append(key)
            checks.append(row["peakMemoryMB"] <= DEFAULT_LIMITS["peakMemoryMB"])
            check_names.append(f"{row['operation']}PeakMemoryMB")
        results["checks"] = [
            {"name": name, "passed": passed} for name, passed in zip(check_names, checks)
        ]
        results["passed"] = all(checks)
        if args.json_out:
            Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json_out).write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if args.markdown_out:
            Path(args.markdown_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.markdown_out).write_text(_markdown(results), encoding="utf-8")
        return results
    finally:
        if temporary is not None:
            temporary.cleanup()
        if temporary_cache is not None:
            temporary_cache.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", help="Existing monorepo root to benchmark read-only.")
    source.add_argument("--synthetic-files", type=int, help="Generate this many deterministic Python modules.")
    parser.add_argument("--source-label", default="")
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--repeat", type=int, default=2, help="Repeated operation calls for median/determinism.")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--markdown-out", default="")
    parser.add_argument("--check", action="store_true", help="Exit 1 when a threshold fails.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repeat < 1:
        raise SystemExit("--repeat must be >= 1")
    results = run_benchmark(args)
    if args.check and not results["passed"]:
        print("monorepo benchmark failed thresholds", file=sys.stderr)
        return 1
    print(json.dumps({"passed": results["passed"], "scale": results["scale"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
