"""Stdio Model Context Protocol server for codebase intelligence.

The server exposes the same six read-only operations as the DSH plugin and the
CLI, backed by the same engine functions (``codebase_intelligence.api``), so all
three transports return identical payloads.  Protocol: newline-delimited
JSON-RPC 2.0 over stdin/stdout; stdout carries protocol messages only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, TextIO

from codebase_intelligence import ENGINE_VERSION
from codebase_intelligence import api
from codebase_intelligence.errors import CbiError, UsageError
from codebase_intelligence.util import canonical_json

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "codebase-intelligence"


def _schema(properties: Mapping[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": dict(properties), "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


_MAX_TOKENS_PROPERTY = {
    "type": "integer",
    "minimum": 64,
    "maximum": api.MAX_TOOL_TOKENS,
    "description": "Token budget for the answer (estimated with chars4-wide-v1).",
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "codebase_overview",
        "description": (
            "Repository overview: file/symbol/relation counts, languages, top directories, entry points and the "
            "index fingerprint. Read-only and deterministic. refresh rebuilds the index; maxTokens bounds the answer."
        ),
        "inputSchema": _schema(
            {
                "maxTokens": dict(_MAX_TOKENS_PROPERTY, description="Token budget for the overview (default 900)."),
                "refresh": {"type": "boolean", "description": "Force a full index rebuild instead of an incremental refresh."},
            }
        ),
    },
    {
        "name": "codebase_map",
        "description": (
            "Compact ranked repository map: the most important files and their symbols with signatures and line "
            "numbers, fitted to a token budget. focus restricts the map to a path prefix."
        ),
        "inputSchema": _schema(
            {
                "maxTokens": dict(_MAX_TOKENS_PROPERTY, description="Token budget for the map (default 1600)."),
                "focus": {"type": "string", "description": "Only include paths under this prefix."},
            }
        ),
    },
    {
        "name": "codebase_search",
        "description": (
            "Search files and symbols by name, path or lexical query. Returns bounded results with path, line, "
            "symbol kind and score evidence. Read-only and deterministic."
        ),
        "inputSchema": _schema(
            {
                "query": {"type": "string", "description": "Search query (required)."},
                "maxTokens": dict(_MAX_TOKENS_PROPERTY, description="Token budget for the results (default 1200)."),
            },
            required=["query"],
        ),
    },
    {
        "name": "codebase_dependencies",
        "description": (
            "Dependency neighborhood for a repository-relative file or a symbol name/id: imports, dependents or both, "
            "up to depth 5. Every edge keeps its resolution status and evidence label; unresolved edges are labelled."
        ),
        "inputSchema": _schema(
            {
                "target": {"type": "string", "description": "Repository-relative file path or symbol name/id (required)."},
                "direction": {"type": "string", "enum": ["both", "imports", "dependents"], "description": "Traversal direction."},
                "depth": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Traversal depth (default 1)."},
                "maxTokens": dict(_MAX_TOKENS_PROPERTY, description="Token budget for the neighborhood (default 1200)."),
            },
            required=["target"],
        ),
    },
    {
        "name": "codebase_context",
        "description": (
            "Task-aware context pack: rank and excerpt the smallest reliable context for a task under maxTokens, with "
            "path:line citations and explicit omitted items. Prefer this over reading many files when orienting."
        ),
        "inputSchema": _schema(
            {
                "task": {"type": "string", "description": "Task or question the context is selected for (required)."},
                "maxTokens": dict(_MAX_TOKENS_PROPERTY, description="Token budget for the pack (default 2200)."),
                "pathPrefix": {"type": "string", "description": "Restrict retrieval to paths under this prefix."},
            },
            required=["task"],
        ),
    },
    {
        "name": "codebase_impact",
        "description": (
            "Conservative change-impact preview: affected files and symbols for the changed files/symbols, with "
            "confidence and reason labels. Heuristic edges are marked; unresolved relationships are not asserted."
        ),
        "inputSchema": _schema(
            {
                "files": {"type": "array", "items": {"type": "string"}, "description": "Changed repository-relative file paths."},
                "symbols": {"type": "array", "items": {"type": "string"}, "description": "Changed symbol names or ids."},
                "maxTokens": dict(_MAX_TOKENS_PROPERTY, description="Token budget for the preview (default 1200)."),
            }
        ),
    },
]

_TOOL_NAMES = {tool["name"] for tool in TOOL_DEFINITIONS}


def _error_text(error: CbiError, *, tool: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "schemaVersion": "1"}
    if tool:
        payload["command"] = tool
    payload["error"] = error.to_dict()
    return payload


class McpServer:
    """One MCP session bound to a repository root."""

    def __init__(self, root: Path, *, cache_dir: Path | None = None):
        self.root = root
        self.cache_dir = cache_dir

    # -- tool dispatch ------------------------------------------------------
    def _call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        args = dict(arguments or {})
        max_tokens = args.get("maxTokens")
        if name == "codebase_overview":
            return api.run_overview(
                self.root,
                cache_dir=self.cache_dir,
                max_tokens=max_tokens,
                force=bool(args.get("refresh", False)),
            )
        if name == "codebase_map":
            return api.run_map(
                self.root,
                cache_dir=self.cache_dir,
                max_tokens=max_tokens,
                focus=args.get("focus"),
            )
        if name == "codebase_search":
            return api.run_search(
                self.root,
                str(args.get("query", "")),
                cache_dir=self.cache_dir,
                max_tokens=max_tokens,
            )
        if name == "codebase_dependencies":
            return api.run_dependencies(
                self.root,
                str(args.get("target", "")),
                direction=str(args.get("direction", "both")),
                depth=int(args.get("depth", 1) or 1),
                cache_dir=self.cache_dir,
                max_tokens=max_tokens,
            )
        if name == "codebase_context":
            return api.run_context(
                self.root,
                str(args.get("task", "")),
                max_tokens=max_tokens,
                path_prefix=args.get("pathPrefix"),
                cache_dir=self.cache_dir,
            )
        if name == "codebase_impact":
            files = args.get("files") or ()
            symbols = args.get("symbols") or ()
            if isinstance(files, str):
                files = [files]
            if isinstance(symbols, str):
                symbols = [symbols]
            return api.run_impact(
                self.root,
                files=list(files),
                symbols=list(symbols),
                max_tokens=max_tokens,
                cache_dir=self.cache_dir,
            )
        raise UsageError(f"unknown tool {name!r}")

    def _tools_call_result(self, request_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or name not in _TOOL_NAMES:
            return self._rpc_error(request_id, -32602, f"unknown tool {name!r}")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            return self._rpc_error(request_id, -32602, "arguments must be an object")
        try:
            payload = self._call_tool(name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": canonical_json(payload)}], "isError": False},
            }
        except CbiError as error:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": canonical_json(_error_text(error, tool=name))}],
                    "isError": True,
                },
            }
        except Exception as error:  # noqa: BLE001 - tool calls must not kill the server
            internal = CbiError(f"{type(error).__name__}: {error}", code="internal_error")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": canonical_json(_error_text(internal, tool=name))}],
                    "isError": True,
                },
            }

    # -- JSON-RPC ----------------------------------------------------------
    @staticmethod
    def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def handle(self, request: Any) -> dict[str, Any] | None:
        if not isinstance(request, Mapping):
            return self._rpc_error(None, -32600, "invalid request")
        method = request.get("method")
        request_id = request.get("id")
        is_notification = "id" not in request or request_id is None
        if not isinstance(method, str):
            return self._rpc_error(request_id, -32600, "invalid request")
        params = request.get("params") or {}
        if not isinstance(params, Mapping):
            return self._rpc_error(request_id, -32602, "params must be an object")

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": ENGINE_VERSION},
                },
            }
        if method in {"notifications/initialized", "notifications/cancelled"} or is_notification:
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOL_DEFINITIONS}}
        if method == "tools/call":
            return self._tools_call_result(request_id, params)
        return self._rpc_error(request_id, -32601, f"method not found: {method}")

    # -- stdio loop --------------------------------------------------------
    def serve(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        source = stdin if stdin is not None else sys.stdin
        sink = stdout if stdout is not None else sys.stdout
        for raw_line in source:
            line = raw_line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                response: dict[str, Any] | None = self._rpc_error(None, -32700, f"parse error: {exc.msg}")
            else:
                response = self.handle(request)
            if response is not None:
                sink.write(canonical_json(response) + "\n")
                sink.flush()


def serve(root: Path, *, cache_dir: Path | None = None, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    """Run the stdio MCP server for ``root`` until EOF."""

    McpServer(root, cache_dir=cache_dir).serve(stdin=stdin, stdout=stdout)
