"""Tests for bridge auth middleware."""

import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient

from bridge.app import create_app
from bridge.pi_session import PiSession


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _mock_validate_response(user_id=1, username="testuser", user_type="human", projects=None):
    """Build a mock vtf validate response."""
    return {
        "user_id": user_id,
        "username": username,
        "user_type": user_type,
        "is_staff": False,
        "projects": projects or [{"project_id": "proj-1", "role": "member"}],
    }


class TestAuthMiddleware:
    @pytest.mark.asyncio
    async def test_health_requires_no_auth(self, client):
        """Health endpoint is public."""
        resp = await client.get("/v1/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_rejects_missing_token(self, client):
        """Protected endpoint without token returns 401."""
        resp = await client.post("/v1/prompt", json={"message": "hello", "role": "assistant"})
        assert resp.status_code == 401
        assert "token" in resp.json()["detail"].lower() or "auth" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_rejects_invalid_token(self, client):
        """Protected endpoint with invalid token returns 401."""
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=None):
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "assistant"},
                headers={"Authorization": "Token bad-token"},
            )
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_accepts_valid_token(self, client):
        """Protected endpoint with valid token succeeds (or gets past auth)."""
        mock_user = _mock_validate_response()
        mock_result = {"session_id": "s1", "text": "ok", "input_tokens": 0, "output_tokens": 0,
                       "total_tokens": 0, "cost_usd": 0, "num_turns": 0, "tool_uses": []}
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=mock_user), \
             patch.object(PiSession, "run_ephemeral", new_callable=AsyncMock, return_value=mock_result):
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "assistant", "project": "proj-1"},
                headers={"Authorization": "Token valid-token"},
            )
            assert resp.status_code != 401

    @pytest.mark.asyncio
    async def test_rejects_non_member(self, client):
        """Valid token but user not in requested project returns 403."""
        mock_user = _mock_validate_response(projects=[{"project_id": "other-proj", "role": "member"}])
        with patch("bridge.auth.validate_token", new_callable=AsyncMock, return_value=mock_user):
            resp = await client.post(
                "/v1/prompt",
                json={"message": "hello", "role": "assistant", "project": "proj-1"},
                headers={"Authorization": "Token valid-token"},
            )
            assert resp.status_code == 403
