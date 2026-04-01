"""Async HTTP client for cxdb REST API.

Implements CxdbReader protocol. All I/O is here — parser and extractor are pure.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("cxdb.client")


class CxdbClient:
    """Read-only async client for cxdb REST API."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 10.0,
        http_client: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = http_client  # Injected for testing

    async def _get(self, path: str, **params: Any) -> dict:
        """GET request with error handling."""
        url = f"{self.base_url}{path}"
        if self._http:
            resp = await self._http.get(url, params=params, timeout=self.timeout)
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    async def find_context_by_task(self, task_id: str) -> int | None:
        """Find the most recent cxdb context_id for a vtf task.

        Searches by label 'task:{task_id}'. Returns the latest context
        if multiple exist (retries). Returns None if not found.
        """
        try:
            data = await self._get("/v1/contexts", limit="100")
        except Exception as e:
            logger.warning(f"Failed to query cxdb contexts: {e}")
            return None

        label = f"task:{task_id}"
        matches: list[tuple[int, int]] = []  # (created_at_ms, context_id)

        for ctx in data.get("contexts", []):
            if label in ctx.get("labels", []):
                matches.append((
                    ctx.get("created_at_unix_ms", 0),
                    ctx["context_id"],
                ))

        if not matches:
            return None

        # Return the most recent
        matches.sort(reverse=True)
        return matches[0][1]

    async def get_turns(self, context_id: int, limit: int = 500) -> list[dict]:
        """Fetch all turns for a context, paginating if needed.

        Returns turns in ascending depth order.
        """
        all_turns: list[dict] = []

        try:
            # First page
            data = await self._get(f"/v1/contexts/{context_id}/turns", limit=str(limit))
            all_turns.extend(data.get("turns", []))

            # Paginate if there are more
            while data.get("next_before_turn_id"):
                data = await self._get(
                    f"/v1/contexts/{context_id}/turns",
                    limit=str(limit),
                    before_turn_id=str(data["next_before_turn_id"]),
                )
                all_turns.extend(data.get("turns", []))

        except Exception as e:
            logger.warning(f"Failed to fetch turns for context {context_id}: {e}")

        return all_turns

    async def list_contexts(self, limit: int = 50) -> list[dict]:
        """List all contexts."""
        try:
            data = await self._get("/v1/contexts", limit=str(limit))
            return data.get("contexts", [])
        except Exception as e:
            logger.warning(f"Failed to list contexts: {e}")
            return []
