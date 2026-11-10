"""Core ranking helpers for the fixture app."""

DEFAULT_TOKENS = 2200


def rank_files(items):
    """Rank files with deterministic lexical scoring."""
    return sorted(items)


def build_context(items, *, max_tokens=DEFAULT_TOKENS):
    """构建有界的上下文包，控制在 token 预算之内。"""
    ranked = rank_files(items)
    return ranked[:max_tokens]
