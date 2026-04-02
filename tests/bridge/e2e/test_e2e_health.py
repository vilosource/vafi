"""E2E test: bridge health endpoint against deployed service."""

import pytest


class TestE2EHealth:
    @pytest.mark.asyncio
    async def test_e2e_health(self, e2e_client):
        resp = await e2e_client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "active_locked_sessions" in data
        assert "active_ephemeral_sessions" in data
