"""Tests for bridge prompt endpoints."""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import ASGITransport, AsyncClient

from bridge.app import create_app
from bridge.pi_session import PiSession


def _mock_user(user_id=1, projects=None):
    return {
        "user_id": user_id, "username": "testuser", "user_type": "human",
        "is_staff": False,
        "projects": projects or [{"project_id": "proj-1", "role": "member"}],
    }


def _mock_pi_result(text="Done", session_id="sess-1", input_tokens=54, output_tokens=5):
    return {
        "session_id": session_id, "text": text,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": 0.001, "num_turns": 1, "tool_uses": [],
    }


ROLES_YAML = """
roles:
  assistant:
    session_type: ephemeral
    harness: pi-rpc
    model: claude-sonnet-4-20250514
    thinking_level: low
    methodology: ""
    mcp_tools: [vtf]
    description: Quick operations
  architect:
    session_type: locked
    harness: pi-rpc
    model: claude-sonnet-4-20250514
    thinking_level: medium
    methodology: /opt/vf-agent/methodologies/architect.md
    mcp_tools: [vtf, cxdb]
    description: Planning
"""


@pytest.fixture
def roles_file(tmp_path):
    f = tmp_path / "roles.yaml"
    f.write_text(ROLES_YAML)
    return str(f)


@pytest.fixture
def app(roles_file):
    return create_app(roles_config=roles_file)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestPromptEndpoint:
    @pytest.mark.asyncio
    async def test_prompt_returns_bridge_response(self, client):
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()), \
             patch.object(PiSession, "run_ephemeral", new_callable=AsyncMock, return_value=_mock_pi_result()):
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "assistant", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["result"] == "Done"
            assert data["session_id"] == "sess-1"
            assert data["input_tokens"] == 54
            assert data["output_tokens"] == 5
            assert data["is_error"] is False

    @pytest.mark.asyncio
    async def test_prompt_unknown_role_returns_400(self, client):
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "nonexistent", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_prompt_project_required(self, client):
        """Design: project is always required."""
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "assistant"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 422 or resp.status_code == 400

    @pytest.mark.asyncio
    async def test_prompt_locked_role_without_lock_returns_409(self, client):
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "architect", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_prompt_timeout_returns_504(self, client):
        """Design: agent timeout returns 504, not 200 with is_error."""
        timeout_result = {**_mock_pi_result(), "error": "Pi process timed out"}
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()), \
             patch.object(PiSession, "run_ephemeral", new_callable=AsyncMock, return_value=timeout_result):
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "assistant", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 504

    @pytest.mark.asyncio
    async def test_prompt_concurrent_limit(self, client):
        """More than MAX_CONCURRENT_EPHEMERAL returns 503."""
        async def slow_run(*args, **kwargs):
            await asyncio.sleep(2)
            return _mock_pi_result()

        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()), \
             patch.object(PiSession, "run_ephemeral", side_effect=slow_run):
            tasks = [
                client.post(
                    "/v1/prompt",
                    json={"message": "hello", "role": "assistant", "project": "proj-1"},
                    headers={"Authorization": "Token valid"},
                )
                for _ in range(6)
            ]
            results = await asyncio.gather(*tasks)
            statuses = [r.status_code for r in results]
            assert 503 in statuses
            assert 200 in statuses

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(self, client):
        """Design: 10 prompts/min per user, 11th returns 429."""
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()), \
             patch.object(PiSession, "run_ephemeral", new_callable=AsyncMock, return_value=_mock_pi_result()):
            for i in range(10):
                resp = await client.post(
                    "/v1/prompt",
                    json={"message": f"msg-{i}", "role": "assistant", "project": "proj-1"},
                    headers={"Authorization": "Token valid"},
                )
                assert resp.status_code == 200, f"Request {i} failed with {resp.status_code}"

            # 11th should be rate limited
            resp = await client.post(
                "/v1/prompt",
                json={"message": "msg-11", "role": "assistant", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 429
            assert "retry-after" in resp.headers


class TestStreamingEndpoint:
    @pytest.mark.asyncio
    async def test_stream_returns_ndjson(self, client):
        PI_EVENTS = [
            '{"type":"session","id":"sess-stream","version":3}',
            json.dumps({"type":"message_update","assistantMessageEvent":{"type":"text_delta","contentIndex":0,"delta":"Hi"},"message":{"content":[{"type":"text","text":"Hi"}]}}),
            json.dumps({"type":"turn_end","message":{"role":"assistant"},"toolResults":[]}),
            json.dumps({"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"Hi"}],"usage":{"input":50,"output":5,"totalTokens":55,"cost":{"total":0}}}]}),
        ]

        async def fake_stream(prompt, env=None):
            for line in PI_EVENTS:
                yield line

        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()), \
             patch.object(PiSession, "stream_ephemeral", side_effect=fake_stream):
            resp = await client.post(
                "/v1/prompt/stream",
                json={"message": "hi", "role": "assistant", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 200
            assert "application/x-ndjson" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_stream_has_agent_event_type(self, client):
        """Design: emit agent_event for every Pi event (rich clients)."""
        PI_EVENTS = [
            '{"type":"session","id":"s1","version":3}',
            json.dumps({"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"ok"}],"usage":{"input":10,"output":2,"totalTokens":12,"cost":{"total":0}}}]}),
        ]

        async def fake_stream(prompt, env=None):
            for line in PI_EVENTS:
                yield line

        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()), \
             patch.object(PiSession, "stream_ephemeral", side_effect=fake_stream):
            resp = await client.post(
                "/v1/prompt/stream",
                json={"message": "hi", "role": "assistant", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            events = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
            agent_events = [e for e in events if e["type"] == "agent_event"]
            assert len(agent_events) > 0, "Must emit agent_event for raw Pi events"

    @pytest.mark.asyncio
    async def test_stream_error_event(self, client):
        """Design: emit error event on failure."""
        async def failing_stream(prompt, env=None):
            yield json.dumps({"type": "error", "message": "Pi crashed"})

        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()), \
             patch("bridge.pi_session.PiSession.stream_ephemeral", side_effect=failing_stream):
            resp = await client.post(
                "/v1/prompt/stream",
                json={"message": "hi", "role": "assistant", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            events = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
            error_events = [e for e in events if e["type"] == "error"]
            assert len(error_events) > 0
