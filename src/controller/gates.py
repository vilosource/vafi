"""Gate execution for vafi task verification.

Gates are shell commands that run after the harness completes to verify
task implementation. They use exit codes to determine success/failure,
following the design principle that controllers never parse LLM output.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import TaskInfo, GateResult

logger = logging.getLogger(__name__)


@dataclass
class GateConfig:
    """Configuration for a single verification gate."""
    name: str
    command: str
    required: bool = True


class GateRunner:
    """Executes verification gates after harness completion.

    Gates are shell commands run in the task workdir that verify the
    implementation is correct. Exit code 0 = pass, non-zero = fail.
    """

    def __init__(self, gates: list[GateConfig]):
        """Initialize the gate runner.

        Args:
            gates: List of gate configurations to execute
        """
        self.gates = gates

    async def run_gates(self, workdir: Path, task: TaskInfo) -> list[GateResult]:
        """Run all configured gates sequentially.

        Gates run in the task workdir and receive the working directory
        as their cwd. For MVP, gates are created from the task's test_command
        field if it exists.

        Args:
            workdir: Working directory for gate execution (task workdir)
            task: Task information for context

        Returns:
            List of GateResult objects with execution details
        """
        if not self.gates:
            logger.debug(f"No gates configured for task {task.id}")
            return []

        logger.info(f"Running {len(self.gates)} gates for task {task.id} in {workdir}")
        results = []

        for gate in self.gates:
            logger.info(f"Running gate '{gate.name}': {gate.command}")
            result = await self._run_single_gate(gate, workdir, task)
            results.append(result)

            if gate.required and not result.passed:
                logger.warning(f"Required gate '{gate.name}' failed for task {task.id}")
                # Continue running remaining gates for complete reporting

        passed_count = sum(1 for r in results if r.passed)
        logger.info(f"Gates complete for task {task.id}: {passed_count}/{len(results)} passed")

        return results

    async def _run_single_gate(self, gate: GateConfig, workdir: Path, task: TaskInfo) -> GateResult:
        """Execute a single gate as a subprocess.

        Runs the gate command in the workdir and captures exit code, stdout, stderr.
        Following the lesson from M2.5, we decode bytes manually rather than using
        text=True on asyncio.create_subprocess_exec.

        Args:
            gate: Gate configuration
            workdir: Working directory for execution
            task: Task info for logging

        Returns:
            GateResult with execution details
        """
        try:
            # Run gate command as subprocess
            # Use shell=True since commands might contain pipes, redirects, etc.
            process = await asyncio.create_subprocess_shell(
                gate.command,
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # Combine stderr with stdout
            )

            # Wait for completion and capture output
            stdout_bytes, _ = await process.communicate()

            # Decode bytes manually (learned from M2.5)
            stdout = stdout_bytes.decode('utf-8') if stdout_bytes else ''

            # Determine pass/fail based on exit code
            passed = process.returncode == 0

            logger.debug(f"Gate '{gate.name}' for task {task.id}: exit_code={process.returncode}, passed={passed}")

            return GateResult(
                name=gate.name,
                command=gate.command,
                exit_code=process.returncode,
                stdout=stdout,
                passed=passed
            )

        except Exception as e:
            logger.error(f"Gate '{gate.name}' execution failed for task {task.id}: {e}", exc_info=True)
            return GateResult(
                name=gate.name,
                command=gate.command,
                exit_code=-1,
                stdout=f"Gate execution error: {str(e)}",
                passed=False
            )

    @classmethod
    def from_task_command(cls, test_command: dict[str, Any]) -> "GateRunner":
        """Create a GateRunner from task test_command field.

        For MVP, create a single gate from the task spec's test_command.
        If test_command exists and has a "command" field, use it as a gate.

        Args:
            test_command: Test command dictionary from task spec

        Returns:
            GateRunner with gates based on test_command
        """
        gates = []

        if test_command and "command" in test_command:
            gate = GateConfig(
                name="task-test",
                command=test_command["command"],
                required=True
            )
            gates.append(gate)
            logger.debug(f"Created gate from test_command: {gate.command}")

        return cls(gates)