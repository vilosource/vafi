"""VtfWorkSource implementation.

This module implements the WorkSource protocol using the vtf REST API.
It wraps VtfClient and contains vtf-specific logic like priority ordering
(rework before new work), review parsing, and session ID extraction.
"""

from typing import Any

from ..types import (
    AgentInfo,
    ExecutionResult,
    RepoInfo,
    ReworkContext,
    TaskInfo,
)
from ..vtf_client import VtfClient


class VtfWorkSource:
    """WorkSource implementation backed by the vtf REST API."""

    def __init__(self, client: VtfClient):
        """Initialize with a VtfClient instance.

        Args:
            client: VtfClient for API communication
        """
        self.client = client

    async def register(self, name: str, tags: list[str]) -> AgentInfo:
        """Register an agent with vtf.

        Calls the vtf agent registration endpoint and stores the returned
        auth token for future requests.

        Args:
            name: Agent name
            tags: Agent tags for task matching

        Returns:
            Agent information including ID and auth token
        """
        agent_data = await self.client.register_agent(name, tags)
        return AgentInfo(
            id=agent_data["id"],
            token=agent_data["token"]
        )

    async def poll(self, agent_id: str, tags: list[str]) -> TaskInfo | None:
        """Poll for available work with priority ordering.

        Priority 1: Rework tasks (changes_requested) assigned to this agent
        Priority 2: New claimable work matching agent tags

        Args:
            agent_id: ID of the polling agent
            tags: Agent tags for task matching

        Returns:
            Next task to execute, or None if no work available
        """
        # Priority 1: Check for rework assigned to this agent
        rework_tasks = await self.client.list_tasks(
            status="changes_requested",
            assigned_to=agent_id,
            expand=["reviews"]
        )
        if rework_tasks:
            task_data = rework_tasks[0]  # Take the first rework task
            return self._task_data_to_info(task_data)

        # Priority 2: Check for new claimable work
        claimable_tasks = await self.client.list_claimable(tags, agent_id)
        if claimable_tasks:
            task_data = claimable_tasks[0]  # Take the first claimable task
            return self._task_data_to_info(task_data)

        return None

    async def claim(self, task_id: str, agent_id: str, tags: list[str]) -> TaskInfo:
        """Claim a task for execution.

        Args:
            task_id: Task ID to claim
            agent_id: ID of the claiming agent
            tags: Agent tags for validation

        Returns:
            Updated task information
        """
        task_data = await self.client.claim_task(task_id, agent_id, tags)
        return self._task_data_to_info(task_data)

    async def heartbeat(self, task_id: str) -> None:
        """Send heartbeat for a claimed task.

        Args:
            task_id: Task ID being executed
        """
        await self.client.heartbeat(task_id)

    async def complete(self, task_id: str, result: ExecutionResult) -> None:
        """Mark a task as completed with execution results.

        Stores the completion report, session ID, and execution metadata
        as notes, then transitions the task to completion state.

        Args:
            task_id: Task ID being completed
            result: Execution results
        """
        # Store completion report as a note
        await self.client.add_note(
            task_id=task_id,
            text=result.completion_report,
            actor_id="controller"  # TODO: Use actual agent ID
        )

        # Store session ID for rework resumption (if available)
        if result.session_id:
            await self.client.add_note(
                task_id=task_id,
                text=f"vafi:session_id={result.session_id}",
                actor_id="controller"
            )

        # Store execution metadata
        metadata_text = (
            f"vafi:execution_metadata\n"
            f"cost_usd: {result.cost_usd}\n"
            f"num_turns: {result.num_turns}\n"
            f"gates: {len(result.gate_results)} executed"
        )
        await self.client.add_note(
            task_id=task_id,
            text=metadata_text,
            actor_id="controller"
        )

        # Complete the task
        await self.client.complete_task(task_id)

    async def fail(self, task_id: str, reason: str) -> None:
        """Mark a task as failed.

        Stores the failure reason as a note, then transitions to failed state.

        Args:
            task_id: Task ID being failed
            reason: Failure reason for human triage
        """
        # Store failure reason as a note
        await self.client.add_note(
            task_id=task_id,
            text=f"Task failed: {reason}",
            actor_id="controller"
        )

        # Fail the task
        await self.client.fail_task(task_id)

    async def get_repo_info(self, project_id: str) -> RepoInfo:
        """Get repository information for a project.

        Args:
            project_id: Project ID from task

        Returns:
            Repository URL and default branch
        """
        project_data = await self.client.get_project(project_id)
        return RepoInfo(
            url=project_data["repo_url"],
            branch=project_data["default_branch"]
        )

    async def get_rework_context(self, task_id: str) -> ReworkContext:
        """Get context for rework execution.

        Extracts judge feedback from the latest changes_requested review
        and looks for session ID in task notes.

        Args:
            task_id: Task ID being reworked

        Returns:
            Rework context including judge feedback and attempt count
        """
        # Get task with reviews to find judge feedback
        task_data = await self.client.get_task(task_id, expand=["reviews"])

        # Find the latest changes_requested review
        judge_feedback = ""
        reviews = task_data.get("reviews", [])
        for review in reversed(reviews):  # Most recent first
            if review.get("decision") == "changes_requested":
                judge_feedback = review.get("reason", "No feedback provided")
                break

        # Try to find session ID from previous execution
        session_id = None
        try:
            notes = await self.client.list_notes(task_id)
            for note in notes:
                text = note.get("text", "")
                if text.startswith("vafi:session_id="):
                    session_id = text.split("=", 1)[1].strip()
                    break
        except Exception:
            # If we can't get notes, continue without session resumption
            pass

        # Count attempts
        attempt_number = await self.count_rework_attempts(task_id)

        return ReworkContext(
            session_id=session_id,
            judge_feedback=judge_feedback,
            attempt_number=attempt_number
        )

    async def count_rework_attempts(self, task_id: str) -> int:
        """Count the number of rework attempts for a task.

        Args:
            task_id: Task ID to check

        Returns:
            Number of changes_requested reviews
        """
        task_data = await self.client.get_task(task_id, expand=["reviews"])
        reviews = task_data.get("reviews", [])

        count = 0
        for review in reviews:
            if review.get("decision") == "changes_requested":
                count += 1

        return count

    def _task_data_to_info(self, task_data: dict[str, Any]) -> TaskInfo:
        """Convert vtf task data to TaskInfo.

        Args:
            task_data: Raw task data from vtf API

        Returns:
            Parsed TaskInfo instance
        """
        return TaskInfo(
            id=task_data["id"],
            title=task_data["title"],
            spec=task_data["spec"],
            project_id=task_data["project"],
            test_command=task_data.get("test_command", {}),
            needs_review=task_data.get("needs_review_on_completion", False),
            assigned_to=task_data.get("assigned_to")
        )