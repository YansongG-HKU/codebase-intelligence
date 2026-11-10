"""Tests for the demo application fixture."""

from __future__ import annotations

from app.services import TaskService, create_default_service
from app.util import format_header, format_task


def test_default_service_has_two_tasks() -> None:
    service = create_default_service()
    assert len(service.list_tasks()) == 2


def test_add_and_complete_task() -> None:
    service = TaskService()
    task = service.add("try codebase context", tags=("probe",))
    assert task.task_id == 1
    completed = service.complete(1)
    assert completed.done is True


def test_complete_unknown_task_raises() -> None:
    service = TaskService()
    try:
        service.complete(99)
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_format_helpers() -> None:
    service = create_default_service()
    first = service.list_tasks()[0]
    assert format_task(first).startswith("[open] #1")
    assert format_header("Tasks") == "== Tasks =="
