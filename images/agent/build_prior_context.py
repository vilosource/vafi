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

Parser logic lives in src/lib/pi_session_history.py so the bridge's Phase 9
history endpoint can use the same implementation.

Exit codes:
    0 — success (output file written with methodology, with or without
        prior-context section)
    1 — error (methodology file missing or unreadable)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make src/lib importable whether we're installed as a package or run from
# /opt/vf-agent inside the pi-agent pod (where src/lib lives at /opt/vf-agent/src/lib).
_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE.parent / "src", _HERE / "src"):
    if (_candidate / "lib" / "pi_session_history.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

from lib.pi_session_history import (  # noqa: E402
    Turn,
    apply_age_cap,
    collect_prior_turns,
)

PRIOR_CONTEXT_HEADER = """---

# Continuation from previous sessions

This is a continuation of a prior conversation on this project. Do not
summarize this context back to the user unless asked. Treat it as
established shared knowledge.
"""


def format_prior_section(turns: list[Turn]) -> str:
    """Format turn tuples as markdown. Empty list → empty string."""
    if not turns:
        return ""
    lines = [PRIOR_CONTEXT_HEADER]
    for ts, user, asst, _sid in turns:
        lines.append("")
        lines.append(f"## User ({ts})")
        lines.append(user)
        lines.append("")
        lines.append("## Assistant")
        lines.append(asst)
    return "\n".join(lines) + "\n"


def trim_to_byte_cap(
    turns: list[Turn],
    max_bytes: int,
) -> list[Turn]:
    """Drop oldest turns until formatted section fits under max_bytes.

    If a single remaining turn still exceeds the cap, truncate its assistant
    text (preserving user intent).
    """
    trimmed = list(turns)
    while len(trimmed) > 1 and len(format_prior_section(trimmed).encode()) > max_bytes:
        trimmed.pop(0)
    if not trimmed:
        return trimmed
    if len(format_prior_section(trimmed).encode()) > max_bytes:
        ts, user, asst, sid = trimmed[-1]
        while len(asst) > 20 and len(format_prior_section(trimmed[:-1] + [(ts, user, asst, sid)]).encode()) > max_bytes:
            asst = asst[: max(20, len(asst) // 2)] + " [truncated]"
        trimmed = trimmed[:-1] + [(ts, user, asst, sid)]
    return trimmed


def build(
    session_dir: Path,
    methodology: Path,
    max_bytes: int = 4096,
    max_prompts: int = 20,
    max_sessions: int = 5,
    max_age_days: int | None = 14,
) -> str:
    """Build the full initial-context content (methodology + optional prior)."""
    methodology_text = methodology.read_text()
    turns = collect_prior_turns(session_dir, max_sessions)
    if turns:
        turns = apply_age_cap(turns, datetime.now(timezone.utc).isoformat(), max_age_days)
        turns = turns[-max_prompts:]
        turns = trim_to_byte_cap(turns, max_bytes)
    prior_section = format_prior_section(turns)
    if prior_section:
        return methodology_text.rstrip() + "\n\n" + prior_section
    return methodology_text


# Re-export parse_session_jsonl for backwards-compat with the existing tests.
# The tests import `bpc.parse_session_jsonl` / `bpc.collect_prior_turns` etc.
from lib.pi_session_history import (  # noqa: E402, F401
    collect_prior_turns,
    parse_session_jsonl,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--methodology", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=4096)
    parser.add_argument("--max-prompts", type=int, default=20)
    parser.add_argument("--max-sessions", type=int, default=5)
    parser.add_argument("--max-age-days", type=int, default=14,
                        help="Drop turns older than this many days. 0 disables.")
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
        max_age_days=args.max_age_days,
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
