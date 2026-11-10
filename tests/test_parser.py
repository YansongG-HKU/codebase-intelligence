"""Tests for the parser adapters (SPEC §6).

Covers the Python ``ast`` adapter (declarations, imports, inheritance, same-file
calls, constants, bounded syntax issues) and the regex heuristic adapters
(declarations, imports, masking, malformed input never raises, determinism).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from codebase_intelligence.model import (
    EvidenceKind,
    FileRecord,
    Language,
    RelationType,
    ResolutionStatus,
    SymbolKind,
)
from codebase_intelligence.parsers import (
    PARSER_VERSIONS,
    ParseResult,
    parse_file,
    parser_version_for,
    parser_versions_digest,
)
from codebase_intelligence.parsers.heuristic import HEURISTIC_LANGUAGES
from codebase_intelligence.util import canonical_json

FIXTURES = Path(__file__).parent / "fixtures" / "parser"

LANGUAGE_BY_SUFFIX = {
    ".py": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".go": Language.GO,
}

EXPECTED_LANGUAGES = {
    Language.PYTHON,
    Language.JAVASCRIPT,
    Language.TYPESCRIPT,
    Language.GO,
    Language.RUST,
    Language.JAVA,
    Language.C,
    Language.CPP,
    Language.CSHARP,
    Language.RUBY,
    Language.PHP,
    Language.SHELL,
}


def make_record(path: str, language: Language, text: str) -> FileRecord:
    data = text.encode("utf-8")
    line_count = text.count("\n") + (1 if data and not text.endswith("\n") else 0)
    return FileRecord(
        path=path,
        language=language,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        line_count=max(1, line_count),
    )


def load_fixture(relative: str) -> tuple[FileRecord, str]:
    text = (FIXTURES / relative).read_text(encoding="utf-8")
    return make_record(relative, LANGUAGE_BY_SUFFIX[Path(relative).suffix], text), text


def fixture_records() -> list[tuple[FileRecord, str]]:
    records: list[tuple[FileRecord, str]] = []
    for path in sorted(FIXTURES.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(FIXTURES).as_posix()
        language = LANGUAGE_BY_SUFFIX.get(path.suffix)
        if language is None:
            continue
        records.append(load_fixture(relative))
    return records


def symbols_by_name(result: ParseResult, name: str) -> list:
    return [symbol for symbol in result.symbols if symbol.name == name]


def relations_of(result: ParseResult, relation_type: RelationType) -> list:
    return [
        relation for relation in result.relations if relation.relation_type is relation_type
    ]


# ---------------------------------------------------------------------------
# Registry / determinism
# ---------------------------------------------------------------------------
def test_parser_versions_cover_every_adapter_language() -> None:
    assert set(PARSER_VERSIONS) == EXPECTED_LANGUAGES
    for language in EXPECTED_LANGUAGES:
        version = parser_version_for(language)
        assert isinstance(version, str) and version
    assert parser_version_for(Language.JSON) == ""


def test_parser_versions_digest_is_canonical_and_stable() -> None:
    expected = hashlib.sha256(canonical_json(PARSER_VERSIONS).encode("utf-8")).hexdigest()
    assert parser_versions_digest() == expected
    assert parser_versions_digest() == parser_versions_digest()
    assert len(parser_versions_digest()) == 64


def test_parse_file_is_deterministic_for_same_input() -> None:
    record, text = load_fixture("python_pkg/models.py")
    first = parse_file(record, text)
    second = parse_file(record, text)
    assert first == second
    assert [symbol.to_dict() for symbol in first.symbols] == [
        symbol.to_dict() for symbol in second.symbols
    ]
    assert [relation.to_dict() for relation in first.relations] == [
        relation.to_dict() for relation in second.relations
    ]
    assert isinstance(first.symbols, tuple)
    assert isinstance(first.relations, tuple)
    assert isinstance(first.issues, tuple)


def test_parse_result_ordering_is_canonical() -> None:
    record, text = load_fixture("python_pkg/app.py")
    result = parse_file(record, text)
    symbol_keys = [
        (symbol.path, symbol.span.start_line, symbol.kind.value, symbol.qualified_name)
        for symbol in result.symbols
    ]
    assert symbol_keys == sorted(symbol_keys)
    relation_keys = [
        (
            relation.source_id,
            relation.relation_type.value,
            relation.target_id or "",
            relation.target_name or "",
            relation.span.start_line if relation.span else 0,
        )
        for relation in result.relations
    ]
    assert relation_keys == sorted(relation_keys)


# ---------------------------------------------------------------------------
# Python adapter
# ---------------------------------------------------------------------------
def test_python_module_and_declarations() -> None:
    record, text = load_fixture("python_pkg/models.py")
    result = parse_file(record, text)
    module = symbols_by_name(result, "models")
    assert len(module) == 1
    assert module[0].kind is SymbolKind.MODULE
    assert module[0].span.start_line == 1
    assert module[0].parent_id is None

    base = symbols_by_name(result, "Base")[0]
    assert base.kind is SymbolKind.CLASS
    assert base.parent_id == module[0].id
    assert "Base class." in (base.doc or "")

    method = symbols_by_name(result, "describe")[0]
    assert method.kind is SymbolKind.METHOD
    assert method.parent_id == base.id
    assert (method.signature or "").startswith("def describe(")

    user = symbols_by_name(result, "User")[0]
    assert user.kind is SymbolKind.CLASS
    role = symbols_by_name(result, "ROLE")[0]
    assert role.kind is SymbolKind.CONSTANT

    helper_text = symbols_by_name(result, "helper_text")[0]
    assert helper_text.kind is SymbolKind.FUNCTION

    cache = symbols_by_name(result, "cache")[0]
    assert cache.kind is SymbolKind.VARIABLE


def test_python_containment_relations_are_parser_facts() -> None:
    record, text = load_fixture("python_pkg/helpers.py")
    result = parse_file(record, text)
    contains = relations_of(result, RelationType.CONTAINS)
    assert contains
    for relation in contains:
        assert relation.status is ResolutionStatus.RESOLVED
        assert relation.evidence is EvidenceKind.PARSER
        assert relation.confidence == 1.0


def test_python_same_file_base_resolves_to_symbol() -> None:
    record, text = load_fixture("python_pkg/models.py")
    result = parse_file(record, text)
    user = symbols_by_name(result, "User")[0]
    base = symbols_by_name(result, "Base")[0]
    inherits = [
        relation
        for relation in relations_of(result, RelationType.INHERITS)
        if relation.source_id == user.id
    ]
    assert len(inherits) == 1
    assert inherits[0].target_id == base.id
    assert inherits[0].status is ResolutionStatus.RESOLVED
    assert inherits[0].evidence is EvidenceKind.PARSER


def test_python_imported_base_stays_unresolved_with_target_name() -> None:
    record, text = load_fixture("python_pkg/helpers.py")
    result = parse_file(record, text)
    calculator = symbols_by_name(result, "Calculator")[0]
    inherits = [
        relation
        for relation in relations_of(result, RelationType.INHERITS)
        if relation.source_id == calculator.id
    ]
    assert len(inherits) == 1
    assert inherits[0].status is ResolutionStatus.UNRESOLVED
    assert inherits[0].target_id is None
    assert inherits[0].target_name == "Base"
    assert inherits[0].evidence is EvidenceKind.PARSER


def test_python_calls_resolved_same_file_are_heuristic_and_bounded() -> None:
    record, text = load_fixture("python_pkg/models.py")
    result = parse_file(record, text)
    calls = relations_of(result, RelationType.CALLS)
    assert calls
    helper_text = symbols_by_name(result, "helper_text")[0]
    targets = {relation.target_id for relation in calls}
    assert helper_text.id in targets
    for relation in calls:
        assert relation.status is ResolutionStatus.RESOLVED
        assert relation.evidence is EvidenceKind.HEURISTIC
        assert 0.0 < relation.confidence <= 0.8


def test_python_import_relations_preserve_specifiers() -> None:
    record, text = load_fixture("python_pkg/app.py")
    result = parse_file(record, text)
    imports = relations_of(result, RelationType.IMPORTS)
    targets = {relation.target_name for relation in imports}
    assert {"os", ".helpers", ".models", ".missing", "python_pkg.helpers"} <= targets
    for relation in imports:
        assert relation.source_id == f"file:{record.path}"
        assert relation.status is ResolutionStatus.UNRESOLVED
        assert relation.evidence is EvidenceKind.PARSER
        assert relation.target_id is None
        assert relation.span is not None and relation.span.path == record.path


def test_python_relative_import_levels_are_preserved() -> None:
    record, text = load_fixture("python_pkg/nested/deep.py")
    result = parse_file(record, text)
    targets = {relation.target_name for relation in relations_of(result, RelationType.IMPORTS)}
    assert targets == {"..helpers"}

    init_record, init_text = load_fixture("python_pkg/nested/__init__.py")
    init_result = parse_file(init_record, init_text)
    targets = {
        relation.target_name for relation in relations_of(init_result, RelationType.IMPORTS)
    }
    assert targets == {".deep"}


def test_python_syntax_error_becomes_bounded_issue_not_exception() -> None:
    record, text = load_fixture("python_pkg/broken.py")
    result = parse_file(record, text)
    assert result.symbols == ()
    assert result.relations == ()
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.path == record.path
    assert "syntax error" in issue.message
    assert len(issue.message) <= 300
    assert "\n" not in issue.message


def test_python_async_and_nested_declarations() -> None:
    text = (
        "class Outer:\n"
        "    class Inner:\n"
        "        async def go(self):\n"
        "            def nested():\n"
        "                return 1\n"
        "            return nested()\n"
    )
    record = make_record("nested.py", Language.PYTHON, text)
    result = parse_file(record, text)
    outer = symbols_by_name(result, "Outer")[0]
    inner = symbols_by_name(result, "Inner")[0]
    assert inner.parent_id == outer.id
    go = symbols_by_name(result, "go")[0]
    assert go.kind is SymbolKind.METHOD
    nested = [symbol for symbol in symbols_by_name(result, "nested") if symbol.kind is SymbolKind.FUNCTION][0]
    assert nested.kind is SymbolKind.FUNCTION
    assert nested.parent_id == go.id
    signatures = {(symbol.signature or "") for symbol in result.symbols}
    assert any(signature.startswith("async def go(") for signature in signatures)


def test_unsupported_language_returns_empty_result_without_issues() -> None:
    record = make_record("data.json", Language.JSON, '{"a": 1}\n')
    result = parse_file(record, "{not valid json")
    assert result == ParseResult()
    assert result.issues == ()


# ---------------------------------------------------------------------------
# Heuristic adapters
# ---------------------------------------------------------------------------
def test_javascript_declarations_and_imports() -> None:
    record, text = load_fixture("web/app.js")
    result = parse_file(record, text)
    assert result.issues == ()
    assert symbols_by_name(result, "Widget")[0].kind is SymbolKind.CLASS
    assert symbols_by_name(result, "build")[0].kind is SymbolKind.FUNCTION
    assert symbols_by_name(result, "MAX_SIZE")[0].kind is SymbolKind.CONSTANT
    for symbol in result.symbols:
        assert symbol.evidence is EvidenceKind.HEURISTIC

    imports = relations_of(result, RelationType.IMPORTS)
    assert {relation.target_name for relation in imports} == {
        "react",
        "./helpers",
        "./dupe",
        "./nope",
    }
    for relation in imports:
        assert relation.evidence is EvidenceKind.HEURISTIC
        assert relation.status is ResolutionStatus.UNRESOLVED

    inherits = relations_of(result, RelationType.INHERITS)
    assert [relation.target_name for relation in inherits] == ["Base"]


def test_heuristic_masking_ignores_comments_and_strings() -> None:
    text = (
        "// class FakeClass { }\n"
        "/* function fakeFunction() { } */\n"
        'const banner = "class StringClass { }";\n'
        "class RealClass { }\n"
        "function realFunction() { }\n"
    )
    record = make_record("mask.js", Language.JAVASCRIPT, text)
    result = parse_file(record, text)
    names = {symbol.name for symbol in result.symbols}
    assert "RealClass" in names
    assert "realFunction" in names
    assert "FakeClass" not in names
    assert "fakeFunction" not in names
    assert "StringClass" not in names


def test_typescript_types_and_imports() -> None:
    record, text = load_fixture("web/app.ts")
    result = parse_file(record, text)
    assert symbols_by_name(result, "Point")[0].kind is SymbolKind.INTERFACE
    assert symbols_by_name(result, "Color")[0].kind is SymbolKind.ENUM
    assert symbols_by_name(result, "Id")[0].kind is SymbolKind.TYPE
    assert symbols_by_name(result, "Service")[0].kind is SymbolKind.CLASS
    implements = relations_of(result, RelationType.IMPLEMENTS)
    assert [relation.target_name for relation in implements] == ["Runnable"]
    imports = {relation.target_name for relation in relations_of(result, RelationType.IMPORTS)}
    assert imports == {"./helpers", "./types"}


def test_go_declarations_and_imports() -> None:
    record, text = load_fixture("go/service/main.go")
    result = parse_file(record, text)
    main_functions = [
        symbol for symbol in symbols_by_name(result, "main") if symbol.kind is SymbolKind.FUNCTION
    ]
    assert len(main_functions) == 1
    assert main_functions[0].kind is SymbolKind.FUNCTION
    imports = {relation.target_name for relation in relations_of(result, RelationType.IMPORTS)}
    assert imports == {"fmt", "example.com/fixture/go/service/util"}

    util_record, util_text = load_fixture("go/service/util/util.go")
    util_result = parse_file(util_record, util_text)
    name = symbols_by_name(util_result, "Name")[0]
    assert name.kind is SymbolKind.CONSTANT
    helper = symbols_by_name(util_result, "Helper")[0]
    assert helper.kind is SymbolKind.FUNCTION
    assert helper.span.start_line == helper.span.end_line == 5


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [
        (
            Language.RUST,
            "pub struct Engine { name: String }\n"
            "pub enum State { Idle }\n"
            "pub trait Runner { fn run(&self); }\n"
            "pub fn start() -> bool { true }\n"
            "use crate::config::Config;\n",
            {"Engine": SymbolKind.STRUCT, "State": SymbolKind.ENUM,
             "Runner": SymbolKind.TRAIT, "start": SymbolKind.FUNCTION},
        ),
        (
            Language.JAVA,
            "import java.util.List;\n"
            "public class App extends Base implements Runnable {\n"
            "    private static final int MAX = 10;\n"
            "    public void run() { helper(); }\n"
            "}\n",
            {"App": SymbolKind.CLASS, "run": SymbolKind.METHOD, "MAX": SymbolKind.CONSTANT},
        ),
        (
            Language.C,
            '#include <stdio.h>\n#include "local.h"\n'
            "struct Point { int x; };\n"
            "int main(void) { return 0; }\n",
            {"Point": SymbolKind.STRUCT, "main": SymbolKind.FUNCTION},
        ),
        (
            Language.CPP,
            '#include "local.h"\n'
            "class Widget : public Base {\npublic:\n"
            "    void render(int x) { helper(x); }\n};\n",
            {"Widget": SymbolKind.CLASS, "render": SymbolKind.METHOD},
        ),
        (
            Language.CSHARP,
            "using System;\n"
            "public class Service : Base {\n"
            "    private static readonly int Max = 10;\n"
            "    public void Run() { Helper(); }\n"
            "}\n",
            {"Service": SymbolKind.CLASS, "Run": SymbolKind.METHOD},
        ),
        (
            Language.RUBY,
            "require 'json'\nclass Widget < Base\n  def render\n    1\n  end\nend\n",
            {"Widget": SymbolKind.CLASS, "render": SymbolKind.FUNCTION},
        ),
        (
            Language.PHP,
            "<?php\nuse App\\Runner;\n"
            "class Widget extends Base implements Runner {\n"
            "    const MAX = 10;\n"
            "    public function render($x) { return $x; }\n}\n",
            {"Widget": SymbolKind.CLASS, "render": SymbolKind.METHOD, "MAX": SymbolKind.CONSTANT},
        ),
        (
            Language.SHELL,
            "#!/usr/bin/env bash\nsource ./lib/common.sh\nMAX_RETRIES=3\n"
            "deploy() {\n    echo deploy\n}\n",
            {"deploy": SymbolKind.FUNCTION, "MAX_RETRIES": SymbolKind.CONSTANT},
        ),
    ],
)
def test_heuristic_language_declarations(
    language: Language, text: str, expected: dict[str, SymbolKind]
) -> None:
    record = make_record(f"sample.{language.value}", language, text)
    result = parse_file(record, text)
    assert result.issues == ()
    for name, kind in expected.items():
        found = symbols_by_name(result, name)
        assert found, f"missing symbol {name} for {language.value}"
        assert found[0].kind is kind
        assert found[0].language is language
        for symbol in result.symbols:
            assert symbol.evidence is EvidenceKind.HEURISTIC


@pytest.mark.parametrize("language", HEURISTIC_LANGUAGES)
def test_heuristic_adapters_never_raise_on_malformed_input(language: Language) -> None:
    samples = [
        "",
        "\x00\x01\x02 {{{ ((( 'unterminated\n",
        "class {\n function (\n #include <\n use ;\n def \n",
        "/* never closed\nimport 'x'\n",
        "`" * 5000,
        "a" * 200_000,
    ]
    for index, text in enumerate(samples):
        record = make_record(f"malformed-{index}.{language.value}", language, text)
        result = parse_file(record, text)
        assert isinstance(result, ParseResult)
        for issue in result.issues:
            assert len(issue.message) <= 300
            assert issue.path == record.path


def test_all_fixture_symbols_have_consistent_paths_and_spans() -> None:
    for record, text in fixture_records():
        result = parse_file(record, text)
        for symbol in result.symbols:
            assert symbol.path == record.path
            assert symbol.language is record.language
            assert 1 <= symbol.span.start_line <= symbol.span.end_line
            assert symbol.span.end_line <= record.line_count + 1
            assert symbol.id == (
                f"sym:{symbol.path}#{symbol.kind.value}:{symbol.qualified_name}"
                f"@{symbol.span.start_line}"
            )
        for relation in result.relations:
            assert relation.span is not None
            assert relation.span.path == record.path
            assert relation.span.start_line >= 1
            assert relation.confidence == round(relation.confidence, 4)
            assert relation.confidence <= 1.0
