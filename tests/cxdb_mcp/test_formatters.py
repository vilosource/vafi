"""TDD tests for MCP turn formatters."""

from cxdb.models import ParsedTurn, ToolResultEvent, ToolUseEvent
from cxdb_mcp.formatters import apply_filters, format_breadcrumbs, format_turn


class TestFormatBreadcrumbs:
    def test_collapses_sequential_reads(self):
        events = [
            ToolUseEvent(1, "c1", "Read", "/a.py", None, None, 100),
            ToolUseEvent(2, "c2", "Read", "/b.py", None, None, 200),
            ToolUseEvent(3, "c3", "Read", "/c.py", None, None, 300),
        ]
        result = format_breadcrumbs(events)
        assert "Read 3 files" in result
        assert "a.py" in result

    def test_includes_bash_description(self):
        events = [
            ToolUseEvent(1, "c1", "Bash", None, "pytest tests/", "Run tests", 100),
        ]
        result = format_breadcrumbs(events)
        assert "Run tests" in result

    def test_includes_test_outcome(self):
        events = [
            ToolUseEvent(1, "c1", "Bash", None, "pytest", "Run tests", 100),
            ToolResultEvent(2, "c1", "Bash", "8 passed, 1 failed in 2.3s", False, 200),
        ]
        result = format_breadcrumbs(events)
        assert "8 passed" in result

    def test_shows_edit_files(self):
        events = [
            ToolUseEvent(1, "c1", "Edit", "/src/auth.py", None, None, 100),
            ToolUseEvent(2, "c2", "Edit", "/src/auth.py", None, None, 200),
        ]
        result = format_breadcrumbs(events)
        assert "auth.py" in result

    def test_shows_write_files(self):
        events = [
            ToolUseEvent(1, "c1", "Write", "/src/new_file.py", None, None, 100),
        ]
        result = format_breadcrumbs(events)
        assert "new_file.py" in result

    def test_empty_events_returns_empty(self):
        result = format_breadcrumbs([])
        assert result == ""


class TestFormatTurn:
    def test_truncates_large_content(self):
        event = ToolResultEvent(1, "c1", "Read", "x" * 10000, False, 100)
        formatted = format_turn(event, max_content=500)
        assert len(formatted["content"]) <= 503  # 500 + "..."

    def test_includes_tool_name_and_error(self):
        event = ToolResultEvent(1, "c1", "Bash", "command failed", True, 100)
        formatted = format_turn(event)
        assert formatted["tool_name"] == "Bash"
        assert formatted["is_error"] is True


class TestApplyFilters:
    def test_filter_by_tool_name(self):
        turns = [
            ParsedTurn(1, 1, 100, "assistant_turn", {"turn": {"tool_calls": [{"name": "Bash", "id": "c1", "args": "{}"}]}}),
            ParsedTurn(2, 2, 200, "assistant_turn", {"turn": {"tool_calls": [{"name": "Read", "id": "c2", "args": "{}"}]}}),
        ]
        filtered = apply_filters(turns, tool_name="Bash")
        assert len(filtered) == 1
        assert filtered[0].turn_id == 1

    def test_filter_by_content(self):
        turns = [
            ParsedTurn(1, 1, 100, "tool_result", {"tool_result": {"content": "FAILED assertion", "is_error": True, "call_id": "c1"}}),
            ParsedTurn(2, 2, 200, "tool_result", {"tool_result": {"content": "all good", "is_error": False, "call_id": "c2"}}),
        ]
        filtered = apply_filters(turns, content_contains="FAILED")
        assert len(filtered) == 1

    def test_filter_by_turn_range(self):
        turns = [
            ParsedTurn(1, 1, 100, "assistant_turn", {}),
            ParsedTurn(2, 5, 200, "assistant_turn", {}),
            ParsedTurn(3, 10, 300, "assistant_turn", {}),
        ]
        filtered = apply_filters(turns, from_depth=3, to_depth=8)
        assert len(filtered) == 1
        assert filtered[0].depth == 5

    def test_no_filters_returns_all(self):
        turns = [ParsedTurn(1, 1, 100, "a", {}), ParsedTurn(2, 2, 200, "b", {})]
        filtered = apply_filters(turns)
        assert len(filtered) == 2
