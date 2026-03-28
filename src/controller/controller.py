"""vafi controller implementation.

The Controller class implements the core poll-claim-execute loop for vafi agents.
It polls for work, claims tasks, executes them via harness invocation, and reports results.
"""

import asyncio
import logging
import signal
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from .config import AgentConfig
from .context import build_context, write_context
from .gates import GateRunner
from .heartbeat import agent_heartbeat_loop, heartbeat_loop
from .invoker import HarnessInvoker
from .types import ExecutionResult

if TYPE_CHECKING:
    from .worksources.protocol import WorkSource

logger = logging.getLogger(__name__)


class Controller:
    """Core controller that implements the vtf task execution loop.

    The controller depends only on the WorkSource protocol, not on VtfClient
    directly. This allows different work sources to be swapped in without
    changing controller logic.
    """

    def __init__(self, work_source: "WorkSource", config: AgentConfig):
        """Initialize the controller.

        Args:
            work_source: WorkSource implementation for task operations
            config: Agent configuration including tags and intervals
        """
        self.work_source = work_source
        self.config = config
        self._shutdown = asyncio.Event()
        self._agent_info = None
        self._invoker = HarnessInvoker(config)

    async def run(self) -> None:
        """Main controller loop.

        Registers with the work source, then starts the agent heartbeat loop
        and polls for work. The agent heartbeat runs continuously (every 30s)
        to signal liveness to vtf. On shutdown, marks the agent offline.
        """
        # Set up signal handlers for graceful shutdown
        self._setup_signal_handlers()

        agent_hb_task = None

        try:
            # Register with work source
            logger.info("Registering agent with work source...")
            self._agent_info = await self.work_source.register(
                name=self.config.agent_id or f"{self.config.agent_role}-default",
                tags=self.config.agent_tags
            )
            logger.info(f"Registered as agent {self._agent_info.id}")

            # Start agent-level heartbeat loop (runs always, independent of tasks)
            agent_hb_task = asyncio.create_task(
                agent_heartbeat_loop(
                    self.work_source,
                    self._agent_info.id,
                    self.config.poll_interval,
                )
            )
            logger.info("Started agent heartbeat loop")

            # Main polling loop
            logger.info("Starting poll loop...")
            while not self._shutdown.is_set():
                try:
                    await self._poll_and_process()
                except Exception as e:
                    logger.error(f"Error in poll loop: {e}", exc_info=True)
                    # Continue loop on errors - don't crash on transient failures

                # Wait for poll interval or shutdown signal
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=self.config.poll_interval
                    )
                    break  # Shutdown requested
                except asyncio.TimeoutError:
                    continue  # Normal polling interval

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Fatal error in controller: {e}", exc_info=True)
        finally:
            # Stop agent heartbeat loop
            if agent_hb_task is not None:
                agent_hb_task.cancel()
                try:
                    await agent_hb_task
                except asyncio.CancelledError:
                    pass

            # Signal offline to vtf
            if self._agent_info:
                try:
                    await self.work_source.set_agent_offline(self._agent_info.id)
                    logger.info(f"Agent {self._agent_info.id} marked offline")
                except Exception as e:
                    logger.warning(f"Failed to mark agent offline: {e}")

            logger.info("Shutting down controller")

    async def _poll_and_process(self) -> None:
        """Poll for work and process a single task if available."""
        if not self._agent_info:
            logger.warning("No agent registration - skipping poll")
            return

        if self.config.agent_role == "judge":
            await self._poll_and_review()
        else:
            await self._poll_and_execute()

    async def _poll_and_execute(self) -> None:
        """Executor: poll for tasks, execute, and report."""
        logger.debug(f"Polling for work (agent_id={self._agent_info.id}, tags={self.config.agent_tags})")
        task = await self.work_source.poll(self._agent_info.id, self.config.agent_tags)

        if task is None:
            logger.debug("No work available")
            return

        logger.info(f"Found task {task.id}: {task.title}")

        try:
            # Claim the task
            logger.info(f"Claiming task {task.id}")
            claimed_task = await self.work_source.claim(task.id, self._agent_info.id)
            logger.info(f"Claimed task {claimed_task.id}: {claimed_task.title}")

            # Log task details
            self._log_task_details(claimed_task)

            # Execute the task
            result = await self.execute(claimed_task)

            # Link execution trace from cxdb (best-effort)
            await self._post_trace_note(task.id)

            # Report result
            if result.success:
                await self.work_source.complete(task.id, result)
                logger.info(f"Completed task {task.id}")
            else:
                # Prepare failure reason with gate output if gates failed
                failure_reason = result.completion_report
                if result.gate_results:
                    failed_gates = [g for g in result.gate_results if not g.passed]
                    if failed_gates:
                        gate_output = "\n\nGate failures:\n"
                        for gate in failed_gates:
                            gate_output += f"Gate '{gate.name}' failed (exit_code={gate.exit_code}):\n{gate.stdout}\n"
                        failure_reason += gate_output

                await self.work_source.fail(task.id, failure_reason)
                logger.info(f"Failed task {task.id}: {failure_reason}")

        except Exception as e:
            logger.error(f"Error processing task {task.id}: {e}", exc_info=True)
            try:
                await self.work_source.fail(task.id, f"error during processing: {str(e)}")
            except Exception:
                logger.error(f"Failed to fail task {task.id}", exc_info=True)

    async def _poll_and_review(self) -> None:
        """Judge: poll for tasks pending review, verify, and submit verdict.

        Unlike executors, judges do not claim tasks. They find a task in
        pending_completion_review, run verification in the shared workdir,
        and submit a review. The review submission handles state transitions.
        """
        logger.debug(f"Polling for reviews (agent_id={self._agent_info.id})")
        task = await self.work_source.poll_reviews(self._agent_info.id)

        if task is None:
            logger.debug("No reviews pending")
            return

        logger.info(f"Found task to review {task.id}: {task.title}")

        try:
            self._log_task_details(task)

            # Execute judge harness (no claim — judge runs in shared workdir)
            result = await self.execute(task)

            # Link execution trace from cxdb (best-effort)
            await self._post_trace_note(task.id)

            # Parse verdict from harness output
            verdict = self._parse_verdict(result.completion_report)

            # Submit review
            await self.work_source.submit_review(
                task.id,
                verdict["decision"],
                verdict["reason"],
                self._agent_info.id,
            )
            logger.info(f"Submitted review for task {task.id}: {verdict['decision']}")

        except Exception as e:
            logger.error(f"Error reviewing task {task.id}: {e}", exc_info=True)
            # Try to add a note about the failure
            try:
                await self.work_source.add_note(
                    task.id, f"Judge error: {str(e)}", "controller"
                )
            except Exception:
                logger.error(f"Failed to post judge error note for task {task.id}", exc_info=True)

    def _parse_verdict(self, completion_report: str) -> dict:
        """Parse judge verdict from harness output.

        Extracts JSON verdict from the completion report. Falls back to
        changes_requested if parsing fails.
        """
        import json

        # Try to find JSON in the output
        try:
            # The harness may wrap the result — try direct parse first
            verdict = json.loads(completion_report)
            if "decision" in verdict:
                return verdict
        except (json.JSONDecodeError, TypeError):
            pass

        # Try to find JSON block in the text
        import re
        json_match = re.search(r'\{[^{}]*"decision"[^{}]*\}', completion_report, re.DOTALL)
        if json_match:
            try:
                verdict = json.loads(json_match.group())
                if "decision" in verdict:
                    return verdict
            except json.JSONDecodeError:
                pass

        # Fallback: could not parse verdict
        logger.warning("Could not parse judge verdict from output, defaulting to changes_requested")
        return {
            "decision": "changes_requested",
            "reason": f"Judge output could not be parsed as verdict. Raw output: {completion_report[:500]}",
        }

    async def execute(self, task) -> ExecutionResult:
        """Execute a task using the harness invoker and run verification gates.

        Implementation follows the M2.6 specification with M2.7 heartbeat:
        1. Start heartbeat coroutine concurrently with execution
        2. Invoke harness (already done in M2.5)
        3. If harness succeeded (is_error=false, exit code 0):
           a. Run gates
           b. All gates pass → success=True
           c. Any gate fails → success=False
        4. If harness failed:
           a. Return failure without running gates
        5. Cancel heartbeat task and await clean shutdown

        Args:
            task: TaskInfo object with task details

        Returns:
            ExecutionResult with success status, execution details, and gate results
        """
        # Start heartbeat coroutine before beginning execution
        heartbeat_task = asyncio.create_task(
            heartbeat_loop(self.work_source, task.id, self.config.heartbeat_interval)
        )
        logger.debug(f"Started heartbeat task for task {task.id}")

        try:
            # Create workdir based on task ID
            workdir = Path(self.config.sessions_dir) / f"task-{task.id}"
            logger.info(f"Creating workdir for task {task.id}: {workdir}")

            # Get repo info from work source
            repo_info = await self.work_source.get_repo_info(task.project_id)

            # Clone repo first (must happen before writing context file)
            await self._invoker._ensure_repo_cloned(repo_info, workdir)

            # Write context file into the cloned workdir
            await self._write_task_context(task, workdir)

            # Build prompt — points agent to the context file
            if self.config.agent_role == "judge":
                prompt = f"Verify task {task.title} ({task.id}). Read .vafi/context.md for the full specification and history."
            else:
                prompt = f"Work on task {task.title} ({task.id}). Read .vafi/context.md for the full specification and history."

            # Invoke harness (clone is no-op since repo already cloned above)
            result = await self._invoker.invoke(task, repo_info, workdir, prompt)

            # If harness failed, return without running gates
            if not result.success:
                logger.info(f"Harness failed for task {task.id}, skipping gates")
                return result

            # Harness succeeded - run gates
            logger.info(f"Harness succeeded for task {task.id}, running gates")
            gate_runner = GateRunner.from_task_command(task.test_command)
            gate_results = await gate_runner.run_gates(workdir, task)

            # Determine overall success based on gate results
            # All required gates must pass for task success
            all_required_gates_passed = True
            for gate_result in gate_results:
                # For MVP, all gates created from test_command are required
                if not gate_result.passed:
                    all_required_gates_passed = False
                    logger.warning(f"Gate '{gate_result.name}' failed for task {task.id}")

            # Create final result with gate information
            final_result = ExecutionResult(
                success=all_required_gates_passed,
                session_id=result.session_id,
                completion_report=result.completion_report,
                cost_usd=result.cost_usd,
                num_turns=result.num_turns,
                gate_results=gate_results
            )

            if final_result.success:
                logger.info(f"Task {task.id} completed successfully with all gates passing")
            else:
                logger.info(f"Task {task.id} failed due to gate failures")

            return final_result

        except Exception as e:
            logger.error(f"Task execution failed for {task.id}: {e}", exc_info=True)
            return ExecutionResult(
                success=False,
                session_id=None,
                completion_report=f"Execution failed: {str(e)}",
                cost_usd=0.0,
                num_turns=0,
                gate_results=[]
            )

        finally:
            # Always cancel heartbeat task and wait for clean shutdown
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                # Expected when we cancelled the task
                logger.debug(f"Heartbeat task cancelled cleanly for task {task.id}")
            except Exception as e:
                # Unexpected error in heartbeat cleanup
                logger.warning(f"Error during heartbeat cleanup for task {task.id}: {e}")

    async def _write_task_context(self, task, workdir: Path) -> None:
        """Fetch task history from vtf and write context file to workdir."""
        try:
            ctx = await self.work_source.get_task_context(task.id)
            task_data = ctx["task"]
            notes = ctx["notes"]
            reviews = task_data.get("reviews", []) or []

            content = build_context(
                task_data=task_data,
                notes=notes,
                reviews=reviews,
                role=self.config.agent_role,
            )
            write_context(workdir, content)

        except Exception as e:
            logger.warning(f"Failed to write context file for task {task.id}: {e}")
            # Non-fatal — agent can still work with just the prompt

    def _log_task_details(self, task) -> None:
        """Log detailed information about a claimed task."""
        logger.info("=== Task Details ===")
        logger.info(f"ID: {task.id}")
        logger.info(f"Title: {task.title}")
        logger.info(f"Project: {task.project_id}")
        logger.info(f"Needs Review: {task.needs_review}")
        logger.info(f"Assigned To: {task.assigned_to}")
        if task.test_command:
            logger.info(f"Test Command: {task.test_command}")
        logger.info("--- Spec ---")
        for i, line in enumerate(task.spec.split('\n'), 1):
            logger.info(f"{i:3}: {line}")
        logger.info("=== End Task Details ===")

    async def _post_trace_note(self, task_id: str) -> None:
        """Look up the cxdb context for a task and post its URL as a vtf note."""
        if not self.config.cxdb_url:
            return

        try:
            context_id = await self._lookup_cxdb_context(task_id)
            if context_id is not None:
                base = self.config.cxdb_public_url or self.config.cxdb_url
                trace_url = f"{base}/c/{context_id}"
                await self.work_source.add_note(
                    task_id, f"vafi:trace_url={trace_url}", "controller"
                )
                logger.info(f"Posted trace link for task {task_id}: {trace_url}")
            else:
                logger.debug(f"No cxdb context found for task {task_id}")
        except Exception as e:
            logger.warning(f"Failed to post trace note for task {task_id}: {e}")

    async def _lookup_cxdb_context(self, task_id: str) -> int | None:
        """Query cxdb for a context matching task:<task_id> label."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.config.cxdb_url}/v1/contexts",
                params={"limit": "50"},
                timeout=5.0,
            )
            response.raise_for_status()
            data = response.json()
            label = f"task:{task_id}"
            for ctx in data.get("contexts", []):
                if label in ctx.get("labels", []):
                    return ctx["context_id"]
        return None

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown")
            self._shutdown.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)