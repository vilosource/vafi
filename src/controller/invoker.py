"""Harness invocation for vafi task execution.

The HarnessInvoker class handles the complete task execution pipeline:
- Repository cloning into per-task workdirs
- Claude Code CLI subprocess invocation
- Structured JSON output parsing
- Error classification and handling

This implements the D8 design decision to use subprocess invocation
rather than Docker API calls.
"""

import asyncio
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from .config import AgentConfig
from .types import TaskInfo, RepoInfo, ExecutionResult

logger = logging.getLogger(__name__)


class HarnessInvoker:
    """Invokes AI harness as subprocess for task execution.

    Handles the complete execution pipeline from repo setup through
    harness invocation to structured output parsing.
    """

    def __init__(self, config: AgentConfig):
        """Initialize the harness invoker.

        Args:
            config: Agent configuration containing timeouts and limits
        """
        self.config = config

    async def invoke(
        self,
        task: TaskInfo,
        repo: RepoInfo,
        workdir: Path,
        prompt: str
    ) -> ExecutionResult:
        """Execute a task using the AI harness.

        This method implements the complete execution pipeline:
        1. Clone repository into workdir (if not already present)
        2. Build Claude Code CLI command
        3. Run as subprocess with timeout
        4. Parse structured JSON output
        5. Return ExecutionResult with success/failure classification

        Args:
            task: Task information containing ID and specifications
            repo: Repository information (URL, branch)
            workdir: Working directory path for this task
            prompt: Rendered prompt to send to the harness

        Returns:
            ExecutionResult with success status, session info, and outputs

        Raises:
            OSError: If subprocess execution fails
            ValueError: If output parsing fails
        """
        logger.info(f"Invoking harness for task {task.id} in {workdir}")

        try:
            # Phase 1: Setup repository
            await self._ensure_repo_cloned(repo, workdir)

            # Phase 2: Invoke harness
            result = await self._run_harness(prompt, workdir, task.id)

            # Phase 3: Parse output
            execution_result = self._parse_harness_output(result, task.id)

            logger.info(f"Harness invocation complete for task {task.id}: success={execution_result.success}")
            return execution_result

        except Exception as e:
            logger.error(f"Harness invocation failed for task {task.id}: {e}", exc_info=True)
            # Return failed ExecutionResult rather than re-raising
            return ExecutionResult(
                success=False,
                session_id=None,
                completion_report=f"Harness invocation error: {str(e)}",
                cost_usd=0.0,
                num_turns=0,
                gate_results=[]
            )

    async def _ensure_repo_cloned(self, repo: RepoInfo, workdir: Path) -> None:
        """Ensure repository is cloned into the workdir.

        If the workdir already exists and contains a git repository,
        this is a no-op (supports rework scenarios). Otherwise, clones
        the repository fresh.

        Args:
            repo: Repository information (URL, branch)
            workdir: Target directory for repository

        Raises:
            subprocess.CalledProcessError: If git clone fails
        """
        if workdir.exists() and (workdir / ".git").exists():
            logger.debug(f"Repository already cloned in {workdir}")
            return

        logger.info(f"Cloning repository {repo.url} branch {repo.branch} to {workdir}")

        # Ensure parent directory exists
        workdir.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Use git clone with specific branch
            cmd = [
                "git", "clone",
                "--branch", repo.branch,
                "--single-branch",
                "--depth", "1",  # Shallow clone for efficiency
                repo.url,
                str(workdir)
            ]

            # Run git clone synchronously (quick operation)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,  # 1 minute timeout for clone
                check=True
            )

            logger.debug(f"Repository cloned successfully: {result.returncode}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Git clone failed: {e.stderr}")
            raise
        except subprocess.TimeoutExpired:
            logger.error("Git clone timed out after 60 seconds")
            raise

    async def _run_harness(self, prompt: str, workdir: Path, task_id: str) -> subprocess.CompletedProcess:
        """Run the AI harness as a subprocess.

        Builds the Claude Code CLI command and executes it with proper
        timeout and working directory settings.

        Args:
            prompt: Prompt text to send to the harness
            workdir: Working directory for harness execution
            task_id: Task ID for logging

        Returns:
            subprocess.CompletedProcess with stdout/stderr and exit code

        Raises:
            subprocess.TimeoutExpired: If harness exceeds task timeout
            FileNotFoundError: If claude CLI is not available
        """
        # Build claude command with required flags
        cmd = [
            "claude",
            "-p", prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions"
        ]

        # Add optional limits from config
        if self.config.max_turns > 0:
            cmd.extend(["--max-turns", str(self.config.max_turns)])

        logger.info(f"Starting harness for task {task_id} with timeout {self.config.task_timeout}s")
        logger.debug(f"Harness command: {' '.join(cmd)}")

        try:
            # Run harness as subprocess
            # Note: Using asyncio.create_subprocess_exec for async operation
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Wait with timeout
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.task_timeout
            )

            # Handle both bytes (real subprocess) and strings (mocked subprocess)
            if isinstance(stdout_bytes, bytes):
                stdout = stdout_bytes.decode('utf-8') if stdout_bytes else ''
            else:
                stdout = stdout_bytes or ''

            if isinstance(stderr_bytes, bytes):
                stderr = stderr_bytes.decode('utf-8') if stderr_bytes else ''
            else:
                stderr = stderr_bytes or ''

            # Create CompletedProcess-like object
            result = subprocess.CompletedProcess(
                args=cmd,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr
            )

            logger.info(f"Harness completed for task {task_id}: exit_code={result.returncode}")
            return result

        except asyncio.TimeoutError:
            # Kill the process and raise timeout
            logger.error(f"Harness timed out after {self.config.task_timeout}s for task {task_id}")
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            raise subprocess.TimeoutExpired(cmd, self.config.task_timeout)

    def _parse_harness_output(self, result: subprocess.CompletedProcess, task_id: str) -> ExecutionResult:
        """Parse harness subprocess output into ExecutionResult.

        Implements the three-level failure classification from vafi-DESIGN.md:
        1. Infrastructure failure (exit_code != 0)
        2. Harness error (is_error == true)
        3. Task failure (is_error == false but gates may fail later)

        Args:
            result: subprocess.CompletedProcess from harness execution
            task_id: Task ID for logging

        Returns:
            ExecutionResult with parsed data and success classification
        """
        logger.debug(f"Parsing harness output for task {task_id}")

        # Level 1: Infrastructure failure (exit code != 0)
        if result.returncode != 0:
            return self._handle_infrastructure_failure(result, task_id)

        # Try to parse JSON output
        try:
            output_data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse harness JSON output for task {task_id}: {e}")
            return ExecutionResult(
                success=False,
                session_id=None,
                completion_report=f"Invalid JSON output: {str(e)}\n\nRaw output:\n{result.stdout}",
                cost_usd=0.0,
                num_turns=0,
                gate_results=[]
            )

        # Level 2: Harness error (is_error == true)
        if output_data.get("is_error", False):
            logger.warning(f"Harness reported error for task {task_id}")
            return ExecutionResult(
                success=False,
                session_id=output_data.get("session_id"),
                completion_report=output_data.get("result", "Harness reported an error"),
                cost_usd=output_data.get("total_cost_usd", 0.0),
                num_turns=output_data.get("num_turns", 0),
                gate_results=[]
            )

        # Level 3: Success (gates will be run later by controller)
        logger.info(f"Harness completed successfully for task {task_id}")
        return ExecutionResult(
            success=True,
            session_id=output_data.get("session_id"),
            completion_report=output_data.get("result", "Task completed"),
            cost_usd=output_data.get("total_cost_usd", 0.0),
            num_turns=output_data.get("num_turns", 0),
            gate_results=[]  # Gates run separately by controller
        )

    def _handle_infrastructure_failure(
        self,
        result: subprocess.CompletedProcess,
        task_id: str
    ) -> ExecutionResult:
        """Handle infrastructure-level failures based on exit code and stderr.

        Classifies failures as auth, rate_limit, OOM, timeout, or unknown
        based on exit code and stderr patterns.

        Args:
            result: subprocess.CompletedProcess with non-zero exit code
            task_id: Task ID for logging

        Returns:
            ExecutionResult with failure classification
        """
        exit_code = result.returncode
        stderr = result.stderr.lower()

        # Classify error type based on exit code and stderr patterns
        if "authentication" in stderr or "unauthorized" in stderr:
            error_type = "auth"
        elif "rate limit" in stderr or "too many requests" in stderr:
            error_type = "rate_limit"
        elif "out of memory" in stderr or "memory" in stderr:
            error_type = "oom"
        elif exit_code == 124:  # Standard timeout exit code
            error_type = "timeout"
        else:
            error_type = "unknown"

        logger.error(f"Infrastructure failure for task {task_id}: {error_type} (exit_code={exit_code})")

        return ExecutionResult(
            success=False,
            session_id=None,
            completion_report=f"Infrastructure failure ({error_type}): {result.stderr}",
            cost_usd=0.0,
            num_turns=0,
            gate_results=[]
        )