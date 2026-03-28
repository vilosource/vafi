"""Tests for judge-specific controller behavior."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.controller.controller import Controller
from src.controller.config import AgentConfig


class TestParseVerdict:
    def setup_method(self):
        self.config = AgentConfig(agent_role="judge")
        mock_ws = MagicMock()
        self.controller = Controller(work_source=mock_ws, config=self.config)

    def test_parses_valid_json_verdict(self):
        report = json.dumps({"decision": "approved", "reason": "All tests pass"})
        verdict = self.controller._parse_verdict(report)
        assert verdict["decision"] == "approved"
        assert verdict["reason"] == "All tests pass"

    def test_parses_changes_requested(self):
        report = json.dumps({"decision": "changes_requested", "reason": "Missing edge case"})
        verdict = self.controller._parse_verdict(report)
        assert verdict["decision"] == "changes_requested"

    def test_extracts_json_from_text(self):
        report = 'Here is my verdict:\n{"decision": "approved", "reason": "Looks good"}\nEnd of review.'
        verdict = self.controller._parse_verdict(report)
        assert verdict["decision"] == "approved"

    def test_fallback_on_unparseable_output(self):
        report = "I think the code looks fine but I cannot produce JSON"
        verdict = self.controller._parse_verdict(report)
        assert verdict["decision"] == "changes_requested"
        assert "could not be parsed" in verdict["reason"].lower()

    def test_fallback_on_empty_output(self):
        verdict = self.controller._parse_verdict("")
        assert verdict["decision"] == "changes_requested"

    def test_fallback_on_json_without_decision(self):
        report = json.dumps({"result": "pass", "notes": "all good"})
        verdict = self.controller._parse_verdict(report)
        assert verdict["decision"] == "changes_requested"


class TestJudgePollAndReview:
    """Test the judge poll path dispatches correctly."""

    def setup_method(self):
        self.config = AgentConfig(agent_role="judge", vtf_api_url="http://test:8000")
        self.mock_ws = AsyncMock()
        self.controller = Controller(work_source=self.mock_ws, config=self.config)

    @pytest.mark.asyncio
    async def test_poll_and_process_calls_review_for_judge(self):
        """When role is judge, _poll_and_process should call _poll_and_review."""
        self.controller._agent_info = MagicMock(id="judge-1")
        self.mock_ws.poll_reviews.return_value = None

        await self.controller._poll_and_process()

        self.mock_ws.poll_reviews.assert_called_once_with("judge-1")
        self.mock_ws.poll.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_and_process_calls_execute_for_executor(self):
        """When role is executor, _poll_and_process should call _poll_and_execute."""
        self.config.agent_role = "executor"
        self.controller._agent_info = MagicMock(id="exec-1")
        self.mock_ws.poll.return_value = None

        await self.controller._poll_and_process()

        self.mock_ws.poll.assert_called_once()
        self.mock_ws.poll_reviews.assert_not_called()
