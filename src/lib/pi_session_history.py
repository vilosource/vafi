"""Pi session JSONL parser — shared between agent-pod scripts and the bridge.

Extracted from images/agent/build_prior_context.py so the bridge's Phase 9
history endpoint can use the same parsing logic as the in-pod prior-context
builder. One parser, one source of truth for "what does a Pi conversation
look like."

Pure functions. No I/O beyond opening files. No network, no side effects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

# A turn is a (timestamp_iso, user_text, assistant_text, session_id) tuple.
# session_id is the Pi session id (from the JSONL `session` event), used by
# the Phase 9 history endpoint to look up `user` via vtf SessionRecord.
Turn = tuple[str, str, str, str]


def _extract_text_content(content: Iterable) -> str:
    """Extract only text parts from a message.content list (skip toolCall, toolResult)."""
    if not isinstance(content, list):
        return ""
    parts = []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            t = c.get("text", "")
            if isinstance(t, str) and t.strip():
                parts.append(t)
    return "\n".join(parts).strip()


def parse_session_jsonl(path: Path) -> list[Turn]:
    """Parse a Pi v3 session JSONL file.

    Returns a list of (timestamp, user_text, assistant_text, session_id) tuples
    in chronological order. Orphan messages (user without reply, assistant
    without preceding user) are discarded. Malformed JSON lines are skipped.
    The session_id is extracted from the file's `session` event — every turn
    in the file shares the same session_id.
    """
    turns: list[Turn] = []
    pending_user: tuple[str, str] | None = None
    session_id = ""

    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict):
                    continue
                etype = ev.get("type")
                if etype == "session":
                    session_id = ev.get("id", "") or session_id
                    continue
                if etype != "message":
                    continue
                msg = ev.get("message")
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                text = _extract_text_content(msg.get("content", []))
                if not text:
                    continue
                ts = ev.get("timestamp", "")
                if role == "user":
                    pending_user = (ts, text)
                elif role == "assistant" and pending_user is not None:
                    turns.append((pending_user[0], pending_user[1], text, session_id))
                    pending_user = None
    except (OSError, IOError):
        pass
    return turns


def collect_prior_turns(
    session_dir: Path,
    max_sessions: int = 5,
) -> list[Turn]:
    """Scan session_dir for Pi JSONL files, return turns across the N most recent (chronological)."""
    if not session_dir.is_dir():
        return []
    jsonl_files = [p for p in session_dir.glob("*.jsonl") if p.is_file()]
    if not jsonl_files:
        return []
    jsonl_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    all_turns: list[Turn] = []
    for jf in jsonl_files[:max_sessions]:
        all_turns.extend(parse_session_jsonl(jf))
    all_turns.sort(key=lambda t: t[0])
    return all_turns


def apply_age_cap(turns: list[Turn], now_iso: str, max_age_days: int | None) -> list[Turn]:
    """Drop turns older than max_age_days relative to now_iso. None / 0 = no cap."""
    if not max_age_days or max_age_days <= 0:
        return turns
    # Lightweight comparison on ISO-8601 timestamps — works because they're
    # lexicographically sortable. Compute cutoff by string manipulation so
    # we don't pull in datetime parsing for this simple case.
    from datetime import datetime, timedelta, timezone

    try:
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except ValueError:
        now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=max_age_days)).isoformat()
    return [t for t in turns if t[0] >= cutoff]
