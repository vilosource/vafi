"""Tests for bridge session recording."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import ASGITransport, AsyncClient

from bridge.app import create_app
from bridge.pi_session import PiSession
from bridge.session_recorder import SessionRecorder


ROLES_YAML = """
roles:
  assistant:
    session_type: ephemeral
    harness: pi-rpc
    model: claude-sonnet-4-20250514
    thinking_level: low
    methodology: ""
    mcp_tools: [vtf]
    description: Quick ops
"""


def _mock_user():
    return {
        "user_id": 1, "username": "testuser", "user_type": "human",
        "is_staff": False, "projects": [{"project_id": "proj-1", "role": "member"}],
    }


def _mock_pi_result():
    return {
        "session_id": "sess-record-test", "text": "done",
        "input_tokens": 50, "output_tokens": 5, "total_tokens": 55,
        "cost_usd": 0, "num_turns": 1, "tool_uses": [],
    }


@pytest.fixture
def roles_file(tmp_path):
    f = tmp_path / "roles.yaml"
    f.write_text(ROLES_YAML)
    return str(f)


@pytest.fixture
def app(roles_file, monkeypatch):
    monkeypatch.setenv("VTF_API_TOKEN", "test-token")
    monkeypatch.setenv("VTF_API_URL", "http://vtf-test:8000")
    return create_app(roles_config=roles_file)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestSessionRecorder:
    @pytest.mark.asyncio
    async def test_records_session_after_prompt(self):
        """SessionRecorder.record() posts to vtf /v1/sessions/."""
        recorder = SessionRecorder(vtf_api_url="http://vtf:8000", vtf_token="test-token")

        with patch("bridge.session_recorder.httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_post.return_value = mock_resp

            await recorder.record(
                user_id=1,
                project_id="proj-1",
                role="assistant",
                channel="web",
                session_id="sess-123",
                cxdb_context_id=42,
            )

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["project_id"] == "proj-1"
            assert body["role"] == "assistant"
            assert body["session_id"] == "sess-123"
            assert body["cxdb_context_id"] == 42

    @pytest.mark.asyncio
    async def test_prompt_triggers_session_recording(self, client):
        """Prompt endpoint calls session recorder after successful response."""
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=_mock_user()), \
             patch.object(PiSession, "run_ephemeral", new_callable=AsyncMock, return_value=_mock_pi_result()), \
             patch.object(SessionRecorder, "record", new_callable=AsyncMock) as mock_record:
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "assistant", "project": "proj-1"},
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 200
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args.kwargs
            assert call_kwargs["project_id"] == "proj-1"
            assert call_kwargs["role"] == "assistant"
            assert call_kwargs["session_id"] == "sess-record-test"
