"""TDD tests for the summarizer orchestrator."""

import json
from pathlib import Path

import pytest

from cxdb.summarizer import Summarizer, SummarizerConfig

FIXTURES_DIR = Path.home() / "KB" / "viloforge" / "fixtures"


def _load_fixture_turns(name: str) -> list[dict]:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)["turns"]


class FakeCxdbReader:
    def __init__(self, context_id=None, turns=None):
        self._context_id = context_id
        self._turns = turns or []

    async def find_context_by_task(self, task_id: str) -> int | None:
        return self._context_id

    async def get_turns(self, context_id: int) -> list[dict]:
        return self._turns


class ErrorCxdbReader:
    async def find_context_by_task(self, task_id: str) -> int | None:
        raise ConnectionError("cxdb unreachable")

    async def get_turns(self, context_id: int) -> list[dict]:
        raise ConnectionError("cxdb unreachable")


class FakeSummaryStore:
    def __init__(self):
        self.stored: dict[str, dict] = {}

    async def store_summary(self, task_id: str, summary: dict) -> None:
        self.stored[task_id] = summary


TEST_CONFIG = SummarizerConfig(cxdb_public_url="https://cxdb.dev.viloforge.com")


class TestSummarizeTask:
    @pytest.mark.asyncio
    async def test_stores_summary_in_vtf(self):
        turns = _load_fixture_turns("cxdb-turns-mid-tools.json")
        cxdb = FakeCxdbReader(context_id=59, turns=turns)
        store = FakeSummaryStore()
        summarizer = Summarizer(cxdb=cxdb, store=store, config=TEST_CONFIG)

        result = await summarizer.summarize_task("abc123")

        assert result is not None
        assert "abc123" in store.stored
        assert store.stored["abc123"]["cxdb_context_id"] == 59
        assert store.stored["abc123"]["trace_url"] == "https://cxdb.dev.viloforge.com/c/59"
        assert "structured" in store.stored["abc123"]

    @pytest.mark.asyncio
    async def test_structured_has_expected_fields(self):
        turns = _load_fixture_turns("cxdb-turns-mid-tools.json")
        cxdb = FakeCxdbReader(context_id=59, turns=turns)
        store = FakeSummaryStore()
        summarizer = Summarizer(cxdb=cxdb, store=store, config=TEST_CONFIG)

        result = await summarizer.summarize_task("abc123")
        s = result["structured"]

        assert "duration_seconds" in s
        assert "turn_count" in s
        assert "tools_used" in s
        assert "files_modified" in s
        assert "files_read" in s
        assert isinstance(s["tools_used"], list)

    @pytest.mark.asyncio
    async def test_returns_none_when_no_context(self):
        cxdb = FakeCxdbReader(context_id=None)
        store = FakeSummaryStore()
        summarizer = Summarizer(cxdb=cxdb, store=store, config=TEST_CONFIG)

        result = await summarizer.summarize_task("abc123")

        assert result is None
        assert "abc123" not in store.stored

    @pytest.mark.asyncio
    async def test_does_not_crash_on_cxdb_error(self):
        cxdb = ErrorCxdbReader()
        store = FakeSummaryStore()
        summarizer = Summarizer(cxdb=cxdb, store=store, config=TEST_CONFIG)

        result = await summarizer.summarize_task("abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_nl_summary_is_none_without_generator(self):
        turns = _load_fixture_turns("cxdb-turns-mid-tools.json")
        cxdb = FakeCxdbReader(context_id=59, turns=turns)
        store = FakeSummaryStore()
        summarizer = Summarizer(cxdb=cxdb, store=store, config=TEST_CONFIG)

        result = await summarizer.summarize_task("abc123")
        assert result["nl_summary"] is None

    @pytest.mark.asyncio
    async def test_summary_includes_attempt_field(self):
        turns = _load_fixture_turns("cxdb-turns-mid-tools.json")
        cxdb = FakeCxdbReader(context_id=59, turns=turns)
        store = FakeSummaryStore()
        summarizer = Summarizer(cxdb=cxdb, store=store, config=TEST_CONFIG)

        result = await summarizer.summarize_task("abc123")
        assert "attempt" in result
