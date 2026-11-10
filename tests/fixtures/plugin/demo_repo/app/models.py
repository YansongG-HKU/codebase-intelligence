"""Small immutable domain models used by the demo application."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Task:
    """One unit of work shown in the demo application."""

    task_id: int
    title: str
    done: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        state = "done" if self.done else "open"
        return f"[{state}] #{self.task_id} {self.title}"
