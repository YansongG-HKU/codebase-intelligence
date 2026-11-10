"""Core engine module."""

from __future__ import annotations

from demo.util import clamp


class Engine:
    """Small computation engine."""

    def __init__(self, limit: int = 10) -> None:
        self.limit = limit
        self._count = 0

    def run(self, value: int) -> int:
        """Clamp the value and count the run."""
        self._count += 1
        return clamp(value, 0, self.limit)

    def status(self) -> dict[str, int]:
        return {"count": self._count, "limit": self.limit}


def build(limit: int = 10) -> Engine:
    """Create an engine with the given limit."""
    return Engine(limit=limit)


def main() -> None:
    """Entry point."""
    engine = build()
    print(engine.run(42))
