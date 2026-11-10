"""Canonical model package: parser-independent entities and provenance."""

from codebase_intelligence.model.entities import (
    SCHEMA_VERSION,
    CacheStats,
    EvidenceKind,
    FileRecord,
    IndexSnapshot,
    Language,
    ParseIssue,
    RelationRecord,
    RelationType,
    ResolutionStatus,
    ScanStats,
    SourceSpan,
    SymbolKind,
    SymbolRecord,
    file_id,
    symbol_id,
)

__all__ = [
    "SCHEMA_VERSION",
    "CacheStats",
    "EvidenceKind",
    "FileRecord",
    "IndexSnapshot",
    "Language",
    "ParseIssue",
    "RelationRecord",
    "RelationType",
    "ResolutionStatus",
    "ScanStats",
    "SourceSpan",
    "SymbolKind",
    "SymbolRecord",
    "file_id",
    "symbol_id",
]
