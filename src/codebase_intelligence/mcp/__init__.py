"""Stdio MCP server package: ``python -m codebase_intelligence.mcp``."""

from codebase_intelligence.mcp.server import McpServer, TOOL_DEFINITIONS, serve

__all__ = ["McpServer", "TOOL_DEFINITIONS", "serve"]
