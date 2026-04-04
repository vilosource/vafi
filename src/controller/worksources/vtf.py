"""VtfWorkSource implementation.

This module implements the WorkSource protocol using the vtf Python SDK.
It wraps AsyncVtfClient and contains vtf-specific logic like priority ordering
(rework before new work), review parsing, and session ID extraction.
"""
from typing import Any

from vtf_sdk.async_client import AsyncVtfClient
from vtf_sdk.entities import Task as SdkTask

from ..types import (
    AgentInfo,
    ExecutionResult,
    RepoInfo,
    ReworkContext,
    TaskInfo,
)


class VtfWorkSource:
    """WorkSource implementation backed by the vtf Python SDK."""

    def __init__(
        self,
        client: AsyncVtfClient,
        tags: list[str] | None = None,
        pod_name: str | None = None,
    ):
        self._client = client
        self._default_tags = tags or []
        self._pod_name = pod_name

    async def register(self, name: str, tags: list[str]) -> AgentInfo:
        """Register an agent with vtf."""
        agent, raw = await self._client.agents.register(
            name=name, tags=tags, pod_name=self._pod_name,
        )
        # Recreate the client with the returned token
        token = raw.get("token", "")
        self._client._transport._client.headers["authorization"] = f"Token {token}"
        return AgentInfo(id=agent.id, token=token)

    async def poll(self, agent_id: str, tags: list[str]) -> TaskInfo | None:
        """Poll for available work with priority ordering."""
        # Priority 1: Rework tasks (changes_requested)
        rework_result = await self._client.tasks.list(status="changes_requested")
        if rework_result.items:
            return self._sdk_task_to_info(rework_result.items[0])

        # Priority 2: Claimable work
        claimable_result = await self._client.tasks.claimable(tags=tags)
        if claimable_result.items:
            return self._sdk_task_to_info(claimable_result.items[0])

        return None

    async def poll_reviews(self, agent_id: str) -> TaskInfo | None:
        """Poll for tasks pending completion review (judge work)."""
        review_result = await self._client.tasks.list(status="pending_completion_review")
        if review_result.items:
            return self._sdk_task_to_info(review_result.items[0])
        return None

    async def claim(self, task_id: str, agent_id: str) -> TaskInfo:
        """Claim a task for execution."""
        task = await self._client.tasks.claim(task_id, agent_id=agent_id)
        return self._sdk_task_to_info(task)

    async def heartbeat(self, task_id: str) -> None:
        """Send heartbeat for a claimed task."""
        await self._client.tasks.heartbeat(task_id)

    async def agent_heartbeat(self, agent_id: str) -> None:
        """Send agent-level heartbeat."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {"last_heartbeat": now}
        if self._pod_name is not None:
            payload["pod_name"] = self._pod_name
        await self._client.agents.update(agent_id, **payload)

    async def set_agent_offline(self, agent_id: str) -> None:
        """Mark agent as offline during graceful shutdown."""
        await self._client.agents.update_status(agent_id, status="offline")

    async def complete(self, task_id: str, result: ExecutionResult) -> None:
        """Mark a task as completed with execution results."""
        await self._client.tasks.add_note(task_id, text=result.completion_report)

        if result.session_id:
            await self._client.tasks.add_note(
                task_id, text=f"vafi:session_id={result.session_id}",
            )

        metadata_text = (
            f"vafi:execution_metadata\n"
            f"cost_usd: {result.cost_usd}\n"
            f"num_turns: {result.num_turns}\n"
            f"gates: {len(result.gate_results)} executed"
        )
        await self._client.tasks.add_note(task_id, text=metadata_text)
        await self._client.tasks.complete(task_id)

    async def fail(self, task_id: str, reason: str) -> None:
        """Mark a task as failed."""
        await self._client.tasks.add_note(task_id, text=f"Task failed: {reason}")
        await self._client.tasks.fail(task_id)

    async def get_task_context(self, task_id: str) -> dict:
        """Get full task data with reviews and notes."""
        task = await self._client.tasks.get(task_id, expand=["reviews"])
        try:
            notes_result = await self._client.tasks.list_notes(task_id)
            notes = [{"text": n.text, "actor": str(n.actor) if n.actor else ""} for n in notes_result.items]
        except Exception:
            notes = []
        return {"task": task.model_dump(mode="json"), "notes": notes}

    async def add_note(self, task_id: str, text: str, actor_id: str) -> None:
        """Add a note to a task."""
        await self._client.tasks.add_note(task_id, text=text)

    async def get_repo_info(self, project_id: str) -> RepoInfo:
        """Get repository information for a project."""
        project = await self._client.projects.get(project_id)
        return RepoInfo(url=project.repo_url, branch=project.default_branch or "main")

    async def get_rework_context(self, task_id: str) -> ReworkContext:
        """Get context for rework execution."""
        task = await self._client.tasks.get(task_id, expand=["reviews"])

        judge_feedback = ""
        if task.reviews:
            for review in reversed(task.reviews):
                if review.decision == "changes_requested":
                    judge_feedback = review.reason or "No feedback provided"
                    break

        session_id = None
        try:
            notes_result = await self._client.tasks.list_notes(task_id)
            for note in notes_result.items:
                if note.text.startswith("vafi:session_id="):
                    session_id = note.text.split("=", 1)[1].strip()
                    break
        except Exception:
            pass

        attempt_number = await self.count_rework_attempts(task_id)
        return ReworkContext(
            session_id=session_id,
            judge_feedback=judge_feedback,
            attempt_number=attempt_number,
        )

    async def count_rework_attempts(self, task_id: str) -> int:
        """Count the number of rework attempts for a task."""
        task = await self._client.tasks.get(task_id, expand=["reviews"])
        if not task.reviews:
            return 0
        return sum(1 for r in task.reviews if r.decision == "changes_requested")

    async def submit(self, task_id: str) -> None:
        """Submit a task from draft to todo status."""
        await self._client.tasks.submit(task_id)

    async def list_submittable(self) -> list[TaskInfo]:
        """List tasks that can be submitted (draft with completed deps)."""
        draft_result = await self._client.tasks.list(status="draft")
        submittable = []
        for task in draft_result.items:
            if self._are_dependencies_completed(task):
                submittable.append(self._sdk_task_to_info(task))
        return submittable

    async def submit_review(self, task_id: str, decision: str, reason: str, reviewer_id: str) -> None:
        """Submit a review for a completed task."""
        await self._client.tasks.submit_review(
            task_id, decision=decision, reason=reason, reviewer_type="agent",
        )

    def _are_dependencies_completed(self, task: SdkTask) -> bool:
        """Check if all task dependencies are completed."""
        if not task.requires:
            return True
        return all(dep.status == "done" for dep in task.requires)

    def _sdk_task_to_info(self, task: SdkTask) -> TaskInfo:
        """Convert SDK Task entity to internal TaskInfo."""
        project_id = task.project.id if task.project else ""
        return TaskInfo(
            id=task.id,
            title=task.title,
            spec=task.spec,
            project_id=project_id,
            test_command=task.test_command,
            needs_review=task.needs_review_on_completion or False,
            assigned_to=str(task.assigned_to) if task.assigned_to else None,
        )
