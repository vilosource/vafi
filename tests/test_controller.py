"""Unit tests for the vafi controller.

Tests the controller poll-claim-log cycle with a mocked WorkSource.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock

from controller.config import AgentConfig
from controller.controller import Controller
from controller.types import AgentInfo, TaskInfo


class MockWorkSource:
    """Mock WorkSource for testing controller logic."""

    def __init__(self):
        self.register = AsyncMock()
        self.poll = AsyncMock()
        self.claim = AsyncMock()
        self.fail = AsyncMock()
        self.heartbeat = AsyncMock()
        self.agent_heartbeat = AsyncMock()
        self.set_agent_offline = AsyncMock()
        self.complete = AsyncMock()
        self.get_repo_info = AsyncMock()
        self.get_rework_context = AsyncMock()
        self.count_rework_attempts = AsyncMock()
        self.submit = AsyncMock()
        self.list_submittable = AsyncMock()
        self.submit_review = AsyncMock()


@pytest.fixture
def mock_work_source():
    """Provide a mock work source for testing."""
    return MockWorkSource()


@pytest.fixture
def test_config():
    """Provide test configuration."""
    return AgentConfig(
        agent_id="test-agent",
        agent_role="executor",
        agent_tags=["executor", "test"],
        vtf_api_url="http://test-vtf:8000",
        poll_interval=1,  # Short interval for testing
    )


@pytest.fixture
def sample_agent():
    """Sample agent info for testing."""
    return AgentInfo(id="agent-123", token="test-token")


@pytest.fixture
def sample_task():
    """Sample task info for testing."""
    return TaskInfo(
        id="task-456",
        title="Test Task",
        spec="test: true\ndescription: A test task",
        project_id="project-789",
        test_command={"command": "echo test"},
        needs_review=False,
        assigned_to=None
    )


class TestController:
    """Test cases for the Controller class."""

    @pytest.mark.asyncio
    async def test_initialization(self, mock_work_source, test_config):
        """Test controller initialization."""
        controller = Controller(mock_work_source, test_config)
        assert controller.work_source is mock_work_source
        assert controller.config is test_config
        assert controller._agent_info is None

    @pytest.mark.asyncio
    async def test_successful_registration(self, mock_work_source, test_config, sample_agent):
        """Test successful agent registration."""
        # Setup mock
        mock_work_source.register.return_value = sample_agent
        mock_work_source.poll.return_value = None  # No work available

        controller = Controller(mock_work_source, test_config)

        # Use timeout to prevent infinite loop
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(controller.run(), timeout=0.1)

        # Verify registration was called
        mock_work_source.register.assert_called_once_with(
            name="test-agent",
            tags=["executor", "test"]
        )

    @pytest.mark.asyncio
    async def test_poll_no_work_available(self, mock_work_source, test_config, sample_agent):
        """Test polling when no work is available."""
        # Setup mocks
        mock_work_source.register.return_value = sample_agent
        mock_work_source.poll.return_value = None

        controller = Controller(mock_work_source, test_config)

        # Use timeout to prevent infinite loop
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(controller.run(), timeout=0.1)

        # Verify polling was attempted
        mock_work_source.poll.assert_called_with("agent-123", ["executor", "test"])

    @pytest.mark.asyncio
    async def test_successful_task_claim_and_execution_failure(self, mock_work_source, test_config, sample_agent, sample_task):
        """Test successful task claim but execution failure due to environment."""
        # Setup mocks
        mock_work_source.register.return_value = sample_agent
        mock_work_source.poll.side_effect = [sample_task, None]  # Return task once, then no work
        mock_work_source.claim.return_value = sample_task

        # Mock repo info
        from controller.types import RepoInfo
        mock_repo = RepoInfo(url="https://github.com/test/repo.git", branch="main")
        mock_work_source.get_repo_info.return_value = mock_repo

        controller = Controller(mock_work_source, test_config)

        # Use timeout to prevent infinite loop
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(controller.run(), timeout=0.1)

        # Verify claim and fail were called (execution will fail due to permissions)
        mock_work_source.claim.assert_called_once_with("task-456", "agent-123")
        # Should fail due to permission error on /sessions directory
        mock_work_source.fail.assert_called_once()
        call_args = mock_work_source.fail.call_args[0]
        assert call_args[0] == "task-456"
        assert "Permission denied" in call_args[1] or "Execution failed" in call_args[1]

    @pytest.mark.asyncio
    async def test_claim_failure_handling(self, mock_work_source, test_config, sample_agent, sample_task):
        """Test handling of claim failures."""
        # Setup mocks
        mock_work_source.register.return_value = sample_agent
        mock_work_source.poll.side_effect = [sample_task, None]
        mock_work_source.claim.side_effect = Exception("Claim failed")

        controller = Controller(mock_work_source, test_config)

        # Use timeout to prevent infinite loop
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(controller.run(), timeout=0.1)

        # Verify error handling - should try to fail the task
        mock_work_source.fail.assert_called_once_with("task-456", "error during processing: Claim failed")

    @pytest.mark.asyncio
    async def test_poll_single_iteration(self, mock_work_source, test_config, sample_agent):
        """Test a single poll iteration without running the full loop."""
        mock_work_source.poll.return_value = None

        controller = Controller(mock_work_source, test_config)
        controller._agent_info = sample_agent

        # Test single poll iteration
        await controller._poll_and_process()

        # Verify poll was called correctly
        mock_work_source.poll.assert_called_once_with("agent-123", ["executor", "test"])

    @pytest.mark.asyncio
    async def test_shutdown_signal_handling(self, mock_work_source, test_config, sample_agent):
        """Test that controller handles shutdown signals properly."""
        mock_work_source.register.return_value = sample_agent
        mock_work_source.poll.return_value = None

        controller = Controller(mock_work_source, test_config)

        # Simulate shutdown signal
        async def trigger_shutdown():
            await asyncio.sleep(0.05)  # Small delay
            controller._shutdown.set()

        # Run controller with shutdown trigger
        await asyncio.gather(
            controller.run(),
            trigger_shutdown()
        )

        # Should exit cleanly
        assert controller._shutdown.is_set()

    @pytest.mark.asyncio
    async def test_marks_agent_offline_on_shutdown(self, mock_work_source, test_config, sample_agent):
        """Test that controller marks agent offline on graceful shutdown."""
        mock_work_source.register.return_value = sample_agent
        mock_work_source.poll.return_value = None

        controller = Controller(mock_work_source, test_config)

        async def trigger_shutdown():
            await asyncio.sleep(0.05)
            controller._shutdown.set()

        await asyncio.gather(
            controller.run(),
            trigger_shutdown()
        )

        mock_work_source.set_agent_offline.assert_called_once_with("agent-123")

    @pytest.mark.asyncio
    async def test_agent_heartbeat_runs_during_idle(self, mock_work_source, test_config, sample_agent):
        """Test that agent heartbeat fires while polling idle."""
        mock_work_source.register.return_value = sample_agent
        mock_work_source.poll.return_value = None

        # Use short poll interval so heartbeat fires
        test_config.poll_interval = 0.05

        controller = Controller(mock_work_source, test_config)

        async def trigger_shutdown():
            await asyncio.sleep(0.15)
            controller._shutdown.set()

        await asyncio.gather(
            controller.run(),
            trigger_shutdown()
        )

        # Agent heartbeat should have fired at least once
        assert mock_work_source.agent_heartbeat.call_count >= 1