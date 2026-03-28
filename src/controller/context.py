"""Task context file generation for agent communication.

Materializes vtf task state (spec, reviews, notes) into a markdown file
in the workdir. Agents read this file to understand the full task history
and what's expected of them.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def build_context(
    task_data: dict,
    notes: list[dict],
    reviews: list[dict],
    role: str = "executor",
) -> str:
    """Build the context markdown from vtf task data.

    Args:
        task_data: Task dict from vtf API (id, title, spec, test_command, etc.)
        notes: List of note dicts from vtf API
        reviews: List of review dicts from vtf API
        role: Agent role ("executor" or "judge") — affects the instruction

    Returns:
        Markdown string for .vafi/context.md
    """
    task_id = task_data.get("id", "unknown")
    title = task_data.get("title", "Untitled")
    spec = task_data.get("spec", "")
    test_command = task_data.get("test_command", {})

    lines = []
    lines.append(f"# Task: {title} ({task_id})")
    lines.append("")

    # Specification
    lines.append("## Specification")
    lines.append(spec if spec else "No specification provided.")
    lines.append("")

    # Test commands
    if test_command:
        lines.append("## Test Commands")
        if isinstance(test_command, dict):
            for key, cmd in test_command.items():
                lines.append(f"- **{key}**: `{cmd}`")
        else:
            lines.append(f"- `{test_command}`")
        lines.append("")

    # History — only include if there are reviews or agent notes
    agent_notes = [n for n in notes if not n.get("text", "").startswith("vafi:")]
    if reviews or agent_notes:
        lines.append("## History")
        lines.append("")

        # Interleave notes and reviews by timestamp
        events = []
        for note in agent_notes:
            events.append({
                "type": "note",
                "timestamp": note.get("created_at", ""),
                "actor": note.get("actor_id", "unknown"),
                "text": note.get("text", ""),
            })
        for review in reviews:
            events.append({
                "type": "review",
                "timestamp": review.get("created_at", ""),
                "actor": review.get("reviewer_id", "unknown"),
                "decision": review.get("decision", ""),
                "text": review.get("reason", ""),
            })

        events.sort(key=lambda e: e.get("timestamp", ""))

        for i, event in enumerate(events, 1):
            if event["type"] == "note":
                lines.append(f"### Note {i} — {event['actor']} ({event['timestamp'][:19]})")
                lines.append(f"> {event['text']}")
                lines.append("")
            elif event["type"] == "review":
                decision = event["decision"]
                lines.append(f"### Review {i} — {event['actor']} ({event['timestamp'][:19]})")
                lines.append(f"Decision: **{decision}**")
                if event["text"]:
                    lines.append(f"> {event['text']}")
                lines.append("")

    # Current instruction based on role and history
    lines.append("## Current Instruction")
    lines.append("")

    has_rejection = any(r.get("decision") == "changes_requested" for r in reviews)

    if role == "judge":
        lines.append("You are the **judge**. Verify the executor's implementation:")
        lines.append("1. Run the test commands")
        lines.append("2. Review the code against the specification")
        lines.append("3. Check all acceptance criteria")
        lines.append("4. Produce your verdict as JSON")
        if has_rejection:
            lines.append("")
            lines.append("This is a **re-review** after rework. Check that the previous rejection issues are resolved.")
    else:
        if has_rejection:
            lines.append("This is a **rework**. The previous implementation was rejected.")
            lines.append("Read the review feedback in the History section above and fix the issues.")
            lines.append("Do not reimplement from scratch — build on the existing code.")
        else:
            lines.append("Implement the task according to the specification above.")
    lines.append("")

    return "\n".join(lines)


def write_context(workdir: Path, content: str) -> None:
    """Write the context file to the workdir.

    Creates the .vafi/ directory if it doesn't exist.

    Args:
        workdir: Task workdir path
        content: Context markdown content
    """
    context_dir = workdir / ".vafi"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_path = context_dir / "context.md"
    context_path.write_text(content, encoding="utf-8")
    logger.info(f"Wrote context file to {context_path} ({len(content)} chars)")
