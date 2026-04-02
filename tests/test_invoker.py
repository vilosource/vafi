"""Unit tests for the HarnessInvoker class.

Tests the complete harness invocation pipeline including repo cloning,
subprocess execution via /opt/vf-harness/run.sh, and output parsing.
"""

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from controller.config import AgentConfig
from controller.invoker import HarnessInvoker
from controller.types import TaskInfo, RepoInfo, ExecutionResult


@pytest.fixture
def test_config():
    return AgentConfig(
        agent_id="test-invoker",
        task_timeout=30,
        max_turns=10,
        sessions_dir="/tmp/test-sessions",
    )


@pytest.fixture
def sample_task():
    return TaskInfo(
        id="test-task-123",
        title="Test Task",
        spec="description: Test task for invoker\nsteps:\n  - implement\n  - test",
        project_id="test-project",
        test_command={"command": "pytest tests/"},
        needs_review=False,
        assigned_to=None,
    )


@pytest.fixture
def sample_repo():
    return RepoInfo(url="https://github.com/test/repo.git", branch="main")


@pytest.fixture
def temp_workdir(tmp_path):
    return tmp_path / "test-workdir"


class TestHarnessInvoker:
    def test_initialization(self, test_config):
        invoker = HarnessInvoker(test_config)
        assert invoker.config is test_config

    @pytest.mark.asyncio
    async def test_command_is_run_sh(self, test_config, sample_task, sample_repo, temp_workdir):
        """Harness command is /opt/vf-harness/run.sh, not claude or pi."""
        invoker = HarnessInvoker(test_config)

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.returncode = 0
            async def mock_communicate():
                return ('{"result": "test", "is_error": false}', "")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            harness_args = mock_subprocess.call_args[0]
            assert harness_args[0] == "/opt/vf-harness/run.sh"
            # No harness CLI names in command
            assert "claude" not in harness_args
            assert "pi" not in harness_args

    @pytest.mark.asyncio
    async def test_prompt_in_env(self, test_config, sample_task, sample_repo, temp_workdir):
        """VF_PROMPT env var contains the prompt text."""
        invoker = HarnessInvoker(test_config)

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.returncode = 0
            async def mock_communicate():
                return ('{"result": "test", "is_error": false}', "")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            kwargs = mock_subprocess.call_args[1]
            assert kwargs["env"]["VF_PROMPT"] == "test prompt"
            assert kwargs["env"]["VF_TASK_ID"] == "test-task-123"

    @pytest.mark.asyncio
    async def test_max_turns_in_env(self, test_config, sample_task, sample_repo, temp_workdir):
        """VF_MAX_TURNS env var set when max_turns > 0."""
        invoker = HarnessInvoker(test_config)

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.returncode = 0
            async def mock_communicate():
                return ('{"result": "test", "is_error": false}', "")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            kwargs = mock_subprocess.call_args[1]
            assert kwargs["env"]["VF_MAX_TURNS"] == "10"

    @pytest.mark.asyncio
    async def test_cxdb_url_in_env(self, sample_task, sample_repo, temp_workdir):
        """VF_CXDB_URL env var set when cxdb configured."""
        config = AgentConfig(
            agent_id="test-cxtx", task_timeout=30, max_turns=10,
            sessions_dir="/tmp/test-sessions",
            cxdb_url="http://cxdb:9010",
        )
        invoker = HarnessInvoker(config)

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.returncode = 0
            async def mock_communicate():
                return ('{"result": "test", "is_error": false}', "")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            kwargs = mock_subprocess.call_args[1]
            assert kwargs["env"]["VF_CXDB_URL"] == "http://cxdb:9010"

    @pytest.mark.asyncio
    async def test_no_cxdb_url_when_not_configured(self, test_config, sample_task, sample_repo, temp_workdir):
        """VF_CXDB_URL not in env when cxdb_url is empty."""
        invoker = HarnessInvoker(test_config)

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.returncode = 0
            async def mock_communicate():
                return ('{"result": "test", "is_error": false}', "")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            kwargs = mock_subprocess.call_args[1]
            assert "VF_CXDB_URL" not in kwargs["env"]

    def test_output_format_selects_parser(self):
        """output_format='pi_jsonl' uses Pi parser."""
        config = AgentConfig(
            agent_id="test-pi", task_timeout=30, max_turns=10,
            sessions_dir="/tmp/test-sessions",
            output_format="pi_jsonl",
        )
        invoker = HarnessInvoker(config)

        pi_output = "\n".join([
            '{"type":"session","id":"s1"}',
            '{"type":"turn_end","message":{}}',
            '{"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"done"}],"usage":{"totalTokens":50,"cost":{"total":0.001}}}]}',
        ])
        result_mock = Mock()
        result_mock.returncode = 0
        result_mock.stdout = pi_output
        result = invoker._parse_harness_output(result_mock, "task-1")
        assert result.success is True
        assert result.session_id == "s1"

    def test_output_format_defaults_to_claude(self, test_config):
        """Default output_format uses Claude JSON parser."""
        invoker = HarnessInvoker(test_config)
        result_mock = Mock()
        result_mock.returncode = 0
        result_mock.stdout = json.dumps({"result": "done", "is_error": False})
        result = invoker._parse_harness_output(result_mock, "task-1")
        assert result.success is True
        assert result.completion_report == "done"

    @pytest.mark.asyncio
    async def test_invoke_complete_pipeline(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test complete invoke pipeline with mocked subprocess."""
        invoker = HarnessInvoker(test_config)
        mock_output = {
            "result": "Task completed successfully",
            "is_error": False,
            "session_id": "session-abc123",
            "total_cost_usd": 0.05,
            "num_turns": 3,
        }

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.returncode = 0
            async def mock_communicate():
                return (json.dumps(mock_output), "")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")

            assert result.success is True
            assert result.session_id == "session-abc123"
            assert result.completion_report == "Task completed successfully"
            assert result.cost_usd == 0.05

    @pytest.mark.asyncio
    async def test_repo_already_cloned(self, test_config, sample_task, sample_repo, temp_workdir):
        """Test that existing repo is not re-cloned."""
        invoker = HarnessInvoker(test_config)
        temp_workdir.mkdir(parents=True)
        (temp_workdir / ".git").mkdir()

        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_process = Mock()
            mock_process.returncode = 0
            async def mock_communicate():
                return ('{"result": "test", "is_error": false}', "")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")
            mock_git.assert_not_called()

    @pytest.mark.asyncio
    async def test_git_clone_failure(self, test_config, sample_task, sample_repo, temp_workdir):
        invoker = HarnessInvoker(test_config)
        with patch('controller.invoker.subprocess.run') as mock_git:
            mock_git.side_effect = subprocess.CalledProcessError(
                1, ["git", "clone"], stderr="Repository not found",
            )
            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_harness_infrastructure_failure(self, test_config, sample_task, sample_repo, temp_workdir):
        invoker = HarnessInvoker(test_config)
        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.returncode = 1
            async def mock_communicate():
                return ("", "Authentication failed")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")
            assert result.success is False
            assert "auth" in result.completion_report

    @pytest.mark.asyncio
    async def test_harness_error_response(self, test_config, sample_task, sample_repo, temp_workdir):
        invoker = HarnessInvoker(test_config)
        error_output = {
            "result": "Failed to complete task",
            "is_error": True,
            "session_id": "session-err",
            "total_cost_usd": 0.02,
            "num_turns": 1,
        }
        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.returncode = 0
            async def mock_communicate():
                return (json.dumps(error_output), "")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")
            assert result.success is False
            assert result.session_id == "session-err"

    @pytest.mark.asyncio
    async def test_invalid_json_output(self, test_config, sample_task, sample_repo, temp_workdir):
        invoker = HarnessInvoker(test_config)
        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.returncode = 0
            async def mock_communicate():
                return ("Not valid JSON output", "")
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")
            assert result.success is False
            assert "Invalid JSON" in result.completion_report

    @pytest.mark.asyncio
    async def test_harness_timeout(self, test_config, sample_task, sample_repo, temp_workdir):
        invoker = HarnessInvoker(test_config)
        with patch('controller.invoker.subprocess.run') as mock_git, \
             patch('controller.invoker.asyncio.create_subprocess_exec') as mock_subprocess:
            mock_git.return_value = Mock(returncode=0, stderr="", stdout="")
            mock_process = Mock()
            mock_process.kill = Mock()
            mock_process.wait = AsyncMock()
            async def mock_communicate():
                raise asyncio.TimeoutError()
            mock_process.communicate = mock_communicate
            mock_subprocess.return_value = mock_process

            result = await invoker.invoke(sample_task, sample_repo, temp_workdir, "test prompt")
            assert result.success is False

    def test_error_classification(self, test_config):
        invoker = HarnessInvoker(test_config)
        result_mock = Mock()
        result_mock.returncode = 1

        result_mock.stderr = "Authentication failed"
        assert "auth" in invoker._handle_infrastructure_failure(result_mock, "t").completion_report

        result_mock.stderr = "Rate limit exceeded"
        assert "rate_limit" in invoker._handle_infrastructure_failure(result_mock, "t").completion_report

        result_mock.stderr = "Out of memory"
        assert "oom" in invoker._handle_infrastructure_failure(result_mock, "t").completion_report

        result_mock.returncode = 124
        result_mock.stderr = "Process timeout"
        assert "timeout" in invoker._handle_infrastructure_failure(result_mock, "t").completion_report

    def test_no_harness_names_in_command(self, test_config):
        """Command list does not contain 'claude' or 'pi'."""
        import inspect
        source = inspect.getsource(HarnessInvoker._run_harness)
        # The command should only be run.sh
        assert '"claude"' not in source
        assert '"pi"' not in source
        assert "_build_claude_command" not in source
        assert "_build_pi_command" not in source

    # --- Pi output parsing tests ---

    def test_parse_pi_output_success(self, test_config):
        config = AgentConfig(**{**test_config.__dict__, "output_format": "pi_jsonl"})
        invoker = HarnessInvoker(config)
        pi_output = "\n".join([
            '{"type":"session","version":3,"id":"sess-abc"}',
            '{"type":"turn_end","message":{"role":"assistant"},"toolResults":[]}',
            '{"type":"turn_end","message":{"role":"assistant"},"toolResults":[]}',
            '{"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"All done"}],"usage":{"totalTokens":500,"cost":{"total":0.005}}}]}',
        ])
        result = invoker._parse_pi_output(pi_output, "task-1")
        assert result.success is True
        assert result.session_id == "sess-abc"
        assert result.completion_report == "All done"
        assert result.num_turns == 2
        assert result.cost_usd == 0.005

    def test_parse_pi_output_empty(self, test_config):
        invoker = HarnessInvoker(test_config)
        result = invoker._parse_pi_output("", "task-2")
        assert result.success is False
        assert "no output" in result.completion_report.lower()

    def test_parse_pi_output_malformed_lines(self, test_config):
        invoker = HarnessInvoker(test_config)
        pi_output = "\n".join([
            '{"type":"session","id":"sess-ok"}',
            'not valid json',
            '{"type":"turn_end","message":{}}',
            '{"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"recovered"}],"usage":{"totalTokens":50,"cost":{"total":0}}}]}',
        ])
        result = invoker._parse_pi_output(pi_output, "task-3")
        assert result.success is True
        assert result.completion_report == "recovered"
