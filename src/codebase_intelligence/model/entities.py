"""Canonical, parser-independent code model.

Everything the engine extracts is expressed with these frozen dataclasses before
it is stored, ranked, rendered or sent to a model.  The separation is
deliberate and is part of the product contract:

* :class:`FileRecord` / :class:`SourceSpan` are *facts*: a path, a byte size, a
  content hash and a line range.
* :class:`SymbolRecord` is a *parser fact* with an :class:`EvidenceKind` label
  (``parser`` for syntax-tree extraction, ``heuristic`` for regex fallbacks).
* :class:`RelationRecord` carries its resolution status and confidence; an
  unresolved or ambiguous edge is preserved and labelled, never silently
  promoted to a dependency.

Field names are serialized as camelCase in JSON; the canonical ordering of
files, symbols and relations is defined in :meth:`IndexSnapshot.build` and is
part of the cache contract (see ``docs/SPEC.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Iterable, Mapping

from codebase_intelligence.util import canonical_json, sha256_text

#: Version of the persisted/indexed JSON shape. Bump on incompatible changes.
SCHEMA_VERSION = "1"


class Language(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    RUST = "rust"
    JAVA = "java"
    C = "c"
    CPP = "cpp"
    CSHARP = "csharp"
    RUBY = "ruby"
    PHP = "php"
    SHELL = "shell"
    HTML = "html"
    CSS = "css"
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"
    MARKDOWN = "markdown"
    SQL = "sql"
    OTHER = "other"


class SymbolKind(StrEnum):
    MODULE = "module"
    PACKAGE = "package"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    CONSTANT = "constant"
    VARIABLE = "variable"
    INTERFACE = "interface"
    TYPE = "type"
    ENUM = "enum"
    STRUCT = "struct"
    TRAIT = "trait"
    MACRO = "macro"


class RelationType(StrEnum):
    CONTAINS = "contains"
    DEFINES = "defines"
    IMPORTS = "imports"
    REFERENCES = "references"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    CALLS = "calls"


class EvidenceKind(StrEnum):
    """Where a structural claim came from (never conflate these)."""

    PARSER = "parser"
    RESOLVER = "resolver"
    HEURISTIC = "heuristic"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    EXTERNAL = "external"


def file_id(path: str) -> str:
    """Stable identifier for a repository file."""

    return f"file:{path}"


def symbol_id(path: str, kind: str | SymbolKind, qualified_name: str, start_line: int) -> str:
    """Stable identifier for a symbol (line-aware to survive overloads/dupes)."""

    return f"sym:{path}#{kind}:{qualified_name}@{start_line}"


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A 1-based line range (and optional 0-based columns) inside one file."""

    path: str
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "startLine": self.start_line,
            "endLine": self.end_line,
            "startColumn": self.start_column,
            "endColumn": self.end_column,
        }


@dataclass(frozen=True, slots=True)
class FileRecord:
    """One indexed text file, identified by a repo-relative POSIX path."""

    path: str
    language: Language
    size_bytes: int
    sha256: str
    line_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language.value,
            "sizeBytes": self.size_bytes,
            "sha256": self.sha256,
            "lineCount": self.line_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FileRecord":
        return cls(
            path=str(data["path"]),
            language=Language(data["language"]),
            size_bytes=int(data["sizeBytes"]),
            sha256=str(data["sha256"]),
            line_count=int(data["lineCount"]),
        )


@dataclass(frozen=True, slots=True)
class SymbolRecord:
    """A declaration extracted from one file, with evidence and location."""

    id: str
    path: str
    name: str
    qualified_name: str
    kind: SymbolKind
    language: Language
    span: SourceSpan
    parent_id: str | None = None
    signature: str | None = None
    doc: str | None = None
    evidence: EvidenceKind = EvidenceKind.PARSER

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "qualifiedName": self.qualified_name,
            "kind": self.kind.value,
            "language": self.language.value,
            "span": self.span.to_dict(),
            "parentId": self.parent_id,
            "signature": self.signature,
            "doc": self.doc,
            "evidence": self.evidence.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SymbolRecord":
        span = data["span"]
        return cls(
            id=str(data["id"]),
            path=str(data["path"]),
            name=str(data["name"]),
            qualified_name=str(data["qualifiedName"]),
            kind=SymbolKind(data["kind"]),
            language=Language(data["language"]),
            span=SourceSpan(
                path=str(span["path"]),
                start_line=int(span["startLine"]),
                end_line=int(span["endLine"]),
                start_column=int(span.get("startColumn", 0)),
                end_column=int(span.get("endColumn", 0)),
            ),
            parent_id=str(data["parentId"]) if data.get("parentId") else None,
            signature=str(data["signature"]) if data.get("signature") else None,
            doc=str(data["doc"]) if data.get("doc") else None,
            evidence=EvidenceKind(data.get("evidence", EvidenceKind.PARSER.value)),
        )


@dataclass(frozen=True, slots=True)
class RelationRecord:
    """One edge between a source file/symbol and a target (may be unresolved)."""

    source_id: str
    relation_type: RelationType
    status: ResolutionStatus
    evidence: EvidenceKind
    target_id: str | None = None
    target_name: str | None = None
    span: SourceSpan | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.source_id,
            "to": self.target_id,
            "targetName": self.target_name,
            "type": self.relation_type.value,
            "status": self.status.value,
            "evidence": self.evidence.value,
            "span": self.span.to_dict() if self.span else None,
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelationRecord":
        span_data = data.get("span")
        span = None
        if isinstance(span_data, Mapping):
            span = SourceSpan(
                path=str(span_data["path"]),
                start_line=int(span_data["startLine"]),
                end_line=int(span_data["endLine"]),
                start_column=int(span_data.get("startColumn", 0)),
                end_column=int(span_data.get("endColumn", 0)),
            )
        return cls(
            source_id=str(data["from"]),
            relation_type=RelationType(data["type"]),
            status=ResolutionStatus(data["status"]),
            evidence=EvidenceKind(data["evidence"]),
            target_id=str(data["to"]) if data.get("to") else None,
            target_name=str(data["targetName"]) if data.get("targetName") else None,
            span=span,
            confidence=float(data.get("confidence", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class ParseIssue:
    """A bounded, honest record of an input a parser could not fully handle."""

    path: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "message": self.message}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ParseIssue":
        return cls(path=str(data["path"]), message=str(data["message"]))


@dataclass(frozen=True, slots=True)
class ScanStats:
    """Counters for one scan (diagnostics only — never in tool payloads)."""

    files_indexed: int
    bytes_indexed: int
    directories_visited: int
    skipped: tuple[tuple[str, int], ...] = ()

    def skip_map(self) -> dict[str, int]:
        return {reason: count for reason, count in self.skipped}

    def to_dict(self) -> dict[str, Any]:
        return {
            "filesIndexed": self.files_indexed,
            "bytesIndexed": self.bytes_indexed,
            "directoriesVisited": self.directories_visited,
            "skipped": self.skip_map(),
        }


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Incremental-index counters (diagnostics only — never in tool payloads)."""

    files_reused: int = 0
    files_reparsed: int = 0
    files_removed: int = 0
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "filesReused": self.files_reused,
            "filesReparsed": self.files_reparsed,
            "filesRemoved": self.files_removed,
            "cacheHit": self.cache_hit,
        }


@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    """One immutable index state: files + symbols + relations + provenance."""

    schema_version: str
    engine_version: str
    policy_fingerprint: str
    files: tuple[FileRecord, ...]
    symbols: tuple[SymbolRecord, ...]
    relations: tuple[RelationRecord, ...]
    parse_issues: tuple[ParseIssue, ...] = ()
    #: Absolute root used at build time; deliberately excluded from serialization.
    root: str = ""
    #: Memoized content fingerprint (not part of equality/serialization).
    _fingerprint_cache: str | None = field(default=None, compare=False, repr=False)

    # -- construction ------------------------------------------------------
    @classmethod
    def build(
        cls,
        *,
        engine_version: str,
        policy_fingerprint: str,
        root: str,
        files: Iterable[FileRecord],
        symbols: Iterable[SymbolRecord],
        relations: Iterable[RelationRecord],
        parse_issues: Iterable[ParseIssue] = (),
    ) -> "IndexSnapshot":
        """Normalize ordering so the same inputs always yield the same bytes."""

        ordered_files = tuple(sorted(files, key=lambda item: item.path))
        ordered_symbols = tuple(
            sorted(
                symbols,
                key=lambda item: (item.path, item.span.start_line, item.kind.value, item.qualified_name),
            )
        )
        ordered_relations = tuple(
            sorted(
                relations,
                key=lambda item: (
                    item.source_id,
                    item.relation_type.value,
                    item.target_id or "",
                    item.target_name or "",
                    item.span.start_line if item.span else 0,
                ),
            )
        )
        ordered_issues = tuple(sorted(parse_issues, key=lambda item: (item.path, item.message)))
        return cls(
            schema_version=SCHEMA_VERSION,
            engine_version=engine_version,
            policy_fingerprint=policy_fingerprint,
            files=ordered_files,
            symbols=ordered_symbols,
            relations=ordered_relations,
            parse_issues=ordered_issues,
            root=root,
        )

    # -- indexes -----------------------------------------------------------
    def index_maps(
        self,
    ) -> tuple[
        dict[str, FileRecord],
        dict[str, SymbolRecord],
        dict[str, tuple[SymbolRecord, ...]],
    ]:
        """Return ``(files_by_path, symbols_by_id, symbols_by_file)``."""

        files_by_path = {item.path: item for item in self.files}
        symbols_by_id = {item.id: item for item in self.symbols}
        grouped: dict[str, list[SymbolRecord]] = {}
        for symbol in self.symbols:
            grouped.setdefault(symbol.path, []).append(symbol)
        symbols_by_file = {path: tuple(items) for path, items in grouped.items()}
        return files_by_path, symbols_by_id, symbols_by_file

    # -- serialization -----------------------------------------------------
    def public_dict(self) -> dict[str, Any]:
        """Deterministic payload without the absolute root or runtime counters."""

        return {
            "schemaVersion": self.schema_version,
            "engineVersion": self.engine_version,
            "policyFingerprint": self.policy_fingerprint,
            "fingerprint": self.fingerprint(),
            "files": [item.to_dict() for item in self.files],
            "symbols": [item.to_dict() for item in self.symbols],
            "relations": [item.to_dict() for item in self.relations],
            "parseIssues": [item.to_dict() for item in self.parse_issues],
        }

    def fingerprint(self) -> str:
        """Content hash of the model (files + symbols + relations + policy).

        The hash is computed once and memoized on the instance: budget-fitting
        renderers call it in a loop, and re-serializing a large model per
        candidate row made the repository map quadratic on real projects.
        """

        cached = self._fingerprint_cache
        if cached is not None:
            return cached
        value = self._compute_fingerprint()
        # Frozen dataclass: this is the documented internal cache write.
        object.__setattr__(self, "_fingerprint_cache", value)
        return value

    def _compute_fingerprint(self) -> str:
        payload = {
            "schemaVersion": self.schema_version,
            "engineVersion": self.engine_version,
            "policyFingerprint": self.policy_fingerprint,
            "files": [item.to_dict() for item in self.files],
            "symbols": [item.to_dict() for item in self.symbols],
            "relations": [item.to_dict() for item in self.relations],
            "parseIssues": [item.to_dict() for item in self.parse_issues],
        }
        return sha256_text(canonical_json(payload))

    @classmethod
    def from_public_dict(cls, data: Mapping[str, Any], *, root: str = "") -> "IndexSnapshot":
        files = tuple(FileRecord.from_dict(item) for item in data.get("files", ()))
        symbols = tuple(SymbolRecord.from_dict(item) for item in data.get("symbols", ()))
        relations = tuple(RelationRecord.from_dict(item) for item in data.get("relations", ()))
        issues = tuple(ParseIssue.from_dict(item) for item in data.get("parseIssues", ()))
        return cls(
            schema_version=str(data.get("schemaVersion", SCHEMA_VERSION)),
            engine_version=str(data.get("engineVersion", "0.0.0")),
            policy_fingerprint=str(data.get("policyFingerprint", "")),
            files=files,
            symbols=symbols,
            relations=relations,
            parse_issues=issues,
            root=root,
        )

    # -- convenience -------------------------------------------------------
    def with_root(self, root: str) -> "IndexSnapshot":
        return replace(self, root=root)

    def file_count(self) -> int:
        return len(self.files)

    def symbol_count(self) -> int:
        return len(self.symbols)

    def relation_count(self) -> int:
        return len(self.relations)

    def entry_points(self) -> tuple[SymbolRecord, ...]:
        """Candidate entry points (conservative, labelled as heuristics)."""

        return tuple(
            symbol
            for symbol in self.symbols
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.CLASS)
            and symbol.parent_id is None
            and symbol.name in {"main", "cli", "app", "server", "run"}
        )
