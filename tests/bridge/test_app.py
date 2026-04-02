"""Tests for bridge app skeleton — health, sessions, CORS."""

import pytest
from unittest.mock import AsyncMock, patch
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


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        resp = await client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "active_locked_sessions" in data
        assert "active_ephemeral_sessions" in data
        assert isinstance(data["active_locked_sessions"], int)
        assert isinstance(data["active_ephemeral_sessions"], int)


class TestSessions:
    @pytest.mark.asyncio
    async def test_sessions_requires_auth(self, client):
        resp = await client.get("/v1/sessions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_sessions_proxies_to_vtf(self, client):
        mock_user = {"user_id": 1, "username": "test", "user_type": "human",
                     "is_staff": False, "projects": []}
        mock_vtf_response = {"results": [{"session_id": "s1", "project": "p1"}]}

        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=mock_user), \
             patch("bridge.app.httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_vtf_response
            mock_get.return_value = mock_resp

            resp = await client.get(
                "/v1/sessions",
                headers={"Authorization": "Token valid"},
            )
            assert resp.status_code == 200
