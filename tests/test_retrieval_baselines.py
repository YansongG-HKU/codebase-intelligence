from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from codebase_intelligence.evaluation.baselines import (
    basic_symbol_rank,
    keyword_rank,
    pack_order,
    query_terms,
    tree_only_rank,
)


def test_query_terms_are_normalized_and_deterministic() -> None:
    assert query_terms("Build_Context build context") == ("build", "context")


def test_tree_only_uses_paths_and_never_needs_file_contents(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "needle.py").write_text("irrelevant", encoding="utf-8")
    (tmp_path / "src" / "plain.py").write_text("needle appears only in this content", encoding="utf-8")
    paths = ("src/plain.py", "src/needle.py")
    assert tree_only_rank(paths, "needle") == ("src/needle.py",)
    assert tree_only_rank(paths, "missing term") == ()


def test_keyword_baseline_ranks_source_matches_with_stable_ties(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("needle needle helper", encoding="utf-8")
    (tmp_path / "b.py").write_text("needle helper", encoding="utf-8")
    (tmp_path / "c.py").write_text("unrelated", encoding="utf-8")
    assert keyword_rank(tmp_path, ("b.py", "c.py", "a.py"), "needle helper") == ("a.py", "b.py")


def test_keyword_baseline_rejects_paths_that_escape_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-cbi-baseline.txt"
    outside.write_text("needle", encoding="utf-8")
    try:
        assert keyword_rank(tmp_path, ("../outside-cbi-baseline.txt",), "needle") == ()
    finally:
        outside.unlink(missing_ok=True)


def test_pack_order_is_unranked_and_deterministic() -> None:
    assert pack_order(("z.py", "a.py", "a.py"), "not relevant") == ("a.py", "z.py")


def test_basic_symbol_map_uses_only_symbol_names_and_stable_ties() -> None:
    symbols = (
        SimpleNamespace(name="helper", qualified_name="pkg.helper", path="b.py", span=SimpleNamespace(start_line=9)),
        SimpleNamespace(name="build_context", qualified_name="pkg.core.build_context", path="a.py", span=SimpleNamespace(start_line=4)),
        SimpleNamespace(name="context", qualified_name="pkg.context", path="a.py", span=SimpleNamespace(start_line=2)),
    )
    ranked = basic_symbol_rank(symbols, "build context")
    assert [item.qualified_name for item in ranked] == ["pkg.core.build_context", "pkg.context"]
