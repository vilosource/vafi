"""vafi controller implementation.

The Controller class implements the core poll-claim-execute loop for vafi agents.
It polls for work, claims tasks, and logs what it would execute. This phase validates
the poll/claim cycle works end-to-end without harness invocation.
"""

import asyncio
import logging
import signal
from typing import TYPE_CHECKING

from .config import AgentConfig

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

            # Log that we would execute (harness not implemented)
            logger.info("Would execute (harness not implemented)")

            # Fail the task with "harness not implemented" reason
            await self.work_source.fail(task.id, "harness not implemented")
            logger.info(f"Failed task {task.id} - harness not ready")

        except Exception as e:
            logger.error(f"Error processing task {task.id}: {e}", exc_info=True)
            # Task claim might have succeeded, so try to fail it
            try:
                await self.work_source.fail(task.id, f"error during processing: {str(e)}")
            except Exception:
                logger.error(f"Failed to fail task {task.id}", exc_info=True)

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