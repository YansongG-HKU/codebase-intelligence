"""Typed result objects for graph queries (part of the public engine contract).

The shapes are normative ``docs/SPEC.md`` §7: reporting builds the ``impact``
payload directly from these records, so field names are not incidental.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Confidence labels allowed on impact entries (``docs/SPEC.md`` §7).
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
_CONFIDENCE_RANK = {CONFIDENCE_HIGH: 3, CONFIDENCE_MEDIUM: 2, CONFIDENCE_LOW: 1}


def confidence_rank(confidence: str) -> int:
    """Rank a confidence label so callers can keep the strongest claim."""

    return _CONFIDENCE_RANK.get(confidence, 0)


@dataclass(frozen=True, slots=True)
class ImpactEntry:
    """One affected file: how far it is, how sure we are, and why."""

    path: str
    distance: int
    confidence: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "distance": self.distance,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ImpactSymbolEntry:
    """One affected symbol (a symbol-level edge, not a file-level guess)."""

    id: str
    path: str
    name: str
    distance: int
    confidence: str

    @property
    def symbol(self) -> str:
        """Payload-facing alias used by the ``impact`` shape in SPEC §10."""

        return self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "symbol": self.name,
            "distance": self.distance,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ImpactResult:
    """Conservative blast radius for a set of changed files/symbols."""

    changed_files: tuple[str, ...] = ()
    changed_symbols: tuple[str, ...] = ()
    affected_files: tuple[ImpactEntry, ...] = ()
    affected_symbols: tuple[ImpactSymbolEntry, ...] = ()
    truncated: bool = False

    def is_empty(self) -> bool:
        return not self.changed_files and not self.changed_symbols

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": {
                "files": list(self.changed_files),
                "symbols": list(self.changed_symbols),
            },
            "affectedFiles": [entry.to_dict() for entry in self.affected_files],
            "affectedSymbols": [entry.to_dict() for entry in self.affected_symbols],
            "truncated": self.truncated,
        }


__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "ImpactEntry",
    "ImpactResult",
    "ImpactSymbolEntry",
    "confidence_rank",
]
