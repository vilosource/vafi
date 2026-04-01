"""Immutable data models for cxdb turn parsing and summary extraction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedTurn:
    """A meaningful turn from a cxdb session, noise filtered out."""

    turn_id: int
    depth: int
    timestamp_ms: int
    item_type: str  # "user_input", "assistant_turn", "tool_result", "system"
    content: dict


@dataclass(frozen=True)
class ToolUseEvent:
    """An agent invoking a tool (Read, Edit, Bash, etc.)."""

    turn_id: int
    call_id: str
    tool_name: str
    file_path: str | None  # Extracted from args for Read/Edit/Write
    command: str | None  # Extracted from args for Bash
    description: str | None  # Extracted from args for Bash
    timestamp_ms: int


@dataclass(frozen=True)
class ToolResultEvent:
    """The result of a tool invocation, paired with ToolUseEvent via call_id."""

    turn_id: int
    call_id: str
    tool_name: str | None  # Resolved by pairing with ToolUseEvent
    content: str
    is_error: bool
    timestamp_ms: int


@dataclass(frozen=True)
class TestResult:
    """Parsed test execution outcome from Bash output."""

    passed: int
    failed: int
    command: str


@dataclass(frozen=True)
class StructuredSummary:
    """Structured extraction from a cxdb session — no LLM needed."""

    duration_seconds: int
    turn_count: int
    model: str
    tools_used: list[str]
    files_modified: list[str]
    files_read: list[str]
    tests: TestResult | None
    commits: list[str]
