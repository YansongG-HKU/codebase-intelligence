"""Subpackage helper with a relative import."""

from __future__ import annotations

from demo.util import helper_used_by_sub

from ..core import Engine


def normalize(text: str) -> str:
    """Normalize text through the shared helper."""
    return helper_used_by_sub(text)


def run_engine() -> int:
    """Run the core engine with a small limit."""
    engine = Engine(limit=3)
    return engine.run(9)
