"""Pi RPC event parsing."""

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class PiEvent:
    type: str
    data: dict[str, Any]


def parse_pi_event(line: str) -> PiEvent | None:
    """Parse a single JSONL line from Pi's --mode json output."""
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
        return PiEvent(type=data.get("type", "unknown"), data=data)
    except json.JSONDecodeError:
        return None
