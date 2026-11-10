"""Deterministic artifact export for the L2 panel (``PANEL_CONTRACT.md`` §1/§2).

``cbi export`` renders one fixed, repository-local bundle from a single index
snapshot and writes it into the generation directory
(``docs/codebase-intelligence/`` by default):

============================  =================================================
``overview.json``             ``reporting.overview_payload`` (budget 2000)
``repo-map.json``             ``reporting.map_payload`` (budget 4000)
``ARCHITECTURE.generated.md`` ``reporting.markdown_report``
``REPO_MAP.md``               ``reporting.markdown_map``
``dependencies.mmd``          Mermaid ``graph LR`` of resolved file imports
``CONTEXT_BRIEF.md``          agent/human orientation brief
``graph.snapshot.json``        layered graph with evidence locations
``manifest.json``             sha256 of the seven content files above (written last)
============================  =================================================

Contract properties enforced here:

* **One index build.**  The index is built exactly once with
  :func:`codebase_intelligence.indexing.ensure_index`; every file is rendered
  from that same snapshot, so the bundle is internally consistent and cheap.
* **Deterministic bytes.**  Canonical JSON with sorted keys plus one trailing
  newline for JSON, LF-only Markdown/Mermaid, every list explicitly ordered.
  No timestamps, durations, host names, absolute paths, cache state or random
  ids are ever rendered, so two runs over identical content are byte-identical.
  The generation directory is excluded from the scan (via
  :data:`~codebase_intelligence.scanner.policy.DEFAULT_EXCLUDED_PATHS` and,
  for custom ``--out`` paths, an extra scan exclude), which is what makes a
  second run stable instead of indexing the files the first run wrote.
* **Atomic writes.**  Each changed file is written to a ``mkstemp`` temp file in
  the destination directory and moved with :func:`os.replace`; unchanged files
  are not touched at all (mtime is preserved).
* **``--check``.**  Renders the full bundle but writes nothing and reports the
  per-file plan (``created``/``updated``/``unchanged``).  The CLI exits ``0``
  only when all eight files exist with identical bytes.
* **Strict path safety.**  ``--out`` must be a repository-relative directory
  inside the resolved workspace root: absolute paths, ``..`` segments, drive
  letters and symlinked components are refused, only the eight fixed file names
  are ever written, and nothing outside ``outDir`` is touched or deleted.

All generated paths are repository-relative POSIX paths.
"""

from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from codebase_intelligence import api
from codebase_intelligence.errors import OutsideRootError, RepositoryError, UsageError
from codebase_intelligence.graph.explorer import graph_view
from codebase_intelligence.graph.snapshot import GRAPH_DIRECTORY, GRAPH_FILE_NAME, graph_snapshot, snapshot_document
from codebase_intelligence.model import (
    SCHEMA_VERSION,
    IndexSnapshot,
    RelationType,
    ResolutionStatus,
)
from codebase_intelligence.util import (
    canonical_json,
    is_within,
    sha256_bytes,
    to_posix,
)

#: Repository-relative directory the panel reads and writes by default.
DEFAULT_OUT_DIR = GRAPH_DIRECTORY

#: Version of the export payload and of ``manifest.json`` (contract §1: "1").
EXPORT_SCHEMA_VERSION = SCHEMA_VERSION

#: Fixed token budgets for the exported JSON artifacts (contract §1).
OVERVIEW_MAX_TOKENS = 2000
MAP_MAX_TOKENS = 4000

#: Bound on rendered Mermaid edges (contract §1: ≤ 400 edges).
MAX_DEPENDENCY_EDGES = 400

#: Bounds for the CONTEXT_BRIEF.md sections (kept small enough to stay useful).
MAX_BRIEF_LANGUAGE_ROWS = 12
MAX_BRIEF_ENTRY_POINTS = 10
MAX_BRIEF_HUB_ROWS = 10
MAX_BRIEF_KEY_FILES = 10

#: Generated file names in write order; ``manifest.json`` is always last.
GENERATED_FILE_NAMES: tuple[str, ...] = (
    "overview.json",
    "repo-map.json",
    GRAPH_FILE_NAME,
    "ARCHITECTURE.generated.md",
    "REPO_MAP.md",
    "dependencies.mmd",
    "CONTEXT_BRIEF.md",
)
MANIFEST_FILE_NAME = "manifest.json"
EXPORT_FILE_NAMES: tuple[str, ...] = (*GENERATED_FILE_NAMES, MANIFEST_FILE_NAME)

#: File status vocabulary reported by ``--check`` and by a normal write.
STATUS_CREATED = "created"
STATUS_UPDATED = "updated"
STATUS_UNCHANGED = "unchanged"
STATUSES = (STATUS_CREATED, STATUS_UPDATED, STATUS_UNCHANGED)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ExportFile:
    """One generated file and what happened to it during this run."""

    name: str
    path: str
    status: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Outcome of one ``cbi export`` run.

    ``out_path`` is kept in-process only; :meth:`to_payload` is the exact
    JSON-safe CLI/panel payload and never contains absolute paths.
    """

    out_dir: str
    out_path: Path
    check: bool
    files: tuple[ExportFile, ...]
    index: dict[str, Any]
    manifest_fingerprint: str
    stale: bool

    def to_payload(self) -> dict[str, Any]:
        """The ``--json`` payload from contract §2 (canonical, path-free)."""

        return {
            "ok": True,
            "schemaVersion": EXPORT_SCHEMA_VERSION,
            "command": "export",
            "check": self.check,
            "outDir": self.out_dir,
            "index": dict(self.index),
            "files": [item.to_dict() for item in self.files],
            "manifestFingerprint": self.manifest_fingerprint,
            "stale": self.stale,
        }


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------
def resolve_out_dir(root: Path, out: str | os.PathLike[str] | None = None) -> tuple[Path, str]:
    """Resolve ``--out`` to ``(absolute path, repo-relative POSIX string)``.

    The directory must be *inside* the resolved repository root.  Absolute
    paths, ``..`` segments, drive letters, control characters and symlinked
    components are refused instead of being normalized away; only the fixed
    file names are ever written below the result.
    """

    raw = DEFAULT_OUT_DIR if out in (None, "") else str(out)
    try:
        text = to_posix(raw).strip()
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise UsageError(f"--out is not a usable path: {raw!r}") from exc
    if not text:
        raise UsageError("--out must name a directory inside the repository root")
    if any(ord(character) < 32 for character in text):
        raise UsageError("--out must not contain control characters")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        raise UsageError(
            f"--out must be repository-relative (got absolute path {raw!r}); "
            "it always resolves inside the workspace root"
        )
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts:
        raise UsageError("--out must name a directory inside the repository root")
    if any(part == ".." for part in parts):
        raise UsageError(f"--out must not contain '..' segments (got {raw!r})")
    if any(":" in part for part in parts):
        raise UsageError(f"--out must be a plain repository-relative path (got {raw!r})")

    relative = "/".join(parts)
    candidate = root.joinpath(*parts)

    current = root
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        except OSError as exc:
            raise RepositoryError(
                f"cannot inspect export directory {relative}: {exc}",
                code="export_failed",
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise OutsideRootError(f"refusing to export through a symlink: {relative}")
        if current != candidate and not stat.S_ISDIR(info.st_mode):
            raise RepositoryError(
                f"export path component is not a directory: {relative}",
                code="export_failed",
            )

    if candidate.exists():
        resolved = _resolve_contained(root, candidate)
        if not resolved.is_dir():
            raise RepositoryError(
                f"export target is not a directory: {relative}",
                code="export_failed",
            )
    return candidate, relative


def _resolve_contained(root: Path, candidate: Path) -> Path:
    """Resolve an existing path and prove it is inside ``root``."""

    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepositoryError(
            f"cannot resolve export path {candidate.name!r}: {exc}",
            code="export_failed",
        ) from exc
    if not is_within(root, resolved):
        raise OutsideRootError("export path escapes the repository root")
    return resolved


def _is_path_covered(relative: str, policy: Any) -> bool:
    """True when the default policy already prunes ``relative`` entirely."""

    parts = relative.split("/")
    if any(part in policy.default_excludes for part in parts):
        return True
    if any(part == policy.index_dir_name for part in parts):
        return True
    if not policy.include_hidden and any(part.startswith(".") for part in parts):
        return True
    for entry in policy.excluded_paths:
        if entry and (relative == entry or relative.startswith(entry + "/")):
            return True
    return False


if TYPE_CHECKING:
    from codebase_intelligence.indexing import IndexResult
    from codebase_intelligence.scanner import ScanPolicy


def _build_export_policy(
    *,
    root: Path,
    out_relative: str,
    cache_path: Path | None,
    max_file_bytes: int | None,
    excludes: Sequence[str],
    include_hidden: bool,
) -> ScanPolicy:
    """Build the scan policy used for the export's single index build.

    The generation directory and (when it lives inside the workspace) the cache
    directory are added as extra excludes unless the default policy already
    prunes them.  Without this, a custom ``--out`` (or an in-repo cache) would
    be indexed by the *next* export and the bundle would stop being
    deterministic.
    """

    policy = api.build_policy(
        max_file_bytes=max_file_bytes,
        excludes=excludes,
        include_hidden=include_hidden,
    )
    extra = list(policy.extra_excludes)
    if not _is_path_covered(out_relative, policy):
        extra.append(out_relative + "/")
    if cache_path is not None and cache_path != root:
        try:
            cache_relative = to_posix(cache_path.relative_to(root))
        except ValueError:
            cache_relative = ""
        if cache_relative and not _is_path_covered(cache_relative, policy):
            extra.append(cache_relative + "/")
    if tuple(extra) == policy.extra_excludes:
        return policy
    return replace(policy, extra_excludes=tuple(extra))


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def _json_bytes(value: Any) -> bytes:
    """Canonical JSON + one trailing newline, UTF-8 (contract §1/SPEC §3)."""

    return (canonical_json(value) + "\n").encode("utf-8", errors="surrogateescape")


def _text_bytes(text: str) -> bytes:
    """LF-only UTF-8 text with exactly one trailing newline."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized.encode("utf-8", errors="surrogateescape")


def _file_path_of(identifier: str) -> str | None:
    """Recover the repository path encoded in a file/symbol id."""

    if identifier.startswith("file:"):
        return identifier[len("file:") :] or None
    if identifier.startswith("sym:"):
        remainder = identifier[len("sym:") :]
        path, _, _rest = remainder.partition("#")
        return path or None
    return None


def _mermaid_label(path: str) -> str:
    """Quote/escape a repository path for a Mermaid ``["…"]`` node label."""

    escaped = (
        path.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return "".join(character if character.isprintable() else "?" for character in escaped)


def _language_rows(snapshot: IndexSnapshot) -> list[tuple[str, int, int]]:
    """``(language, files, symbols)`` rows, ordered by size then name."""

    stats: dict[str, list[int]] = {}
    for file in sorted(snapshot.files, key=lambda item: item.path):
        stats.setdefault(file.language.value, [0, 0])[0] += 1
    for symbol in sorted(
        snapshot.symbols,
        key=lambda item: (item.path, item.span.start_line, item.kind.value, item.qualified_name),
    ):
        stats.setdefault(symbol.language.value, [0, 0])[1] += 1
    rows = [(language, values[0], values[1]) for language, values in stats.items()]
    rows.sort(key=lambda row: (-row[1], -row[2], row[0]))
    return rows


# ---------------------------------------------------------------------------
# Renderers (pure functions of the index snapshot + graph)
# ---------------------------------------------------------------------------
def render_dependencies_mermaid(snapshot: IndexSnapshot, index: Mapping[str, Any]) -> str:
    """Deterministic Mermaid ``graph LR`` over *resolved* file import edges.

    Only :data:`~codebase_intelligence.model.entities.ResolutionStatus.RESOLVED`
    ``imports`` relations between two indexed files are rendered; unresolved,
    ambiguous, external and out-of-scope edges are omitted and counted in one
    header comment (they are not dependencies).  Edges are sorted and bounded to
    :data:`MAX_DEPENDENCY_EDGES`; nodes are labelled with repository-relative
    paths and numbered in sorted path order so the ids are stable.
    """

    indexed = {record.path for record in snapshot.files}
    edges: set[tuple[str, str]] = set()
    omitted = 0
    for relation in snapshot.relations:
        if relation.relation_type is not RelationType.IMPORTS:
            continue
        if relation.status is not ResolutionStatus.RESOLVED:
            omitted += 1
            continue
        source = _file_path_of(relation.source_id)
        target = _file_path_of(relation.target_id or "")
        if (
            source is None
            or target is None
            or source not in indexed
            or target not in indexed
            or source == target
        ):
            omitted += 1
            continue
        edges.add((source, target))

    ordered = sorted(edges)
    rendered = ordered[:MAX_DEPENDENCY_EDGES]
    dropped = len(ordered) - len(rendered)
    nodes = sorted({path for edge in rendered for path in edge})
    node_ids = {path: f"n{position}" for position, path in enumerate(nodes)}

    lines: list[str] = [
        "%% Codebase Intelligence dependency graph. Generated by `cbi export`; do not edit.",
        f"%% index fingerprint: {index.get('fingerprint', '')}",
        (
            f"%% engine {index.get('engineVersion', '')}, "
            f"schema {index.get('schemaVersion', '')}, "
            f"policy {index.get('policyFingerprint', '')}"
        ),
        f"%% resolved import edges among indexed files: {len(ordered)}",
    ]
    if dropped:
        lines.append(
            f"%% edge bound: rendering the first {MAX_DEPENDENCY_EDGES} edges in sorted "
            f"order; {dropped} edge(s) omitted."
        )
    lines.append(
        f"%% omitted {omitted} unresolved/external/out-of-scope import edge(s): "
        "they are not dependencies."
    )
    if not nodes:
        lines.append("%% no resolved import edges between indexed files")
    lines.append("graph LR")
    for path in nodes:
        lines.append(f'    {node_ids[path]}["{_mermaid_label(path)}"]')
    for source, target in rendered:
        lines.append(f"    {node_ids[source]} --> {node_ids[target]}")
    return "\n".join(lines) + "\n"


def render_context_brief(
    snapshot: IndexSnapshot,
    graph: Any,
    index: Mapping[str, Any],
    out_dir: str = DEFAULT_OUT_DIR,
) -> str:
    """Deterministic, agent-facing orientation brief (bounded, cited, path-free).

    Sections: snapshot identity, language mix, entry points (shared heuristic),
    top modules by resolved in-degree, files with the most declarations, how to
    query the engine, and honest limitations.  Everything is sorted; there are
    no timestamps, absolute paths or cache counters.
    """

    from codebase_intelligence import reporting

    lines: list[str] = [
        "# Codebase intelligence brief",
        "",
        "Orientation snapshot for agents and humans working in this repository.",
        "It is generated by `cbi export` and is deliberately not part of the model",
        "context: read it, do not edit it by hand.",
        "",
        "## Snapshot",
        "",
        f"- index fingerprint: `{index.get('fingerprint', '')}`",
        f"- index schema: `{index.get('schemaVersion', '')}` (engine `{index.get('engineVersion', '')}`)",
        f"- policy fingerprint: `{index.get('policyFingerprint', '')}`",
        f"- files: {len(snapshot.files)}",
        f"- symbols: {len(snapshot.symbols)}",
        f"- relations: {len(snapshot.relations)}",
        f"- parser issues: {len(snapshot.parse_issues)}",
        f"- generated directory: `{out_dir}` (excluded from the next scan)",
        "",
        "## Languages",
        "",
    ]
    language_rows = _language_rows(snapshot)
    if language_rows:
        for language, file_count, symbol_count in language_rows[:MAX_BRIEF_LANGUAGE_ROWS]:
            lines.append(f"- {language}: {file_count} files, {symbol_count} symbols")
        remaining = len(language_rows) - MAX_BRIEF_LANGUAGE_ROWS
        if remaining > 0:
            lines.append(f"- ... {remaining} more language(s)")
    else:
        lines.append("- none: no files were indexed")

    entry_points = reporting.entry_point_rows(snapshot)
    lines.extend(["", "## Entry points", ""])
    if entry_points:
        for row in entry_points[:MAX_BRIEF_ENTRY_POINTS]:
            location = f"`{row['path']}:{row['line']}`"
            if row.get("symbol"):
                lines.append(f"- {location} {row['kind']} {row['symbol']}")
            else:
                lines.append(f"- {location} file entry point")
        remaining = len(entry_points) - MAX_BRIEF_ENTRY_POINTS
        if remaining > 0:
            lines.append(f"- ... {remaining} more entry point(s) (name heuristic)")
    else:
        lines.append("- none detected by the name heuristic")

    hubs: list[tuple[str, int, int]] = []
    for file in sorted(snapshot.files, key=lambda item: item.path):
        hubs.append(
            (
                file.path,
                len(graph.file_dependents(file.path)),
                len(graph.file_imports(file.path)),
            )
        )
    hubs.sort(key=lambda row: (-row[1], -row[2], row[0]))
    lines.extend(["", "## Top modules by resolved in-degree", ""])
    with_dependents = [row for row in hubs if row[1] > 0]
    if with_dependents:
        for path, dependent_count, import_count in with_dependents[:MAX_BRIEF_HUB_ROWS]:
            lines.append(
                f"- `{path}` - imported by {dependent_count} file(s), imports {import_count}"
            )
        remaining = len(with_dependents) - MAX_BRIEF_HUB_ROWS
        if remaining > 0:
            lines.append(f"- ... {remaining} more module(s)")
    else:
        lines.append("- none: no resolved import edges in this index")

    symbol_counts: dict[str, int] = {}
    for symbol in snapshot.symbols:
        symbol_counts[symbol.path] = symbol_counts.get(symbol.path, 0) + 1
    by_lines = {record.path: record.line_count for record in snapshot.files}
    key_rows = [
        (path, count, by_lines.get(path, 0))
        for path, count in symbol_counts.items()
        if count > 0
    ]
    key_rows.sort(key=lambda row: (-row[1], -row[2], row[0]))
    lines.extend(["", "## Files with the most declarations", ""])
    if key_rows:
        for path, count, line_count in key_rows[:MAX_BRIEF_KEY_FILES]:
            lines.append(f"- `{path}` - {count} declaration(s), {line_count} line(s)")
        remaining = len(key_rows) - MAX_BRIEF_KEY_FILES
        if remaining > 0:
            lines.append(f"- ... {remaining} more file(s)")
    else:
        lines.append("- none: no declarations were extracted")

    lines.extend(
        [
            "",
            "## How to query this codebase",
            "",
            "The CLI, the stdio MCP server and the DSH plugin return the same",
            "deterministic payloads, so an agent answer and the right-sidebar panel",
            "stay consistent:",
            "",
            '- overview: `cbi overview . --json`',
            '- map: `cbi map . --json`',
            '- search: `cbi search . --query "<term>" --json`',
            '- dependencies: `cbi dependencies . --target "<path>" --json`',
            '- context: `cbi context . --task "<what you are changing>" --json`',
            '- impact: `cbi impact . --files "<changed path>" --json`',
            "- report: `cbi report . --out ARCHITECTURE.md`",
            "",
            "The rest of the bundle next to this file: `overview.json` and",
            "`repo-map.json` (canonical JSON), `graph.snapshot.json`, `ARCHITECTURE.generated.md`,",
            "`REPO_MAP.md`, `dependencies.mmd` (Mermaid) and `manifest.json`",
            "(sha256 of every generated file; written last).",
            "",
            "## Limitations",
            "",
            "- Structural view only: files, declarations and edges, not program",
            "  behaviour or runtime effects.",
            "- Declarations and relations labelled heuristic come from regex adapters;",
            "  they can be incomplete or mislabelled. Treat them as leads.",
            "- Unresolved and external imports are kept in the JSON reports but are",
            "  not dependencies and are omitted from `dependencies.mmd`.",
            "- The snapshot is only as fresh as the last `cbi export`; regenerate it",
            "  after significant changes.",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_project_graph(snapshot: IndexSnapshot) -> str:
    view = graph_view(snapshot)
    nodes = {node["id"]: f"n{i}" for i, node in enumerate(view["nodes"])}
    lines = [
        "## Project graph",
        "",
        "Top-level directories and files with resolved imports between them.",
        f"Showing {len(nodes)} of {view['totalNodes']} top-level nodes.",
        f"The [saved graph]({GRAPH_FILE_NAME}) includes the full directory, file, and symbol data.",
        "",
    ]
    if nodes:
        lines.extend(("```mermaid", "flowchart LR"))
        lines.extend(
            f'    {nodes[node["id"]]}["{_mermaid_label(node["path"][:120])}"]'
            for node in view["nodes"]
        )
        resolved = {
            (edge["from"], edge["to"])
            for edge in view["edges"]
            if edge["status"] == ResolutionStatus.RESOLVED.value
        }
        lines.extend(f"    {nodes[left]} --> {nodes[right]}" for left, right in sorted(resolved))
        lines.extend(("```", ""))
        if view["omittedEdges"]:
            lines.extend(("Some relationships are omitted from this overview.", ""))
    return "\n".join(lines)


def render_bundle(
    snapshot: IndexSnapshot,
    graph: Any,
    *,
    out_dir: str = DEFAULT_OUT_DIR,
    policy: ScanPolicy | None = None,
) -> dict[str, bytes]:
    """Render the complete bundle (all eight files) for one snapshot.

    Returns an ordered ``{file name: bytes}`` mapping in :data:`EXPORT_FILE_NAMES`
    order: the seven content files first, then ``manifest.json`` (which describes
    them).  Pure and deterministic apart from the caller's out dir string, which
    only appears inside the manifest and the brief.
    """

    from codebase_intelligence import reporting

    index = api.index_block(snapshot)
    saved = graph_snapshot(snapshot)
    contents: dict[str, bytes] = {
        "overview.json": _json_bytes(
            reporting.overview_payload(snapshot, graph, max_tokens=OVERVIEW_MAX_TOKENS)
        ),
        "repo-map.json": _json_bytes(
            reporting.map_payload(snapshot, graph, max_tokens=MAP_MAX_TOKENS)
        ),
        GRAPH_FILE_NAME: _json_bytes(snapshot_document(saved, policy or api.build_policy())),
        "ARCHITECTURE.generated.md": _text_bytes(reporting.markdown_report(snapshot, graph)),
        "REPO_MAP.md": _text_bytes(reporting.markdown_map(snapshot) + "\n" + _render_project_graph(saved)),
        "dependencies.mmd": _text_bytes(render_dependencies_mermaid(snapshot, index)),
        "CONTEXT_BRIEF.md": _text_bytes(
            render_context_brief(snapshot, graph, index, out_dir=out_dir)
        ),
    }
    contents[MANIFEST_FILE_NAME] = _json_bytes(_manifest(index, out_dir, contents))
    return contents


def _manifest(
    index: Mapping[str, Any],
    out_dir: str,
    contents: Mapping[str, bytes],
) -> dict[str, Any]:
    """``manifest.json`` body: identity + sha256 of every other generated file."""

    entries = [
        {
            "path": f"{out_dir}/{name}",
            "bytes": len(contents[name]),
            "sha256": sha256_bytes(contents[name]),
        }
        for name in sorted(contents)
    ]
    return {
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "engineVersion": str(index.get("engineVersion", "")),
        "policyFingerprint": str(index.get("policyFingerprint", "")),
        "fingerprint": str(index.get("fingerprint", "")),
        "outDir": out_dir,
        "files": entries,
    }


# ---------------------------------------------------------------------------
# Filesystem writes
# ---------------------------------------------------------------------------
def _read_existing(path: Path) -> bytes | None:
    """Existing file bytes, or ``None`` when the target does not exist.

    Raises on anything that is not a regular file: writing through a symlink or
    over a directory is refused rather than repaired.
    """

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RepositoryError(
            f"cannot inspect export file {path.name!r}: {exc}",
            code="export_failed",
        ) from exc
    if stat.S_ISLNK(info.st_mode):
        raise OutsideRootError(
            f"refusing to write through a symlink in the export directory: {path.name}"
        )
    if stat.S_ISDIR(info.st_mode):
        raise RepositoryError(
            f"export target is a directory, not a file: {path.name}",
            code="export_failed",
        )
    if not stat.S_ISREG(info.st_mode):
        raise RepositoryError(
            f"export target is not a regular file: {path.name}",
            code="export_failed",
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RepositoryError(
            f"cannot read existing export file {path.name!r}: {exc}",
            code="export_failed",
        ) from exc


def _atomic_write(path: Path, data: bytes) -> None:
    """Write *data* atomically: temp file in the same directory + ``os.replace``."""

    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o644)
        except OSError:  # pragma: no cover - platform/umask dependent
            pass
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:  # pragma: no cover - best-effort temp cleanup
            pass
        raise


def _prepare_out_dir(out_path: Path) -> None:
    """Create ``outDir`` (parents included) and prove it is a directory."""

    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RepositoryError(
            f"cannot create the export directory {out_path.name!r}: {exc}",
            code="export_failed",
        ) from exc
    if not out_path.is_dir():
        raise RepositoryError(
            f"export target is not a directory: {out_path.name}",
            code="export_failed",
        )


def _write_changed(out_path: Path, contents: Mapping[str, bytes], files: Sequence[ExportFile]) -> None:
    """Write only the changed files, in order (manifest last), atomically."""

    pending = [item for item in files if item.status != STATUS_UNCHANGED]
    if not pending:
        return
    _prepare_out_dir(out_path)
    for item in pending:
        try:
            _atomic_write(out_path / item.name, contents[item.name])
        except OSError as exc:
            raise RepositoryError(
                f"failed to write export file {item.name!r}: {exc}",
                code="export_failed",
            ) from exc


# ---------------------------------------------------------------------------
# Export driver
# ---------------------------------------------------------------------------
def build_export(
    root: str | os.PathLike[str],
    *,
    out: str | os.PathLike[str] | None = None,
    cache_dir: str | os.PathLike[str] | None = None,
    force: bool = False,
    max_file_bytes: int | None = None,
    excludes: Sequence[str] = (),
    include_hidden: bool = False,
    check: bool = False,
) -> ExportResult:
    """Build the index once, render the fixed bundle and (unless ``check``) write it.

    Args:
        root: Repository/workspace root (resolved strictly; must exist).
        out: Generation directory relative to ``root`` (default
            :data:`DEFAULT_OUT_DIR`).
        cache_dir: Index cache location; defaults like every other CLI command.
        force: Rebuild the index from scratch instead of an incremental refresh.
        max_file_bytes: Scan-policy override for the single index build.
        excludes: Extra scan excludes (CLI ``--exclude``, repeatable).
        include_hidden: Scan-policy override for hidden files.
        check: Render and report the plan without writing anything.

    Returns:
        :class:`ExportResult` with per-file statuses, the index block and the
        sha256 of the manifest bytes (``manifestFingerprint``).

    Raises:
        UsageError: ``out`` is not a safe repository-relative directory.
        OutsideRootError: ``out`` escapes the root through symlinks/``..``.
        RepositoryError: The root, the index or the write target is unusable.
    """

    root_path = api.resolve_root(root)
    out_path, out_relative = resolve_out_dir(root_path, out)
    cache_path = api.resolve_cache_dir(cache_dir)
    policy = _build_export_policy(
        root=root_path,
        out_relative=out_relative,
        cache_path=cache_path,
        max_file_bytes=max_file_bytes,
        excludes=excludes,
        include_hidden=include_hidden,
    )
    index_result = _ensure_index(root_path, policy, cache_path, force)
    snapshot = index_result.snapshot
    graph = api.graph_for(snapshot)
    contents = render_bundle(snapshot, graph, out_dir=out_relative, policy=policy)
    index = api.index_block(snapshot)
    manifest_fingerprint = sha256_bytes(contents[MANIFEST_FILE_NAME])

    files: list[ExportFile] = []
    stale = False
    for name in EXPORT_FILE_NAMES:
        data = contents[name]
        existing = _read_existing(out_path / name)
        if existing is None:
            status = STATUS_CREATED
        elif existing == data:
            status = STATUS_UNCHANGED
        else:
            status = STATUS_UPDATED
        if status != STATUS_UNCHANGED:
            stale = True
        files.append(
            ExportFile(
                name=name,
                path=f"{out_relative}/{name}",
                status=status,
                size_bytes=len(data),
                sha256=sha256_bytes(data),
            )
        )

    if check:
        if out_path.exists():
            _resolve_contained(root_path, out_path)
    else:
        _write_changed(out_path, contents, files)
        _resolve_contained(root_path, out_path)
        # After a successful write the on-disk bundle matches the rendered one.
        stale = False

    return ExportResult(
        out_dir=out_relative,
        out_path=out_path,
        check=check,
        files=tuple(files),
        index=index,
        manifest_fingerprint=manifest_fingerprint,
        stale=stale,
    )


def _ensure_index(
    root: Path, policy: ScanPolicy, cache_path: Path | None, force: bool
) -> IndexResult:
    """Build/refresh the index exactly once via the shared engine entry point."""

    from codebase_intelligence.indexing import ensure_index

    return ensure_index(root, policy, cache_dir=cache_path, force=force)


__all__ = [
    "DEFAULT_OUT_DIR",
    "EXPORT_FILE_NAMES",
    "EXPORT_SCHEMA_VERSION",
    "ExportFile",
    "ExportResult",
    "GENERATED_FILE_NAMES",
    "MANIFEST_FILE_NAME",
    "MAP_MAX_TOKENS",
    "MAX_DEPENDENCY_EDGES",
    "OVERVIEW_MAX_TOKENS",
    "STATUSES",
    "build_export",
    "render_bundle",
    "render_context_brief",
    "render_dependencies_mermaid",
    "resolve_out_dir",
]
