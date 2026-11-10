"""Utility helpers."""

from __future__ import annotations


def clamp(value: int, low: int, high: int) -> int:
    """Clamp a value into the inclusive range."""
    if value < low:
        return low
    if value > high:
        return high
    return value


def estimate(rows: int, per_row: int = 4) -> int:
    """Estimate a token budget from rows."""
    return rows * per_row


def helper_used_by_sub(path: str) -> str:
    """Normalization helper used by the subpackage."""
    return path.strip()
