"""Heartbeat mechanism for vafi task execution.

The heartbeat coroutine runs concurrently with harness execution to keep
task claims alive in vtf by periodically calling the heartbeat API.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .worksources.protocol import WorkSource

logger = logging.getLogger(__name__)


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