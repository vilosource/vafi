"""NL summary generation via Anthropic Haiku API.

Implements the NLGenerator protocol. Converts structured extraction + last turns
into a human-readable summary with one_liner, what_happened, key_decisions, if_failed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from .models import ParsedTurn, StructuredSummary

logger = logging.getLogger("cxdb.nl_summary")

_PROMPT_TEMPLATE = """You are summarizing an AI agent's execution of a coding task. Given the structured data and conversation excerpt below, generate a JSON object with these fields:

1. "one_liner": Single sentence under 80 characters summarizing the outcome
2. "what_happened": One paragraph describing what the agent did
3. "key_decisions": List of non-obvious technical choices the agent made (empty list if none)
4. "if_failed": If the task failed, describe what went wrong. null if succeeded.

Structured execution data:
{structured_json}

Task outcome: {outcome}
{judge_section}
{turns_section}

Respond with ONLY a JSON object, no markdown fences or extra text."""


class HaikuNLGenerator:
    """Generates NL summaries by calling the Anthropic Haiku API."""

    def __init__(
        self,
        http_client: Any,
        base_url: str,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._http = http_client
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    async def generate(
        self,
        structured: StructuredSummary,
        last_turns: list[ParsedTurn],
        outcome: str,
        judge_feedback: str | None,
    ) -> dict | None:
        """Generate NL summary fields. Returns dict or None on failure."""
        try:
            return await self._do_generate(structured, last_turns, outcome, judge_feedback)
        except Exception as e:
            logger.warning(f"NL summary generation failed: {e}")
            return None

    async def _do_generate(
        self,
        structured: StructuredSummary,
        last_turns: list[ParsedTurn],
        outcome: str,
        judge_feedback: str | None,
    ) -> dict | None:
        # Build prompt
        structured_json = json.dumps(asdict(structured), indent=2)

        judge_section = ""
        if judge_feedback:
            judge_section = f"Judge feedback: {judge_feedback}"

        turns_section = ""
        if last_turns:
            turn_texts = []
            for t in last_turns[-10:]:
                if t.item_type == "assistant_turn":
                    text = t.content.get("turn", {}).get("text", "")
                    if text:
                        turn_texts.append(f"Assistant: {text[:500]}")
                elif t.item_type == "tool_result":
                    tr = t.content.get("tool_result", {})
                    content = tr.get("content", "")[:300]
                    turn_texts.append(f"Tool result: {content}")
            if turn_texts:
                turns_section = "Last conversation turns:\n" + "\n".join(turn_texts)

        prompt = _PROMPT_TEMPLATE.format(
            structured_json=structured_json,
            outcome=outcome,
            judge_section=judge_section,
            turns_section=turns_section,
        )

        # Call API
        url = f"{self._base_url}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": self._model,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        }

        resp = await self._http.post(url, headers=headers, json=body, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Haiku API returned {resp.status_code}")
            return None

        data = resp.json()
        text = data["content"][0]["text"]

        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Parse JSON response
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Haiku returned invalid JSON: {text[:200]}")
            return None

        # Validate required fields
        required = {"one_liner", "what_happened", "key_decisions", "if_failed"}
        if not required.issubset(result.keys()):
            logger.warning(f"Haiku response missing fields: {required - result.keys()}")
            return None

        return result
