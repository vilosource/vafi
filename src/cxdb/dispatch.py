"""Build dispatch prompts with prior attempt summaries and workplan context.

Pure function — no I/O. The controller calls this before invoking the harness.
"""

from __future__ import annotations

from typing import Any


def build_dispatch_prompt(
    spec: str,
    prior_summaries: list[dict[str, Any]],
    workplan_context: str,
) -> str:
    """Build a dispatch prompt enriched with prior attempt context.

    Args:
        spec: The task specification text.
        prior_summaries: List of execution_summary dicts from prior attempts.
        workplan_context: Accumulated key decisions from the workplan.

    Returns:
        The complete prompt string for the harness.
    """
    parts: list[str] = []

    # Workplan context (cross-task knowledge)
    if workplan_context:
        parts.append(workplan_context)
        parts.append("")

    # Prior attempt summaries
    if prior_summaries:
        parts.append(f"## Prior Attempts on This Task ({len(prior_summaries)} attempt{'s' if len(prior_summaries) > 1 else ''})")
        parts.append("")
        for summary in prior_summaries:
            attempt = summary.get("attempt", "?")
            parts.append(f"### Attempt {attempt}")
            nl = summary.get("nl_summary")
            if nl:
                parts.append(f"Outcome: {nl.get('one_liner', 'unknown')}")
                if nl.get("what_happened"):
                    parts.append(f"Approach: {nl['what_happened']}")
                if nl.get("key_decisions"):
                    parts.append(f"Decisions: {', '.join(nl['key_decisions'])}")
                if nl.get("if_failed"):
                    parts.append(f"Failure: {nl['if_failed']}")
            else:
                # Fall back to structured data when NL is not available (Phase A summaries)
                s = summary.get("structured", {})
                if s.get("files_modified"):
                    parts.append(f"Files modified: {', '.join(s['files_modified'])}")
                if s.get("tools_used"):
                    parts.append(f"Tools used: {', '.join(s['tools_used'])}")
                if s.get("duration_seconds"):
                    parts.append(f"Duration: {s['duration_seconds']}s")
            parts.append("")

    # Task spec
    parts.append(spec)

    return "\n".join(parts)
