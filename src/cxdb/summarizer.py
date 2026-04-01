"""Summarizer orchestrator — composes cxdb reader, parser, extractor, and store.

Depends on abstractions (protocols), not concrete implementations.
Phase A: structured extraction only (nl_generator is None).
Phase B: adds NL summary via injected generator (OCP — no modification to this code).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from .extractor import extract_structured
from .parser import extract_tool_events, parse_turns

logger = logging.getLogger("cxdb.summarizer")


class CxdbReader(Protocol):
    async def find_context_by_task(self, task_id: str) -> int | None: ...
    async def get_turns(self, context_id: int) -> list[dict]: ...


class SummaryStore(Protocol):
    async def store_summary(self, task_id: str, summary: dict) -> None: ...


class NLGenerator(Protocol):
    async def generate(
        self,
        structured: Any,
        last_turns: list[Any],
        outcome: str,
        judge_feedback: str | None,
    ) -> dict | None: ...


@dataclass
class SummarizerConfig:
    cxdb_public_url: str = ""


class Summarizer:
    """Orchestrates: find context → fetch turns → parse → extract → store.

    Composes CxdbReader + SummaryStore + optional NLGenerator via constructor injection.
    """

    def __init__(
        self,
        cxdb: CxdbReader,
        store: SummaryStore,
        config: SummarizerConfig,
        nl_generator: NLGenerator | None = None,
    ) -> None:
        self._cxdb = cxdb
        self._store = store
        self._config = config
        self._nl_generator = nl_generator

    async def summarize_task(
        self,
        task_id: str,
        outcome: str = "",
        judge_feedback: str | None = None,
    ) -> dict | None:
        """Find cxdb context for task, extract summary, store in vtf.

        Returns the summary dict, or None if no context found or on error.
        """
        try:
            return await self._do_summarize(task_id, outcome, judge_feedback)
        except Exception as e:
            logger.warning(f"Summarization failed for task {task_id}: {e}")
            return None

    async def _do_summarize(
        self,
        task_id: str,
        outcome: str,
        judge_feedback: str | None,
    ) -> dict | None:
        # 1. Find context
        context_id = await self._cxdb.find_context_by_task(task_id)
        if context_id is None:
            logger.debug(f"No cxdb context found for task {task_id}")
            return None

        # 2. Fetch turns
        raw_turns = await self._cxdb.get_turns(context_id)

        # 3. Parse
        parsed = parse_turns(raw_turns)
        tool_events = extract_tool_events(parsed)

        # 4. Extract structured fields
        structured = extract_structured(events=tool_events, parsed_turns=parsed)

        # 5. NL summary (Phase B — None in Phase A)
        nl_summary = None
        if self._nl_generator is not None:
            last_turns = parsed[-10:] if parsed else []
            nl_summary = await self._nl_generator.generate(
                structured, last_turns, outcome, judge_feedback,
            )

        # 6. Build summary
        trace_url = f"{self._config.cxdb_public_url}/c/{context_id}"
        summary: dict[str, Any] = {
            "cxdb_context_id": context_id,
            "trace_url": trace_url,
            "attempt": 1,  # TODO: determine from vtf task history
            "structured": asdict(structured),
            "nl_summary": nl_summary,
        }

        # 7. Store
        await self._store.store_summary(task_id, summary)

        logger.info(f"Stored summary for task {task_id} (context={context_id})")
        return summary
