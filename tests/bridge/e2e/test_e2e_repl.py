"""E2E test: REPL sync and streaming paths against deployed bridge."""

import json
import os

import httpx
import pytest

from tests.bridge.e2e.conftest import BRIDGE_URL


VTF_TOKEN = os.environ.get("VTF_TOKEN", "")
PROJECT_ID = os.environ.get("VTF_PROJECT_ID", "6udCSkejRVk0vO0k9dxaQ")


@pytest.mark.skipif(not VTF_TOKEN, reason="VTF_TOKEN not set")
class TestE2ERepl:
    @pytest.mark.asyncio
    async def test_repl_sync_path(self):
        headers = {"Authorization": f"Token {VTF_TOKEN}", "Content-Type": "application/json"}
        body = {"message": "Reply with exactly: REPL_SYNC_OK", "role": "assistant", "project": PROJECT_ID}

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{BRIDGE_URL}/v1/prompt", headers=headers, json=body)

        assert resp.status_code == 200
        data = resp.json()
        assert data["result"], "Expected non-empty result"
        assert data["is_error"] is False

    @pytest.mark.asyncio
    async def test_repl_stream_path(self):
        headers = {"Authorization": f"Token {VTF_TOKEN}", "Content-Type": "application/json"}
        body = {"message": "Reply with exactly: REPL_STREAM_OK", "role": "assistant", "project": PROJECT_ID}

        events = []
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", f"{BRIDGE_URL}/v1/prompt/stream", headers=headers, json=body) as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if line.strip():
                        events.append(json.loads(line))

        event_types = [e["type"] for e in events]
        assert "session_start" in event_types
        assert "agent_event" in event_types
        assert "result" in event_types
