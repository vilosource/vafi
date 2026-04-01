"""TDD tests for cxdb turn parser — RED phase."""

import json
from pathlib import Path

import pytest

from cxdb.models import ToolResultEvent, ToolUseEvent
from cxdb.parser import extract_tool_events, parse_turns

FIXTURES_DIR = Path.home() / "KB" / "viloforge" / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    """Load raw turns from a fixture file."""
    with open(FIXTURES_DIR / name) as f:
        data = json.load(f)
    return data["turns"]


class TestParseTurns:
    """parse_turns: raw cxdb turns → ParsedTurn list."""

    def test_filters_out_rewind_system_turns(self):
        raw = _load_fixture("cxdb-turns-start.json")
        parsed = parse_turns(raw)
        for t in parsed:
            if t.item_type == "system":
                kind = t.content.get("system", {}).get("kind")
                assert kind not in ("rewind", "request_parse_error", "response_parse_error")

    def test_preserves_session_start_and_end(self):
        raw = _load_fixture("cxdb-turns-start.json")
        parsed = parse_turns(raw)
        system_titles = [
            t.content.get("system", {}).get("title")
            for t in parsed
            if t.item_type == "system"
        ]
        assert "session_start" in system_titles

    def test_preserves_assistant_and_tool_result_turns(self):
        raw = _load_fixture("cxdb-turns-mid-tools.json")
        parsed = parse_turns(raw)
        item_types = {t.item_type for t in parsed}
        assert "assistant_turn" in item_types
        assert "tool_result" in item_types

    def test_extracts_timestamps(self):
        raw = _load_fixture("cxdb-turns-mid-tools.json")
        parsed = parse_turns(raw)
        for t in parsed:
            assert t.timestamp_ms > 0

    def test_preserves_turn_ids_and_depth(self):
        raw = _load_fixture("cxdb-turns-mid-tools.json")
        parsed = parse_turns(raw)
        for t in parsed:
            assert t.turn_id > 0
            assert t.depth >= 0


class TestExtractToolEvents:
    """extract_tool_events: ParsedTurn list → ToolUseEvent/ToolResultEvent list."""

    def test_extracts_tool_use_from_assistant_turn(self):
        raw = _load_fixture("cxdb-turns-mid-tools.json")
        parsed = parse_turns(raw)
        events = extract_tool_events(parsed)
        uses = [e for e in events if isinstance(e, ToolUseEvent)]
        assert len(uses) > 0
        assert all(e.tool_name in ("Read", "Edit", "Write", "Bash", "Grep", "Glob") for e in uses)

    def test_extracts_file_path_from_read_args(self):
        raw = _load_fixture("cxdb-turns-mid-tools.json")
        parsed = parse_turns(raw)
        events = extract_tool_events(parsed)
        reads = [e for e in events if isinstance(e, ToolUseEvent) and e.tool_name == "Read"]
        assert len(reads) > 0
        for r in reads:
            assert r.file_path is not None
            assert r.file_path.startswith("/")

    def test_extracts_tool_results_with_content(self):
        raw = _load_fixture("cxdb-turns-mid-tools.json")
        parsed = parse_turns(raw)
        events = extract_tool_events(parsed)
        results = [e for e in events if isinstance(e, ToolResultEvent)]
        assert len(results) > 0
        assert all(isinstance(e.content, str) for e in results)

    def test_extracts_bash_command_and_description(self):
        raw = _load_fixture("cxdb-turns-end.json")
        parsed = parse_turns(raw)
        events = extract_tool_events(parsed)
        bashes = [e for e in events if isinstance(e, ToolUseEvent) and e.tool_name == "Bash"]
        if bashes:
            assert bashes[0].command is not None

    def test_handles_malformed_args_gracefully(self):
        """Corrupt args JSON → skip tool, don't crash."""
        raw_turn = {
            "turn_id": 999,
            "depth": 1,
            "data": {
                "item_type": "assistant_turn",
                "timestamp": "2026-01-01T00:00:00Z",
                "turn": {
                    "tool_calls": [
                        {"name": "Read", "args": "NOT VALID JSON", "id": "x1"}
                    ],
                    "metrics": {"model": "claude-sonnet-4-6"},
                },
            },
        }
        parsed = parse_turns([raw_turn])
        events = extract_tool_events(parsed)
        # Should not crash — may produce event with file_path=None or skip entirely
        uses = [e for e in events if isinstance(e, ToolUseEvent)]
        for u in uses:
            # If it produced an event, file_path should be None (couldn't parse)
            if u.tool_name == "Read":
                assert u.file_path is None

    def test_pairs_tool_result_call_id_with_use(self):
        raw = _load_fixture("cxdb-turns-mid-tools.json")
        parsed = parse_turns(raw)
        events = extract_tool_events(parsed)
        uses = {e.call_id: e for e in events if isinstance(e, ToolUseEvent)}
        results = [e for e in events if isinstance(e, ToolResultEvent)]
        for r in results:
            assert r.call_id in uses, f"tool_result {r.call_id} has no matching tool_use"
