#!/usr/bin/env python3
"""Build Pi initial-context file: methodology + optional prior-session context.

Purpose:
    Produce a single file that Pi receives via --append-system-prompt on
    session launch. Always includes the role methodology. If the session
    directory contains prior Pi JSONL files, appends a summary of the most
    recent user/assistant exchanges.

Design note:
    Pi only honors the LAST --append-system-prompt flag (verified 2026-04-19
    in the Phase 8 spike). That's why methodology and prior-context must be
    merged into a single file rather than passed as two flags.

Exit codes:
    0 — success (output file written with methodology, with or without
        prior-context section)
    1 — error (methodology file missing or unreadable)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PRIOR_CONTEXT_HEADER = """---

# Continuation from previous sessions

This is a continuation of a prior conversation on this project. Do not
summarize this context back to the user unless asked. Treat it as
established shared knowledge.
"""


def _extract_text_content(content: list) -> str:
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


def parse_session_jsonl(path: Path) -> list[tuple[str, str, str]]:
    """Parse a Pi v3 session JSONL file.

    Returns a list of (timestamp, user_text, assistant_text) tuples, in
    chronological order within the file. Orphan user messages (no assistant
    reply) and assistant-only messages are skipped. Malformed JSON lines are
    skipped silently.
    """
    turns: list[tuple[str, str, str]] = []
    pending_user: tuple[str, str] | None = None  # (timestamp, text)

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
                if not isinstance(ev, dict) or ev.get("type") != "message":
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
                    turns.append((pending_user[0], pending_user[1], text))
                    pending_user = None
                # toolResult or assistant-without-text: ignore
    except (OSError, IOError):
        pass
    return turns


def collect_prior_turns(
    session_dir: Path,
    max_sessions: int,
) -> list[tuple[str, str, str]]:
    """Scan session_dir for Pi JSONL files, return turns across the N most recent."""
    if not session_dir.is_dir():
        return []
    jsonl_files = [p for p in session_dir.glob("*.jsonl") if p.is_file()]
    if not jsonl_files:
        return []
    jsonl_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    all_turns: list[tuple[str, str, str]] = []
    for jf in jsonl_files[:max_sessions]:
        all_turns.extend(parse_session_jsonl(jf))
    all_turns.sort(key=lambda t: t[0])  # chronological
    return all_turns


def format_prior_section(turns: list[tuple[str, str, str]]) -> str:
    """Format turn tuples as markdown. Empty list → empty string."""
    if not turns:
        return ""
    lines = [PRIOR_CONTEXT_HEADER]
    for ts, user, asst in turns:
        lines.append("")
        lines.append(f"## User ({ts})")
        lines.append(user)
        lines.append("")
        lines.append("## Assistant")
        lines.append(asst)
    return "\n".join(lines) + "\n"


def trim_to_byte_cap(
    turns: list[tuple[str, str, str]],
    max_bytes: int,
) -> list[tuple[str, str, str]]:
    """Drop oldest turns until the formatted section fits under max_bytes.

    If a single remaining turn still exceeds the cap, truncate its assistant
    text (not the user text — user intent is more load-bearing for context).
    """
    trimmed = list(turns)
    # Drop oldest turns while we have more than 1 and we're over cap.
    while len(trimmed) > 1 and len(format_prior_section(trimmed).encode()) > max_bytes:
        trimmed.pop(0)
    if not trimmed:
        return trimmed
    # Single turn still over cap: truncate assistant text (preserve user intent).
    if len(format_prior_section(trimmed).encode()) > max_bytes:
        ts, user, asst = trimmed[-1]
        while len(asst) > 20 and len(format_prior_section(trimmed[:-1] + [(ts, user, asst)]).encode()) > max_bytes:
            asst = asst[: max(20, len(asst) // 2)] + " [truncated]"
        trimmed = trimmed[:-1] + [(ts, user, asst)]
    return trimmed


def build(
    session_dir: Path,
    methodology: Path,
    max_bytes: int = 4096,
    max_prompts: int = 20,
    max_sessions: int = 5,
) -> str:
    """Build the full initial-context content (methodology + optional prior)."""
    methodology_text = methodology.read_text()
    turns = collect_prior_turns(session_dir, max_sessions)
    if turns:
        # Keep the most-recent max_prompts turns
        turns = turns[-max_prompts:]
        turns = trim_to_byte_cap(turns, max_bytes)
    prior_section = format_prior_section(turns)
    if prior_section:
        return methodology_text.rstrip() + "\n\n" + prior_section
    return methodology_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--methodology", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=4096)
    parser.add_argument("--max-prompts", type=int, default=20)
    parser.add_argument("--max-sessions", type=int, default=5)
    args = parser.parse_args(argv)

    if not args.methodology.is_file():
        print(f"[prior-ctx] ERROR: methodology file not found: {args.methodology}", file=sys.stderr)
        return 1

    content = build(
        session_dir=args.session_dir,
        methodology=args.methodology,
        max_bytes=args.max_bytes,
        max_prompts=args.max_prompts,
        max_sessions=args.max_sessions,
    )
    args.output.write_text(content)

    turns = collect_prior_turns(args.session_dir, args.max_sessions)
    print(
        f"[prior-ctx] wrote {len(content)} bytes to {args.output} "
        f"(methodology: {args.methodology.stat().st_size}B, "
        f"prior turns: {len(turns)})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
