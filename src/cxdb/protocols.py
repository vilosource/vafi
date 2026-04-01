"""Protocols (interfaces) for dependency inversion."""

from __future__ import annotations

from typing import Protocol


class CxdbReader(Protocol):
    """Read-only access to cxdb sessions and turns."""

    async def find_context_by_task(self, task_id: str) -> int | None:
        """Find the most recent cxdb context_id for a vtf task."""
        ...

    async def get_turns(self, context_id: int) -> list[dict]:
        """Fetch all turns for a context as raw dicts."""
        ...


class SummaryStore(Protocol):
    """Persist execution summaries to the task tracker."""

    async def store_summary(self, task_id: str, summary: dict) -> None:
        """Store the execution summary on a task."""
        ...
