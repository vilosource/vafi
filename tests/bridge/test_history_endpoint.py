"""Phase 9: GET /v1/sessions/history endpoint tests.

Covers: auth, project-scoping, JSONL → turns flattening, vtf attribution join,
graceful degradation when vtf is down, limit + truncated flag.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from bridge.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def make_jsonl_session(path, session_id: str, pairs: list[tuple[str, str, str]]):
    """Write a Pi v3 JSONL at path. pairs = [(ts_iso, user_text, asst_text), ...]."""
    lines = [
        json.dumps({"type": "session", "version": 3, "id": session_id, "timestamp": pairs[0][0], "cwd": "/x"}),
    ]
    for i, (ts, u, a) in enumerate(pairs):
        lines.append(json.dumps({
            "type": "message", "id": f"u{i}", "timestamp": ts,
            "message": {"role": "user", "content": [{"type": "text", "text": u}]},
        }))
        lines.append(json.dumps({
            "type": "message", "id": f"a{i}", "timestamp": ts,
            "message": {"role": "assistant", "content": [{"type": "text", "text": a}], "stopReason": "stop"},
        }))
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def populated_sessions_dir(tmp_path, monkeypatch):
    """Populate a fake /sessions/{slug}/ with two sessions, different session_ids."""
    slug_dir = tmp_path / "my-proj"
    slug_dir.mkdir()
    make_jsonl_session(
        slug_dir / "2026-01-01T10-00-00_sidAAA.jsonl",
        "sid-aaa",
        [("2026-01-01T10:00:00Z", "alice prompt 1", "architect reply 1")],
    )
    make_jsonl_session(
        slug_dir / "2026-01-02T10-00-00_sidBBB.jsonl",
        "sid-bbb",
        [("2026-01-02T10:00:00Z", "bob prompt 1", "architect reply 2")],
    )
    # Point SESSIONS_DIR env at the tmp root so the endpoint reads /tmp/.../my-proj
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def auth_stub():
    """Stub require_auth + check_project_membership to return a fake authenticated user."""
    fake_user = {"user_id": 1, "username": "alice", "is_staff": True, "projects": []}
    with patch("bridge.app.require_auth", new=AsyncMock(return_value=fake_user)), \
         patch("bridge.app.check_project_membership", return_value=None):
        yield fake_user


@pytest.fixture
def vtf_stub():
    """Stub the httpx.AsyncClient.get call the endpoint makes to vtf."""
    class FakeResponse:
        status_code = 200
        def json(self):
            return {"results": [
                {"session_id": "sid-aaa", "username": "alice", "user_id": 1},
                {"session_id": "sid-bbb", "username": "bob", "user_id": 2},
            ]}

    with patch("httpx.AsyncClient") as mock_client:
        instance = mock_client.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=FakeResponse())
        yield instance


class TestHistoryEndpoint:
    @pytest.mark.asyncio
    async def test_requires_project_param(self, client, auth_stub):
        resp = await client.get("/v1/sessions/history")
        assert resp.status_code == 400
        assert "project" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_returns_flattened_messages_with_attribution(
        self, client, populated_sessions_dir, auth_stub, vtf_stub,
    ):
        # Disable age cap in tests — fixture timestamps are fixed in 2026-01.
        resp = await client.get("/v1/sessions/history?project=my-proj&max_age_days=0")
        assert resp.status_code == 200
        data = resp.json()
        turns = data["turns"]
        # 2 JSONL files × 2 messages each = 4 messages
        assert len(turns) == 4
        # Chronological (alice first)
        assert turns[0]["role"] == "user"
        assert turns[0]["text"] == "alice prompt 1"
        assert turns[0]["username"] == "alice"
        assert turns[1]["role"] == "assistant"
        assert turns[1]["username"] is None  # assistant not attributed
        assert turns[2]["text"] == "bob prompt 1"
        assert turns[2]["username"] == "bob"
        assert data["truncated"] is False

    @pytest.mark.asyncio
    async def test_limit_truncates(self, client, populated_sessions_dir, auth_stub, vtf_stub):
        resp = await client.get("/v1/sessions/history?project=my-proj&limit=1&max_age_days=0")
        assert resp.status_code == 200
        data = resp.json()
        # limit=1 pair → 2 messages
        assert len(data["turns"]) == 2
        assert data["truncated"] is True
        # Only the most-recent (bob's) survives
        assert data["turns"][0]["username"] == "bob"

    @pytest.mark.asyncio
    async def test_empty_session_dir(self, client, tmp_path, auth_stub, monkeypatch, vtf_stub):
        monkeypatch.setenv("SESSIONS_DIR", str(tmp_path))
        resp = await client.get("/v1/sessions/history?project=nonexistent")
        assert resp.status_code == 200
        assert resp.json() == {"turns": [], "truncated": False}

    @pytest.mark.asyncio
    async def test_vtf_down_returns_unattributed(
        self, client, populated_sessions_dir, auth_stub,
    ):
        """If vtf is unreachable, endpoint still returns turns without username."""
        with patch("httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=Exception("vtf down"))
            resp = await client.get("/v1/sessions/history?project=my-proj&max_age_days=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["turns"]) == 4
        assert all(t["username"] is None for t in data["turns"])
