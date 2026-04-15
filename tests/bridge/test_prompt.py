"""Tests for bridge prompt endpoints."""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import ASGITransport, AsyncClient

from bridge.app import create_app
from bridge.pi_session import PiSession
from bridge.pod_process import PodProcessManager, PodSession


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


def _mock_pod_session():
    """Create a mocked PodSession for locked streaming tests."""
    session = MagicMock(spec=PodSession)
    session.session_id = "mock-locked-sess"
    session.is_alive = True
    session.initialize = AsyncMock()
    session.send_prompt = AsyncMock()
    session.stream_prompt = AsyncMock()
    session.shutdown = AsyncMock()
    return session


class TestLockedStreamingEndpoint:
    """Tests for POST /v1/prompt/stream with locked (architect) role."""

    @pytest.fixture(autouse=True)
    def mock_pod_creation(self):
        """Mock pod creation for locked streaming tests."""
        mock_session = _mock_pod_session()
        with patch.object(PodProcessManager, "create_and_exec", new_callable=AsyncMock, return_value=MagicMock()), \
             patch("bridge.app.PodSession", return_value=mock_session):
            yield mock_session

    @pytest.mark.asyncio
    async def test_locked_stream_result_on_message_stop(self, client, mock_pod_creation):
        """Locked stream: message(stopReason=stop) → result event with text and usage."""
        PI_EVENTS = [
            json.dumps({"type": "session", "id": "locked-sess", "version": 3}),
            json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "Hello"}}),
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello world"}], "stopReason": "stop", "usage": {"input": 50, "output": 10}}}),
        ]

        async def fake_stream(message):
            for line in PI_EVENTS:
                yield line

        mock_pod_creation.stream_prompt = fake_stream

        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            # Acquire lock first
            resp = await client.post(
                "/v1/lock",
                json={"project": "proj-1", "role": "architect"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 200

            # Stream prompt
            resp = await client.post(
                "/v1/prompt/stream",
                json={"message": "hello", "role": "architect", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 200
            events = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
            types = [e["type"] for e in events]

            assert "text_delta" in types
            assert "result" in types

            result = next(e for e in events if e["type"] == "result")
            assert result["result"] == "Hello world"
            assert result["input_tokens"] == 50
            assert result["output_tokens"] == 10

    @pytest.mark.asyncio
    async def test_locked_stream_forwards_tool_use(self, client, mock_pod_creation):
        """Locked stream: tool_execution_start/end → tool_use events."""
        PI_EVENTS = [
            json.dumps({"type": "session", "id": "s1", "version": 3}),
            json.dumps({"type": "tool_execution_start", "toolName": "bash"}),
            json.dumps({"type": "tool_execution_end", "toolName": "bash"}),
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}], "stopReason": "stop", "usage": {"input": 10, "output": 2}}}),
        ]

        async def fake_stream(message):
            for line in PI_EVENTS:
                yield line

        mock_pod_creation.stream_prompt = fake_stream

        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            await client.post("/v1/lock", json={"project": "proj-1", "role": "architect"}, headers={"Authorization": "Token valid"})
            resp = await client.post("/v1/prompt/stream", json={"message": "ls", "role": "architect", "project": "proj-1"}, headers={"Authorization": "Token valid"})
            events = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]

            tool_events = [e for e in events if e["type"] == "tool_use"]
            assert len(tool_events) == 2
            assert tool_events[0]["tool"] == "bash"
            assert tool_events[0]["status"] == "started"
            assert tool_events[1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_locked_stream_forwards_error(self, client, mock_pod_creation):
        """Locked stream: error events forwarded to client."""
        PI_EVENTS = [
            json.dumps({"type": "session", "id": "s1", "version": 3}),
            json.dumps({"type": "error", "message": "Something broke"}),
        ]

        async def fake_stream(message):
            for line in PI_EVENTS:
                yield line

        mock_pod_creation.stream_prompt = fake_stream

        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            await client.post("/v1/lock", json={"project": "proj-1", "role": "architect"}, headers={"Authorization": "Token valid"})
            resp = await client.post("/v1/prompt/stream", json={"message": "hi", "role": "architect", "project": "proj-1"}, headers={"Authorization": "Token valid"})
            events = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]

            error_events = [e for e in events if e["type"] == "error"]
            assert len(error_events) >= 1
            assert error_events[0]["message"] == "Something broke"

    @pytest.mark.asyncio
    async def test_locked_stream_backward_compat_agent_end(self, client, mock_pod_creation):
        """Locked stream still works with agent_end (backward compatible)."""
        PI_EVENTS = [
            json.dumps({"type": "session", "id": "s1", "version": 3}),
            json.dumps({"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": "Hi from agent_end"}], "usage": {"input": 20, "output": 3}}]}),
        ]

        async def fake_stream(message):
            for line in PI_EVENTS:
                yield line

        mock_pod_creation.stream_prompt = fake_stream

        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()):
            await client.post("/v1/lock", json={"project": "proj-1", "role": "architect"}, headers={"Authorization": "Token valid"})
            resp = await client.post("/v1/prompt/stream", json={"message": "hi", "role": "architect", "project": "proj-1"}, headers={"Authorization": "Token valid"})
            events = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]

            result = next(e for e in events if e["type"] == "result")
            assert result["result"] == "Hi from agent_end"
            assert result["input_tokens"] == 20
