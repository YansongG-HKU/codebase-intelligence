"""Formatting helpers shared by the demo application."""

from __future__ import annotations

from app.models import Task


def format_task(task: Task) -> str:
    """Render one task as a single line of text."""

    return f"{task.summary()} ({len(task.tags)} tag(s))"


def format_header(title: str) -> str:
    """Render a section header used by the demo CLI."""

    return f"== {title} =="
