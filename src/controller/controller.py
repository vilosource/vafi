"""vafi controller implementation.

The Controller class implements the core poll-claim-execute loop for vafi agents.
It polls for work, claims tasks, executes them via harness invocation, and reports results.
"""

import asyncio
import logging
import signal
from pathlib import Path
from typing import TYPE_CHECKING

from .config import AgentConfig
from .invoker import HarnessInvoker
from .prompt import load_template, render_prompt
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

        Registers with the work source, then polls for work, claims tasks,
        and logs what would be executed. Handles graceful shutdown.
        """
        # Set up signal handlers for graceful shutdown
        self._setup_signal_handlers()

        try:
            # Register with work source
            logger.info("Registering agent with work source...")
            self._agent_info = await self.work_source.register(
                name=self.config.agent_id or f"{self.config.agent_role}-default",
                tags=self.config.agent_tags
            )
            logger.info(f"Registered as agent {self._agent_info.id}")

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
            logger.info("Shutting down controller")

    async def _poll_and_process(self) -> None:
        """Poll for work and process a single task if available."""
        if not self._agent_info:
            logger.warning("No agent registration - skipping poll")
            return

        # Poll for work (rework priority, then claimable)
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

            # Report result
            if result.success:
                await self.work_source.complete(task.id)
                logger.info(f"Completed task {task.id}")
            else:
                await self.work_source.fail(task.id, result.completion_report)
                logger.info(f"Failed task {task.id}: {result.completion_report}")

        except Exception as e:
            logger.error(f"Error processing task {task.id}: {e}", exc_info=True)
            # Task claim might have succeeded, so try to fail it
            try:
                await self.work_source.fail(task.id, f"error during processing: {str(e)}")
            except Exception:
                logger.error(f"Failed to fail task {task.id}", exc_info=True)

    async def execute(self, task) -> ExecutionResult:
        """Execute a task using the harness invoker.

        Creates a workdir, gets repo info, builds prompt, and invokes harness.

        Args:
            task: TaskInfo object with task details

        Returns:
            ExecutionResult with success status and execution details
        """
        try:
            # Create workdir based on task ID
            workdir = Path(self.config.sessions_dir) / f"task-{task.id}"
            logger.info(f"Creating workdir for task {task.id}: {workdir}")

            # Get repo info from work source
            repo_info = await self.work_source.get_repo_info(task.project_id)

            # Load and render prompt template
            template_path = Path("/opt/vf-agent/templates/task.txt")
            # Fallback to local path if container path doesn't exist
            if not template_path.exists():
                template_path = Path(__file__).parent.parent.parent / "templates" / "task.txt"

            template = load_template(template_path)
            prompt = render_prompt(template, task)

            # Invoke harness
            result = await self._invoker.invoke(task, repo_info, workdir, prompt)

            return result

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

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown")
            self._shutdown.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)