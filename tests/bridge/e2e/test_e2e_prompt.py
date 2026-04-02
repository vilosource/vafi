"""E2E test: real prompt through deployed bridge with real Pi --mode rpc."""

import json
import os

import pytest


VTF_TOKEN = os.environ.get("VTF_TOKEN", "")
PROJECT_ID = os.environ.get("VTF_PROJECT_ID", "6udCSkejRVk0vO0k9dxaQ")


@pytest.mark.skipif(not VTF_TOKEN, reason="VTF_TOKEN not set")
class TestE2EPrompt:
    @pytest.mark.asyncio
    async def test_e2e_ephemeral_prompt(self, e2e_client):
        """AC-1: Send a real prompt, get a real Pi --mode rpc response."""
        resp = await e2e_client.post(
            "/v1/prompt",
            json={
                "message": "Reply with exactly one word: WORKING",
                "role": "assistant",
                "project": PROJECT_ID,
            },
            headers={"Authorization": f"Token {VTF_TOKEN}"},
            timeout=120,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["result"], "Expected non-empty result"
        assert data["session_id"], "Expected session_id"
        assert data["role"] == "assistant"
        assert data["is_error"] is False
        assert data["input_tokens"] >= 0
        assert data["output_tokens"] >= 0

    @pytest.mark.asyncio
    async def test_e2e_streaming_prompt(self, e2e_client):
        """AC-2: Stream a real prompt, receive NDJSON with agent_event, text_delta, result."""
        async with e2e_client.stream(
            "POST",
            "/v1/prompt/stream",
            json={
                "message": "Reply with exactly one word: STREAMING",
                "role": "assistant",
                "project": PROJECT_ID,
            },
            headers={"Authorization": f"Token {VTF_TOKEN}"},
            timeout=120,
        ) as resp:
            assert resp.status_code == 200
            assert "application/x-ndjson" in resp.headers.get("content-type", "")

            events = []
            async for line in resp.aiter_lines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))

        event_types = [e["type"] for e in events]
        assert "session_start" in event_types, f"Missing session_start. Got: {event_types}"
        assert "agent_event" in event_types, f"Missing agent_event. Got: {event_types}"
        assert "result" in event_types, f"Missing result. Got: {event_types}"
        assert event_types[-1] == "result"

        result_event = next(e for e in events if e["type"] == "result")
        assert result_event["result"], "Expected non-empty result text"
        assert result_event["input_tokens"] >= 0
        assert result_event["output_tokens"] >= 0
