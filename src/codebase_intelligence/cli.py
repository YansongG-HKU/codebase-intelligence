"""``cbi`` — command-line entry point.

Structural commands print canonical, deterministic JSON with ``--json`` (this is
what the DSH bridge consumes); human-readable text is available for scan, index
and report.  Exit codes: 0 success, 2 usage, 3 repository/index failure,
4 internal failure.  See ``docs/SPEC.md`` §11.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from codebase_intelligence import ENGINE_VERSION
from codebase_intelligence import api
from codebase_intelligence.errors import CbiError, UsageError, error_envelope
from codebase_intelligence.model import SCHEMA_VERSION
from codebase_intelligence.util import canonical_json, force_utf8_stdio

__version__ = ENGINE_VERSION


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def _add_root_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", nargs="?", default=".", help="Repository root (default: current directory).")
    parser.add_argument("--root", dest="root_override", default=None, help="Repository root (alternative to the positional path).")


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit one canonical JSON object.")


def _add_index_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache-dir", default=None, help="Index cache directory (default: <root>/.codebase-intelligence).")
    parser.add_argument("--force", action="store_true", help="Force a full rebuild instead of an incremental refresh.")
    parser.add_argument("--max-file-bytes", type=int, default=None, help="Skip files larger than this many bytes.")
    parser.add_argument("--exclude", action="append", default=[], help="Extra ignore glob (repeatable).")
    parser.add_argument("--include-hidden", action="store_true", help="Include dotfiles not excluded by .gitignore.")


def _add_budget(parser: argparse.ArgumentParser, default: int) -> None:
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=default,
        help=f"Answer budget in estimated tokens (default {default}, hard cap {api.MAX_TOOL_TOKENS}).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cbi",
        description="Build a structural, token-aware map of a source repository.",
    )
    parser.add_argument("--version", action="version", version=f"cbi {ENGINE_VERSION}")
    subparsers = parser.add_subparsers(dest="command")

    version = subparsers.add_parser("version", help="Print engine and schema versions.")
    _add_json(version)

    doctor = subparsers.add_parser("doctor", help="Report engine, Python runtime and module status.")
    _add_json(doctor)

    scan = subparsers.add_parser("scan", help="Scan a repository without building the index (diagnostics).")
    _add_root_options(scan)
    _add_json(scan)
    scan.add_argument("--max-file-bytes", type=int, default=None)
    scan.add_argument("--exclude", action="append", default=[])
    scan.add_argument("--include-hidden", action="store_true")
    scan.add_argument("--list-files", action="store_true", help="Include the per-file list in the payload.")

    index = subparsers.add_parser("index", help="Build or incrementally refresh the repository index.")
    _add_root_options(index)
    _add_json(index)
    _add_index_options(index)
    index.add_argument("--diagnostics", action="store_true", help="Include cache counters and the index path (volatile).")

    overview = subparsers.add_parser("overview", help="Repository overview under a token budget.")
    _add_root_options(overview)
    _add_json(overview)
    _add_index_options(overview)
    _add_budget(overview, api.DEFAULT_TOOL_TOKENS["overview"])

    map_parser = subparsers.add_parser("map", help="Compact ranked repository map.")
    _add_root_options(map_parser)
    _add_json(map_parser)
    _add_index_options(map_parser)
    _add_budget(map_parser, api.DEFAULT_TOOL_TOKENS["map"])
    map_parser.add_argument("--focus", default=None, help="Restrict the map to a path prefix.")

    search = subparsers.add_parser("search", help="Search files and symbols with source evidence.")
    _add_root_options(search)
    _add_json(search)
    _add_index_options(search)
    _add_budget(search, api.DEFAULT_TOOL_TOKENS["search"])
    search.add_argument("--query", required=True, help="Search query.")

    dependencies = subparsers.add_parser("dependencies", help="Dependency neighborhood for a file or symbol.")
    _add_root_options(dependencies)
    _add_json(dependencies)
    _add_index_options(dependencies)
    _add_budget(dependencies, api.DEFAULT_TOOL_TOKENS["dependencies"])
    dependencies.add_argument("--target", required=True, help="Repository-relative file path or symbol name/id.")
    dependencies.add_argument("--direction", choices=["both", "imports", "dependents"], default="both")
    dependencies.add_argument("--depth", type=int, default=1, help="Traversal depth (1-5).")

    context = subparsers.add_parser("context", help="Task-aware context pack under a token budget.")
    _add_root_options(context)
    _add_json(context)
    _add_index_options(context)
    _add_budget(context, api.DEFAULT_TOOL_TOKENS["context"])
    context.add_argument("--task", required=True, help="Task or question the context is selected for.")
    context.add_argument("--path-prefix", default=None, help="Restrict retrieval to a path prefix.")

    impact = subparsers.add_parser("impact", help="Conservative change-impact preview.")
    _add_root_options(impact)
    _add_json(impact)
    _add_index_options(impact)
    _add_budget(impact, api.DEFAULT_TOOL_TOKENS["impact"])
    impact.add_argument("--files", action="append", default=[], help="Changed file (repeatable or comma separated).")
    impact.add_argument("--symbols", action="append", default=[], help="Changed symbol (repeatable or comma separated).")

    report = subparsers.add_parser("report", help="Render the architecture report as Markdown.")
    _add_root_options(report)
    _add_json(report)
    _add_index_options(report)
    report.add_argument("--out", default=None, help="Write the Markdown report to this file instead of stdout.")

    export = subparsers.add_parser(
        "export",
        help="Write the deterministic artifact bundle for the right-sidebar panel.",
    )
    _add_root_options(export)
    _add_json(export)
    _add_index_options(export)
    export.add_argument(
        "--out",
        default=None,
        help="Generation directory relative to the repository root (default: docs/codebase-intelligence).",
    )
    export.add_argument(
        "--check",
        action="store_true",
        help="Report the export plan without writing; exit 1 when anything is stale.",
    )

    mcp = subparsers.add_parser("mcp", help="Run the stdio MCP server for this repository root.")
    _add_root_options(mcp)
    mcp.add_argument("--cache-dir", default=None)

    return parser


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def _write_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(canonical_json(payload) + "\n")
    sys.stdout.flush()


def _write_human(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        _write_json(payload)
    else:
        _write_human(payload)


def _root_of(args: argparse.Namespace) -> Path:
    raw = getattr(args, "root_override", None) or getattr(args, "path", ".")
    return api.resolve_root(raw)


def _cache_dir_of(args: argparse.Namespace) -> Path | None:
    return api.resolve_cache_dir(getattr(args, "cache_dir", None))


def _policy_of(args: argparse.Namespace):
    return api.build_policy(
        max_file_bytes=getattr(args, "max_file_bytes", None),
        excludes=getattr(args, "exclude", ()),
        include_hidden=bool(getattr(args, "include_hidden", False)),
    )


def _split(values: Sequence[str]) -> list[str]:
    items: list[str] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                items.append(part)
    return items


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def _cmd_version(args: argparse.Namespace) -> int:
    payload = {
        "ok": True,
        "schemaVersion": SCHEMA_VERSION,
        "command": "version",
        "engineVersion": ENGINE_VERSION,
    }
    if getattr(args, "json", False):
        _write_json(payload)
    else:
        print(f"cbi {ENGINE_VERSION} (schema {SCHEMA_VERSION})")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    payload = api.doctor_payload()
    _emit(payload, as_json=getattr(args, "json", False))
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    root = _root_of(args)
    payload = api.scan_payload(root, policy=_policy_of(args))
    if not getattr(args, "list_files", False):
        payload["files"] = payload["files"][:10]
        payload["filesTruncated"] = True
    if getattr(args, "json", False):
        _write_json(payload)
    else:
        stats = payload["stats"]
        print(f"{stats['filesIndexed']} files, {stats['bytesIndexed']} bytes under {root}")
        skipped = stats.get("skipped") or {}
        if skipped:
            print("skipped: " + ", ".join(f"{key}={value}" for key, value in sorted(skipped.items())))
        for item in payload["files"][:10]:
            print(f"  {item['path']} ({item['language']}, {item['lineCount']} lines)")
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    root = _root_of(args)
    payload = api.index_payload(
        root,
        cache_dir=_cache_dir_of(args),
        force=bool(getattr(args, "force", False)),
        policy=_policy_of(args),
        diagnostics=bool(getattr(args, "diagnostics", False)),
    )
    if getattr(args, "json", False):
        _write_json(payload)
    else:
        repo = payload["repo"]
        print(f"indexed {repo['files']} files, {repo['symbols']} symbols, {repo['relations']} relations")
        print(f"fingerprint {payload['index']['fingerprint'][:16]}…")
        diagnostics = payload.get("diagnostics")
        if diagnostics:
            cache = diagnostics["cache"]
            print(
                "cache: reused={filesReused} reparsed={filesReparsed} removed={filesRemoved} hit={cacheHit}".format(
                    **cache
                )
            )
    return 0


def _cmd_overview(args: argparse.Namespace) -> int:
    root = _root_of(args)
    payload = api.run_overview(
        root,
        cache_dir=_cache_dir_of(args),
        max_tokens=args.max_tokens,
        force=bool(getattr(args, "force", False)),
    )
    _emit(payload, as_json=getattr(args, "json", False))
    return 0


def _cmd_map(args: argparse.Namespace) -> int:
    root = _root_of(args)
    payload = api.run_map(
        root,
        cache_dir=_cache_dir_of(args),
        max_tokens=args.max_tokens,
        focus=getattr(args, "focus", None),
        force=bool(getattr(args, "force", False)),
    )
    _emit(payload, as_json=getattr(args, "json", False))
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    root = _root_of(args)
    payload = api.run_search(
        root,
        args.query,
        cache_dir=_cache_dir_of(args),
        max_tokens=args.max_tokens,
        force=bool(getattr(args, "force", False)),
    )
    _emit(payload, as_json=getattr(args, "json", False))
    return 0


def _cmd_dependencies(args: argparse.Namespace) -> int:
    root = _root_of(args)
    payload = api.run_dependencies(
        root,
        args.target,
        direction=args.direction,
        depth=args.depth,
        cache_dir=_cache_dir_of(args),
        max_tokens=args.max_tokens,
        force=bool(getattr(args, "force", False)),
    )
    _emit(payload, as_json=getattr(args, "json", False))
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    root = _root_of(args)
    payload = api.run_context(
        root,
        args.task,
        max_tokens=args.max_tokens,
        path_prefix=getattr(args, "path_prefix", None),
        cache_dir=_cache_dir_of(args),
        force=bool(getattr(args, "force", False)),
    )
    _emit(payload, as_json=getattr(args, "json", False))
    return 0


def _cmd_impact(args: argparse.Namespace) -> int:
    root = _root_of(args)
    payload = api.run_impact(
        root,
        files=_split(args.files),
        symbols=_split(args.symbols),
        max_tokens=args.max_tokens,
        cache_dir=_cache_dir_of(args),
        force=bool(getattr(args, "force", False)),
    )
    _emit(payload, as_json=getattr(args, "json", False))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    root = _root_of(args)
    markdown = api.report_markdown(root, cache_dir=_cache_dir_of(args), force=bool(getattr(args, "force", False)))
    out = getattr(args, "out", None)
    if out:
        target = Path(out).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8", newline="\n")
        if getattr(args, "json", False):
            _write_json(
                {
                    "ok": True,
                    "schemaVersion": SCHEMA_VERSION,
                    "command": "report",
                    "path": str(target),
                    "bytes": len(markdown.encode("utf-8")),
                }
            )
        else:
            print(f"wrote {target} ({len(markdown.encode('utf-8'))} bytes)")
        return 0
    if getattr(args, "json", False):
        _write_json(
            {
                "ok": True,
                "schemaVersion": SCHEMA_VERSION,
                "command": "report",
                "markdown": markdown,
            }
        )
    else:
        sys.stdout.write(markdown)
        if not markdown.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from codebase_intelligence import export as export_module

    root = _root_of(args)
    result = export_module.build_export(
        root,
        out=getattr(args, "out", None),
        cache_dir=_cache_dir_of(args),
        force=bool(getattr(args, "force", False)),
        max_file_bytes=getattr(args, "max_file_bytes", None),
        excludes=getattr(args, "exclude", ()),
        include_hidden=bool(getattr(args, "include_hidden", False)),
        check=bool(getattr(args, "check", False)),
    )
    payload = result.to_payload()
    if getattr(args, "json", False):
        _write_json(payload)
    else:
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        for item in payload["files"]:
            counts[item["status"]] += 1
        summary = (
            f"created={counts['created']} updated={counts['updated']} "
            f"unchanged={counts['unchanged']}"
        )
        if payload["check"]:
            state = "stale" if payload["stale"] else "up to date"
            print(f"export check: {state} under {payload['outDir']} ({summary})")
            for item in payload["files"]:
                if item["status"] != "unchanged":
                    print(f"  {item['status']:<9} {item['path']} ({item['bytes']} bytes)")
        else:
            print(
                f"exported {len(payload['files'])} file(s) under {payload['outDir']} ({summary})"
            )
            print(f"manifest {payload['manifestFingerprint']}")
    if payload["check"] and payload["stale"]:
        return 1
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    from codebase_intelligence.mcp.server import serve

    root = api.resolve_root(getattr(args, "root_override", None) or getattr(args, "path", "."))
    cache_dir = _cache_dir_of(args)
    serve(root, cache_dir=cache_dir)
    return 0


_COMMANDS = {
    "version": _cmd_version,
    "doctor": _cmd_doctor,
    "scan": _cmd_scan,
    "index": _cmd_index,
    "overview": _cmd_overview,
    "map": _cmd_map,
    "search": _cmd_search,
    "dependencies": _cmd_dependencies,
    "context": _cmd_context,
    "impact": _cmd_impact,
    "report": _cmd_report,
    "export": _cmd_export,
    "mcp": _cmd_mcp,
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run(argv: Sequence[str] | None = None) -> int:
    # Repository paths and JSON payloads may contain non-ASCII characters; the
    # Windows console code page must never turn a valid payload into a crash.
    force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    command = getattr(args, "command", None)
    if command is None:
        parser.print_help()
        return 0
    handler = _COMMANDS.get(command)
    if handler is None:  # pragma: no cover - argparse enforces the choices
        raise UsageError(f"unknown command {command!r}")
    try:
        return handler(args)
    except CbiError as error:
        if getattr(args, "json", False):
            _write_json(error_envelope(error, command=command))
        else:
            print(f"cbi: {error.code}: {error.message}", file=sys.stderr)
            if error.detail:
                print(f"cbi: detail: {error.detail}", file=sys.stderr)
        return error.exit_code
    except BrokenPipeError:  # pragma: no cover - piping into head
        return 0
    except Exception as error:  # noqa: BLE001 - CLI boundary must not traceback
        if getattr(args, "json", False):
            _write_json(
                error_envelope(
                    CbiError(f"{type(error).__name__}: {error}", code="internal_error"),
                    command=command,
                )
            )
        else:
            print(f"cbi: internal_error: {type(error).__name__}: {error}", file=sys.stderr)
        return 4


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
