"""Measure the model-facing token cost and the cache/determinism behaviour.

Run with the package on the path:

    python scripts/bench.py --root . --json-out bench/results.json \
        --markdown-out docs/BENCHMARKS.md

Everything measured here is a *property of the shipped engine*: the always-on
tool-catalogue cost, the size of the six budgeted operations, byte determinism
across repeated calls, and the incremental index cache behaviour.  Volatile
values (durations) are reported only in the JSON/markdown artifact, never in a
tool payload.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from codebase_intelligence import ENGINE_VERSION, api
from codebase_intelligence.mcp.server import TOOL_DEFINITIONS
from codebase_intelligence.util import TOKEN_ESTIMATOR, canonical_json, estimate_tokens

INFRASTRUCTURE = Path(__file__).resolve().parent.parent


def _measure_text(text: str) -> dict[str, Any]:
    encoded = text.encode("utf-8")
    return {
        "bytes": len(encoded),
        "chars": len(text),
        "tokensEstimated": estimate_tokens(text),
        "tokenEstimator": TOKEN_ESTIMATOR,
    }


def measure_tool_catalogue() -> dict[str, Any]:
    payload = _measure_text(canonical_json(TOOL_DEFINITIONS))
    payload["toolCount"] = len(TOOL_DEFINITIONS)
    return payload


def measure_plugin_footprint(plugin_dir: Path, node: str | None) -> dict[str, Any]:
    script = plugin_dir / "scripts" / "footprint.mjs"
    if node is None or not script.is_file():
        return {"available": False, "reason": "node or scripts/footprint.mjs missing"}
    try:
        completed = subprocess.run(
            [node, str(script)],
            cwd=str(plugin_dir),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    if completed.returncode != 0:
        return {"available": False, "reason": completed.stderr.strip()[-500:] or "footprint failed"}
    text = completed.stdout.strip()
    payload = None
    try:
        payload = json.loads(text)
    except ValueError:
        # Tolerate a leading log line; the script itself prints one JSON object.
        for line in reversed(text.splitlines()):
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            break
    if not isinstance(payload, dict):
        return {"available": False, "reason": "footprint script did not print JSON"}
    payload["available"] = True
    return payload


def _timed(runner: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    payload = runner()
    return payload, (time.perf_counter() - started) * 1000.0


def measure_operations(root: Path, cache_dir: Path | None) -> dict[str, Any]:
    snapshot = api.open_index(root, cache_dir=cache_dir).snapshot
    python_files = [item.path for item in snapshot.files if item.language.value == "python"]
    target_file = python_files[0] if python_files else snapshot.files[0].path
    symbols = [item for item in snapshot.symbols if item.path == target_file]
    target_symbol = symbols[0].id if symbols else None

    operations: list[tuple[str, str, int, Callable[[], dict[str, Any]]]] = [
        ("overview", "repository overview", api.DEFAULT_TOOL_TOKENS["overview"],
         lambda: api.run_overview(root, cache_dir=cache_dir)),
        ("map", "ranked repository map", api.DEFAULT_TOOL_TOKENS["map"],
         lambda: api.run_map(root, cache_dir=cache_dir)),
        ("search", "search 'token budget'", api.DEFAULT_TOOL_TOKENS["search"],
         lambda: api.run_search(root, "token budget", cache_dir=cache_dir)),
        ("dependencies", f"dependencies of {target_file}", api.DEFAULT_TOOL_TOKENS["dependencies"],
         lambda: api.run_dependencies(root, target_file, cache_dir=cache_dir)),
        ("context", "add a token budget to the DSH plugin", api.DEFAULT_TOOL_TOKENS["context"],
         lambda: api.run_context(root, "add a token budget to the DSH plugin", cache_dir=cache_dir)),
        ("impact", f"impact of changing {target_file}", api.DEFAULT_TOOL_TOKENS["impact"],
         lambda: api.run_impact(root, files=[target_file], cache_dir=cache_dir)),
    ]
    if target_symbol is not None:
        operations.append(
            (
                "symbol-neighborhood",
                f"neighborhood of {target_symbol}",
                api.DEFAULT_TOOL_TOKENS["dependencies"],
                lambda: api.run_dependencies(root, target_symbol, cache_dir=cache_dir),
            )
        )

    results: list[dict[str, Any]] = []
    for tool, description, budget, runner in operations:
        first, first_ms = _timed(runner)
        second, second_ms = _timed(runner)
        first_text = canonical_json(first)
        second_text = canonical_json(second)
        measured = _measure_text(first_text)
        results.append(
            {
                "operation": tool,
                "description": description,
                "budgetTokens": budget,
                "tokensEstimated": measured["tokensEstimated"],
                "bytes": measured["bytes"],
                "withinBudget": measured["tokensEstimated"] <= budget,
                "deterministic": first_text == second_text,
                "firstMs": round(first_ms, 1),
                "secondMs": round(second_ms, 1),
                "truncated": bool(first.get("truncated", False)),
            }
        )
    return {"operations": results}


def measure_index_cache(root: Path, cache_dir: Path | None) -> dict[str, Any]:
    cold_payload = api.index_payload(root, cache_dir=cache_dir, force=True, diagnostics=True)
    warm_payload = api.index_payload(root, cache_dir=cache_dir, diagnostics=True)
    plain_first = api.index_payload(root, cache_dir=cache_dir)
    plain_second = api.index_payload(root, cache_dir=cache_dir)
    cold_payload.pop("diagnostics", None)
    warm_payload.pop("diagnostics", None)
    return {
        "cold": cold_payload,
        "warm": warm_payload,
        "plainIdentical": canonical_json(plain_first) == canonical_json(plain_second),
        "coldDiagnostics": api.index_payload(root, cache_dir=cache_dir, force=True, diagnostics=True)["diagnostics"],
        "warmDiagnostics": api.index_payload(root, cache_dir=cache_dir, diagnostics=True)["diagnostics"],
    }


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    catalog = report["toolCatalogue"]
    operations = report["operations"]["operations"]
    cache = report["indexCache"]
    cold_cache = cache["coldDiagnostics"]["cache"]
    warm_cache = cache["warmDiagnostics"]["cache"]
    lines: list[str] = [
        "# Token & Cache Benchmarks",
        "",
        "Generated by `python scripts/bench.py`; regenerate after engine changes.",
        "Token counts use the documented `chars4-wide-v1` estimator, not a model tokenizer.",
        "",
        "## Always-on footprint",
        "",
        "| Surface | Tools | Bytes | Estimated tokens |",
        "|---|---|---|---|",
        f"| MCP/CLI tool catalogue | {catalog['toolCount']} | {catalog['bytes']} | {catalog['tokensEstimated']} |",
    ]
    plugin = report.get("pluginFootprint", {})
    if plugin.get("available"):
        lines.append(
            f"| DSH plugin tools + prompt section | {plugin.get('toolCount', '?')} | "
            f"{plugin.get('toolSchemaBytes', '?')} | {plugin.get('toolSchemaTokensEstimated', '?')} |"
        )
        lines.append("")
        lines.append(
            f"DSH prompt section alone: {plugin.get('promptSectionTokensEstimated', '?')} tokens "
            f"({plugin.get('promptSectionBytes', '?')} bytes, static hash "
            f"`{plugin.get('promptSectionTextHash', '?')}`)."
        )
    lines.extend(
        [
            "",
            "## Budgeted operations",
            "",
            "| Operation | Budget | Estimated tokens | Bytes | Within budget | Deterministic | Truncated |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for item in operations:
        lines.append(
            "| {operation} | {budgetTokens} | {tokensEstimated} | {bytes} | {withinBudget} | "
            "{deterministic} | {truncated} |".format(**{key: _fmt(value) for key, value in item.items()})
        )
    lines.extend(
        [
            "",
            "## Incremental index cache",
            "",
            f"- Cold build reused files: {cold_cache.get('filesReused', '?')}, reparsed: {cold_cache.get('filesReparsed', '?')}",
            f"- Warm build reused files: {warm_cache.get('filesReused', '?')}, reparsed: {warm_cache.get('filesReparsed', '?')}",
            f"- Warm cache hit: {_fmt(warm_cache.get('cacheHit'))}",
            f"- Identical public index payload on repeated runs: {_fmt(cache['plainIdentical'])}",
            f"- Index fingerprint: `{cache['warm']['index']['fingerprint']}`",
            "",
            "## Cache-friendliness invariants",
            "",
            "- The six model-facing payloads contain no timestamps, absolute paths, durations or cache flags.",
            "- Repeated identical calls return identical canonical JSON (verified above per operation).",
            "- The DSH prompt section is a static string (no interpolation); tool schemas are static.",
            "- The index cache is content-addressed: warm runs reuse unchanged files without changing output bytes.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root to benchmark (default: this repository).")
    parser.add_argument("--cache-dir", default=None, help="Index cache directory (default: <root>/.codebase-intelligence).")
    parser.add_argument("--plugin-dir", default=str(INFRASTRUCTURE / "integrations" / "deepseek-harness" / "plugin"))
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--markdown-out", default=None)
    args = parser.parse_args(argv)

    root = api.resolve_root(args.root)
    cache_dir = api.resolve_cache_dir(args.cache_dir)
    plugin_dir = Path(args.plugin_dir).expanduser().resolve()
    node = shutil.which("node")
    report: dict[str, Any] = {
        "engineVersion": ENGINE_VERSION,
        "root": str(root),
        "tokenEstimator": TOKEN_ESTIMATOR,
        "toolCatalogue": measure_tool_catalogue(),
        "pluginFootprint": measure_plugin_footprint(plugin_dir, node),
        "operations": measure_operations(root, cache_dir),
        "indexCache": measure_index_cache(root, cache_dir),
    }
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    if args.markdown_out:
        target = Path(args.markdown_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
