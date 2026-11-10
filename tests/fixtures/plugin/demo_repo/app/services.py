"""In-memory task service used by the demo application."""

from __future__ import annotations

from app.models import Task
from app.util import format_task


class TaskService:
    """Keep tasks in memory and expose a tiny deterministic API."""

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._next_id = 1

    def add(self, title: str, tags: tuple[str, ...] = ()) -> Task:
        task = Task(task_id=self._next_id, title=title, tags=tags)
        self._next_id += 1
        self._tasks.append(task)
        return task

    def complete(self, task_id: int) -> Task:
        for index, task in enumerate(self._tasks):
            if task.task_id == task_id:
                updated = Task(task_id=task.task_id, title=task.title, done=True, tags=task.tags)
                self._tasks[index] = updated
                return updated
        raise KeyError(f"unknown task id {task_id}")

    def list_tasks(self) -> tuple[Task, ...]:
        return tuple(self._tasks)

    def describe(self) -> tuple[str, ...]:
        return tuple(format_task(task) for task in self._tasks)


def create_default_service() -> TaskService:
    """Build a service pre-populated with two sample tasks."""

    service = TaskService()
    service.add("write the spec", tags=("docs",))
    service.add("implement the scanner", tags=("code", "core"))
    return service
