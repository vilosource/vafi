"""Heartbeat mechanisms for vafi controller.

Two separate heartbeat concerns:
- agent_heartbeat_loop: Agent-level liveness signal (am I alive?). Runs always.
- heartbeat_loop: Task-level claim keepalive (am I still working on this task?).
  Runs only during task execution.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .worksources.protocol import WorkSource

logger = logging.getLogger(__name__)


async def agent_heartbeat_loop(
    work_source: "WorkSource",
    agent_id: str,
    interval_seconds: int,
) -> None:
    """Send periodic agent-level heartbeats to signal liveness.

    Runs as a background asyncio task for the lifetime of the controller.
    Independent of task execution — beats whether idle or busy.

    Args:
        work_source: WorkSource implementation for heartbeat calls
        agent_id: Agent ID to heartbeat for
        interval_seconds: Seconds between heartbeat calls
    """
    logger.info(f"Starting agent heartbeat loop (interval={interval_seconds}s)")

    try:
        while True:
            try:
                await work_source.agent_heartbeat(agent_id)
                logger.debug(f"Agent heartbeat sent for {agent_id}")
            except Exception as e:
                logger.warning(f"Agent heartbeat failed: {e}")

            await asyncio.sleep(interval_seconds)

    except asyncio.CancelledError:
        logger.info("Agent heartbeat loop stopped")
        raise


async def heartbeat_loop(work_source: "WorkSource", task_id: str, interval_seconds: int) -> None:
    """Send periodic heartbeats for a claimed task.

    Runs as an asyncio task concurrently with harness execution. Calls
    work_source.heartbeat(task_id) every interval_seconds to extend the
    claim timeout in vtf.

    Args:
        work_source: WorkSource implementation for heartbeat calls
        task_id: ID of the claimed task
        interval_seconds: Seconds between heartbeat calls

    The coroutine runs until cancelled via asyncio.CancelledError.
    Logs each heartbeat attempt and handles errors gracefully.
    """
    logger.info(f"Starting heartbeat loop for task {task_id} (interval={interval_seconds}s)")

    try:
        while True:
            await asyncio.sleep(interval_seconds)

            try:
                await work_source.heartbeat(task_id)
                logger.debug(f"Heartbeat sent for task {task_id}")
            except Exception as e:
                # Log heartbeat errors but don't crash the loop
                # The task execution should continue even if heartbeats fail
                logger.warning(f"Heartbeat failed for task {task_id}: {e}")

    except asyncio.CancelledError:
        logger.info(f"Heartbeat loop cancelled for task {task_id}")
        # Re-raise to properly handle cancellation
        raise