"""Regex-based heuristic adapters for the non-Python languages.

These adapters are intentionally modest: they recognize declaration keywords,
import statements and a few inheritance clauses with line-oriented regular
expressions, label everything :class:`EvidenceKind.HEURISTIC`, and document
their limits instead of pretending to be real compilers (``docs/SPEC.md`` §6).

Design rules that the tests enforce:

* no regular expression can raise on malformed input — every adapter is wrapped
  in a defensive boundary and returns a bounded :class:`ParseIssue` instead;
* output is deterministic (text order in, canonical order out);
* brace-delimited bodies get a best-effort end line for context excerpts;
  languages without reliable braces (Ruby) report single-line declarations;
* no code is executed and no file is opened here — the input text is untrusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from codebase_intelligence.model import (
    EvidenceKind,
    FileRecord,
    Language,
    ParseIssue,
    RelationRecord,
    RelationType,
    ResolutionStatus,
    SymbolKind,
    SymbolRecord,
    file_id,
)
from codebase_intelligence.parsers.base import (
    MAX_ISSUE_MESSAGE_CHARS,
    ParseResult,
    block_end_line,
    finalize,
    line_of,
    line_starts,
    make_issue,
    make_relation,
    make_symbol,
    module_symbol,
)
from codebase_intelligence.util import bounded_text

#: Version tag shared by the regex adapters; part of ``PARSER_VERSIONS``.
PARSER_VERSION = "regex-v1"

#: A declaration with this many leading/trailing junk characters is not a name.
_NAME_RE = re.compile(r"[A-Za-z_$][\w$]*")
_DOTTED_RE = re.compile(r"[A-Za-z_][\w.:\\-]*")

#: Identifiers that look like declarations but are control flow / syntax.
_KEYWORDS = frozenset(
    {
        "if",
        "for",
        "foreach",
        "while",
        "switch",
        "case",
        "catch",
        "return",
        "new",
        "else",
        "do",
        "try",
        "throw",
        "throws",
        "finally",
        "default",
        "function",
        "func",
        "class",
        "struct",
        "enum",
        "interface",
        "trait",
        "impl",
        "fn",
        "def",
        "fun",
        "const",
        "var",
        "let",
        "static",
        "public",
        "private",
        "protected",
        "internal",
        "async",
        "await",
        "import",
        "from",
        "package",
        "module",
        "namespace",
        "using",
        "include",
        "require",
        "define",
        "typeof",
        "delete",
        "void",
        "int",
        "char",
        "float",
        "double",
        "long",
        "short",
        "unsigned",
        "signed",
        "bool",
        "boolean",
        "string",
        "object",
        "yield",
        "with",
        "lambda",
        "assert",
        "print",
        "echo",
        "then",
        "fi",
        "done",
        "esac",
        "elif",
        "unless",
        "match",
        "when",
        "loop",
        "where",
        "select",
        "lock",
        "get",
        "set",
    }
)


@dataclass(frozen=True)
class _Rule:
    """One declaration-recognition rule (group 1 is the identifier)."""

    pattern: re.Pattern[str]
    kind: SymbolKind | None = None
    name_group: int = 1
    base_group: int | None = None
    implements_group: int | None = None


@dataclass(frozen=True)
class _ImportRule:
    """One import-recognition rule; group ``target_group`` is the specifier."""

    pattern: re.Pattern[str]
    target_group: int = 1
    mode: str = "raw"  # raw | strip_quotes


@dataclass(frozen=True)
class _LanguageSpec:
    language: Language
    class_rules: tuple[_Rule, ...] = ()
    type_rules: tuple[_Rule, ...] = ()
    function_rules: tuple[_Rule, ...] = ()
    variable_rules: tuple[_Rule, ...] = ()
    import_rules: tuple[_ImportRule, ...] = ()
    import_handler: Callable[[str, list[int]], list[tuple[str, int]]] | None = None
    comment_markers: tuple[str, ...] = ("//",)
    block_comments: bool = True
    brace_spans: bool = True


# ---------------------------------------------------------------------------
# Masks: comments and string bodies become spaces so declarations inside them
# are not reported.  Masks keep the original length, so offsets/line numbers of
# the real text are still valid.
# ---------------------------------------------------------------------------
def _mask_comments(text: str, markers: tuple[str, ...], block_comments: bool) -> str:
    chars = list(text)
    length = len(text)
    index = 0
    while index < length:
        matched = False
        for marker in markers:
            if text.startswith(marker, index):
                end = text.find("\n", index)
                if end == -1:
                    end = length
                for position in range(index, end):
                    chars[position] = " "
                index = end
                matched = True
                break
        if matched:
            continue
        if block_comments and text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = length if end == -1 else end + 2
            for position in range(index, end):
                if chars[position] != "\n":
                    chars[position] = " "
            index = end
            continue
        index += 1
    return "".join(chars)


def _mask_strings(text: str) -> str:
    chars = list(text)
    length = len(text)
    index = 0
    while index < length:
        char = text[index]
        if char in ("'", '"', "`"):
            quote = char
            index += 1
            while index < length:
                current = text[index]
                if current == "\\":
                    index += 2
                    continue
                if current == quote:
                    index += 1
                    break
                if current != "\n":
                    chars[index] = " "
                index += 1
            continue
        index += 1
    return "".join(chars)


def _first_line(raw: str) -> str:
    line = raw.strip().splitlines()[0] if raw.strip() else ""
    return bounded_text(line, 240)


def _name_or_none(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value or len(value) > 200:
        return None
    if not _NAME_RE.fullmatch(value) and not _DOTTED_RE.fullmatch(value):
        return None
    return value


def _is_constant_name(name: str) -> bool:
    return name.isupper() and any(char.isalpha() for char in name)


def _split_bases(raw: str | None) -> list[str]:
    if not raw:
        return []
    cleaned: list[str] = []
    for part in raw.split(","):
        value = part.strip()
        # C++/C# inheritance lists can carry access specifiers (``public Base``).
        for modifier in ("public", "private", "protected", "virtual", "internal"):
            if value.startswith(modifier + " "):
                value = value[len(modifier) :].strip()
                break
        if value:
            cleaned.append(value)
    return cleaned


# ---------------------------------------------------------------------------
# Import extraction helpers
# ---------------------------------------------------------------------------
def _javascript_imports(code_text: str, starts: list[int]) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    patterns = (
        re.compile(r"^[ \t]*(?:import|export)\b[^;'\"\n]*?from\s+['\"]([^'\"\n]+)['\"]", re.M),
        re.compile(r"^[ \t]*import\s+['\"]([^'\"\n]+)['\"]", re.M),
        re.compile(r"\brequire\s*\(\s*['\"]([^'\"\n]+)['\"]\s*\)"),
        re.compile(r"\bimport\s*\(\s*['\"]([^'\"\n]+)['\"]\s*\)"),
    )
    for pattern in patterns:
        for match in pattern.finditer(code_text):
            found.append((match.group(1), line_of(starts, match.start(1))))
    return found


def _go_imports(code_text: str, starts: list[int]) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    single = re.compile(r'^[ \t]*import\s+(?:[A-Za-z_.]\w*\s+)?"([^"\n]+)"', re.M)
    for match in single.finditer(code_text):
        found.append((match.group(1), line_of(starts, match.start(1))))
    blocks = re.compile(r"^[ \t]*import\s*\(([^)]*)\)", re.M)
    for block in blocks.finditer(code_text):
        for match in re.finditer(r'"([^"\n]+)"', block.group(1)):
            offset = block.start(1) + match.start(1)
            found.append((match.group(1), line_of(starts, offset)))
    return found


def _shell_imports(code_text: str, starts: list[int]) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    pattern = re.compile(r"^[ \t]*(?:source|\.)[ \t]+([^\s;#'\"\n]+)", re.M)
    for match in pattern.finditer(code_text):
        found.append((match.group(1), line_of(starts, match.start(1))))
    return found


# ---------------------------------------------------------------------------
# Language specifications (compiled once at import time, deterministic)
# ---------------------------------------------------------------------------
_JS_CLASS = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+"
    r"([A-Za-z_$][\w$]*)(?:\s+extends\s+([A-Za-z_$][\w$.]*))?"
    r"(?:\s+implements\s+([A-Za-z_$][\w$.,\s]*))?",
    re.M,
)
_JS_FUNCTION = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*"
    r"([A-Za-z_$][\w$]*)\s*\(",
    re.M,
)
_JS_ARROW = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"(?:\s*:\s*[^=\n]+)?\s*=\s*(?:async\s*)?"
    r"(?:function\s*\*?|\([^)\n]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)",
    re.M,
)
_JS_METHOD = re.compile(
    r"^[ \t]+(?:static\s+|async\s+|get\s+|set\s+|\*)*"
    r"([A-Za-z_$][\w$]*)\s*\([^;{}\n]*\)\s*(?::[^;{=\n]+)?\{",
    re.M,
)
_JS_VARIABLE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"(?:\s*:\s*[^=\n]+)?\s*=",
    re.M,
)
_JS_IMPORTS: tuple[_ImportRule, ...] = ()

_TS_EXTRA_TYPES = (
    _Rule(
        re.compile(
            r"^[ \t]*(?:export\s+)?(?:declare\s+)?interface\s+"
            r"([A-Za-z_$][\w$]*)(?:\s+extends\s+([\w$.,\s]+?))?\s*\{",
            re.M,
        ),
        kind=SymbolKind.INTERFACE,
        base_group=2,
    ),
    _Rule(
        re.compile(r"^[ \t]*(?:export\s+)?(?:declare\s+)?enum\s+([A-Za-z_$][\w$]*)", re.M),
        kind=SymbolKind.ENUM,
    ),
    _Rule(
        re.compile(r"^[ \t]*(?:export\s+)?(?:declare\s+)?type\s+([A-Za-z_$][\w$]*)\s*=", re.M),
        kind=SymbolKind.TYPE,
    ),
)

_GO_METHOD = re.compile(r"^func\s+\([^)\n]*\)\s*([A-Za-z_]\w*)\s*\(", re.M)
_GO_FUNCTION = re.compile(r"^func\s+([A-Za-z_]\w*)\s*\(", re.M)
_GO_TYPES = (
    _Rule(re.compile(r"^type\s+([A-Za-z_]\w*)\s+struct\b", re.M), kind=SymbolKind.STRUCT),
    _Rule(re.compile(r"^type\s+([A-Za-z_]\w*)\s+interface\b", re.M), kind=SymbolKind.INTERFACE),
    _Rule(
        re.compile(r"^type\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*=", re.M),
        kind=SymbolKind.TYPE,
    ),
)
_GO_VARIABLES = (
    _Rule(re.compile(r"^const\s+([A-Za-z_]\w*)", re.M), kind=SymbolKind.CONSTANT),
    _Rule(re.compile(r"^var\s+([A-Za-z_]\w*)", re.M), kind=SymbolKind.VARIABLE),
)

_RUST_TYPES = (
    _Rule(
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?struct\s+([A-Za-z_]\w*)", re.M),
        kind=SymbolKind.STRUCT,
    ),
    _Rule(
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?enum\s+([A-Za-z_]\w*)", re.M),
        kind=SymbolKind.ENUM,
    ),
    _Rule(
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?trait\s+([A-Za-z_]\w*)", re.M),
        kind=SymbolKind.TRAIT,
    ),
    _Rule(
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?type\s+([A-Za-z_]\w*)", re.M),
        kind=SymbolKind.TYPE,
    ),
    _Rule(
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?mod\s+([A-Za-z_]\w*)", re.M),
        kind=SymbolKind.MODULE,
    ),
)
_RUST_FUNCTIONS = (
    _Rule(
        re.compile(
            r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?"
            r"(?:const\s+)?fn\s+([A-Za-z_]\w*)",
            re.M,
        ),
        kind=SymbolKind.FUNCTION,
    ),
)
_RUST_VARIABLES = (
    _Rule(
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?const\s+([A-Za-z_]\w*)", re.M),
        kind=SymbolKind.CONSTANT,
    ),
    _Rule(
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?static\s+([A-Za-z_]\w*)", re.M),
        kind=SymbolKind.CONSTANT,
    ),
)
_RUST_IMPORTS = (
    _ImportRule(
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?use\s+([^;\n]+)\s*;", re.M),
        mode="strip_semicolon",
    ),
)

_JAVA_CLASS = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|static|final|abstract|sealed|non-sealed|"
    r"strictfp)\s+)*class\s+([A-Za-z_]\w*)(?:\s*<[^>\n]*>)?"
    r"(?:\s+extends\s+([\w.$<>]+))?(?:\s+implements\s+([\w.$<>,\s]+?))?\s*\{",
    re.M,
)
_JAVA_INTERFACE = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|static|final|abstract|sealed|non-sealed|"
    r"strictfp)\s+)*interface\s+([A-Za-z_]\w*)(?:\s*<[^>\n]*>)?"
    r"(?:\s+extends\s+([\w.$<>,\s]+?))?\s*\{",
    re.M,
)
_JAVA_ENUM = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|static|final|abstract|strictfp)\s+)*"
    r"enum\s+([A-Za-z_]\w*)",
    re.M,
)
_JAVA_RECORD = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|static|final|abstract|strictfp)\s+)*"
    r"record\s+([A-Za-z_]\w*)\s*\(",
    re.M,
)
_JAVA_METHOD = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|static|final|abstract|synchronized|"
    r"native|default|strictfp)\s+)*(?:<[^>\n]+>\s+)?(?:[\w.$<>\[\],?]+\s+)?"
    r"([A-Za-z_]\w*)\s*\([^;{}\n]*\)\s*(?:throws\s+[\w.,\s]+)?\{",
    re.M,
)
_JAVA_VARIABLE = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|static|final|volatile|transient)\s+)+"
    r"(?:[\w.$<>\[\],?]+\s+)?([A-Za-z_]\w*)\s*(?:=|;)",
    re.M,
)
_JAVA_IMPORTS = (
    _ImportRule(re.compile(r"^[ \t]*import\s+(?:static\s+)?([\w.$]+)\s*;", re.M)),
)

_C_FUNCTION = re.compile(
    r"^[ \t]*(?:static\s+|inline\s+|extern\s+|constexpr\s+|virtual\s+|explicit\s+)*"
    r"(?:[A-Za-z_][\w:<>,\*&\s\[\]]*?[\s\*&]+)([A-Za-z_]\w*)\s*"
    r"\([^;{}\n]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?\{",
    re.M,
)
_C_TYPES = (
    _Rule(
        re.compile(r"^[ \t]*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)\s*\{", re.M),
        kind=SymbolKind.STRUCT,
    ),
    _Rule(
        re.compile(r"^[ \t]*(?:typedef\s+)?enum\s+([A-Za-z_]\w*)", re.M),
        kind=SymbolKind.ENUM,
    ),
)
_CPP_TYPES = _C_TYPES + (
    _Rule(
        re.compile(
            r"^[ \t]*(?:template\s*<[^>\n]*>\s*)?class\s+([A-Za-z_]\w*)"
            r"(?:\s*:\s*([^{\n]+?))?\s*\{",
            re.M,
        ),
        kind=SymbolKind.CLASS,
        base_group=2,
    ),
)
_C_VARIABLES = (
    _Rule(
        re.compile(
            r"^(?:static\s+|const\s+|extern\s+|volatile\s+)*([A-Za-z_]\w*)"
            r"\s*(?:\[[^\]]*\])?\s*=",
            re.M,
        ),
    ),
)
_C_IMPORTS = (
    _ImportRule(re.compile(r"^[ \t]*#[ \t]*include\s*[<\"]([^>\"\n]+)[>\"]", re.M)),
)

_CS_CLASS = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|internal|static|sealed|abstract|partial|"
    r"readonly|unsafe|new)\s+)*class\s+([A-Za-z_]\w*)(?:\s*:\s*([\w.,\s<>]+?))?\s*\{",
    re.M,
)
_CS_INTERFACE = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|internal|static|sealed|abstract|partial|"
    r"unsafe|new)\s+)*interface\s+([A-Za-z_]\w*)(?:\s*:\s*([\w.,\s<>]+?))?\s*\{",
    re.M,
)
_CS_STRUCT = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|internal|static|readonly|partial|"
    r"unsafe|new)\s+)*struct\s+([A-Za-z_]\w*)(?:\s*:\s*([\w.,\s<>]+?))?\s*\{",
    re.M,
)
_CS_ENUM = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|internal|static)\s+)*enum\s+([A-Za-z_]\w*)",
    re.M,
)
_CS_RECORD = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|internal|static|sealed|abstract|partial)\s+)*"
    r"record\s+([A-Za-z_]\w*)\s*\(",
    re.M,
)
_CS_METHOD = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|internal|static|virtual|override|"
    r"abstract|sealed|async|extern|unsafe|new|partial)\s+)*(?:[\w.<>\[\],?]+\s+)?"
    r"([A-Za-z_]\w*)\s*\([^;{}\n]*\)\s*\{",
    re.M,
)
_CS_VARIABLE = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|internal|static|readonly|const)\s+)+"
    r"(?:[\w.<>\[\],?]+\s+)?([A-Za-z_]\w*)\s*(?:=|;)",
    re.M,
)
_CS_IMPORTS = (
    _ImportRule(re.compile(r"^[ \t]*using\s+(?:static\s+)?([\w.]+)\s*;", re.M)),
)

_RUBY_CLASS = re.compile(
    r"^[ \t]*class\s+([A-Z]\w*)(?:\s*<\s*([A-Z][\w:]*))?", re.M
)
_RUBY_MODULE = re.compile(r"^[ \t]*module\s+([A-Z]\w*)", re.M)
_RUBY_METHOD = re.compile(r"^[ \t]*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)", re.M)
_RUBY_VARIABLES = (
    _Rule(re.compile(r"^[ \t]*([A-Z][A-Z0-9_]*)\s*=", re.M)),
)
_RUBY_IMPORTS = (
    _ImportRule(re.compile(r"^[ \t]*require\s+['\"]([^'\"\n]+)['\"]", re.M)),
    _ImportRule(re.compile(r"^[ \t]*require_relative\s+['\"]([^'\"\n]+)['\"]", re.M)),
)

_PHP_CLASS = re.compile(
    r"^[ \t]*(?:(?:abstract|final|readonly)\s+)*class\s+([A-Za-z_]\w*)"
    r"(?:\s+extends\s+([\w\\]+))?(?:\s+implements\s+([\w\\,\s]+?))?\s*\{",
    re.M,
)
_PHP_INTERFACE = re.compile(
    r"^[ \t]*(?:(?:abstract|final)\s+)*interface\s+([A-Za-z_]\w*)"
    r"(?:\s+extends\s+([\w\\,\s]+?))?\s*\{",
    re.M,
)
_PHP_TRAIT = re.compile(r"^[ \t]*(?:trait)\s+([A-Za-z_]\w*)", re.M)
_PHP_ENUM = re.compile(r"^[ \t]*(?:enum)\s+([A-Za-z_]\w*)", re.M)
_PHP_FUNCTION = re.compile(
    r"^[ \t]*(?:(?:public|private|protected|static|final|abstract|readonly)\s+)*"
    r"function\s+&?\s*([A-Za-z_]\w*)\s*\(",
    re.M,
)
_PHP_VARIABLES = (
    _Rule(re.compile(r"^[ \t]*const\s+([A-Za-z_]\w*)", re.M), kind=SymbolKind.CONSTANT),
    _Rule(
        re.compile(r"^[ \t]*define\s*\(\s*['\"]([A-Za-z_]\w*)['\"]", re.M),
        kind=SymbolKind.CONSTANT,
    ),
)
_PHP_IMPORTS = (
    _ImportRule(re.compile(r"^[ \t]*use\s+([A-Za-z_\\][\w\\]*)\s*;", re.M)),
    _ImportRule(
        re.compile(r"\b(?:require|include)(?:_once)?\s*\(?\s*['\"]([^'\"\n]+)['\"]", re.M),
    ),
)

_SHELL_FUNCTIONS = (
    _Rule(
        re.compile(
            r"^[ \t]*(?:function\s+)?([A-Za-z_][\w:.-]*)\s*\(\)\s*\{", re.M
        ),
        kind=SymbolKind.FUNCTION,
    ),
    _Rule(
        re.compile(r"^[ \t]*function\s+([A-Za-z_][\w:.-]*)(?:\s*\(\))?\s*\{", re.M),
        kind=SymbolKind.FUNCTION,
    ),
)
_SHELL_VARIABLES = (
    _Rule(
        re.compile(r"^(?:export\s+|readonly\s+|declare(?:\s+-\w+)?\s+)?([A-Za-z_]\w*)=", re.M)
    ),
)

_SPECS: dict[Language, _LanguageSpec] = {
    Language.JAVASCRIPT: _LanguageSpec(
        language=Language.JAVASCRIPT,
        class_rules=(_Rule(_JS_CLASS, kind=SymbolKind.CLASS, base_group=2),),
        function_rules=(
            _Rule(_JS_FUNCTION, kind=SymbolKind.FUNCTION),
            _Rule(_JS_ARROW, kind=SymbolKind.FUNCTION),
            _Rule(_JS_METHOD, kind=SymbolKind.FUNCTION),
        ),
        variable_rules=(_Rule(_JS_VARIABLE),),
        import_rules=_JS_IMPORTS,
        import_handler=_javascript_imports,
    ),
    Language.TYPESCRIPT: _LanguageSpec(
        language=Language.TYPESCRIPT,
        class_rules=(
            _Rule(
                _JS_CLASS,
                kind=SymbolKind.CLASS,
                base_group=2,
                implements_group=3,
            ),
        ),
        type_rules=_TS_EXTRA_TYPES,
        function_rules=(
            _Rule(_JS_FUNCTION, kind=SymbolKind.FUNCTION),
            _Rule(_JS_ARROW, kind=SymbolKind.FUNCTION),
            _Rule(_JS_METHOD, kind=SymbolKind.FUNCTION),
        ),
        variable_rules=(_Rule(_JS_VARIABLE),),
        import_rules=_JS_IMPORTS,
        import_handler=_javascript_imports,
    ),
    Language.GO: _LanguageSpec(
        language=Language.GO,
        type_rules=_GO_TYPES,
        function_rules=(
            _Rule(_GO_METHOD, kind=SymbolKind.METHOD),
            _Rule(_GO_FUNCTION, kind=SymbolKind.FUNCTION),
        ),
        variable_rules=_GO_VARIABLES,
        import_handler=_go_imports,
    ),
    Language.RUST: _LanguageSpec(
        language=Language.RUST,
        type_rules=_RUST_TYPES,
        function_rules=_RUST_FUNCTIONS,
        variable_rules=_RUST_VARIABLES,
        import_rules=_RUST_IMPORTS,
    ),
    Language.JAVA: _LanguageSpec(
        language=Language.JAVA,
        class_rules=(
            _Rule(_JAVA_CLASS, kind=SymbolKind.CLASS, base_group=2, implements_group=3),
            _Rule(_JAVA_INTERFACE, kind=SymbolKind.INTERFACE, base_group=2),
            _Rule(_JAVA_ENUM, kind=SymbolKind.ENUM),
            _Rule(_JAVA_RECORD, kind=SymbolKind.CLASS),
        ),
        function_rules=(_Rule(_JAVA_METHOD, kind=SymbolKind.FUNCTION),),
        variable_rules=(_Rule(_JAVA_VARIABLE),),
        import_rules=_JAVA_IMPORTS,
    ),
    Language.C: _LanguageSpec(
        language=Language.C,
        type_rules=_C_TYPES,
        function_rules=(_Rule(_C_FUNCTION, kind=SymbolKind.FUNCTION),),
        variable_rules=_C_VARIABLES,
        import_rules=_C_IMPORTS,
    ),
    Language.CPP: _LanguageSpec(
        language=Language.CPP,
        type_rules=_CPP_TYPES,
        function_rules=(_Rule(_C_FUNCTION, kind=SymbolKind.FUNCTION),),
        variable_rules=_C_VARIABLES,
        import_rules=_C_IMPORTS,
    ),
    Language.CSHARP: _LanguageSpec(
        language=Language.CSHARP,
        class_rules=(
            _Rule(_CS_CLASS, kind=SymbolKind.CLASS, base_group=2),
            _Rule(_CS_INTERFACE, kind=SymbolKind.INTERFACE, base_group=2),
            _Rule(_CS_STRUCT, kind=SymbolKind.STRUCT, base_group=2),
            _Rule(_CS_ENUM, kind=SymbolKind.ENUM),
            _Rule(_CS_RECORD, kind=SymbolKind.CLASS),
        ),
        function_rules=(_Rule(_CS_METHOD, kind=SymbolKind.FUNCTION),),
        variable_rules=(_Rule(_CS_VARIABLE),),
        import_rules=_CS_IMPORTS,
    ),
    Language.RUBY: _LanguageSpec(
        language=Language.RUBY,
        class_rules=(
            _Rule(_RUBY_CLASS, kind=SymbolKind.CLASS, base_group=2),
            _Rule(_RUBY_MODULE, kind=SymbolKind.MODULE),
        ),
        function_rules=(_Rule(_RUBY_METHOD, kind=SymbolKind.FUNCTION),),
        variable_rules=_RUBY_VARIABLES,
        import_rules=_RUBY_IMPORTS,
        comment_markers=("#",),
        block_comments=False,
        brace_spans=False,
    ),
    Language.PHP: _LanguageSpec(
        language=Language.PHP,
        class_rules=(
            _Rule(_PHP_CLASS, kind=SymbolKind.CLASS, base_group=2, implements_group=3),
            _Rule(_PHP_INTERFACE, kind=SymbolKind.INTERFACE, base_group=2),
            _Rule(_PHP_TRAIT, kind=SymbolKind.TRAIT),
            _Rule(_PHP_ENUM, kind=SymbolKind.ENUM),
        ),
        function_rules=(_Rule(_PHP_FUNCTION, kind=SymbolKind.FUNCTION),),
        variable_rules=_PHP_VARIABLES,
        import_rules=_PHP_IMPORTS,
    ),
    Language.SHELL: _LanguageSpec(
        language=Language.SHELL,
        function_rules=_SHELL_FUNCTIONS,
        variable_rules=_SHELL_VARIABLES,
        import_handler=_shell_imports,
        comment_markers=("#",),
        block_comments=False,
    ),
}

#: Languages handled by the regex adapters exported to ``parsers/__init__.py``.
HEURISTIC_LANGUAGES: tuple[Language, ...] = tuple(_SPECS)


def _clean_import_target(raw: str, mode: str) -> str:
    value = raw.strip()
    if mode == "strip_semicolon":
        value = value.rstrip(";").strip()
    elif mode == "strip_quotes":
        value = value.strip("'\"")
    return bounded_text(value, MAX_ISSUE_MESSAGE_CHARS)


def _collect_imports(
    spec: _LanguageSpec, code_text: str, starts: list[int]
) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    if spec.import_handler is not None:
        found.extend(spec.import_handler(code_text, starts))
    for rule in spec.import_rules:
        for match in rule.pattern.finditer(code_text):
            raw = match.group(rule.target_group)
            if not raw:
                continue
            found.append(
                (
                    _clean_import_target(raw, rule.mode),
                    line_of(starts, match.start(rule.target_group)),
                )
            )
    return found


# ---------------------------------------------------------------------------
# Generic extractor
# ---------------------------------------------------------------------------
class _Collector:
    def __init__(self, file: FileRecord, text: str, spec: _LanguageSpec) -> None:
        self.file = file
        self.text = text
        self.spec = spec
        self.starts = line_starts(text)
        code_text = _mask_comments(text, spec.comment_markers, spec.block_comments)
        self.code_text = code_text
        self.decl_text = _mask_strings(code_text)
        self.module = module_symbol(file, evidence=EvidenceKind.HEURISTIC)
        self.symbols: list[SymbolRecord] = [self.module]
        self.relations: list[RelationRecord] = []
        self.issues: list[ParseIssue] = []
        self._claimed: dict[tuple[str, int], SymbolRecord] = {}
        self._class_ranges: list[tuple[int, int, SymbolRecord]] = []
        self._base_edges: list[tuple[SymbolRecord, str, list[str]]] = []
        self._import_keys: set[tuple[str, int]] = set()

    # -- helpers ------------------------------------------------------------
    def _innermost_class(self, line: int) -> SymbolRecord | None:
        best: tuple[int, SymbolRecord] | None = None
        for start, end, symbol in self._class_ranges:
            if start <= line <= end and (best is None or start > best[0]):
                best = (start, symbol)
        return best[1] if best else None

    def _span_end(self, offset: int, line: int) -> int:
        if not self.spec.brace_spans:
            return line
        brace = self.text.find("{", offset)
        if brace == -1:
            return line
        brace_line = line_of(self.starts, brace)
        if brace_line == line + 1:
            # Allman style is only plausible when nothing but indentation sits
            # before the brace on its own line.
            line_start = self.starts[brace_line - 1]
            if self.text[line_start:brace].strip():
                return line
        elif brace_line != line:
            return line
        end = block_end_line(self.text, offset, self.starts)
        return max(line, min(end, len(self.starts)))

    def _add_symbol(
        self,
        *,
        name: str | None,
        kind: SymbolKind,
        start_line: int,
        end_line: int,
        signature: str,
        parent: SymbolRecord,
    ) -> SymbolRecord | None:
        if name is None:
            return None
        key = (name, start_line)
        if key in self._claimed:
            return None
        qualified = f"{parent.qualified_name}.{name}"
        symbol = make_symbol(
            self.file,
            name=name,
            qualified_name=qualified,
            kind=kind,
            start_line=start_line,
            end_line=end_line,
            parent_id=parent.id,
            signature=signature,
            evidence=EvidenceKind.HEURISTIC,
        )
        self._claimed[key] = symbol
        self.symbols.append(symbol)
        return symbol

    # -- extraction ---------------------------------------------------------
    def collect(self) -> None:
        self._collect_classes()
        self._collect_types()
        self._collect_functions()
        self._collect_variables()
        self._collect_imports()
        self._emit_containment()
        self._emit_base_edges()

    def _collect_classes(self) -> None:
        for rule in self.spec.class_rules:
            for match in rule.pattern.finditer(self.decl_text):
                name = _name_or_none(match.group(rule.name_group))
                if name is None or name in _KEYWORDS:
                    continue
                line = line_of(self.starts, match.start())
                end = self._span_end(match.start(), line)
                signature = _first_line(match.group(0))
                symbol = self._add_symbol(
                    name=name,
                    kind=rule.kind or SymbolKind.CLASS,
                    start_line=line,
                    end_line=end,
                    signature=signature,
                    parent=self.module,
                )
                if symbol is None:
                    continue
                self._class_ranges.append((line, end, symbol))
                bases: list[str] = []
                if rule.base_group is not None:
                    bases = _split_bases(match.group(rule.base_group))
                implements: list[str] = []
                if rule.implements_group is not None:
                    try:
                        implements = _split_bases(match.group(rule.implements_group))
                    except IndexError:
                        implements = []
                if bases or implements:
                    self._base_edges.append((symbol, "inherits", bases))
                    self._base_edges.append((symbol, "implements", implements))

    def _collect_types(self) -> None:
        for rule in self.spec.type_rules:
            for match in rule.pattern.finditer(self.decl_text):
                name = _name_or_none(match.group(rule.name_group))
                if name is None or name in _KEYWORDS:
                    continue
                line = line_of(self.starts, match.start())
                kind = rule.kind or SymbolKind.TYPE
                end = self._span_end(match.start(), line)
                parent = self._innermost_class(line) or self.module
                symbol = self._add_symbol(
                    name=name,
                    kind=kind,
                    start_line=line,
                    end_line=end,
                    signature=_first_line(match.group(0)),
                    parent=parent,
                )
                if symbol is None:
                    continue
                if kind in (
                    SymbolKind.CLASS,
                    SymbolKind.INTERFACE,
                    SymbolKind.STRUCT,
                ):
                    self._class_ranges.append((line, end, symbol))
                if rule.base_group is not None and match.group(rule.base_group):
                    bases = _split_bases(match.group(rule.base_group))
                    if bases:
                        self._base_edges.append((symbol, "inherits", bases))

    def _collect_functions(self) -> None:
        for rule in self.spec.function_rules:
            for match in rule.pattern.finditer(self.decl_text):
                name = _name_or_none(match.group(rule.name_group))
                if name is None or name in _KEYWORDS:
                    continue
                line = line_of(self.starts, match.start())
                parent_class = self._innermost_class(line)
                parent = parent_class or self.module
                kind = rule.kind or SymbolKind.FUNCTION
                if parent_class is not None and kind is SymbolKind.FUNCTION:
                    kind = SymbolKind.METHOD
                self._add_symbol(
                    name=name,
                    kind=kind,
                    start_line=line,
                    end_line=self._span_end(match.start(), line),
                    signature=_first_line(match.group(0)),
                    parent=parent,
                )

    def _collect_variables(self) -> None:
        for rule in self.spec.variable_rules:
            for match in rule.pattern.finditer(self.decl_text):
                name = _name_or_none(match.group(rule.name_group))
                if name is None or name in _KEYWORDS:
                    continue
                line = line_of(self.starts, match.start())
                parent = self._innermost_class(line) or self.module
                kind = rule.kind
                if kind is None:
                    kind = (
                        SymbolKind.CONSTANT
                        if _is_constant_name(name)
                        else SymbolKind.VARIABLE
                    )
                self._add_symbol(
                    name=name,
                    kind=kind,
                    start_line=line,
                    end_line=line,
                    signature=_first_line(match.group(0)),
                    parent=parent,
                )

    def _collect_imports(self) -> None:
        for target, line in _collect_imports(self.spec, self.code_text, self.starts):
            if not target or (target, line) in self._import_keys:
                continue
            self._import_keys.add((target, line))
            self.relations.append(
                make_relation(
                    source_id=file_id(self.file.path),
                    relation_type=RelationType.IMPORTS,
                    path=self.file.path,
                    start_line=line,
                    target_name=target,
                    status=ResolutionStatus.UNRESOLVED,
                    evidence=EvidenceKind.HEURISTIC,
                    confidence=0.5,
                )
            )

    def _emit_containment(self) -> None:
        by_id = {item.id: item for item in self.symbols}
        for symbol in self.symbols[1:]:
            parent_id = symbol.parent_id or self.module.id
            parent = by_id.get(parent_id, self.module)
            self.relations.append(
                make_relation(
                    source_id=parent.id,
                    relation_type=RelationType.CONTAINS,
                    path=self.file.path,
                    start_line=symbol.span.start_line,
                    end_line=symbol.span.end_line,
                    target_id=symbol.id,
                    target_name=symbol.name,
                    status=ResolutionStatus.RESOLVED,
                    evidence=EvidenceKind.HEURISTIC,
                    confidence=1.0,
                )
            )

    def _emit_base_edges(self) -> None:
        for symbol, relation_kind, targets in self._base_edges:
            relation_type = (
                RelationType.IMPLEMENTS
                if relation_kind == "implements"
                else RelationType.INHERITS
            )
            seen: set[str] = set()
            for target in targets:
                clean = bounded_text(target, 200)
                if not clean or clean in seen:
                    continue
                seen.add(clean)
                self.relations.append(
                    make_relation(
                        source_id=symbol.id,
                        relation_type=relation_type,
                        path=self.file.path,
                        start_line=symbol.span.start_line,
                        target_name=clean,
                        status=ResolutionStatus.UNRESOLVED,
                        evidence=EvidenceKind.HEURISTIC,
                        confidence=0.5,
                    )
                )


def _heuristic_failure(file: FileRecord, exc: BaseException) -> ParseResult:
    detail = f"heuristic parse failed: {type(exc).__name__}: {exc}"
    return ParseResult(issues=(make_issue(file.path, bounded_text(detail, MAX_ISSUE_MESSAGE_CHARS)),))


def parse_heuristic(file: FileRecord, text: str) -> ParseResult:
    """Run the regex adapter for ``file.language`` (empty result if unsupported)."""

    spec = _SPECS.get(file.language)
    if spec is None:
        return ParseResult()
    try:
        collector = _Collector(file, text, spec)
        collector.collect()
    except Exception as exc:  # noqa: BLE001 - untrusted input, never raise
        return _heuristic_failure(file, exc)
    return finalize(
        file,
        symbols=collector.symbols,
        relations=collector.relations,
        issues=collector.issues,
    )


class HeuristicAdapter:
    """Adapter object shared by every regex language."""

    def __init__(self, language: Language) -> None:
        self.language = language
        self.version = PARSER_VERSION

    def parse(self, file: FileRecord, text: str) -> ParseResult:
        return parse_heuristic(file, text)


def adapters() -> dict[Language, HeuristicAdapter]:
    return {language: HeuristicAdapter(language) for language in HEURISTIC_LANGUAGES}


__all__ = [
    "HEURISTIC_LANGUAGES",
    "PARSER_VERSION",
    "HeuristicAdapter",
    "adapters",
    "parse_heuristic",
]
