"""Tests for the canonical model in ``model/entities.py``.

The model is the persisted contract: field names, enum values, ordering, JSON
round trips and fingerprints are covered here because the index cache and every
tool payload depend on them staying byte-stable.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from codebase_intelligence.model import (
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
from codebase_intelligence.util import canonical_json, sha256_text

ENGINE_VERSION = "0.1.0-test"
POLICY_FINGERPRINT = "policy-fingerprint"


def make_file(
    path: str = "src/app.py",
    *,
    language: Language = Language.PYTHON,
    size_bytes: int = 10,
    sha: str = "a" * 64,
    line_count: int = 3,
) -> FileRecord:
    return FileRecord(
        path=path,
        language=language,
        size_bytes=size_bytes,
        sha256=sha,
        line_count=line_count,
    )


def make_symbol(
    path: str = "src/app.py",
    *,
    name: str = "main",
    qualified_name: str = "main",
    kind: SymbolKind = SymbolKind.FUNCTION,
    start_line: int = 1,
    end_line: int = 3,
    parent_id: str | None = None,
    signature: str | None = None,
    doc: str | None = None,
    evidence: EvidenceKind = EvidenceKind.PARSER,
) -> SymbolRecord:
    return SymbolRecord(
        id=symbol_id(path, kind, qualified_name, start_line),
        path=path,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        language=Language.PYTHON,
        span=SourceSpan(path=path, start_line=start_line, end_line=end_line),
        parent_id=parent_id,
        signature=signature,
        doc=doc,
        evidence=evidence,
    )


def make_relation(
    source_id: str = "file:src/app.py",
    *,
    relation_type: RelationType = RelationType.IMPORTS,
    status: ResolutionStatus = ResolutionStatus.UNRESOLVED,
    evidence: EvidenceKind = EvidenceKind.RESOLVER,
    target_id: str | None = None,
    target_name: str | None = "os",
    start_line: int = 1,
    confidence: float = 0.0,
) -> RelationRecord:
    return RelationRecord(
        source_id=source_id,
        relation_type=relation_type,
        status=status,
        evidence=evidence,
        target_id=target_id,
        target_name=target_name,
        span=SourceSpan(path="src/app.py", start_line=start_line, end_line=start_line),
        confidence=confidence,
    )


def build_snapshot(
    *,
    files: tuple[FileRecord, ...] = (),
    symbols: tuple[SymbolRecord, ...] = (),
    relations: tuple[RelationRecord, ...] = (),
    issues: tuple[ParseIssue, ...] = (),
    root: str = "/checkout/repo",
    engine_version: str = ENGINE_VERSION,
    policy_fingerprint: str = POLICY_FINGERPRINT,
) -> IndexSnapshot:
    return IndexSnapshot.build(
        engine_version=engine_version,
        policy_fingerprint=policy_fingerprint,
        root=root,
        files=files,
        symbols=symbols,
        relations=relations,
        parse_issues=issues,
    )


# ---------------------------------------------------------------------------
# ids, enums and simple records
# ---------------------------------------------------------------------------
def test_schema_version() -> None:
    assert SCHEMA_VERSION == "1"


def test_stable_ids() -> None:
    assert file_id("src/app.py") == "file:src/app.py"
    assert file_id("a/b/c.py") == "file:a/b/c.py"
    assert (
        symbol_id("src/app.py", SymbolKind.FUNCTION, "App.run", 7)
        == "sym:src/app.py#function:App.run@7"
    )
    assert symbol_id("x.py", "class", "Thing", 2) == "sym:x.py#class:Thing@2"
    assert file_id("src/app.py") != file_id("src/other.py")


def test_str_enums_serialize_as_plain_strings() -> None:
    assert Language.PYTHON == "python"
    assert Language("go") is Language.GO
    assert isinstance(Language.PYTHON, str)
    assert str(Language.PYTHON) == "python"
    assert SymbolKind.METHOD.value == "method"
    assert RelationType.CALLS.value == "calls"
    assert EvidenceKind.HEURISTIC.value == "heuristic"
    assert ResolutionStatus.AMBIGUOUS.value == "ambiguous"
    for member in Language:
        assert isinstance(member.value, str) and member.value


def test_source_span_roundtrip() -> None:
    span = SourceSpan(
        path="src/app.py",
        start_line=2,
        end_line=5,
        start_column=4,
        end_column=10,
    )
    assert span.to_dict() == {
        "path": "src/app.py",
        "startLine": 2,
        "endLine": 5,
        "startColumn": 4,
        "endColumn": 10,
    }


def test_file_record_roundtrip() -> None:
    record = make_file(size_bytes=42, line_count=7)
    payload = record.to_dict()
    assert set(payload) == {"path", "language", "sizeBytes", "sha256", "lineCount"}
    assert payload["language"] == "python"
    assert payload["sizeBytes"] == 42
    restored = FileRecord.from_dict(payload)
    assert restored == record


def test_symbol_record_roundtrip() -> None:
    record = make_symbol(
        name="run",
        qualified_name="App.run",
        kind=SymbolKind.METHOD,
        start_line=10,
        end_line=12,
        parent_id="sym:src/app.py#class:App@1",
        signature="def run(self) -> None",
        doc="Run the app.",
        evidence=EvidenceKind.HEURISTIC,
    )
    payload = record.to_dict()
    assert payload["qualifiedName"] == "App.run"
    assert payload["parentId"] == "sym:src/app.py#class:App@1"
    assert payload["evidence"] == "heuristic"
    assert payload["span"]["startLine"] == 10
    assert SymbolRecord.from_dict(payload) == record


def test_symbol_record_from_minimal_dict() -> None:
    data: dict[str, Any] = {
        "id": "sym:x.py#function:f@1",
        "path": "x.py",
        "name": "f",
        "qualifiedName": "f",
        "kind": "function",
        "language": "python",
        "span": {"path": "x.py", "startLine": 1, "endLine": 1},
    }
    symbol = SymbolRecord.from_dict(data)
    assert symbol.parent_id is None
    assert symbol.signature is None
    assert symbol.doc is None
    assert symbol.evidence is EvidenceKind.PARSER
    assert symbol.span.start_column == 0
    assert symbol.span.end_column == 0
    assert symbol.id == "sym:x.py#function:f@1"


def test_relation_record_roundtrip_resolved() -> None:
    relation = make_relation(
        status=ResolutionStatus.RESOLVED,
        target_id="file:src/os_like.py",
        target_name="os_like",
        start_line=3,
        confidence=0.75,
    )
    payload = relation.to_dict()
    assert set(payload) == {
        "from",
        "to",
        "targetName",
        "type",
        "status",
        "evidence",
        "span",
        "confidence",
    }
    assert payload["type"] == "imports"
    assert payload["status"] == "resolved"
    assert payload["span"] == relation.span.to_dict()  # type: ignore[union-attr]
    assert RelationRecord.from_dict(payload) == relation


def test_relation_record_unresolved_keeps_no_target_id() -> None:
    relation = make_relation(
        status=ResolutionStatus.UNRESOLVED,
        target_id=None,
        target_name="unknown.pkg",
    )
    payload = relation.to_dict()
    assert payload["to"] is None
    assert payload["status"] == "unresolved"
    restored = RelationRecord.from_dict(payload)
    assert restored.target_id is None
    assert restored.target_name == "unknown.pkg"
    assert restored.status is ResolutionStatus.UNRESOLVED


def test_relation_record_without_span() -> None:
    relation = RelationRecord(
        source_id="file:a.py",
        relation_type=RelationType.REFERENCES,
        status=ResolutionStatus.EXTERNAL,
        evidence=EvidenceKind.RESOLVER,
        target_name="requests",
    )
    payload = relation.to_dict()
    assert payload["span"] is None
    assert RelationRecord.from_dict(payload) == relation


def test_relation_confidence_is_rounded_to_four_decimals() -> None:
    relation = make_relation(confidence=1 / 3)
    payload = relation.to_dict()
    assert payload["confidence"] == 0.3333
    assert RelationRecord.from_dict(payload).confidence == 0.3333
    assert make_relation(confidence=0.25).to_dict()["confidence"] == 0.25


def test_parse_issue_roundtrip() -> None:
    issue = ParseIssue(path="src/broken.py", message="unexpected EOF")
    assert issue.to_dict() == {"path": "src/broken.py", "message": "unexpected EOF"}
    assert ParseIssue.from_dict(issue.to_dict()) == issue


def test_scan_stats_serialization() -> None:
    stats = ScanStats(
        files_indexed=5,
        bytes_indexed=123,
        directories_visited=2,
        skipped=(("gitignore", 3), ("hidden", 1)),
    )
    assert stats.skip_map() == {"gitignore": 3, "hidden": 1}
    assert stats.to_dict() == {
        "filesIndexed": 5,
        "bytesIndexed": 123,
        "directoriesVisited": 2,
        "skipped": {"gitignore": 3, "hidden": 1},
    }
    assert ScanStats(0, 0, 1).skipped == ()


def test_cache_stats_serialization() -> None:
    assert CacheStats() == CacheStats(0, 0, 0, False)
    assert CacheStats().to_dict() == {
        "filesReused": 0,
        "filesReparsed": 0,
        "filesRemoved": 0,
        "cacheHit": False,
    }
    assert CacheStats(files_reused=3, files_reparsed=1, files_removed=2, cache_hit=True).to_dict() == {
        "filesReused": 3,
        "filesReparsed": 1,
        "filesRemoved": 2,
        "cacheHit": True,
    }


# ---------------------------------------------------------------------------
# build-time normalization
# ---------------------------------------------------------------------------
def test_build_orders_files() -> None:
    snapshot = build_snapshot(
        files=(make_file("src/z.py"), make_file("README.md"), make_file("src/a.py"))
    )
    assert [item.path for item in snapshot.files] == ["README.md", "src/a.py", "src/z.py"]


def test_build_orders_symbols() -> None:
    symbols = (
        make_symbol("b.py", name="z", qualified_name="z", start_line=1),
        make_symbol("a.py", name="z", qualified_name="z", start_line=2, end_line=9),
        make_symbol("a.py", name="z", qualified_name="z", start_line=1),
        make_symbol("a.py", name="a", qualified_name="a", start_line=1),
        make_symbol("a.py", name="B", qualified_name="B", kind=SymbolKind.CLASS, start_line=1),
    )
    snapshot = build_snapshot(symbols=symbols)
    order = [
        (item.path, item.span.start_line, item.kind.value, item.qualified_name)
        for item in snapshot.symbols
    ]
    assert order == [
        ("a.py", 1, "class", "B"),
        ("a.py", 1, "function", "a"),
        ("a.py", 1, "function", "z"),
        ("a.py", 2, "function", "z"),
        ("b.py", 1, "function", "z"),
    ]


def test_build_orders_relations_with_ties() -> None:
    relations = (
        make_relation(source_id="file:b.py", target_name="z"),
        make_relation(source_id="file:a.py", target_name="z"),
        make_relation(source_id="file:a.py", target_name="a"),
        make_relation(
            source_id="file:a.py",
            target_name="b",
            relation_type=RelationType.CALLS,
        ),
        make_relation(source_id="file:a.py", target_name="a", start_line=2),
        make_relation(source_id="file:a.py", target_name="a", start_line=1),
    )
    snapshot = build_snapshot(relations=relations)
    order = [
        (item.source_id, item.relation_type.value, item.target_name, item.span.start_line)  # type: ignore[union-attr]
        for item in snapshot.relations
    ]
    assert order == [
        ("file:a.py", "calls", "b", 1),
        ("file:a.py", "imports", "a", 1),
        ("file:a.py", "imports", "a", 1),
        ("file:a.py", "imports", "a", 2),
        ("file:a.py", "imports", "z", 1),
        ("file:b.py", "imports", "z", 1),
    ]


def test_build_orders_parse_issues() -> None:
    snapshot = build_snapshot(
        issues=(
            ParseIssue("b.py", "boom"),
            ParseIssue("a.py", "z failure"),
            ParseIssue("a.py", "a failure"),
        )
    )
    assert [(item.path, item.message) for item in snapshot.parse_issues] == [
        ("a.py", "a failure"),
        ("a.py", "z failure"),
        ("b.py", "boom"),
    ]


def test_build_accepts_any_iterable() -> None:
    snapshot = build_snapshot(files=[make_file()], symbols=[], relations=[])  # type: ignore[arg-type]
    assert len(snapshot.files) == 1
    assert snapshot.symbols == ()
    assert snapshot.relations == ()
    assert snapshot.parse_issues == ()


# ---------------------------------------------------------------------------
# serialization and fingerprints
# ---------------------------------------------------------------------------
def _populated_snapshot() -> IndexSnapshot:
    symbol = make_symbol(
        path="src/app.py",
        name="main",
        qualified_name="main",
        signature="def main() -> int",
        doc="Entry point.",
    )
    return build_snapshot(
        files=(make_file(), make_file("README.md", language=Language.MARKDOWN, line_count=1)),
        symbols=(symbol,),
        relations=(
            make_relation(
                status=ResolutionStatus.RESOLVED,
                target_id=file_id("src/os_like.py"),
                target_name="os_like",
            ),
        ),
        issues=(ParseIssue("src/broken.py", "unexpected EOF"),),
    )


def test_public_dict_shape_and_fingerprint() -> None:
    snapshot = _populated_snapshot()
    payload = snapshot.public_dict()
    assert set(payload) == {
        "schemaVersion",
        "engineVersion",
        "policyFingerprint",
        "fingerprint",
        "files",
        "symbols",
        "relations",
        "parseIssues",
    }
    assert payload["schemaVersion"] == SCHEMA_VERSION
    assert payload["engineVersion"] == ENGINE_VERSION
    assert payload["policyFingerprint"] == POLICY_FINGERPRINT
    assert payload["fingerprint"] == snapshot.fingerprint()
    assert len(payload["fingerprint"]) == 64
    without_fingerprint = {key: value for key, value in payload.items() if key != "fingerprint"}
    assert payload["fingerprint"] == sha256_text(canonical_json(without_fingerprint))


def test_public_dict_has_no_absolute_paths_or_root() -> None:
    snapshot = _populated_snapshot()
    payload = snapshot.public_dict()
    assert "root" not in payload
    encoded = canonical_json(payload)
    assert snapshot.root not in encoded
    assert "generatedAt" not in encoded
    assert "timings" not in encoded


def test_public_dict_is_stable_across_input_order() -> None:
    first = build_snapshot(
        files=(make_file("b.py"), make_file("a.py")),
        symbols=(make_symbol("b.py", qualified_name="f", start_line=2), make_symbol("a.py")),
        relations=(make_relation(source_id="file:b.py"), make_relation(source_id="file:a.py")),
    )
    second = build_snapshot(
        files=(make_file("a.py"), make_file("b.py")),
        symbols=(make_symbol("a.py"), make_symbol("b.py", qualified_name="f", start_line=2)),
        relations=(make_relation(source_id="file:a.py"), make_relation(source_id="file:b.py")),
    )
    assert canonical_json(first.public_dict()) == canonical_json(second.public_dict())
    assert first.fingerprint() == second.fingerprint()


def test_fingerprint_changes_with_any_component() -> None:
    base = _populated_snapshot()
    fingerprints = {
        base.fingerprint(),
        build_snapshot(
            files=(make_file(sha="b" * 64),),
            symbols=base.symbols,
            relations=base.relations,
            issues=base.parse_issues,
        ).fingerprint(),
        build_snapshot(
            files=base.files,
            symbols=(make_symbol("src/app.py", qualified_name="other"),),
            relations=base.relations,
            issues=base.parse_issues,
        ).fingerprint(),
        build_snapshot(
            files=base.files,
            symbols=base.symbols,
            relations=(),
            issues=base.parse_issues,
        ).fingerprint(),
        build_snapshot(
            files=base.files,
            symbols=base.symbols,
            relations=base.relations,
            issues=(),
        ).fingerprint(),
        build_snapshot(files=base.files).with_root("/elsewhere").fingerprint(),
        build_snapshot(files=base.files, policy_fingerprint="other-policy").fingerprint(),
        build_snapshot(files=base.files, engine_version="9.9.9").fingerprint(),
    }
    assert len(fingerprints) == 8


def test_public_dict_roundtrip() -> None:
    snapshot = _populated_snapshot()
    payload = snapshot.public_dict()
    restored = IndexSnapshot.from_public_dict(payload, root="/another/root")
    assert restored.files == snapshot.files
    assert restored.symbols == snapshot.symbols
    assert restored.relations == snapshot.relations
    assert restored.parse_issues == snapshot.parse_issues
    assert restored.root == "/another/root"
    assert restored.fingerprint() == snapshot.fingerprint()
    assert restored.public_dict() == payload


def test_from_public_dict_minimal_payload() -> None:
    snapshot = IndexSnapshot.from_public_dict(
        {
            "schemaVersion": "1",
            "engineVersion": "e",
            "policyFingerprint": "p",
            "files": [],
            "symbols": [],
            "relations": [],
        }
    )
    assert snapshot.schema_version == "1"
    assert snapshot.engine_version == "e"
    assert snapshot.policy_fingerprint == "p"
    assert snapshot.parse_issues == ()
    assert snapshot.root == ""


def test_empty_snapshot_is_stable() -> None:
    snapshot = build_snapshot()
    payload = snapshot.public_dict()
    assert payload["files"] == []
    assert payload["symbols"] == []
    assert payload["relations"] == []
    assert payload["parseIssues"] == []
    other = build_snapshot(root="/different/root")
    assert other.fingerprint() == snapshot.fingerprint()
    assert other.public_dict() == payload


def test_canonical_json_keeps_unicode_and_is_stable() -> None:
    payload = {"path": "src/日本語.py", "name": "café", "kind": "function"}
    encoded = canonical_json(payload)
    assert "日本語" in encoded
    assert "café" in encoded
    assert encoded == canonical_json({"kind": "function", "name": "café", "path": "src/日本語.py"})
    assert json.loads(encoded) == payload
    assert sha256_text(encoded) == sha256_text(encoded)
    assert sha256_text(encoded) != sha256_text(encoded + " ")


# ---------------------------------------------------------------------------
# indexes and convenience helpers
# ---------------------------------------------------------------------------
def test_index_maps() -> None:
    files = (make_file("a.py"), make_file("b.py"))
    symbols = (
        make_symbol("a.py", qualified_name="first", start_line=1),
        make_symbol("a.py", qualified_name="second", start_line=5),
        make_symbol("b.py", qualified_name="third", start_line=1),
    )
    snapshot = build_snapshot(files=files, symbols=symbols)
    files_by_path, symbols_by_id, symbols_by_file = snapshot.index_maps()
    assert set(files_by_path) == {"a.py", "b.py"}
    assert set(symbols_by_id) == {symbol.id for symbol in symbols}
    assert len(symbols_by_file["a.py"]) == 2
    assert len(symbols_by_file["b.py"]) == 1
    assert "b.py" in symbols_by_file


def test_entry_points_are_conservative() -> None:
    parent = symbol_id("src/app.py", SymbolKind.CLASS, "Holder", 1)
    symbols = (
        make_symbol("src/app.py", name="main", qualified_name="main", start_line=1),
        make_symbol("src/app.py", name="cli", qualified_name="cli", kind=SymbolKind.CLASS, start_line=5),
        make_symbol("src/app.py", name="app", qualified_name="app", kind=SymbolKind.CLASS, start_line=9),
        make_symbol("src/app.py", name="helper", qualified_name="helper", start_line=13),
        make_symbol(
            "src/app.py",
            name="run",
            qualified_name="Holder.run",
            kind=SymbolKind.METHOD,
            start_line=17,
            parent_id=parent,
        ),
    )
    snapshot = build_snapshot(symbols=symbols)
    assert {item.name for item in snapshot.entry_points()} == {"main", "cli", "app"}


def test_with_root_keeps_model_identity() -> None:
    snapshot = _populated_snapshot()
    moved = snapshot.with_root("/elsewhere")
    assert moved.root == "/elsewhere"
    assert moved.files == snapshot.files
    assert moved.public_dict() == snapshot.public_dict()
    assert moved.fingerprint() == snapshot.fingerprint()


def test_fingerprint_is_memoized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Budget-fitting renderers call fingerprint() in a loop; it must hash once."""

    from codebase_intelligence.model import entities

    snapshot = _populated_snapshot()
    calls = {"count": 0}
    original = entities.canonical_json

    def counting(value: Any) -> str:
        calls["count"] += 1
        return original(value)

    monkeypatch.setattr(entities, "canonical_json", counting)
    first = snapshot.fingerprint()
    second = snapshot.fingerprint()
    assert first == second
    assert calls["count"] == 1, "fingerprint must be computed once and memoized"


def test_frozen_records_reject_mutation() -> None:
    record = make_file()
    with pytest.raises(FrozenInstanceError):
        record.path = "other.py"  # type: ignore[misc]
    span = SourceSpan(path="a.py", start_line=1, end_line=1)
    with pytest.raises(FrozenInstanceError):
        span.start_line = 2  # type: ignore[misc]
    snapshot = build_snapshot(files=(record,))
    with pytest.raises(FrozenInstanceError):
        snapshot.files = ()  # type: ignore[misc]
