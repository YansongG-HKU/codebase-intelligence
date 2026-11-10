"""Protocol-level tests for the stdio MCP server (docs/SPEC.md §12).

These do not need a real index: they pin the JSON-RPC surface, the tool catalogue
and the token footprint of the tool schemas.  End-to-end tool calls are covered
in tests/test_cli.py against a fixture repository.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from codebase_intelligence.mcp.server import PROTOCOL_VERSION, TOOL_DEFINITIONS, McpServer, serve
from codebase_intelligence.util import canonical_json, estimate_tokens

EXPECTED_TOOLS = {
    "codebase_overview",
    "codebase_map",
    "codebase_search",
    "codebase_dependencies",
    "codebase_context",
    "codebase_impact",
}


def _server(tmp_path: Path) -> McpServer:
    return McpServer(tmp_path)


def test_initialize_reports_protocol_and_server_info(tmp_path: Path) -> None:
    response = _server(tmp_path).handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response is not None
    result = response["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"]["name"] == "codebase-intelligence"
    assert isinstance(result["serverInfo"]["version"], str)


def test_tools_list_pins_names_and_schemas(tmp_path: Path) -> None:
    response = _server(tmp_path).handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert response is not None
    tools = response["result"]["tools"]
    assert {tool["name"] for tool in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool["description"].strip()
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        for prop in schema["properties"].values():
            assert "type" in prop or "enum" in prop


def test_tool_schema_footprint_is_bounded() -> None:
    """The catalogue is paid on every session; keep the prompt cost honest."""

    text = canonical_json(TOOL_DEFINITIONS)
    # chars4-wide-v1 estimate; a generous ceiling that still catches bloat.
    assert estimate_tokens(text) <= 2200, f"tool schema footprint grew: {estimate_tokens(text)} tokens"


def test_unknown_method_and_unknown_tool_are_structured_errors(tmp_path: Path) -> None:
    server = _server(tmp_path)
    method_error = server.handle({"jsonrpc": "2.0", "id": 3, "method": "no/such"})
    assert method_error is not None
    assert method_error["error"]["code"] == -32601

    tool_error = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "codebase_nope", "arguments": {}},
        }
    )
    assert tool_error is not None
    assert tool_error["error"]["code"] == -32602


def test_notifications_get_no_response_and_ping_works(tmp_path: Path) -> None:
    server = _server(tmp_path)
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    pong = server.handle({"jsonrpc": "2.0", "id": 5, "method": "ping"})
    assert pong == {"jsonrpc": "2.0", "id": 5, "result": {}}


def test_stdio_loop_is_newline_delimited_json(tmp_path: Path) -> None:
    requests = [
        {"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 11, "method": "tools/list"},
    ]
    stdin = io.StringIO("\n".join(json.dumps(item) for item in requests) + "\n")
    stdout = io.StringIO()
    serve(tmp_path, stdin=stdin, stdout=stdout)
    lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
    assert len(lines) == 2
    responses = [json.loads(line) for line in lines]
    assert [item["id"] for item in responses] == [10, 11]
    assert all(item["jsonrpc"] == "2.0" for item in responses)


def test_invalid_json_line_returns_parse_error(tmp_path: Path) -> None:
    stdout = io.StringIO()
    serve(tmp_path, stdin=io.StringIO("{not json}\n"), stdout=stdout)
    response = json.loads(stdout.getvalue().strip())
    assert response["error"]["code"] == -32700


# -- real tool calls against the fixture repository -------------------------
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cli" / "demo_repo"


def _tool_call(server: McpServer, tool: str, arguments: dict | None) -> dict:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }
    )
    assert response is not None
    return response["result"]


def test_tools_call_overview_is_real_and_deterministic(tmp_path: Path) -> None:
    server = McpServer(FIXTURE, cache_dir=tmp_path / "cache")
    first = _tool_call(server, "codebase_overview", {"maxTokens": 500})
    second = _tool_call(server, "codebase_overview", {"maxTokens": 500})
    assert first["isError"] is False
    text = first["content"][0]["text"]
    payload = json.loads(text)
    assert payload["ok"] is True
    assert payload["budgets"]["tokensEstimated"] <= 500
    assert payload["index"]["fingerprint"]
    assert str(FIXTURE) not in text
    assert second["content"][0]["text"] == text


def test_tools_call_context_returns_citations(tmp_path: Path) -> None:
    server = McpServer(FIXTURE, cache_dir=tmp_path / "cache")
    result = _tool_call(server, "codebase_context", {"task": "clamp helper", "maxTokens": 600})
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["items"]
    assert any(item["path"].endswith(".py") and item["startLine"] >= 1 for item in payload["items"])


def test_tools_call_error_is_tool_error_not_transport_error(tmp_path: Path) -> None:
    server = McpServer(FIXTURE, cache_dir=tmp_path / "cache")
    result = _tool_call(server, "codebase_search", {})
    assert result["isError"] is True
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
