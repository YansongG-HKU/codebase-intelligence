"""Transparent deterministic retrieval baselines for benchmark comparison."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

MAX_BASELINE_FILE_BYTES = 1_048_576


def query_terms(value: str) -> tuple[str, ...]:
    """Normalize a query into deterministic Unicode word tokens."""

    return tuple(sorted(set(re.findall(r"[\w]+", value.casefold(), flags=re.UNICODE))))


def tree_only_rank(paths: Sequence[str], query: str) -> tuple[str, ...]:
    """Rank files using path tokens only; source contents are never opened."""

    terms = set(query_terms(query))
    if not terms:
        return ()
    scored: list[tuple[int, str]] = []
    for path in paths:
        path_tokens = set(query_terms(path.replace("/", " ")))
        score = len(terms.intersection(path_tokens))
        if score:
            scored.append((score, path))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(path for _, path in scored)


def keyword_rank(root: str | Path, paths: Sequence[str], query: str) -> tuple[str, ...]:
    """Rank eligible files by capped source-text term frequency."""

    terms = query_terms(query)
    if not terms:
        return ()
    root_path = Path(root).resolve()
    scored: list[tuple[int, str]] = []
    for relative in paths:
        candidate = (root_path / PurePosixPath(relative)).resolve()
        if not candidate.is_relative_to(root_path):
            continue
        try:
            with candidate.open("rb") as stream:
                raw = stream.read(MAX_BASELINE_FILE_BYTES + 1)
            if len(raw) > MAX_BASELINE_FILE_BYTES:
                raw = raw[:MAX_BASELINE_FILE_BYTES]
            text = raw.decode("utf-8", errors="ignore").casefold()
        except OSError:
            continue
        score = sum(min(text.count(term), 3) for term in terms)
        if score:
            scored.append((score, relative))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(path for _, path in scored)


def pack_order(paths: Sequence[str], query: str) -> tuple[str, ...]:
    """Return every file in stable path order, modelling an unranked full pack."""

    del query
    return tuple(sorted(set(paths)))


def basic_symbol_rank(symbols: Sequence[Any], query: str) -> tuple[Any, ...]:
    """Rank symbols by name-only lexical overlap, without graph features."""

    terms = set(query_terms(query))
    if not terms:
        return ()
    scored: list[tuple[int, str, str, int, Any]] = []
    for symbol in symbols:
        name_tokens = set(query_terms(f"{symbol.name} {symbol.qualified_name}"))
        score = len(terms.intersection(name_tokens))
        if score:
            scored.append((score, symbol.qualified_name, symbol.path, symbol.span.start_line, symbol))
    scored.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    return tuple(item[4] for item in scored)


def build_baseline_retrievers(
    root: str | Path,
    snapshot: Any,
) -> dict[str, Callable[[str], Sequence[str]]]:
    """Build controlled file/symbol retrieval callbacks over one index snapshot."""

    paths = tuple(sorted(file.path for file in snapshot.files))

    def retrieve_tree(query: str) -> Sequence[str]:
        return tree_only_rank(paths, query)

    def retrieve_keyword(query: str) -> Sequence[str]:
        return keyword_rank(root, paths, query)

    def retrieve_pack(query: str) -> Sequence[str]:
        return pack_order(paths, query)

    def retrieve_symbol_map_files(query: str) -> Sequence[str]:
        ranked = basic_symbol_rank(snapshot.symbols, query)
        seen: set[str] = set()
        ordered: list[str] = []
        for symbol in ranked:
            if symbol.path not in seen:
                seen.add(symbol.path)
                ordered.append(symbol.path)
        return tuple(ordered)

    def retrieve_symbol_map_symbols(query: str) -> Sequence[str]:
        return tuple(symbol.qualified_name for symbol in basic_symbol_rank(snapshot.symbols, query))

    return {
        "tree_only": retrieve_tree,
        "keyword": retrieve_keyword,
        "pack_order": retrieve_pack,
        "basic_symbol_map_files": retrieve_symbol_map_files,
        "basic_symbol_map_symbols": retrieve_symbol_map_symbols,
    }
