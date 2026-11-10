"""Import resolution: turn raw parser ``IMPORTS`` facts into typed edges.

Parsers emit raw specifiers (``os``, ``.helpers``, ``./util``,
``example.com/app/service/util``).  This module resolves *where that is safe*
against the set of files that were actually scanned, following
``docs/SPEC.md`` §7:

* Python: dotted modules and relative imports, based on the importing file's
  package; ``<module>.py`` or ``<package>/__init__.py``;
* JavaScript/TypeScript: relative specifiers only, with the usual extension and
  ``index.*`` fallbacks; bare specifiers are ``EXTERNAL``;
* Go: package paths map to local directories when a directory suffix matches,
  otherwise the import is ``EXTERNAL``;
* languages without a specified resolver keep their honest ``UNRESOLVED``
  parser edge (never promoted, never dropped).

Resolution never guesses: two equally valid candidates become ``AMBIGUOUS`` with
no target id, and a local prefix that does not resolve stays ``UNRESOLVED``.
The resulting relations use ``EvidenceKind.RESOLVER`` and a status in
``{resolved, external, unresolved, ambiguous}``.  ``resolve_imports`` is
idempotent: relations that already carry ``EvidenceKind.RESOLVER`` pass through
unchanged.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Iterable, Sequence

from codebase_intelligence.model import (
    EvidenceKind,
    FileRecord,
    Language,
    RelationRecord,
    RelationType,
    ResolutionStatus,
)
from codebase_intelligence.util import to_posix

#: JS/TS extensions tried for extension-less relative specifiers, in order.
_JS_EXTENSIONS: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
#: ``INDEX`` extensions are the same set; kept as a named constant for clarity.
_JS_INDEX_EXTENSIONS: tuple[str, ...] = _JS_EXTENSIONS

#: Resolver confidence labels (float on RelationRecord, rounded by the model).
_CONFIDENCE_RESOLVED = 0.95
_CONFIDENCE_EXTERNAL = 0.9
_CONFIDENCE_UNRESOLVED = 0.3
_CONFIDENCE_LOCAL_UNRESOLVED = 0.4
_CONFIDENCE_AMBIGUOUS = 0.3
_CONFIDENCE_GO_DIRECTORY = 0.7
_CONFIDENCE_GO_EXTERNAL = 0.8


@dataclass(frozen=True)
class ResolutionContext:
    """Precomputed lookups for one file set (built once per resolution pass)."""

    files_by_path: dict[str, FileRecord]
    python_modules: dict[str, tuple[str, ...]]
    go_directories: dict[str, tuple[str, ...]]
    local_top_level: frozenset[str]
    source_roots: tuple[str, ...]


_PYTHON_SUFFIXES: tuple[str, ...] = (".py", ".pyi")


def _strip_python_suffix(filename: str) -> str | None:
    for suffix in _PYTHON_SUFFIXES:
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return None


def _dotted_from_python_tail(tail: str) -> str | None:
    """Dotted module name for a path tail relative to a source root."""

    parts = [part for part in tail.split("/") if part]
    if not parts:
        return None
    stem = _strip_python_suffix(parts[-1])
    if stem is None or not stem:
        return None
    if stem == "__init__":
        parts = parts[:-1]
    else:
        parts[-1] = stem
    if not parts:
        return None
    return ".".join(parts)


def python_module_name(path: str) -> str | None:
    """Dotted module name for a Python file path (``pkg/mod.py`` → ``pkg.mod``)."""

    posix = to_posix(path)
    return _dotted_from_python_tail(posix)


def detect_source_roots(files: Iterable[FileRecord]) -> tuple[str, ...]:
    """Detect import source roots such as ``src/`` or ``lib/`` from the file set.

    A source root is the parent of the *topmost* package directory in a package
    chain: for ``src/demo/core.py`` with ``src/demo/__init__.py`` present and no
    ``src/__init__.py``, the root is ``src`` (so ``from demo.util import x`` is
    a repository-local import).  The repository root ``""`` is always a source
    root, which keeps flat layouts and relative imports working unchanged.

    The helper is deliberately independent of Python parsing (it only looks at
    file paths, using the presence of ``__init__.py`` for package detection), so
    future heuristic language adapters can reuse it.
    """

    python_paths = [
        to_posix(file.path) for file in files if file.language is Language.PYTHON
    ]
    package_dirs: set[str] = set()
    for path in python_paths:
        directory, _, filename = path.rpartition("/")
        if directory and filename in ("__init__.py", "__init__.pyi"):
            package_dirs.add(directory)
    roots: set[str] = {""}
    for path in python_paths:
        directory = posixpath.dirname(path)
        if not directory or directory not in package_dirs:
            continue
        current = directory
        while True:
            parent = posixpath.dirname(current)
            if parent and parent in package_dirs:
                current = parent
                continue
            roots.add(parent)
            break
    return tuple([""] + sorted(root for root in roots if root))


def python_module_aliases(
    path: str, source_roots: Sequence[str]
) -> tuple[str, ...]:
    """Every dotted module name *path* can be imported as, given source roots.

    ``src/demo/core.py`` with source roots ``("", "src")`` yields
    ``("demo.core", "src.demo.core")``: the source-root name is what absolute
    imports use, the repository-root name is what relative imports resolve to.
    """

    posix = to_posix(path)
    aliases: list[str] = []
    for root in source_roots:
        prefix = f"{root}/" if root else ""
        if not posix.startswith(prefix):
            continue
        name = _dotted_from_python_tail(posix[len(prefix) :])
        if name is not None:
            aliases.append(name)
    return tuple(sorted(set(aliases)))


def build_python_module_index(
    files: Iterable[FileRecord],
    *,
    source_roots: Sequence[str] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Map every dotted module alias → sorted tuple of candidate file paths."""

    ordered = tuple(files)
    roots = (
        tuple(source_roots)
        if source_roots is not None
        else detect_source_roots(ordered)
    )
    grouped: dict[str, list[str]] = {}
    for file in ordered:
        if file.language is not Language.PYTHON:
            continue
        for name in python_module_aliases(file.path, roots):
            grouped.setdefault(name, []).append(file.path)
    return {name: tuple(sorted(paths)) for name, paths in grouped.items()}


def build_go_directory_index(files: Iterable[FileRecord]) -> dict[str, tuple[str, ...]]:
    """Map repository-relative directory → sorted tuple of Go files in it."""

    grouped: dict[str, list[str]] = {}
    for file in files:
        if file.language is not Language.GO:
            continue
        directory = posixpath.dirname(to_posix(file.path))
        grouped.setdefault(directory, []).append(file.path)
    return {directory: tuple(sorted(paths)) for directory, paths in grouped.items()}


def _local_top_level_names(
    files: Iterable[FileRecord], python_modules: dict[str, tuple[str, ...]]
) -> frozenset[str]:
    names: set[str] = set()
    for module in python_modules:
        names.add(module.split(".")[0])
    for file in files:
        parts = to_posix(file.path).split("/")
        if not parts:
            continue
        if len(parts) == 1:
            names.add(parts[0].rsplit(".", 1)[0] if "." in parts[0] else parts[0])
        else:
            names.add(parts[0])
    return frozenset(name for name in names if name)


def build_resolution_context(files: Sequence[FileRecord]) -> ResolutionContext:
    """Build the lookup tables used for every import in one file set."""

    ordered = tuple(files)
    files_by_path = {file.path: file for file in ordered}
    source_roots = detect_source_roots(ordered)
    python_modules = build_python_module_index(ordered, source_roots=source_roots)
    return ResolutionContext(
        files_by_path=files_by_path,
        python_modules=python_modules,
        go_directories=build_go_directory_index(ordered),
        local_top_level=_local_top_level_names(ordered, python_modules),
        source_roots=source_roots,
    )


def _python_module_tails(path: str, source_roots: Sequence[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """(source root, dotted components) for every source root prefixing *path*."""

    posix = to_posix(path)
    tails: list[tuple[str, tuple[str, ...]]] = []
    for root in source_roots:
        prefix = f"{root}/" if root else ""
        if not posix.startswith(prefix):
            continue
        dotted = _dotted_from_python_tail(posix[len(prefix) :])
        if dotted is not None:
            tails.append((root, tuple(dotted.split("."))))
    return tuple(tails)


def _common_prefix_length(left: Sequence[str], right: Sequence[str]) -> int:
    count = 0
    for left_part, right_part in zip(left, right):
        if left_part != right_part:
            break
        count += 1
    return count


def _select_python_candidate(
    context: ResolutionContext, importer_path: str, candidates: Sequence[str]
) -> str | None:
    """Pick the candidate sharing the longest package-path prefix, else ``None``.

    ``None`` means the candidates are indistinguishable, which the resolver
    reports as ``AMBIGUOUS`` instead of guessing.
    """

    if len(candidates) == 1:
        return candidates[0]
    importer_tails = _python_module_tails(importer_path, context.source_roots)
    scored: list[tuple[tuple[int, int], str]] = []
    for candidate in candidates:
        candidate_tails = _python_module_tails(candidate, context.source_roots)
        best: tuple[int, int] = (0, 0)
        for importer_root, importer_parts in importer_tails:
            for candidate_root, candidate_parts in candidate_tails:
                score = (
                    _common_prefix_length(importer_parts, candidate_parts),
                    1 if importer_root == candidate_root else 0,
                )
                if score > best:
                    best = score
        scored.append((best, candidate))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


# ---------------------------------------------------------------------------
# Per-language resolution
# ---------------------------------------------------------------------------
def _python_target_module(source_path: str, target: str) -> str | None:
    """Convert a raw Python import specifier to a dotted module name."""

    if not target:
        return None
    if target.startswith("."):
        level = len(target) - len(target.lstrip("."))
        remainder = target[level:]
        package_parts = to_posix(source_path).split("/")[:-1]
        keep = len(package_parts) - (level - 1)
        if keep < 0:
            return None
        base = package_parts[:keep]
        parts = base + (remainder.split(".") if remainder else [])
        if not parts:
            return None
        return ".".join(part for part in parts if part)
    value = target.rstrip(".")
    return value or None


def _resolve_python(
    context: ResolutionContext, source: FileRecord, target: str
) -> tuple[ResolutionStatus, str | None, float]:
    module = _python_target_module(source.path, target)
    if module is None:
        return ResolutionStatus.UNRESOLVED, None, _CONFIDENCE_UNRESOLVED
    candidates = context.python_modules.get(module, ())
    if candidates:
        selected = _select_python_candidate(context, source.path, candidates)
        if selected is None:
            return ResolutionStatus.AMBIGUOUS, None, _CONFIDENCE_AMBIGUOUS
        return ResolutionStatus.RESOLVED, f"file:{selected}", _CONFIDENCE_RESOLVED
    if target.startswith("."):
        # A relative import can never be external; it is just not in the index.
        return ResolutionStatus.UNRESOLVED, None, _CONFIDENCE_UNRESOLVED
    top_level = module.split(".")[0]
    if top_level in context.local_top_level:
        return ResolutionStatus.UNRESOLVED, None, _CONFIDENCE_LOCAL_UNRESOLVED
    return ResolutionStatus.EXTERNAL, None, _CONFIDENCE_EXTERNAL


def _is_relative_js_specifier(target: str) -> bool:
    return target.startswith("./") or target.startswith("../")


def _js_candidates(context: ResolutionContext, joined: str) -> tuple[str, ...]:
    """All existing files a relative JS/TS specifier could mean (sorted)."""

    base = posixpath.basename(joined)
    looks_explicit = "." in base
    candidates: list[str] = []
    if looks_explicit:
        if joined in context.files_by_path:
            candidates.append(joined)
        return tuple(candidates)
    if joined in context.files_by_path:
        candidates.append(joined)
    for extension in _JS_EXTENSIONS:
        candidate = joined + extension
        if candidate in context.files_by_path:
            candidates.append(candidate)
    for extension in _JS_INDEX_EXTENSIONS:
        candidate = f"{joined}/index{extension}"
        if candidate in context.files_by_path:
            candidates.append(candidate)
    return tuple(sorted(set(candidates)))


def _resolve_javascript(
    context: ResolutionContext, source: FileRecord, target: str
) -> tuple[ResolutionStatus, str | None, float]:
    if not _is_relative_js_specifier(target):
        if target.startswith("/"):
            return ResolutionStatus.UNRESOLVED, None, _CONFIDENCE_UNRESOLVED
        # Bare specifier: package/nodule builtin, never a repository file.
        return ResolutionStatus.EXTERNAL, None, _CONFIDENCE_EXTERNAL
    source_dir = posixpath.dirname(to_posix(source.path))
    joined = posixpath.normpath(posixpath.join(source_dir, target))
    if joined in (".", "") or joined.startswith(".."):
        return ResolutionStatus.UNRESOLVED, None, _CONFIDENCE_UNRESOLVED
    candidates = _js_candidates(context, joined)
    if len(candidates) == 1:
        return ResolutionStatus.RESOLVED, f"file:{candidates[0]}", _CONFIDENCE_RESOLVED
    if len(candidates) > 1:
        return ResolutionStatus.AMBIGUOUS, None, _CONFIDENCE_AMBIGUOUS
    return ResolutionStatus.UNRESOLVED, None, _CONFIDENCE_UNRESOLVED


def _go_representative(files: tuple[str, ...]) -> str:
    """Pick one deterministic file to stand for a Go package directory."""

    ordered = sorted(files)
    for path in ordered:
        directory, filename = posixpath.split(path)
        stem = filename[:-3] if filename.endswith(".go") else filename
        if stem == posixpath.basename(directory):
            return path
    return ordered[0]


def _resolve_go(
    context: ResolutionContext, source: FileRecord, target: str
) -> tuple[ResolutionStatus, str | None, float]:
    parts = [part for part in target.split("/") if part]
    # 1. Exact repo-relative directory suffix (repository root == module root).
    for count in range(len(parts), 0, -1):
        candidate = "/".join(parts[-count:])
        files = context.go_directories.get(candidate)
        if files:
            return (
                ResolutionStatus.RESOLVED,
                f"file:{_go_representative(files)}",
                _CONFIDENCE_GO_DIRECTORY,
            )
    # 2. The repository may live below the module root, so a local directory can
    #    be a suffix of the import path itself (``.../service/util`` → ``service/util``).
    needle = target.strip("/")
    best_directory: str | None = None
    for directory in context.go_directories:
        if not directory:
            continue
        if needle == directory or needle.endswith("/" + directory):
            if best_directory is None or directory.count("/") > best_directory.count("/"):
                best_directory = directory
    if best_directory is not None:
        return (
            ResolutionStatus.RESOLVED,
            f"file:{_go_representative(context.go_directories[best_directory])}",
            _CONFIDENCE_GO_DIRECTORY,
        )
    # No local directory matches: stdlib or a third-party module.
    return ResolutionStatus.EXTERNAL, None, _CONFIDENCE_GO_EXTERNAL


def _resolve_import(
    context: ResolutionContext, source: FileRecord, target_name: str
) -> tuple[ResolutionStatus, str | None, float] | None:
    if source.language is Language.PYTHON:
        return _resolve_python(context, source, target_name)
    if source.language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
        return _resolve_javascript(context, source, target_name)
    if source.language is Language.GO:
        return _resolve_go(context, source, target_name)
    # No resolver is specified for this language: keep the honest raw edge.
    return None


def source_path_from_id(source_id: str) -> str | None:
    """Inverse of :func:`codebase_intelligence.model.file_id`."""

    if not source_id.startswith("file:"):
        return None
    return source_id[len("file:") :]


def _relation_sort_key(relation: RelationRecord) -> tuple[str, str, str, str, int]:
    return (
        relation.source_id,
        relation.relation_type.value,
        relation.target_id or "",
        relation.target_name or "",
        relation.span.start_line if relation.span else 0,
    )


def resolve_imports(
    files: Iterable[FileRecord], relations: Iterable[RelationRecord]
) -> tuple[RelationRecord, ...]:
    """Return *relations* with every raw ``IMPORTS`` edge resolved where safe.

    Non-import relations and relations that were already produced by a resolver
    are returned unchanged, which makes repeated graph construction idempotent.
    """

    file_list = tuple(files)
    context = build_resolution_context(file_list)
    resolved: list[RelationRecord] = []
    for relation in relations:
        if (
            relation.relation_type is not RelationType.IMPORTS
            or relation.evidence is EvidenceKind.RESOLVER
        ):
            resolved.append(relation)
            continue
        source_path = source_path_from_id(relation.source_id)
        source = context.files_by_path.get(source_path) if source_path else None
        if source is None or not relation.target_name:
            resolved.append(relation)
            continue
        outcome = _resolve_import(context, source, relation.target_name)
        if outcome is None:
            resolved.append(relation)
            continue
        status, target_id, confidence = outcome
        resolved.append(
            RelationRecord(
                source_id=relation.source_id,
                relation_type=relation.relation_type,
                status=status,
                evidence=EvidenceKind.RESOLVER,
                target_id=target_id,
                target_name=relation.target_name,
                span=relation.span,
                confidence=round(float(confidence), 4),
            )
        )
    return tuple(sorted(resolved, key=_relation_sort_key))


__all__ = [
    "ResolutionContext",
    "build_go_directory_index",
    "build_python_module_index",
    "build_resolution_context",
    "python_module_name",
    "resolve_imports",
    "source_path_from_id",
]
