"""Shared parser-adapter contract and helpers.

Every adapter turns one :class:`FileRecord` plus its decoded text into a
:class:`ParseResult`.  The contract in ``docs/SPEC.md`` §6 is deliberately small:

* a parser *never* raises on malformed source input — syntax errors become
  :class:`ParseIssue` records with bounded messages;
* a parser *never* executes the code it reads (Python uses :mod:`ast`, the other
  adapters are pure regular expressions);
* every symbol records where it came from (:class:`EvidenceKind.PARSER` for the
  Python syntax tree, :class:`EvidenceKind.HEURISTIC` for regex extraction);
* imports are emitted as raw, unresolved ``IMPORTS`` relations carrying the
  original specifier in ``target_name``.  Resolution is the graph's job
  (``docs/SPEC.md`` §7), never the parser's.

The helpers here are shared by both adapters so ids, spans and ordering stay
consistent — the index fingerprint depends on them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from codebase_intelligence.model import (
    EvidenceKind,
    FileRecord,
    ParseIssue,
    RelationRecord,
    RelationType,
    ResolutionStatus,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
    symbol_id,
)
from codebase_intelligence.util import bounded_text, to_posix

#: Parsers must keep failure records short and actionable (SPEC §6).
MAX_ISSUE_MESSAGE_CHARS = 300
#: Signatures/docstrings are embedded in model payloads; keep them bounded too.
MAX_SIGNATURE_CHARS = 240
MAX_DOC_CHARS = 600
#: Hard safety valves against pathological inputs; truncation is reported.
MAX_SYMBOLS_PER_FILE = 2_000
MAX_RELATIONS_PER_FILE = 4_000


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Everything one adapter extracted from one file."""

    symbols: tuple[SymbolRecord, ...] = ()
    relations: tuple[RelationRecord, ...] = ()
    issues: tuple[ParseIssue, ...] = ()

    def normalized(self) -> "ParseResult":
        """Return the same result with the canonical ordering applied.

        ``IndexSnapshot.build`` re-sorts anyway, but adapters share their output
        in tests and in the incremental cache; a stable order there makes cache
        bytes and parser tests deterministic for free.
        """

        ordered_symbols = tuple(
            sorted(
                self.symbols,
                key=lambda item: (
                    item.path,
                    item.span.start_line,
                    item.kind.value,
                    item.qualified_name,
                ),
            )
        )
        ordered_relations = tuple(
            sorted(
                self.relations,
                key=lambda item: (
                    item.source_id,
                    item.relation_type.value,
                    item.target_id or "",
                    item.target_name or "",
                    item.span.start_line if item.span else 0,
                ),
            )
        )
        ordered_issues = tuple(sorted(self.issues, key=lambda item: (item.path, item.message)))
        return ParseResult(
            symbols=ordered_symbols,
            relations=ordered_relations,
            issues=ordered_issues,
        )


def module_names(path: str) -> tuple[str, str]:
    """Return ``(name, qualified_name)`` for the module symbol of *path*.

    The dotted name is derived from the repository-relative path so it is stable
    across machines: ``pkg/mod.py`` → ``("mod", "pkg.mod")`` and
    ``pkg/__init__.py`` → ``("pkg", "pkg")``.  Resolution in the graph uses the
    same convention, so symbols and imports agree on module identity.
    """

    posix = to_posix(path)
    parts = [part for part in posix.split("/") if part not in ("", ".")]
    if not parts:
        return ("", "")
    filename = parts[-1]
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    if stem == "__init__" and len(parts) > 1:
        parts = parts[:-1]
        return (parts[-1], ".".join(parts))
    parts = parts[:-1] + [stem]
    dotted = ".".join(parts)
    return (stem, dotted)


def module_symbol(file: FileRecord, *, evidence: EvidenceKind = EvidenceKind.PARSER) -> SymbolRecord:
    """Create the per-file ``module`` symbol every adapter starts from."""

    name, qualified = module_names(file.path)
    line_count = int(file.line_count) if file.line_count > 0 else 1
    return SymbolRecord(
        id=symbol_id(file.path, SymbolKind.MODULE, qualified, 1),
        path=file.path,
        name=name or file.path,
        qualified_name=qualified or file.path,
        kind=SymbolKind.MODULE,
        language=file.language,
        span=SourceSpan(path=file.path, start_line=1, end_line=max(1, line_count)),
        parent_id=None,
        signature=None,
        doc=None,
        evidence=evidence,
    )


def make_symbol(
    file: FileRecord,
    *,
    name: str,
    qualified_name: str,
    kind: SymbolKind,
    start_line: int,
    end_line: int | None = None,
    parent_id: str | None = None,
    signature: str | None = None,
    doc: str | None = None,
    evidence: EvidenceKind = EvidenceKind.PARSER,
    start_column: int = 0,
    end_column: int = 0,
) -> SymbolRecord:
    """Build a :class:`SymbolRecord` with a stable id and bounded text fields."""

    line = max(1, int(start_line))
    end = max(line, int(end_line)) if end_line is not None else line
    return SymbolRecord(
        id=symbol_id(file.path, kind, qualified_name, line),
        path=file.path,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        language=file.language,
        span=SourceSpan(
            path=file.path,
            start_line=line,
            end_line=end,
            start_column=max(0, start_column),
            end_column=max(0, end_column),
        ),
        parent_id=parent_id,
        signature=bounded_text(signature, MAX_SIGNATURE_CHARS) if signature else None,
        doc=bounded_text(doc, MAX_DOC_CHARS) if doc else None,
        evidence=evidence,
    )


def make_relation(
    *,
    source_id: str,
    relation_type: RelationType,
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    status: ResolutionStatus = ResolutionStatus.UNRESOLVED,
    evidence: EvidenceKind = EvidenceKind.PARSER,
    confidence: float = 0.0,
) -> RelationRecord:
    """Build a :class:`RelationRecord` whose target name is bounded."""

    line = max(1, int(start_line))
    span = SourceSpan(
        path=path,
        start_line=line,
        end_line=max(line, int(end_line)) if end_line is not None else line,
    )
    return RelationRecord(
        source_id=source_id,
        relation_type=relation_type,
        status=status,
        evidence=evidence,
        target_id=target_id,
        target_name=bounded_text(target_name, MAX_ISSUE_MESSAGE_CHARS) if target_name else None,
        span=span,
        confidence=round(float(confidence), 4),
    )


def make_issue(path: str, message: str) -> ParseIssue:
    """Create a bounded :class:`ParseIssue` (never an exception)."""

    return ParseIssue(path=path, message=bounded_text(str(message), MAX_ISSUE_MESSAGE_CHARS))


def finalize(
    file: FileRecord,
    *,
    symbols: Iterable[SymbolRecord],
    relations: Iterable[RelationRecord],
    issues: Iterable[ParseIssue] = (),
) -> ParseResult:
    """Apply per-file safety caps and the canonical order."""

    symbol_list = list(symbols)
    relation_list = list(relations)
    issue_list = list(issues)
    if len(symbol_list) > MAX_SYMBOLS_PER_FILE:
        symbol_list = symbol_list[:MAX_SYMBOLS_PER_FILE]
        issue_list.append(make_issue(file.path, "symbol limit reached; declarations truncated"))
    if len(relation_list) > MAX_RELATIONS_PER_FILE:
        relation_list = relation_list[:MAX_RELATIONS_PER_FILE]
        issue_list.append(make_issue(file.path, "relation limit reached; edges truncated"))
    return ParseResult(
        symbols=tuple(symbol_list),
        relations=tuple(relation_list),
        issues=tuple(issue_list),
    ).normalized()


# ---------------------------------------------------------------------------
# Span helpers shared with the regex adapters (pure functions, no I/O)
# ---------------------------------------------------------------------------
def line_starts(text: str) -> list[int]:
    """Offsets of the beginning of every line (0-based list of char offsets)."""

    starts = [0]
    index = text.find("\n")
    while index != -1:
        starts.append(index + 1)
        index = text.find("\n", index + 1)
    return starts


def line_of(starts: list[int], offset: int) -> int:
    """1-based line number for a character *offset* (binary search)."""

    if not starts:
        return 1
    low, high = 0, len(starts) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if starts[middle] <= offset:
            low = middle
        else:
            high = middle - 1
    return low + 1


def block_end_line(text: str, offset: int, starts: list[int], *, max_scan: int = 200_000) -> int:
    """Best-effort end line of a brace-delimited block starting at/near *offset*.

    Regex adapters are allowed to be approximate, but a wrong span would put a
    declaration's ``endLine`` in the wrong place for context excerpts, so we
    brace-match the body with a bounded, string/comment-aware scanner.  When no
    block is found the declaration is reported as a one-line span — honest and
    deterministic, never an exception.
    """

    start_line = line_of(starts, offset)
    open_at = text.find("{", offset, min(len(text), offset + 4_096))
    if open_at == -1:
        return start_line
    depth = 0
    index = open_at
    limit = min(len(text), open_at + max_scan)
    quote: str | None = None
    while index < limit:
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ("'", '"', "`"):
            quote = char
            index += 1
            continue
        if char == "/" and index + 1 < limit:
            following = text[index + 1]
            if following == "/":
                newline = text.find("\n", index + 2, limit)
                if newline == -1:
                    break
                index = newline + 1
                continue
            if following == "*":
                closing = text.find("*/", index + 2, limit)
                if closing == -1:
                    break
                index = closing + 2
                continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return line_of(starts, index)
        index += 1
    return start_line


__all__ = [
    "MAX_DOC_CHARS",
    "MAX_ISSUE_MESSAGE_CHARS",
    "MAX_RELATIONS_PER_FILE",
    "MAX_SIGNATURE_CHARS",
    "MAX_SYMBOLS_PER_FILE",
    "ParseResult",
    "block_end_line",
    "finalize",
    "line_of",
    "line_starts",
    "make_issue",
    "make_relation",
    "make_symbol",
    "module_names",
    "module_symbol",
]
