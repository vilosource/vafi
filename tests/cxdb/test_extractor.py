"""TDD tests for cxdb structured extractor."""

import json
from pathlib import Path

from cxdb.extractor import extract_structured
from cxdb.models import ToolResultEvent, ToolUseEvent
from cxdb.parser import extract_tool_events, parse_turns

FIXTURES_DIR = Path.home() / "KB" / "viloforge" / "fixtures"


def _load_events(name: str) -> list[ToolUseEvent | ToolResultEvent]:
    with open(FIXTURES_DIR / name) as f:
        data = json.load(f)
    parsed = parse_turns(data["turns"])
    return extract_tool_events(parsed)


def _load_parsed(name: str):
    with open(FIXTURES_DIR / name) as f:
        data = json.load(f)
    return parse_turns(data["turns"])


class TestExtractFilesModified:
    def test_deduplicates_edit_paths(self):
        events = [
            ToolUseEvent(1, "c1", "Edit", "/src/auth.py", None, None, 100),
            ToolUseEvent(2, "c2", "Edit", "/src/auth.py", None, None, 200),
            ToolUseEvent(3, "c3", "Write", "/tests/test_auth.py", None, None, 300),
        ]
        summary = extract_structured(events=events)
        assert summary.files_modified == ["/src/auth.py", "/tests/test_auth.py"]

    def test_read_only_files_not_in_modified(self):
        events = [
            ToolUseEvent(1, "c1", "Read", "/src/auth.py", None, None, 100),
        ]
        summary = extract_structured(events=events)
        assert summary.files_modified == []
        assert summary.files_read == ["/src/auth.py"]


class TestExtractTestResults:
    def test_parses_pytest_output(self):
        events = [
            ToolUseEvent(1, "c1", "Bash", None, "pytest tests/", "Run tests", 100),
            ToolResultEvent(2, "c1", "Bash", "12 passed, 1 failed in 3.2s", False, 200),
        ]
        summary = extract_structured(events=events)
        assert summary.tests is not None
        assert summary.tests.passed == 12
        assert summary.tests.failed == 1

    def test_parses_all_passed(self):
        events = [
            ToolResultEvent(1, "c1", "Bash", "8 passed in 1.5s", False, 100),
        ]
        summary = extract_structured(events=events)
        assert summary.tests is not None
        assert summary.tests.passed == 8
        assert summary.tests.failed == 0

    def test_no_test_output_returns_none(self):
        events = [
            ToolResultEvent(1, "c1", "Bash", "file created successfully", False, 100),
        ]
        summary = extract_structured(events=events)
        assert summary.tests is None


class TestExtractCommits:
    def test_parses_git_commit_output(self):
        events = [
            ToolResultEvent(1, "c1", "Bash", "[main a1b2c3d] Add OAuth2 login\n 2 files changed", False, 100),
        ]
        summary = extract_structured(events=events)
        assert len(summary.commits) == 1
        assert "a1b2c3d" in summary.commits[0]

    def test_no_commits_returns_empty(self):
        events = [
            ToolResultEvent(1, "c1", "Bash", "ok", False, 100),
        ]
        summary = extract_structured(events=events)
        assert summary.commits == []


class TestExtractDuration:
    def test_computes_from_first_last_timestamps(self):
        events = [
            ToolUseEvent(1, "c1", "Read", "/f", None, None, 1000000),
            ToolResultEvent(2, "c1", "Read", "...", False, 1230000),
        ]
        summary = extract_structured(events=events)
        assert summary.duration_seconds == 230


class TestExtractToolsUsed:
    def test_deduplicates(self):
        events = [
            ToolUseEvent(1, "c1", "Read", "/a", None, None, 100),
            ToolUseEvent(2, "c2", "Read", "/b", None, None, 200),
            ToolUseEvent(3, "c3", "Edit", "/a", None, None, 300),
        ]
        summary = extract_structured(events=events)
        assert sorted(summary.tools_used) == ["Edit", "Read"]


class TestExtractModel:
    def test_extracts_model_from_fixtures(self):
        parsed = _load_parsed("cxdb-turns-mid-tools.json")
        events = extract_tool_events(parsed)
        summary = extract_structured(events=events, parsed_turns=parsed)
        assert summary.model == "claude-sonnet-4-6"


class TestExtractFromFixtures:
    def test_mid_tools_fixture_extracts_files(self):
        events = _load_events("cxdb-turns-mid-tools.json")
        summary = extract_structured(events=events)
        assert len(summary.files_read) > 0  # Fixture has Read calls
        assert len(summary.tools_used) > 0
