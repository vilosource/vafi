"""Tests for WorkSource protocol and VtfWorkSource implementation."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.controller.types import AgentInfo, TaskInfo, RepoInfo, ReworkContext, ExecutionResult, GateResult
from src.controller.worksources.protocol import WorkSource
from src.controller.worksources.vtf import VtfWorkSource
from src.controller.vtf_client import VtfClient


class TestWorkSourceProtocol:
    """Test the WorkSource protocol definition."""

    def test_vtfworksource_implements_protocol(self):
        """Verify that VtfWorkSource implements all required methods."""
        # This tests that VtfWorkSource implements the WorkSource protocol
        # by checking it has all the required methods
        protocol_methods = {
            'register',
            'poll',
            'claim',
            'heartbeat',
            'complete',
            'fail',
            'submit',
            'list_submittable',
            'submit_review',
            'get_repo_info',
            'get_rework_context',
            'count_rework_attempts'
        }

        # Check that VtfWorkSource has all the methods
        vtf_methods = set(dir(VtfWorkSource))
        missing_methods = protocol_methods - vtf_methods

        assert not missing_methods, f"VtfWorkSource missing methods: {missing_methods}"

        # Also verify they are callable
        mock_client = MagicMock()
        work_source = VtfWorkSource(mock_client)
        for method_name in protocol_methods:
            method = getattr(work_source, method_name)
            assert callable(method), f"{method_name} is not callable"


class TestVtfWorkSource:
    """Test VtfWorkSource implementation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_client = AsyncMock(spec=VtfClient)
        self.work_source = VtfWorkSource(self.mock_client)

    async def test_register(self):
        """Test agent registration."""
        # Mock the client response
        self.mock_client.register_agent.return_value = {
            "id": "agent_123",
            "name": "test-agent",
            "token": "test_token_456"
        }

        # Call register
        result = await self.work_source.register("test-agent", ["executor", "claude"])

        # Verify the call and result
        self.mock_client.register_agent.assert_called_once_with("test-agent", ["executor", "claude"])
        assert isinstance(result, AgentInfo)
        assert result.id == "agent_123"
        assert result.token == "test_token_456"

    async def test_poll_returns_rework_first(self):
        """Test that poll prioritizes rework over new work."""
        # Mock rework task available
        rework_task_data = {
            "id": "task_rework",
            "title": "Rework Task",
            "spec": "task spec content",
            "project": "proj_123",
            "test_command": {"cmd": "pytest"},
            "needs_review_on_completion": True,
            "assigned_to": "agent_123"
        }
        self.mock_client.list_tasks.return_value = [rework_task_data]
        self.mock_client.list_claimable.return_value = []

        # Call poll
        result = await self.work_source.poll("agent_123", ["executor"])

        # Verify it called list_tasks for rework first
        self.mock_client.list_tasks.assert_called_once_with(
            status="changes_requested",
            assigned_to="agent_123",
            expand=["reviews"]
        )
        # Should not call list_claimable since rework was found
        self.mock_client.list_claimable.assert_not_called()

        assert isinstance(result, TaskInfo)
        assert result.id == "task_rework"

    async def test_poll_returns_claimable_when_no_rework(self):
        """Test that poll returns claimable work when no rework available."""
        # Mock no rework, but claimable work available
        claimable_task_data = {
            "id": "task_new",
            "title": "New Task",
            "spec": "new task spec",
            "project": "proj_456",
            "test_command": {"cmd": "make test"},
            "needs_review_on_completion": False,
            "assigned_to": None
        }
        self.mock_client.list_tasks.return_value = []
        self.mock_client.list_claimable.return_value = [claimable_task_data]

        # Call poll
        result = await self.work_source.poll("agent_123", ["executor"])

        # Verify it called both endpoints in priority order
        self.mock_client.list_tasks.assert_called_once_with(
            status="changes_requested",
            assigned_to="agent_123",
            expand=["reviews"]
        )
        self.mock_client.list_claimable.assert_called_once_with(["executor"], "agent_123")

        assert isinstance(result, TaskInfo)
        assert result.id == "task_new"

    async def test_poll_returns_none_when_no_work(self):
        """Test that poll returns None when no work is available."""
        # Mock no work available
        self.mock_client.list_tasks.return_value = []
        self.mock_client.list_claimable.return_value = []

        # Call poll
        result = await self.work_source.poll("agent_123", ["executor"])

        # Verify it called both endpoints
        self.mock_client.list_tasks.assert_called_once()
        self.mock_client.list_claimable.assert_called_once()

        assert result is None

    async def test_claim(self):
        """Test task claiming."""
        task_data = {
            "id": "task_123",
            "title": "Test Task",
            "spec": "test spec",
            "project": "proj_123",
            "test_command": {},
            "needs_review_on_completion": False,
            "assigned_to": "agent_123"
        }
        self.mock_client.claim_task.return_value = task_data

        result = await self.work_source.claim("task_123", "agent_123")

        self.mock_client.claim_task.assert_called_once_with("task_123", "agent_123", [])
        assert isinstance(result, TaskInfo)
        assert result.id == "task_123"

    async def test_heartbeat(self):
        """Test heartbeat."""
        await self.work_source.heartbeat("task_123")

        self.mock_client.heartbeat.assert_called_once_with("task_123")

    async def test_complete_with_session_id(self):
        """Test task completion with session ID."""
        execution_result = ExecutionResult(
            success=True,
            session_id="session_abc123",
            completion_report="Task completed successfully",
            cost_usd=0.042,
            num_turns=5,
            gate_results=[
                GateResult(
                    name="test_gate",
                    command="pytest tests/",
                    exit_code=0,
                    stdout="All tests passed",
                    passed=True
                )
            ]
        )

        await self.work_source.complete("task_123", execution_result)

        # Verify all the notes were added
        assert self.mock_client.add_note.call_count == 3

        # Check completion report note
        calls = self.mock_client.add_note.call_args_list
        assert calls[0][1]['text'] == "Task completed successfully"

        # Check session ID note
        assert calls[1][1]['text'] == "vafi:session_id=session_abc123"

        # Check metadata note
        assert "vafi:execution_metadata" in calls[2][1]['text']
        assert "cost_usd: 0.042" in calls[2][1]['text']

        # Verify complete was called
        self.mock_client.complete_task.assert_called_once_with("task_123")

    async def test_complete_without_session_id(self):
        """Test task completion without session ID."""
        execution_result = ExecutionResult(
            success=True,
            session_id=None,
            completion_report="Task completed",
            cost_usd=0.01,
            num_turns=2,
            gate_results=[]
        )

        await self.work_source.complete("task_123", execution_result)

        # Should only add 2 notes (no session ID)
        assert self.mock_client.add_note.call_count == 2
        self.mock_client.complete_task.assert_called_once_with("task_123")

    async def test_fail(self):
        """Test task failure."""
        await self.work_source.fail("task_123", "Test execution failed")

        self.mock_client.add_note.assert_called_once_with(
            task_id="task_123",
            text="Task failed: Test execution failed",
            actor_id="controller"
        )
        self.mock_client.fail_task.assert_called_once_with("task_123")

    async def test_get_repo_info(self):
        """Test getting repository information."""
        project_data = {
            "id": "proj_123",
            "name": "test-project",
            "repo_url": "git@github.com:test/repo.git",
            "default_branch": "main"
        }
        self.mock_client.get_project.return_value = project_data

        result = await self.work_source.get_repo_info("proj_123")

        self.mock_client.get_project.assert_called_once_with("proj_123")
        assert isinstance(result, RepoInfo)
        assert result.url == "git@github.com:test/repo.git"
        assert result.branch == "main"

    async def test_get_rework_context(self):
        """Test getting rework context."""
        # Mock task data with reviews
        task_data = {
            "id": "task_123",
            "reviews": [
                {
                    "decision": "approved",
                    "reason": "Looks good"
                },
                {
                    "decision": "changes_requested",
                    "reason": "Please add more tests"
                }
            ]
        }
        self.mock_client.get_task.return_value = task_data

        # Mock notes with session ID
        notes_data = [
            {"text": "Some other note"},
            {"text": "vafi:session_id=session_xyz789"}
        ]
        self.mock_client.list_notes.return_value = notes_data

        result = await self.work_source.get_rework_context("task_123")

        # Verify API calls
        self.mock_client.get_task.assert_called_with("task_123", expand=["reviews"])
        self.mock_client.list_notes.assert_called_once_with("task_123")

        assert isinstance(result, ReworkContext)
        assert result.session_id == "session_xyz789"
        assert result.judge_feedback == "Please add more tests"
        assert result.attempt_number == 1  # One changes_requested review

    async def test_get_rework_context_no_session_id(self):
        """Test getting rework context when no session ID is found."""
        task_data = {
            "id": "task_123",
            "reviews": [
                {
                    "decision": "changes_requested",
                    "reason": "Needs improvement"
                }
            ]
        }
        self.mock_client.get_task.return_value = task_data
        self.mock_client.list_notes.return_value = []

        result = await self.work_source.get_rework_context("task_123")

        assert result.session_id is None
        assert result.judge_feedback == "Needs improvement"

    async def test_count_rework_attempts(self):
        """Test counting rework attempts."""
        task_data = {
            "reviews": [
                {"decision": "approved"},
                {"decision": "changes_requested"},
                {"decision": "changes_requested"},
                {"decision": "approved"}
            ]
        }
        self.mock_client.get_task.return_value = task_data

        result = await self.work_source.count_rework_attempts("task_123")

        assert result == 2  # Two changes_requested reviews

    async def test_submit(self):
        """Test task submission."""
        await self.work_source.submit("task_123")

        self.mock_client.submit_task.assert_called_once_with("task_123")

    async def test_list_submittable_with_dependencies(self):
        """Test listing submittable tasks when dependencies are met."""
        draft_task_with_deps_completed = {
            "id": "task_draft",
            "title": "Draft Task",
            "spec": "draft spec",
            "project": "proj_123",
            "test_command": {},
            "needs_review_on_completion": False,
            "assigned_to": None,
            "depends_on": [
                {
                    "id": "dep_task_1",
                    "status": "done"
                },
                {
                    "id": "dep_task_2",
                    "status": "done"
                }
            ]
        }

        draft_task_with_pending_deps = {
            "id": "task_draft2",
            "title": "Draft Task 2",
            "spec": "draft spec 2",
            "project": "proj_456",
            "test_command": {},
            "needs_review_on_completion": False,
            "assigned_to": None,
            "depends_on": [
                {
                    "id": "dep_task_3",
                    "status": "done"
                },
                {
                    "id": "dep_task_4",
                    "status": "in_progress"  # Not done
                }
            ]
        }

        self.mock_client.list_tasks.return_value = [
            draft_task_with_deps_completed,
            draft_task_with_pending_deps
        ]

        result = await self.work_source.list_submittable()

        self.mock_client.list_tasks.assert_called_once_with(
            status="draft",
            expand=["links"]
        )

        # Only the task with completed dependencies should be returned
        assert len(result) == 1
        assert result[0].id == "task_draft"

    async def test_list_submittable_no_dependencies(self):
        """Test listing submittable tasks with no dependencies."""
        draft_task_no_deps = {
            "id": "task_draft_nodeps",
            "title": "Draft Task No Deps",
            "spec": "draft spec",
            "project": "proj_789",
            "test_command": {},
            "needs_review_on_completion": False,
            "assigned_to": None,
            "depends_on": []
        }

        self.mock_client.list_tasks.return_value = [draft_task_no_deps]

        result = await self.work_source.list_submittable()

        assert len(result) == 1
        assert result[0].id == "task_draft_nodeps"

    async def test_submit_review(self):
        """Test submitting a review."""
        await self.work_source.submit_review(
            "task_123",
            "changes_requested",
            "Please add more tests",
            "judge_agent_456"
        )

        self.mock_client.submit_review.assert_called_once_with(
            "task_123",
            "changes_requested",
            "Please add more tests",
            "judge_agent_456"
        )