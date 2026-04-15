"""Shared Pi RPC protocol helpers.

Extracted to avoid duplication of the get_state handshake across
PodSession.initialize(), PiSession.run_ephemeral(), and PiSession.stream_ephemeral().
"""

import json
import logging
from typing import Any, Awaitable, Callable

from .pi_events import parse_pi_event

logger = logging.getLogger(__name__)

INIT_TIMEOUT = 15.0


async def pi_handshake(
    write_fn: Callable[[bytes], Awaitable[None]],
    read_fn: Callable[[], Awaitable[str | None]],
    timeout: float = INIT_TIMEOUT,
) -> str | None:
    """Send get_state to Pi and extract session ID.

    Args:
        write_fn: async callable that writes bytes to Pi's stdin.
        read_fn: async callable that returns the next JSONL line from Pi's
                 stdout, or None on EOF. Should handle its own timeout.
        timeout: not used directly (caller's read_fn should enforce it),
                 kept for documentation.

    Returns:
        Session ID string, or None if not available.
    """
    import asyncio

    cmd = json.dumps({"type": "get_state"}) + "\n"
    await write_fn(cmd.encode("utf-8"))

    while True:
        line = await read_fn()
        if line is None:
            break
        event = parse_pi_event(line)
        if event and event.type == "response" and event.data.get("command") == "get_state":
            session_id = event.data.get("data", {}).get("sessionId")
            logger.info(f"Pi handshake complete: session_id={session_id}")
            return session_id
        # Skip extension_ui_request and other init events

    return None
