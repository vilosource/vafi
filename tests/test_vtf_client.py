"""Unit tests for VtfClient.

Tests cover the main API interactions: register, poll, claim, complete, fail.
Uses pytest-asyncio for async test support.
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from controller.vtf_client import (
    VtfClient,
    VtfError,
    VtfNotFoundError,
    VtfConflictError,
    VtfValidationError,
)


@pytest.fixture
def client():
    """Create a VtfClient instance for testing."""
    return VtfClient(base_url="http://test.example.com")


@pytest.fixture
def mock_response():
    """Create a mock HTTP response."""
    response = MagicMock(spec=httpx.Response)
    response.is_success = True
    response.status_code = 200
    response.json.return_value = {}
    response.text = ""
    return response


class TestVtfClient:
    """Test suite for VtfClient."""

    def test_init(self):
        """Test client initialization."""
        client = VtfClient("http://example.com/", "test-token")
        assert client.base_url == "http://example.com"
        assert client.token == "test-token"

    def test_headers_without_token(self, client):
        """Test headers without authentication token."""
        headers = client._headers()
        assert headers == {"Content-Type": "application/json"}

    def test_headers_with_token(self, client):
        """Test headers with authentication token."""
        client.token = "test-token"
        headers = client._headers()
        assert headers == {
            "Content-Type": "application/json",
            "Authorization": "Token test-token"
        }

    def test_handle_error_404(self, client):
        """Test error handling for 404 responses."""
        response = MagicMock(spec=httpx.Response)
        response.status_code = 404
        response.text = "Not found"

        with pytest.raises(VtfNotFoundError, match="Resource not found: Not found"):
            client._handle_error(response)

    def test_handle_error_409(self, client):
        """Test error handling for 409 responses."""
        response = MagicMock(spec=httpx.Response)
        response.status_code = 409
        response.text = "Conflict"

        with pytest.raises(VtfConflictError, match="Conflict: Conflict"):
            client._handle_error(response)

    def test_handle_error_422(self, client):
        """Test error handling for 422 responses."""
        response = MagicMock(spec=httpx.Response)
        response.status_code = 422
        response.text = "Validation failed"

        with pytest.raises(VtfValidationError, match="Validation error: Validation failed"):
            client._handle_error(response)

    def test_handle_error_generic(self, client):
        """Test error handling for other HTTP errors."""
        response = MagicMock(spec=httpx.Response)
        response.status_code = 500
        response.text = "Internal server error"
        response.is_success = False

        with pytest.raises(VtfError, match="HTTP 500: Internal server error"):
            client._handle_error(response)

    def test_handle_error_success(self, client):
        """Test that successful responses don't raise errors."""
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        response.is_success = True

        # Should not raise
        client._handle_error(response)

    @pytest.mark.asyncio
    async def test_register_agent(self, client, mock_response):
        """Test agent registration."""
        mock_response.json.return_value = {
            "id": "agent_123",
            "name": "test-agent",
            "tags": ["executor"],
            "token": "auth_token_here"
        }

        with patch.object(client._client, 'post', return_value=mock_response) as mock_post:
            result = await client.register_agent("test-agent", ["executor"])

        # Check the request
        mock_post.assert_called_once_with(
            "http://test.example.com/v1/agents/",
            json={"name": "test-agent", "tags": ["executor"]},
            headers={"Content-Type": "application/json"}
        )

        # Check the response
        assert result["id"] == "agent_123"
        assert result["token"] == "auth_token_here"

        # Check that token was stored
        assert client.token == "auth_token_here"

    @pytest.mark.asyncio
    async def test_list_claimable(self, client, mock_response):
        """Test listing claimable tasks."""
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "task_123",
                    "title": "Test task",
                    "spec": "task spec content"
                }
            ]
        }

        with patch.object(client._client, 'get', return_value=mock_response) as mock_get:
            result = await client.list_claimable(["executor"], "agent_123")

        mock_get.assert_called_once_with(
            "http://test.example.com/v1/tasks/claimable/",
            params={"tags": "executor", "agent_id": "agent_123"},
            headers={"Content-Type": "application/json"}
        )

        assert len(result) == 1
        assert result[0]["id"] == "task_123"

    @pytest.mark.asyncio
    async def test_list_tasks_basic(self, client, mock_response):
        """Test listing tasks with basic parameters."""
        mock_response.json.return_value = {"results": []}

        with patch.object(client._client, 'get', return_value=mock_response) as mock_get:
            await client.list_tasks("todo")

        mock_get.assert_called_once_with(
            "http://test.example.com/v1/tasks/",
            params={"status": "todo"},
            headers={"Content-Type": "application/json"}
        )

    @pytest.mark.asyncio
    async def test_list_tasks_with_filters(self, client, mock_response):
        """Test listing tasks with filters and expand."""
        mock_response.json.return_value = {"results": []}

        with patch.object(client._client, 'get', return_value=mock_response) as mock_get:
            await client.list_tasks(
                "changes_requested",
                assigned_to="agent_123",
                expand=["reviews"]
            )

        mock_get.assert_called_once_with(
            "http://test.example.com/v1/tasks/",
            params={
                "status": "changes_requested",
                "assigned_to": "agent_123",
                "expand": "reviews"
            },
            headers={"Content-Type": "application/json"}
        )

    @pytest.mark.asyncio
    async def test_claim_task(self, client, mock_response):
        """Test claiming a task."""
        mock_response.json.return_value = {
            "id": "task_123",
            "claimed_by": "agent_123",
            "claimed_at": "2026-03-22T10:00:00Z"
        }

        with patch.object(client._client, 'post', return_value=mock_response) as mock_post:
            result = await client.claim_task("task_123", "agent_123", ["executor"])

        mock_post.assert_called_once_with(
            "http://test.example.com/v1/tasks/task_123/claim/",
            json={"agent_id": "agent_123", "tags": ["executor"]},
            headers={"Content-Type": "application/json"}
        )

        assert result["id"] == "task_123"
        assert result["claimed_by"] == "agent_123"

    @pytest.mark.asyncio
    async def test_heartbeat(self, client, mock_response):
        """Test sending task heartbeat."""
        with patch.object(client._client, 'post', return_value=mock_response) as mock_post:
            await client.heartbeat("task_123")

        mock_post.assert_called_once_with(
            "http://test.example.com/v1/tasks/task_123/heartbeat/",
            headers={"Content-Type": "application/json"}
        )

    @pytest.mark.asyncio
    async def test_complete_task(self, client, mock_response):
        """Test completing a task."""
        with patch.object(client._client, 'post', return_value=mock_response) as mock_post:
            await client.complete_task("task_123")

        mock_post.assert_called_once_with(
            "http://test.example.com/v1/tasks/task_123/complete/",
            headers={"Content-Type": "application/json"}
        )

    @pytest.mark.asyncio
    async def test_fail_task(self, client, mock_response):
        """Test failing a task."""
        with patch.object(client._client, 'post', return_value=mock_response) as mock_post:
            await client.fail_task("task_123")

        mock_post.assert_called_once_with(
            "http://test.example.com/v1/tasks/task_123/fail/",
            headers={"Content-Type": "application/json"}
        )

    @pytest.mark.asyncio
    async def test_get_project(self, client, mock_response):
        """Test getting project metadata."""
        mock_response.json.return_value = {
            "id": "project_123",
            "name": "test-project",
            "repo_url": "git@example.com:test/repo.git",
            "default_branch": "main"
        }

        with patch.object(client._client, 'get', return_value=mock_response) as mock_get:
            result = await client.get_project("project_123")

        mock_get.assert_called_once_with(
            "http://test.example.com/v1/projects/project_123/",
            headers={"Content-Type": "application/json"}
        )

        assert result["repo_url"] == "git@example.com:test/repo.git"
        assert result["default_branch"] == "main"

    @pytest.mark.asyncio
    async def test_add_note(self, client, mock_response):
        """Test adding a task note."""
        mock_response.json.return_value = {
            "id": "note_123",
            "text": "Test note",
            "actor_id": "agent_123"
        }

        with patch.object(client._client, 'post', return_value=mock_response) as mock_post:
            result = await client.add_note("task_123", "Test note", "agent_123")

        mock_post.assert_called_once_with(
            "http://test.example.com/v1/tasks/task_123/notes/",
            json={"text": "Test note", "actor_id": "agent_123"},
            headers={"Content-Type": "application/json"}
        )

        assert result["text"] == "Test note"

    @pytest.mark.asyncio
    async def test_get_task(self, client, mock_response):
        """Test getting task details."""
        mock_response.json.return_value = {
            "id": "task_123",
            "title": "Test task",
            "spec": "task spec content"
        }

        with patch.object(client._client, 'get', return_value=mock_response) as mock_get:
            result = await client.get_task("task_123")

        mock_get.assert_called_once_with(
            "http://test.example.com/v1/tasks/task_123/",
            params={},
            headers={"Content-Type": "application/json"}
        )

        assert result["id"] == "task_123"

    @pytest.mark.asyncio
    async def test_get_task_with_expand(self, client, mock_response):
        """Test getting task details with expand."""
        mock_response.json.return_value = {"id": "task_123"}

        with patch.object(client._client, 'get', return_value=mock_response) as mock_get:
            await client.get_task("task_123", expand=["reviews", "links"])

        mock_get.assert_called_once_with(
            "http://test.example.com/v1/tasks/task_123/",
            params={"expand": "reviews,links"},
            headers={"Content-Type": "application/json"}
        )

    @pytest.mark.asyncio
    async def test_submit_review(self, client, mock_response):
        """Test submitting a review."""
        mock_response.json.return_value = {
            "id": "review_123",
            "decision": "approved",
            "reason": "Looks good",
            "reviewer_id": "judge_123"
        }

        with patch.object(client._client, 'post', return_value=mock_response) as mock_post:
            result = await client.submit_review(
                "task_123", "approved", "Looks good", "judge_123"
            )

        mock_post.assert_called_once_with(
            "http://test.example.com/v1/tasks/task_123/reviews/",
            json={
                "decision": "approved",
                "reason": "Looks good",
                "reviewer_id": "judge_123",
                "reviewer_type": "agent"
            },
            headers={"Content-Type": "application/json"}
        )

        assert result["decision"] == "approved"

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager support."""
        async with VtfClient("http://example.com") as client:
            assert isinstance(client, VtfClient)
            # Client should be properly initialized

    @pytest.mark.asyncio
    async def test_close(self, client):
        """Test client closing."""
        with patch.object(client._client, 'aclose') as mock_close:
            await client.close()

        mock_close.assert_called_once()