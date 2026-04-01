"""Parse raw cxdb turns into typed events.

Pure functions — no I/O, no side effects. Handles malformed data gracefully.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .models import ParsedTurn, ToolResultEvent, ToolUseEvent

logger = logging.getLogger("cxdb.parser")

# System turn kinds that are noise — not meaningful for summarization
_NOISE_KINDS = frozenset({"rewind", "request_parse_error", "response_parse_error"})

# Tools that operate on files — extract file_path from their args
_FILE_TOOLS = frozenset({"Read", "Edit", "Write"})


def parse_turns(raw_turns: list[dict]) -> list[ParsedTurn]:
    """Convert raw cxdb turn dicts into ParsedTurn objects, filtering noise.

    Filters out system turns with noisy kinds (rewind, parse errors).
    """
    result: list[ParsedTurn] = []
    for raw in raw_turns:
        data = raw.get("data", {})
        item_type = data.get("item_type", "")

        # Filter system noise
        if item_type == "system":
            kind = data.get("system", {}).get("kind", "")
            if kind in _NOISE_KINDS:
                continue

        timestamp_ms = _parse_timestamp(data.get("timestamp", ""))

        result.append(ParsedTurn(
            turn_id=raw.get("turn_id", 0),
            depth=raw.get("depth", 0),
            timestamp_ms=timestamp_ms,
            item_type=item_type,
            content=data,
        ))
    return result


def extract_tool_events(
    parsed_turns: list[ParsedTurn],
) -> list[ToolUseEvent | ToolResultEvent]:
    """Extract tool use and result events from parsed turns.

    Pairs tool_result.call_id with tool_use.call_id to resolve tool names on results.
    """
    events: list[ToolUseEvent | ToolResultEvent] = []
    call_id_to_tool: dict[str, str] = {}

    for turn in parsed_turns:
        if turn.item_type == "assistant_turn":
            tool_calls = turn.content.get("turn", {}).get("tool_calls", [])
            for tc in tool_calls:
                call_id = tc.get("id", "")
                tool_name = tc.get("name", "")
                call_id_to_tool[call_id] = tool_name

                file_path, command, description = _parse_tool_args(tool_name, tc.get("args", ""))

                events.append(ToolUseEvent(
                    turn_id=turn.turn_id,
                    call_id=call_id,
                    tool_name=tool_name,
                    file_path=file_path,
                    command=command,
                    description=description,
                    timestamp_ms=turn.timestamp_ms,
                ))

        elif turn.item_type == "tool_result":
            tr = turn.content.get("tool_result", {})
            call_id = tr.get("call_id", "")
            events.append(ToolResultEvent(
                turn_id=turn.turn_id,
                call_id=call_id,
                tool_name=call_id_to_tool.get(call_id),
                content=tr.get("content", ""),
                is_error=tr.get("is_error", False),
                timestamp_ms=turn.timestamp_ms,
            ))

    return events


def _parse_tool_args(tool_name: str, args_raw: str) -> tuple[str | None, str | None, str | None]:
    """Parse the double-encoded JSON args from a tool_call.

    Returns (file_path, command, description). All may be None if parsing fails.
    """
    if not args_raw:
        return None, None, None

    try:
        # args is a JSON string — sometimes with a leading {} prefix (observed in data)
        cleaned = args_raw
        if cleaned.startswith("{}"):
            cleaned = cleaned[2:]
        args = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        logger.debug(f"Failed to parse args for {tool_name}: {args_raw[:100]}")
        return None, None, None

    file_path = args.get("file_path") if tool_name in _FILE_TOOLS else None
    command = args.get("command") if tool_name == "Bash" else None
    description = args.get("description") if tool_name == "Bash" else None

    return file_path, command, description


def _parse_timestamp(ts_str: str) -> int:
    """Parse ISO 8601 timestamp to unix milliseconds."""
    if not ts_str:
        return 0
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return 0
