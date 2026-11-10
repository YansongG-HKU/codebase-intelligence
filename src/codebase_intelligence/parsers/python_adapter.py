"""Python adapter built on the standard-library :mod:`ast` module.

This is the only *syntax-tree-backed* adapter in the engine: everything it emits
is a parser fact (``EvidenceKind.PARSER``) except ``CALLS`` edges, which are
target-resolution guesses and therefore labelled ``HEURISTIC`` with
``confidence <= 0.8`` (see ``docs/SPEC.md`` §6).

Extracted nodes:

* one ``module`` symbol per file;
* ``class`` declarations (including nested classes) with bases → ``INHERITS``;
* ``function`` declarations and ``method`` declarations (a function directly in
  a class body), including nested functions;
* module-level and class-level assignments → ``constant`` (UPPER_CASE) or
  ``variable``;
* ``import`` / ``from ... import`` statements → raw ``IMPORTS`` relations with
  the original dotted/relative specifier preserved in ``target_name``;
* same-file unambiguous call sites → ``CALLS`` edges resolved to the local
  symbol.  Calls that cannot be resolved *in this file* are intentionally not
  emitted: the contract forbids pretending they are dependencies.

Malformed source never raises: :class:`SyntaxError` (and any other parse-time
failure) becomes one bounded :class:`ParseIssue`.
"""

from __future__ import annotations

import ast
from typing import Iterable

from codebase_intelligence.model import (
    EvidenceKind,
    FileRecord,
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
    finalize,
    make_issue,
    make_relation,
    make_symbol,
    module_symbol,
)
from codebase_intelligence.util import bounded_text

#: Version tag of this adapter; part of ``PARSER_VERSIONS`` and cache keys.
PARSER_VERSION = "ast-v1"

#: Confidence attached to a same-file call resolution (heuristic label, SPEC §6).
_CALL_CONFIDENCE = 0.8

#: Node kinds whose subtrees are handled by their own visitor, not the caller.
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _safe_unparse(node: ast.AST) -> str:
    """``ast.unparse`` that never raises on oddly constructed nodes."""

    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - best-effort rendering only
        return ""


def _docstring(node: ast.AST) -> str | None:
    try:
        return ast.get_docstring(node, clean=True)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - malformed docstrings must not break parsing
        return None


def _line(node: ast.AST) -> int:
    return max(1, int(getattr(node, "lineno", 1) or 1))


def _end_line(node: ast.AST, fallback: int) -> int:
    end = int(getattr(node, "end_lineno", 0) or 0)
    return max(fallback, end) if end else fallback


def _signature(node: ast.AST, name: str, *, async_: bool = False) -> str:
    """Render a bounded, human-readable declaration signature."""

    if isinstance(node, ast.ClassDef):
        bases = [_safe_unparse(base) for base in node.bases]
        keywords = [_safe_unparse(keyword) for keyword in node.keywords]
        parts = bases + keywords
        return f"class {name}" + (f"({', '.join(parts)})" if parts else "")
    arguments = getattr(node, "args", None)
    rendered = _safe_unparse(arguments) if arguments is not None else ""
    returns = getattr(node, "returns", None)
    result = f"{'async ' if async_ else ''}def {name}({rendered})"
    if returns is not None:
        result += f" -> {_safe_unparse(returns)}"
    return result


def _call_sources(node: ast.AST) -> list[ast.Call]:
    """Calls directly owned by *node*, without descending into nested scopes."""

    found: list[ast.Call] = []

    def visit(current: ast.AST) -> None:
        if isinstance(current, _SCOPE_NODES):
            return
        if isinstance(current, ast.Call):
            found.append(current)
        for child in ast.iter_child_nodes(current):
            visit(child)

    visit(node)
    return found


class _PythonCollector:
    """Single-pass collector over an already-parsed module."""

    def __init__(self, file: FileRecord) -> None:
        self.file = file
        self.module: SymbolRecord = module_symbol(file)
        self.symbols: list[SymbolRecord] = [self.module]
        self.relations: list[RelationRecord] = []
        self.issues: list[ParseIssue] = []
        self._classes: list[tuple[ast.ClassDef, SymbolRecord]] = []
        self._class_bases: dict[str, list[str]] = {}
        self._by_name: dict[str, list[SymbolRecord]] = {}
        self._import_keys: set[tuple[str, int]] = set()
        self._call_keys: set[tuple[str, str, int]] = set()
        self._contains_keys: set[tuple[str, str]] = set()
        # Calls are resolved only after every declaration in the file is known,
        # so a function defined later can still be the target of an earlier call.
        self._deferred_calls: list[tuple[str, str, int, int]] = []

    # -- symbol registration ------------------------------------------------
    def _register(
        self,
        symbol: SymbolRecord,
        *,
        container: SymbolRecord,
        contain: bool = True,
    ) -> None:
        self.symbols.append(symbol)
        self._by_name.setdefault(symbol.name, []).append(symbol)
        if contain:
            self._add_contains(container, symbol)

    def _add_contains(self, parent: SymbolRecord, child: SymbolRecord) -> None:
        key = (parent.id, child.id)
        if key in self._contains_keys:
            return
        self._contains_keys.add(key)
        self.relations.append(
            make_relation(
                source_id=parent.id,
                relation_type=RelationType.CONTAINS,
                path=self.file.path,
                start_line=child.span.start_line,
                end_line=child.span.end_line,
                target_id=child.id,
                target_name=child.name,
                status=ResolutionStatus.RESOLVED,
                evidence=EvidenceKind.PARSER,
                confidence=1.0,
            )
        )

    # -- imports ------------------------------------------------------------
    def _add_import(self, target_name: str | None, node: ast.AST) -> None:
        if not target_name:
            return
        start = _line(node)
        key = (target_name, start)
        if key in self._import_keys:
            return
        self._import_keys.add(key)
        self.relations.append(
            make_relation(
                source_id=file_id(self.file.path),
                relation_type=RelationType.IMPORTS,
                path=self.file.path,
                start_line=start,
                end_line=_end_line(node, start),
                target_name=target_name,
                status=ResolutionStatus.UNRESOLVED,
                evidence=EvidenceKind.PARSER,
                confidence=0.0,
            )
        )

    # -- traversal ----------------------------------------------------------
    def collect(self, tree: ast.Module) -> None:
        self._visit_body(tree.body, container=self.module, scope="module")

    def _visit_body(  # noqa: C901 - explicit is better than clever here
        self, nodes: Iterable[ast.stmt], *, container: SymbolRecord, scope: str
    ) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                self._visit_class(node, container=container, scope=scope)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._visit_function(node, container=container, scope=scope)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self._add_import(alias.name, node)
            elif isinstance(node, ast.ImportFrom):
                level = int(node.level or 0)
                dotted = "." * level + (node.module or "")
                self._add_import(dotted, node)
            else:
                if scope in ("module", "class") and isinstance(
                    node, (ast.Assign, ast.AnnAssign)
                ):
                    self._visit_assignment(node, container=container)
                self._visit_calls(node, source=container)

    def _visit_class(self, node: ast.ClassDef, *, container: SymbolRecord, scope: str) -> None:
        name = node.name
        qualified = f"{container.qualified_name}.{name}"
        base_names = [_safe_unparse(base) for base in node.bases]
        symbol = make_symbol(
            self.file,
            name=name,
            qualified_name=qualified,
            kind=SymbolKind.CLASS,
            start_line=_line(node),
            end_line=_end_line(node, _line(node)),
            parent_id=container.id,
            signature=_signature(node, name),
            doc=_docstring(node),
            evidence=EvidenceKind.PARSER,
            start_column=int(getattr(node, "col_offset", 0) or 0),
            end_column=int(getattr(node, "end_col_offset", 0) or 0),
        )
        # Dataclasses are immutable, so base edges are stored and emitted later
        # once every class name in the file is known.
        self._class_bases[symbol.id] = base_names
        self._register(symbol, container=container)
        self._classes.append((node, symbol))
        self._visit_body(node.body, container=symbol, scope="class")

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        container: SymbolRecord,
        scope: str,
    ) -> None:
        name = node.name
        is_async = isinstance(node, ast.AsyncFunctionDef)
        kind = SymbolKind.METHOD if scope == "class" else SymbolKind.FUNCTION
        qualified = f"{container.qualified_name}.{name}"
        symbol = make_symbol(
            self.file,
            name=name,
            qualified_name=qualified,
            kind=kind,
            start_line=_line(node),
            end_line=_end_line(node, _line(node)),
            parent_id=container.id,
            signature=_signature(node, name, async_=is_async),
            doc=_docstring(node),
            evidence=EvidenceKind.PARSER,
            start_column=int(getattr(node, "col_offset", 0) or 0),
            end_column=int(getattr(node, "end_col_offset", 0) or 0),
        )
        self._register(symbol, container=container)
        self._visit_body(node.body, container=symbol, scope="function")

    def _visit_assignment(
        self, node: ast.Assign | ast.AnnAssign, *, container: SymbolRecord
    ) -> None:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value: ast.AST | None = node.value
        else:
            targets = [node.target]
            value = node.value
        for target in targets:
            for leaf in self._assignment_leaves(target):
                name = leaf.id
                qualified = f"{container.qualified_name}.{name}"
                kind = SymbolKind.CONSTANT if name.isupper() else SymbolKind.VARIABLE
                rendered_value = _safe_unparse(value) if value is not None else ""
                signature = f"{name} = {rendered_value}" if rendered_value else name
                symbol = make_symbol(
                    self.file,
                    name=name,
                    qualified_name=qualified,
                    kind=kind,
                    start_line=_line(node),
                    end_line=_end_line(node, _line(node)),
                    parent_id=container.id,
                    signature=signature,
                    evidence=EvidenceKind.PARSER,
                    start_column=int(getattr(leaf, "col_offset", 0) or 0),
                )
                self._register(symbol, container=container)

    def _assignment_leaves(self, target: ast.expr) -> list[ast.Name]:
        """Simple ``Name`` targets; ``a = b = 1`` yields both names."""

        if isinstance(target, ast.Name):
            return [target]
        if isinstance(target, (ast.Tuple, ast.List)):
            leaves: list[ast.Name] = []
            for element in target.elts:
                leaves.extend(self._assignment_leaves(element))
            return leaves
        return []

    def _visit_calls(self, node: ast.AST, *, source: SymbolRecord) -> None:
        for call in _call_sources(node):
            function = call.func
            if not isinstance(function, ast.Name):
                continue
            line = _line(call)
            self._deferred_calls.append(
                (source.id, function.id, line, _end_line(call, line))
            )

    def resolve_calls(self) -> None:
        """Resolve deferred call sites against every symbol declared in the file."""

        for source_id, name, line, end_line in self._deferred_calls:
            key = (source_id, name, line)
            if key in self._call_keys:
                continue
            candidates = [
                symbol
                for symbol in self._by_name.get(name, ())
                if symbol.kind
                in (SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CLASS)
            ]
            if not candidates:
                # The callee is defined outside this file (or is a builtin).
                # Same-file call resolution cannot confirm it, so emit nothing.
                continue
            self._call_keys.add(key)
            if len(candidates) == 1:
                target = candidates[0]
                self.relations.append(
                    make_relation(
                        source_id=source_id,
                        relation_type=RelationType.CALLS,
                        path=self.file.path,
                        start_line=line,
                        end_line=end_line,
                        target_id=target.id,
                        target_name=name,
                        status=ResolutionStatus.RESOLVED,
                        evidence=EvidenceKind.HEURISTIC,
                        confidence=_CALL_CONFIDENCE,
                    )
                )
            else:
                self.relations.append(
                    make_relation(
                        source_id=source_id,
                        relation_type=RelationType.CALLS,
                        path=self.file.path,
                        start_line=line,
                        end_line=end_line,
                        target_name=name,
                        status=ResolutionStatus.AMBIGUOUS,
                        evidence=EvidenceKind.HEURISTIC,
                        confidence=0.3,
                    )
                )

    # -- post-processing ----------------------------------------------------
    def resolve_bases(self) -> None:
        for node, symbol in self._classes:
            base_names: list[str] = self._class_bases.get(symbol.id, [])
            for base_name in base_names:
                if not base_name:
                    continue
                simple = base_name if _is_simple_name(base_name) else None
                candidates = self._by_name.get(simple, ()) if simple else ()
                classes = [item for item in candidates if item.kind is SymbolKind.CLASS]
                if len(classes) == 1:
                    relation = make_relation(
                        source_id=symbol.id,
                        relation_type=RelationType.INHERITS,
                        path=self.file.path,
                        start_line=symbol.span.start_line,
                        target_id=classes[0].id,
                        target_name=base_name,
                        status=ResolutionStatus.RESOLVED,
                        evidence=EvidenceKind.PARSER,
                        confidence=0.8,
                    )
                elif len(classes) > 1:
                    relation = make_relation(
                        source_id=symbol.id,
                        relation_type=RelationType.INHERITS,
                        path=self.file.path,
                        start_line=symbol.span.start_line,
                        target_name=base_name,
                        status=ResolutionStatus.AMBIGUOUS,
                        evidence=EvidenceKind.PARSER,
                        confidence=0.3,
                    )
                else:
                    relation = make_relation(
                        source_id=symbol.id,
                        relation_type=RelationType.INHERITS,
                        path=self.file.path,
                        start_line=symbol.span.start_line,
                        target_name=base_name,
                        status=ResolutionStatus.UNRESOLVED,
                        evidence=EvidenceKind.PARSER,
                        confidence=0.5,
                    )
                self.relations.append(relation)


def _is_simple_name(name: str) -> bool:
    return name.isidentifier()


def _parse_failure(file: FileRecord, exc: BaseException) -> ParseResult:
    if isinstance(exc, SyntaxError):
        line = getattr(exc, "lineno", None)
        column = getattr(exc, "offset", None)
        location = f"line {line}" if line else "unknown line"
        if column:
            location += f", column {column}"
        detail = f"syntax error at {location}: {exc.msg}"
    else:
        detail = f"python parse failed: {type(exc).__name__}: {exc}"
    return ParseResult(issues=(make_issue(file.path, bounded_text(detail, MAX_ISSUE_MESSAGE_CHARS)),))


def parse_python(file: FileRecord, text: str) -> ParseResult:
    """Parse one Python file into symbols, raw relations and bounded issues."""

    try:
        tree = ast.parse(text, filename=file.path)
    except (SyntaxError, ValueError) as exc:
        return _parse_failure(file, exc)
    except Exception as exc:  # noqa: BLE001 - parser must never raise
        return _parse_failure(file, exc)

    collector = _PythonCollector(file)
    try:
        collector.collect(tree)
        collector.resolve_bases()
        collector.resolve_calls()
    except Exception as exc:  # noqa: BLE001 - defensive: untrusted input
        return _parse_failure(file, exc)
    return finalize(
        file,
        symbols=collector.symbols,
        relations=collector.relations,
        issues=collector.issues,
    )


class PythonAstAdapter:
    """Thin adapter object kept for symmetry with future language adapters."""

    language = "python"
    version = PARSER_VERSION

    def parse(self, file: FileRecord, text: str) -> ParseResult:
        return parse_python(file, text)


__all__ = ["PARSER_VERSION", "PythonAstAdapter", "parse_python"]
