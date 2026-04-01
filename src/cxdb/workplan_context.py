"""Build workplan-level context from completed task summaries.

Accumulates key decisions across tasks so executors stay consistent.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger("cxdb.workplan_context")


class WorkplanTaskSource(Protocol):
    async def list_tasks_by_workplan(self, workplan_id: str) -> list[dict]: ...


async def build_workplan_context(
    vtf: WorkplanTaskSource,
    workplan_id: str,
) -> str:
    """Build a context document from completed task summaries in a workplan.

    Returns markdown text with key decisions, or empty string if none found.
    """
    tasks = await vtf.list_tasks_by_workplan(workplan_id)

    seen_decisions: set[str] = set()
    lines: list[str] = []

    for task in tasks:
        summary = task.get("execution_summary")
        if not summary:
            continue

        nl = summary.get("nl_summary")
        if not nl:
            continue

        decisions = nl.get("key_decisions", [])
        title = task.get("title", "Unknown task")

        for d in decisions:
            if d not in seen_decisions:
                seen_decisions.add(d)
                lines.append(f"- {title}: {d}")

    if not lines:
        return ""

    return "## Workplan Context — Decisions from Prior Tasks\n\n" + "\n".join(lines)
