"""Codebase Intelligence: local-first repository understanding.

Public surface: the canonical model, the scanner/parser/graph engine, retrieval
and reporting, a CLI (``cbi``), a stdio MCP server and the DeepSeek Harness
plugin bridge (which drives the same CLI).  See ``docs/SPEC.md``.
"""

from __future__ import annotations

from codebase_intelligence.model import SCHEMA_VERSION

__version__ = "0.1.0"
ENGINE_VERSION = __version__

__all__ = ["ENGINE_VERSION", "SCHEMA_VERSION", "__version__"]
