"""MockVtfClient for testing consumers of the SDK."""
from __future__ import annotations

from vtf_sdk.entities import Task, Project
from vtf_sdk.pagination import PagedResult
from .factories import build_task, build_project, _next_id


class _MockTaskManager:
    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def get(self, id: str, expand: list[str] | None = None) -> Task:
        if id in self._tasks:
            return self._tasks[id]
        return build_task(id=id)

    def list(self, **kwargs) -> PagedResult[Task]:
        items = list(self._tasks.values()) or [build_task()]
        return PagedResult(items=items, has_more=False)

    def create(self, *, title: str, project: str, **kwargs) -> Task:
        task = build_task(id=_next_id("tsk"), title=title, **kwargs)
        self._tasks[task.id] = task
        return task


class _MockProjectManager:
    def __init__(self):
        self._projects: dict[str, Project] = {}

    def get(self, id: str) -> Project:
        if id in self._projects:
            return self._projects[id]
        return build_project(id=id)

    def list(self, **kwargs) -> PagedResult[Project]:
        items = list(self._projects.values()) or [build_project()]
        return PagedResult(items=items, has_more=False)


class MockVtfClient:
    """In-memory mock client for testing SDK consumers."""

    def __init__(self):
        self.tasks = _MockTaskManager()
        self.projects = _MockProjectManager()
