"""Bounded views of the repository's existing evidence graph."""

from pathlib import Path
from typing import Any

from codebase_intelligence.errors import RepositoryError, UsageError
from codebase_intelligence.model import FileRecord, IndexSnapshot, SymbolRecord, RelationType, file_id
from codebase_intelligence.util import is_within, sha256_bytes

MAX_NODES = 80
MAX_EDGES = 160
MAX_SOURCE_BYTES = 1024 * 1024


def _symbol(symbol: SymbolRecord) -> dict[str, Any]:
    return {
        "id": symbol.id, "label": symbol.name, "kind": "symbol", "path": symbol.path,
        "symbolKind": symbol.kind.value, "line": symbol.span.start_line,
    }


def _path_node(path: str, kind: str) -> dict[str, Any]:
    return {"id": f"{kind}:{path}", "label": path.rsplit("/", 1)[-1], "kind": kind, "path": path}


def graph_view(
    snapshot: IndexSnapshot, focus: str = "", offset: int = 0, relation_type: str = ""
) -> dict[str, Any]:
    if relation_type and relation_type not in {kind.value for kind in RelationType}:
        raise UsageError("unknown graph relation type")
    files = {file_id(file.path): file.path for file in snapshot.files}
    symbols = {symbol.id: symbol for symbol in snapshot.symbols}
    paths = {**files, **{key: symbol.path for key, symbol in symbols.items()}}
    nodes: dict[str, dict[str, Any]] = {}
    projection: dict[str, str] = {}
    edges: dict[tuple[str, ...], dict[str, Any]] = {}
    breadcrumbs: list[dict[str, Any]] = []
    active_path = ""

    if focus in symbols:
        active_path = symbols[focus].path
        nodes[focus] = {**_symbol(symbols[focus]), "side": "focus"}
    elif focus in files:
        active_path = files[focus]
        nodes = {key: _symbol(symbol) for key, symbol in symbols.items() if symbol.path == active_path}
        projection = {key: key for key in nodes}
    else:
        if focus and not focus.startswith("dir:"):
            raise RepositoryError("graph node is not in the current index", code="not_found")
        active_path = focus.removeprefix("dir:")
        prefix = active_path + "/" if active_path else ""
        for file_key, path in files.items():
            if not path.startswith(prefix):
                continue
            child, slash, _ = path[len(prefix):].partition("/")
            node = _path_node(prefix + child, "dir" if slash else "file")
            nodes[node["id"]] = node
            projection[file_key] = node["id"]
        if focus and not nodes:
            raise RepositoryError("graph directory is not in the current index", code="not_found")

    for relation in snapshot.relations:
        if relation_type and relation.relation_type.value != relation_type:
            continue
        origin = relation.source_id
        target = relation.target_id or ""
        if focus in symbols:
            if origin != focus and target != focus:
                continue
            neighbor = target if origin == focus else origin
            if neighbor in symbols:
                node = _symbol(symbols[neighbor])
            elif neighbor in files:
                node = _path_node(files[neighbor], "file")
            else:
                label = (relation.target_name or neighbor or "unknown")[:160]
                node = {"id": "unresolved:" + label, "label": label, "kind": "unresolved"}
            if neighbor != focus:
                side = "out" if origin == focus else "in"
                previous = nodes.get(node["id"])
                if previous and previous["side"] != side:
                    side = "both"
                nodes[node["id"]] = {**node, "side": side}
            left, right = (focus, node["id"]) if origin == focus else (node["id"], focus)
        else:
            if focus not in files and relation.relation_type.value != "imports":
                continue
            if focus not in files:
                origin = file_id(paths[origin]) if origin in paths else origin
                target = file_id(paths[target]) if target in paths else target
            left, right = projection.get(origin, ""), projection.get(target, "")
            if not left or not right or left == right:
                continue
        kind, status, evidence = relation.relation_type.value, relation.status.value, relation.evidence.value
        key = (left, right, kind, status, evidence)
        edge = edges.setdefault(key, {
            "from": left, "to": right, "type": kind, "status": status, "evidence": evidence,
            "count": 0, "sites": [],
        })
        edge["count"] += 1
        if relation.span and len(edge["sites"]) < 3:
            span = relation.span.to_dict()
            if span not in edge["sites"]:
                edge["sites"].append(span)

    parts = active_path.split("/") if active_path else []
    directory_parts = parts if focus.startswith("dir:") else parts[:-1]
    for index in range(len(directory_parts)):
        breadcrumbs.append(_path_node("/".join(parts[:index + 1]), "dir"))
    if focus in files or focus in symbols:
        breadcrumbs.append(_path_node(active_path, "file"))
    if focus in symbols:
        breadcrumbs.append(_symbol(symbols[focus]))
    ordered = sorted(
        nodes.values(), key=lambda n: (n["id"] != focus, n["kind"] != "dir", n["label"], n["id"])
    )
    if focus in symbols:
        # Keep the focal symbol on every page so all shown edges have a visible anchor.
        page = [nodes[focus], *ordered[1 + offset:offset + MAX_NODES]]
    else:
        page = ordered[offset:offset + MAX_NODES]
    visible = {node["id"] for node in page}
    candidates = [
        edge for key, edge in sorted(edges.items()) if key[0] in visible and key[1] in visible
    ]
    return {
        "focus": focus, "relation": relation_type, "nodes": page, "edges": candidates[:MAX_EDGES], "breadcrumbs": breadcrumbs,
        "totalNodes": len(nodes), "offset": offset,
        "nextOffset": offset + len(page) - int(focus in symbols)
        if offset + len(page) < len(nodes) else None,
        "omittedEdges": len(edges) - min(len(candidates), MAX_EDGES),
    }


def source_excerpt(root: Path, files: tuple[FileRecord, ...], path: str, line: int) -> dict[str, Any]:
    record = next((file for file in files if file.path == path), None)
    if record is None:
        raise RepositoryError("source file is not in the current index", code="not_found")
    if not 1 <= line <= max(record.line_count, 1):
        raise UsageError("source line is outside the indexed file")
    candidate = root / path
    if Path(path).is_absolute() or ".." in Path(path).parts or not is_within(root, candidate):
        raise RepositoryError("source file is outside the workspace", code="outside_root")
    if not candidate.is_file():
        raise RepositoryError("source file is no longer readable", code="not_found")
    try:
        with candidate.open("rb") as handle:
            data = handle.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        raise RepositoryError("source file is no longer readable", code="not_found") from exc
    if len(data) > MAX_SOURCE_BYTES or sha256_bytes(data) != record.sha256:
        raise RepositoryError("source changed or exceeds the excerpt limit", code="stale_graph")
    lines = data.decode("utf-8", errors="replace").split("\n")[:record.line_count]
    start = max(1, line - 6)
    return {
        "path": path, "line": line, "startLine": start,
        "lines": [text.rstrip("\r")[:500] for text in lines[start - 1:line + 6]],
    }
