"""Extract structured summary fields from parsed cxdb events.

Pure functions — no I/O, no LLM. Regex-based extraction for test results and commits.
"""

from __future__ import annotations

import re

from .models import ParsedTurn, StructuredSummary, TestResult, ToolResultEvent, ToolUseEvent

# Tools that modify files
_WRITE_TOOLS = frozenset({"Edit", "Write"})

# Regex patterns for test result extraction
_PYTEST_PATTERN = re.compile(r"(\d+) passed(?:,\s*(\d+) failed)?")
_PYTEST_FAILED_ONLY = re.compile(r"(\d+) failed")

# Regex for git commit output: [branch hash] message
_COMMIT_PATTERN = re.compile(r"\[[\w/.-]+ ([a-f0-9]{7,})\] (.+)")


def extract_structured(
    events: list[ToolUseEvent | ToolResultEvent],
    parsed_turns: list[ParsedTurn] | None = None,
) -> StructuredSummary:
    """Extract all structured fields from tool events.

    Args:
        events: Tool use and result events from the parser.
        parsed_turns: Optional full parsed turns for model extraction.
    """
    tools_used: list[str] = []
    files_modified: list[str] = []
    files_read: list[str] = []
    seen_tools: set[str] = set()
    seen_modified: set[str] = set()
    seen_read: set[str] = set()
    tests: TestResult | None = None
    commits: list[str] = []
    model = ""

    # Extract model from parsed turns (assistant_turn metrics)
    if parsed_turns:
        for t in parsed_turns:
            if t.item_type == "assistant_turn":
                m = t.content.get("turn", {}).get("metrics", {}).get("model", "")
                if m:
                    model = m
                    break

    # Collect timestamps for duration
    timestamps: list[int] = []

    for event in events:
        timestamps.append(event.timestamp_ms)

        if isinstance(event, ToolUseEvent):
            if event.tool_name not in seen_tools:
                seen_tools.add(event.tool_name)
                tools_used.append(event.tool_name)

            if event.file_path:
                if event.tool_name in _WRITE_TOOLS:
                    if event.file_path not in seen_modified:
                        seen_modified.add(event.file_path)
                        files_modified.append(event.file_path)
                elif event.tool_name == "Read":
                    if event.file_path not in seen_read:
                        seen_read.add(event.file_path)
                        files_read.append(event.file_path)

        elif isinstance(event, ToolResultEvent):
            if event.tool_name == "Bash" and not event.is_error:
                # Check for test results
                test_result = _extract_test_result(event.content)
                if test_result is not None:
                    tests = test_result  # Last test run wins

                # Check for git commits
                commit = _extract_commit(event.content)
                if commit:
                    commits.append(commit)

    # Duration from first to last timestamp
    duration = 0
    if len(timestamps) >= 2:
        duration = (max(timestamps) - min(timestamps)) // 1000

    return StructuredSummary(
        duration_seconds=duration,
        turn_count=len(events),
        model=model,
        tools_used=tools_used,
        files_modified=files_modified,
        files_read=files_read,
        tests=tests,
        commits=commits,
    )


def _extract_test_result(output: str) -> TestResult | None:
    """Parse pytest-style output for pass/fail counts."""
    match = _PYTEST_PATTERN.search(output)
    if match:
        passed = int(match.group(1))
        failed = int(match.group(2)) if match.group(2) else 0
        # Try to find the command from nearby context
        return TestResult(passed=passed, failed=failed, command="pytest")

    # Check for failed-only pattern
    match = _PYTEST_FAILED_ONLY.search(output)
    if match:
        return TestResult(passed=0, failed=int(match.group(1)), command="pytest")

    return None


def _extract_commit(output: str) -> str | None:
    """Parse git commit output for hash and message."""
    match = _COMMIT_PATTERN.search(output)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return None
