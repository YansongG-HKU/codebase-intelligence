"""Small, dependency-free helpers shared by the engine.

The project deliberately ships with **zero runtime dependencies**: everything
here is standard library.  These helpers are the only place where canonical
serialization, hashing and token estimation are defined; changing them changes
the index fingerprint, so treat them as part of the persisted format.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

#: Identifier of the token estimator used in every budgeted output.
TOKEN_ESTIMATOR = "chars4-wide-v1"


def canonical_json(value: Any) -> str:
    """Serialize with sorted keys and no insignificant whitespace.

    The exact bytes are part of the cache contract: two equivalent models must
    produce the same string so that index fingerprints and cached tool results
    stay stable.
    """

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8", errors="surrogateescape"))


def sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def to_posix(path: str | os.PathLike[str]) -> str:
    """Normalize to forward slashes so outputs are platform-independent."""

    return str(path).replace("\\", "/")


def relative_posix(root: Path, path: Path) -> str:
    """Render *path* relative to *root* as a POSIX string, never absolute."""

    try:
        rel = path.relative_to(root)
    except ValueError as exc:  # pragma: no cover - callers validate bounds first
        raise ValueError(f"{path} is not inside {root}") from exc
    return to_posix(rel)


def is_within(root: Path, candidate: Path) -> bool:
    """True when *candidate* resolves inside *root* (symlinks included)."""

    try:
        root_resolved = root.resolve(strict=True)
        candidate_resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError:
        return False
    return True


def bounded_text(text: str, max_chars: int, *, suffix: str = "…") -> str:
    """Truncate *text* to at most *max_chars* characters, including the suffix."""

    if len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(suffix))
    return text[:keep] + suffix


def estimate_tokens(text: str) -> int:
    """Estimate model tokens for *text* without shipping a tokenizer.

    Method (``chars4-wide-v1``): a tokenizer-independent lower/upper bound mix —
    every 4 ASCII characters count as one token, every non-ASCII character
    counts as one token (CJK text is roughly one token per character).  This is
    intentionally conservative for ASCII prose and code, and it is reported in
    every budgeted payload so callers can compare against a real tokenizer.
    """

    if not text:
        return 0
    ascii_chars = 0
    wide_chars = 0
    for char in text:
        if ord(char) < 128:
            ascii_chars += 1
        else:
            wide_chars += 1
    return max(1, math.ceil(ascii_chars / 4) + wide_chars)


def json_line(value: Any) -> str:
    """One deterministic JSON object followed by a newline (tool/stdio wire)."""

    return canonical_json(value) + "\n"


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def force_utf8_stdio() -> None:
    """Make stdout/stderr emit UTF-8 regardless of the Windows console code page.

    Repository paths and generated JSON may contain non-ASCII characters; the
    default GBK console encoding would otherwise make a valid payload fail with
    ``UnicodeEncodeError``.  Streams that cannot be reconfigured (test doubles,
    already-detached pipes) are left untouched.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            continue
