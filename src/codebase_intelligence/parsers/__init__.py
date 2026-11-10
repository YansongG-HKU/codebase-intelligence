"""Language-aware parsing: the entry point every index build goes through.

``parse_file`` dispatches on the scanned file's language:

* Python → standard-library :mod:`ast` adapter (``EvidenceKind.PARSER``);
* JavaScript, TypeScript, Go, Rust, Java, C, C++, C#, Ruby, PHP, Shell →
  conservative regex adapters (``EvidenceKind.HEURISTIC``);
* anything else → an empty :class:`ParseResult` with no issue: the file is
  indexed as a file only (``docs/SPEC.md`` §6).

``PARSER_VERSIONS`` is part of the incremental-index cache key: when an adapter
changes in a way that changes its output, bump its version string so cached
parse results are invalidated.  ``parser_versions_digest()`` is the canonical
hash of that mapping (sorted keys, UTF-8, no whitespace).
"""

from __future__ import annotations

from codebase_intelligence.model import FileRecord, Language, ParseIssue
from codebase_intelligence.parsers.base import ParseResult, make_issue
from codebase_intelligence.parsers.heuristic import (
    HEURISTIC_LANGUAGES,
    PARSER_VERSION as HEURISTIC_PARSER_VERSION,
    parse_heuristic,
)
from codebase_intelligence.parsers.python_adapter import (
    PARSER_VERSION as PYTHON_PARSER_VERSION,
    parse_python,
)
from codebase_intelligence.util import bounded_text, canonical_json, sha256_text

#: Bump the relevant value whenever an adapter's output contract changes.
PARSER_VERSIONS: dict[Language, str] = {
    Language.PYTHON: PYTHON_PARSER_VERSION,
    **{language: HEURISTIC_PARSER_VERSION for language in HEURISTIC_LANGUAGES},
}

#: Languages with a dedicated adapter (everything else is file-only indexing).
SUPPORTED_LANGUAGES: tuple[Language, ...] = (
    Language.PYTHON,
    *HEURISTIC_LANGUAGES,
)

_MAX_FALLBACK_MESSAGE = 300


def parser_versions_digest() -> str:
    """Canonical hash of :data:`PARSER_VERSIONS` (used as a cache generation)."""

    return sha256_text(canonical_json(PARSER_VERSIONS))


def parser_version_for(language: Language) -> str:
    """Adapter version for *language*, or ``""`` when the language has none."""

    return PARSER_VERSIONS.get(language, "")


def parse_file(file: FileRecord, text: str) -> ParseResult:
    """Extract symbols, raw relations and bounded issues from one file.

    This function is the only public parsing entry point.  It never raises for
    input-related problems: syntax errors and unexpected adapter failures are
    returned as :class:`ParseIssue` records so one bad file can never abort an
    index build.
    """

    try:
        if file.language is Language.PYTHON:
            return parse_python(file, text)
        if file.language in HEURISTIC_LANGUAGES:
            return parse_heuristic(file, text)
        # Unsupported language: indexed as a file only, no symbols, no issues.
        return ParseResult()
    except Exception as exc:  # noqa: BLE001 - last-resort boundary for untrusted input
        message = f"parser for {file.language.value} failed: {type(exc).__name__}: {exc}"
        issue = ParseIssue(path=file.path, message=bounded_text(message, _MAX_FALLBACK_MESSAGE))
        return ParseResult(issues=(issue,))


__all__ = [
    "HEURISTIC_LANGUAGES",
    "PARSER_VERSIONS",
    "SUPPORTED_LANGUAGES",
    "ParseIssue",
    "ParseResult",
    "make_issue",
    "parse_file",
    "parser_version_for",
    "parser_versions_digest",
]
