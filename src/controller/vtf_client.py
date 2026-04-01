"""HTTP client for vtf REST API.

This is a thin wrapper around the vtf API endpoints. One method per endpoint,
no business logic. All methods are async and use httpx for HTTP operations.
"""

import httpx
from typing import Any


class VtfError(Exception):
    """Base exception for vtf API errors."""
    pass


class VtfNotFoundError(VtfError):
    """Raised when a resource is not found (404)."""
    pass


class VtfConflictError(VtfError):
    """Raised when a conflict occurs (409)."""
    pass


class VtfValidationError(VtfError):
    """Raised when validation fails (422)."""
    pass


class VtfClient:
    """HTTP client for the vtf REST API.

    Handles authentication, JSON serialization, error mapping, and pagination.
    One method per API endpoint.
    """

    def __init__(self, base_url: str, token: str | None = None):
        """Initialize the client with base URL and optional auth token.

        Args:
            base_url: Base URL of the vtf API (e.g., "http://localhost:8002")
            token: Authentication token (set after agent registration)
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.AsyncClient()

    async def __aenter__(self):
        """Async context manager entry."""
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        """Build headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def _handle_error(self, response: httpx.Response) -> None:
        """Handle HTTP error responses by raising appropriate exceptions."""
        if response.status_code == 404:
            raise VtfNotFoundError(f"Resource not found: {response.text}")
        elif response.status_code == 409:
            raise VtfConflictError(f"Conflict: {response.text}")
        elif response.status_code == 422:
            raise VtfValidationError(f"Validation error: {response.text}")
        elif not response.is_success:
            raise VtfError(f"HTTP {response.status_code}: {response.text}")

    async def register_agent(
        self, name: str, tags: list[str], pod_name: str | None = None
    ) -> dict[str, Any]:
        """Register a new agent with vtf.

        Args:
            name: Agent name
            tags: Agent tags for task matching
            pod_name: Kubernetes pod name (from Downward API)

        Returns:
            Agent data including ID and auth token
        """
        url = f"{self.base_url}/v1/agents/"
        payload: dict[str, Any] = {"name": name, "tags": tags}
        if pod_name is not None:
            payload["pod_name"] = pod_name

        response = await self._client.post(url, json=payload, headers=self._headers())
        self._handle_error(response)

        agent_data = response.json()
        # Store the token for future requests
        self.token = agent_data.get("token")
        return agent_data

    async def list_claimable(self, tags: list[str], agent_id: str) -> list[dict[str, Any]]:
        """Get claimable tasks for an agent.

        Args:
            tags: Agent tags to match against task requirements
            agent_id: Agent ID for assignment filtering

        Returns:
            List of claimable task data
        """
        url = f"{self.base_url}/v1/tasks/claimable/"
        params = {
            "tags": ",".join(tags),
            "agent_id": agent_id
        }

        response = await self._client.get(url, params=params, headers=self._headers())
        self._handle_error(response)

        data = response.json()
        return data.get("results", [])

    async def list_tasks(
        self,
        status: str,
        assigned_to: str | None = None,
        expand: list[str] | None = None,
        workplan: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filtering.

        Args:
            status: Task status to filter by
            assigned_to: Agent ID to filter by assignment
            expand: Related fields to expand (e.g., ["reviews", "links"])
            workplan: Workplan ID to filter by

        Returns:
            List of task data
        """
        url = f"{self.base_url}/v1/tasks/"
        params = {"status": status}

        if assigned_to:
            params["assigned_to"] = assigned_to
        if expand:
            params["expand"] = ",".join(expand)
        if workplan:
            params["workplan"] = workplan

        response = await self._client.get(url, params=params, headers=self._headers())
        self._handle_error(response)

        data = response.json()
        return data.get("results", [])

    async def claim_task(self, task_id: str, agent_id: str, tags: list[str]) -> dict[str, Any]:
        """Claim a task for an agent.

        Args:
            task_id: Task ID to claim
            agent_id: Agent ID making the claim
            tags: Agent tags for validation

        Returns:
            Updated task data
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/claim/"
        payload = {
            "agent_id": agent_id,
            "tags": tags
        }

        response = await self._client.post(url, json=payload, headers=self._headers())
        self._handle_error(response)

        return response.json()

    async def heartbeat(self, task_id: str) -> None:
        """Send heartbeat for a claimed task.

        Args:
            task_id: Task ID to send heartbeat for
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/heartbeat/"

        response = await self._client.post(url, headers=self._headers())
        self._handle_error(response)

    async def complete_task(self, task_id: str) -> None:
        """Mark a task as completed.

        Args:
            task_id: Task ID to complete
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/complete/"

        response = await self._client.post(url, headers=self._headers())
        self._handle_error(response)

    async def fail_task(self, task_id: str) -> None:
        """Mark a task as failed.

        Args:
            task_id: Task ID to fail
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/fail/"

        response = await self._client.post(url, headers=self._headers())
        self._handle_error(response)

    async def get_project(self, project_id: str) -> dict[str, Any]:
        """Get project metadata.

        Args:
            project_id: Project ID

        Returns:
            Project data including repo URL and default branch
        """
        url = f"{self.base_url}/v1/projects/{project_id}/"

        response = await self._client.get(url, headers=self._headers())
        self._handle_error(response)

        return response.json()

    async def add_note(self, task_id: str, text: str, actor_id: str) -> dict[str, Any]:
        """Add a note to a task.

        Args:
            task_id: Task ID
            text: Note content
            actor_id: ID of the actor adding the note

        Returns:
            Created note data
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/notes/"
        payload = {
            "text": text,
            "actor_id": actor_id
        }

        response = await self._client.post(url, json=payload, headers=self._headers())
        self._handle_error(response)

        return response.json()

    async def list_notes(self, task_id: str) -> list[dict[str, Any]]:
        """List notes for a task.

        Args:
            task_id: Task ID

        Returns:
            List of note data
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/notes/"

        response = await self._client.get(url, headers=self._headers())
        self._handle_error(response)

        data = response.json()
        return data.get("results", [])

    async def get_task(self, task_id: str, expand: list[str] | None = None) -> dict[str, Any]:
        """Get task details.

        Args:
            task_id: Task ID
            expand: Related fields to expand (e.g., ["reviews", "links"])

        Returns:
            Task data
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/"
        params = {}

        if expand:
            params["expand"] = ",".join(expand)

        response = await self._client.get(url, params=params, headers=self._headers())
        self._handle_error(response)

        return response.json()

    async def submit_review(
        self,
        task_id: str,
        decision: str,
        reason: str,
        reviewer_id: str
    ) -> dict[str, Any]:
        """Submit a review for a task.

        Args:
            task_id: Task ID being reviewed
            decision: Review decision ("approved", "changes_requested")
            reason: Review reasoning/feedback
            reviewer_id: ID of the reviewer

        Returns:
            Created review data
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/reviews/"
        payload = {
            "decision": decision,
            "reason": reason,
            "reviewer_id": reviewer_id,
            "reviewer_type": "agent"
        }

        response = await self._client.post(url, json=payload, headers=self._headers())
        self._handle_error(response)

        return response.json()

    async def update_agent(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update agent fields.

        Args:
            agent_id: Agent ID to update
            data: Fields to update (e.g., last_heartbeat, status)

        Returns:
            Updated agent data
        """
        url = f"{self.base_url}/v1/agents/{agent_id}/"

        response = await self._client.patch(url, json=data, headers=self._headers())
        self._handle_error(response)

        return response.json()

    async def update_task(self, task_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Partial update of task fields.

        Args:
            task_id: Task ID to update
            data: Fields to update (e.g., execution_summary)

        Returns:
            Updated task data
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/"

        response = await self._client.patch(url, json=data, headers=self._headers())
        self._handle_error(response)

        return response.json()

    async def submit_task(self, task_id: str) -> None:
        """Submit a task from draft to todo status.

        Args:
            task_id: Task ID to submit
        """
        url = f"{self.base_url}/v1/tasks/{task_id}/submit/"

        response = await self._client.post(url, headers=self._headers())
        self._handle_error(response)