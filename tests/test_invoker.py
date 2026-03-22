"""Unit tests for the HarnessInvoker class.

Tests the complete harness invocation pipeline including repo cloning,
subprocess execution, and output parsing.
"""

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch, MagicMock
import pytest

from controller.config import AgentConfig
from controller.invoker import HarnessInvoker
from controller.types import TaskInfo, RepoInfo, ExecutionResult


@pytest.fixture
def test_config():
    """Test configuration for invoker."""
    return AgentConfig(
        agent_id="test-invoker",
        task_timeout=30,
        max_turns=10,
        sessions_dir="/tmp/test-sessions",
    )


@pytest.fixture
def sample_task():
    """Sample task for testing."""
    return TaskInfo(
        id="test-task-123",
        title="Test Task",
        spec="description: Test task for invoker\nsteps:\n  - implement\n  - test",
        project_id="test-project",
        test_command={"command": "pytest tests/"},
        needs_review=False,
        assigned_to=None
    )


@pytest.fixture
def sample_repo():
    """Sample repository info."""
    return RepoInfo(
        url="https://github.com/test/repo.git",
        branch="main"
    )


@pytest.fixture
def temp_workdir(tmp_path):
    """Temporary workdir for testing."""
    return tmp_path / "test-workdir"


class TestHarnessInvoker:
    """Test cases for HarnessInvoker."""

    def test_initialization(self, test_config):
        """Test invoker initialization."""
        invoker = HarnessInvoker(test_config)
        assert invoker.config is test_config

    @pytest.mark.asyncio
    async def test_invoke_complete_pipeline(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test complete invoke pipeline with mocked subprocess."""
        invoker = HarnessInvoker(test_config)

        # Mock successful harness output
        mock_output = {
            "result": "Task completed successfully",
            "is_error": False,
            "session_id": "session-abc123",
            "total_cost_usd": 0.05,
            "num_turns": 3,
            "stop_reason": "end_turn"
        }

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:

            # Mock git clone
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")

            # Mock harness subprocess
            mock_process = Mock()
            mock_process.returncode = 0

            async def mock_communicate():
                return (json.dumps(mock_output), "")

            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            # Mock prompt
            prompt = "Test prompt for task test-task-123"

            # Execute
            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, prompt)

            # Verify result
            assert isinstance(result, ExecutionResult)
            assert result.success is True
            assert result.session_id == "session-abc123"
            assert result.completion_report == "Task completed successfully"
            assert result.cost_usd == 0.05
            assert result.num_turns == 3

            # Verify git clone was called
            mock_git.assert_called_once()
            git_args = mock_git.call_args[0][0]
            assert git_args[0] == "git"
            assert git_args[1] == "clone"
            assert "--branch" in git_args
            assert "main" in git_args
            assert sample_repo.url in git_args

            # Verify harness was called
            mock_subprocess.assert_called_once()
            harness_args = mock_subprocess.call_args[0]
            assert harness_args[0] == "claude"
            assert "-p" in harness_args
            assert prompt in harness_args
            assert "--output-format" in harness_args
            assert "json" in harness_args

    @pytest.mark.asyncio
    async def test_repo_already_cloned(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test that existing repo is not re-cloned."""
        invoker = HarnessInvoker(test_config)

        # Create existing repo directory with .git
        temp_workdir.mkdir(parents=True)
        (temp_workdir / ".git").mkdir()

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:

            # Mock harness subprocess
            mock_process = Mock()
            mock_process.returncode = 0

            async def mock_communicate():
                return ('{"result": "test", "is_error": false}', "")

            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            # Execute
            await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            # Verify git clone was NOT called
            mock_git.assert_not_called()

    @pytest.mark.asyncio
    async def test_git_clone_failure(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test handling of git clone failures."""
        invoker = HarnessInvoker(test_config)

        with patch('controller.invoker.subprocess.run') as mock_git:
            # Mock git clone failure
            mock_git.side_effect = subprocess.CalledProcessError(
                1, ["git", "clone"], stderr="Repository not found"
            )

            # Execute
            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            # Verify failure result
            assert isinstance(result, ExecutionResult)
            assert result.success is False
            assert "invocation error" in result.completion_report.lower()

    @pytest.mark.asyncio
    async def test_harness_infrastructure_failure(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test handling of harness infrastructure failures."""
        invoker = HarnessInvoker(test_config)

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:

            # Mock git clone success
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")

            # Mock harness failure
            mock_process = Mock()
            mock_process.returncode = 1

            async def mock_communicate():
                return ("", "Authentication failed")

            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            # Execute
            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            # Verify infrastructure failure handling
            assert result.success is False
            assert "Infrastructure failure" in result.completion_report
            assert "auth" in result.completion_report

    @pytest.mark.asyncio
    async def test_harness_error_response(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test handling of harness error responses."""
        invoker = HarnessInvoker(test_config)

        # Mock harness error output
        error_output = {
            "result": "Failed to complete task due to syntax error",
            "is_error": True,
            "session_id": "session-error123",
            "total_cost_usd": 0.02,
            "num_turns": 1
        }

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:

            # Mock git clone success
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")

            # Mock harness error response
            mock_process = Mock()
            mock_process.returncode = 0

            async def mock_communicate():
                return (json.dumps(error_output), "")

            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            # Execute
            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            # Verify harness error handling
            assert result.success is False
            assert result.session_id == "session-error123"
            assert result.completion_report == "Failed to complete task due to syntax error"
            assert result.cost_usd == 0.02
            assert result.num_turns == 1

    @pytest.mark.asyncio
    async def test_invalid_json_output(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test handling of invalid JSON output from harness."""
        invoker = HarnessInvoker(test_config)

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:

            # Mock git clone success
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")

            # Mock harness with invalid JSON
            mock_process = Mock()
            mock_process.returncode = 0

            async def mock_communicate():
                return ("Not valid JSON output", "")

            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            # Execute
            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            # Verify JSON parse error handling
            assert result.success is False
            assert "Invalid JSON output" in result.completion_report
            assert "Not valid JSON output" in result.completion_report

    @pytest.mark.asyncio
    async def test_harness_timeout(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test handling of harness timeouts."""
        invoker = HarnessInvoker(test_config)

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:

            # Mock git clone success
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")

            # Mock harness timeout
            mock_process = Mock()
            mock_process.kill = Mock()
            mock_process.wait = AsyncMock()

            # Mock communicate to raise timeout
            async def mock_communicate():
                raise asyncio.TimeoutError()
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            # Execute
            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            # Verify timeout handling
            assert result.success is False
            assert "invocation error" in result.completion_report.lower()

    def test_error_classification(self, test_config):
        """Test infrastructure error classification."""
        invoker = HarnessInvoker(test_config)

        # Test auth error
        result_mock = Mock()
        result_mock.returncode = 1
        result_mock.stderr = "Authentication failed"
        result = invoker._handle_infrastructure_failure(result_mock, "test-task")
        assert "auth" in result.completion_report

        # Test rate limit error
        result_mock.stderr = "Rate limit exceeded"
        result = invoker._handle_infrastructure_failure(result_mock, "test-task")
        assert "rate_limit" in result.completion_report

        # Test OOM error
        result_mock.stderr = "Out of memory"
        result = invoker._handle_infrastructure_failure(result_mock, "test-task")
        assert "oom" in result.completion_report

        # Test timeout error
        result_mock.returncode = 124
        result_mock.stderr = "Process timeout"
        result = invoker._handle_infrastructure_failure(result_mock, "test-task")
        assert "timeout" in result.completion_report

        # Test unknown error
        result_mock.returncode = 2
        result_mock.stderr = "Unknown error"
        result = invoker._handle_infrastructure_failure(result_mock, "test-task")
        assert "unknown" in result.completion_report

    @pytest.mark.asyncio
    async def test_max_turns_parameter(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test that max_turns parameter is passed to harness."""
        invoker = HarnessInvoker(test_config)

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:

            # Mock git clone success
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")

            # Mock harness success
            mock_process = Mock()
            mock_process.returncode = 0

            async def mock_communicate():
                return ('{"result": "test", "is_error": false}', "")

            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            # Execute
            await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            # Verify max_turns parameter was included
            mock_subprocess.assert_called_once()
            harness_args = mock_subprocess.call_args[0]
            assert "--max-turns" in harness_args
            assert str(test_config.max_turns) in harness_args