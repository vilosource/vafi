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


class TestJudgeVerdictWriteFailLoud:
    """R3b — the controller must not silently swallow a review-path failure.

    Per I2 (controller fail-loud obligation) the judge, on any unrecoverable
    error reviewing a task, must drive it pending_completion_review ->
    needs_attention via work_source.fail() rather than leaving it stranded
    for R3's server-side expire_stale_reviews reaper to eventually catch.
    """

    def setup_method(self):
        self.config = AgentConfig(agent_role="judge", vtf_api_url="http://test:8000")
        self.mock_ws = AsyncMock()
        self.controller = Controller(work_source=self.mock_ws, config=self.config)
        self.controller._agent_info = MagicMock(id="judge-1")
        task = MagicMock(id="task-1", title="t")
        self.mock_ws.poll_reviews.return_value = task
        # Patch the harness so the review path runs without a real invoker.
        self.controller._post_trace_note = AsyncMock()
        self.controller._log_task_details = MagicMock()

    def _good_result(self):
        return MagicMock(completion_report=json.dumps(
            {"decision": "approved", "reason": "ok"}))

    @pytest.mark.asyncio
    async def test_verdict_write_failure_escalates_to_needs_attention(self):
        """submit_review failing must NOT be swallowed — escalate via fail()."""
        self.controller.execute = AsyncMock(return_value=self._good_result())
        self.mock_ws.submit_review.side_effect = RuntimeError("vtf 500")

        await self.controller._poll_and_review()

        self.mock_ws.fail.assert_awaited_once()
        assert self.mock_ws.fail.await_args.args[0] == "task-1"

    @pytest.mark.asyncio
    async def test_judge_harness_failure_escalates_to_needs_attention(self):
        """A harness/parse failure also strands the task — escalate."""
        self.controller.execute = AsyncMock(side_effect=RuntimeError("harness died"))

        await self.controller._poll_and_review()

        self.mock_ws.submit_review.assert_not_awaited()
        self.mock_ws.fail.assert_awaited_once()
        assert self.mock_ws.fail.await_args.args[0] == "task-1"

    @pytest.mark.asyncio
    async def test_escalation_failure_is_logged_not_raised(self):
        """If fail() also fails (vtf down), the server reaper backstops —
        the controller logs but never lets the exception propagate."""
        self.controller.execute = AsyncMock(return_value=self._good_result())
        self.mock_ws.submit_review.side_effect = RuntimeError("vtf 500")
        self.mock_ws.fail.side_effect = RuntimeError("vtf still down")

        # Must not raise.
        await self.controller._poll_and_review()
        self.mock_ws.fail.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_successful_review_does_not_escalate(self):
        """Happy path: a recorded verdict must never trigger fail()."""
        self.controller.execute = AsyncMock(return_value=self._good_result())

        await self.controller._poll_and_review()

        self.mock_ws.submit_review.assert_awaited_once()
        self.mock_ws.fail.assert_not_awaited()
