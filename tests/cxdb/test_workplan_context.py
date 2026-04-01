"""TDD tests for workplan context builder."""

import pytest

from cxdb.workplan_context import build_workplan_context


class FakeVtfClient:
    def __init__(self, tasks=None):
        self._tasks = tasks or []

    async def list_tasks_by_workplan(self, workplan_id: str) -> list[dict]:
        return self._tasks


class TestBuildWorkplanContext:
    @pytest.mark.asyncio
    async def test_builds_from_completed_tasks(self):
        vtf = FakeVtfClient(tasks=[
            {"title": "Auth endpoint", "status": "done", "execution_summary": {
                "nl_summary": {"key_decisions": ["Used python-jose for JWT"]}}},
            {"title": "Rate limiting", "status": "done", "execution_summary": {
                "nl_summary": {"key_decisions": ["Middleware at router level"]}}},
        ])
        context = await build_workplan_context(vtf, "wp1")
        assert "python-jose" in context
        assert "Middleware" in context

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_tasks(self):
        vtf = FakeVtfClient(tasks=[])
        context = await build_workplan_context(vtf, "wp1")
        assert context == ""

    @pytest.mark.asyncio
    async def test_skips_tasks_without_summaries(self):
        vtf = FakeVtfClient(tasks=[
            {"title": "No summary", "status": "done", "execution_summary": None},
            {"title": "Has summary", "status": "done", "execution_summary": {
                "nl_summary": {"key_decisions": ["Used Redis"]}}},
        ])
        context = await build_workplan_context(vtf, "wp1")
        assert "Redis" in context
        assert "No summary" not in context

    @pytest.mark.asyncio
    async def test_skips_tasks_without_nl_summary(self):
        """Phase A summaries have nl_summary=None."""
        vtf = FakeVtfClient(tasks=[
            {"title": "Phase A task", "status": "done", "execution_summary": {
                "nl_summary": None, "structured": {"files_modified": ["a.py"]}}},
        ])
        context = await build_workplan_context(vtf, "wp1")
        assert context == ""

    @pytest.mark.asyncio
    async def test_deduplicates_decisions(self):
        vtf = FakeVtfClient(tasks=[
            {"title": "T1", "status": "done", "execution_summary": {
                "nl_summary": {"key_decisions": ["Used python-jose"]}}},
            {"title": "T2", "status": "done", "execution_summary": {
                "nl_summary": {"key_decisions": ["Used python-jose"]}}},
        ])
        context = await build_workplan_context(vtf, "wp1")
        assert context.count("python-jose") == 1
