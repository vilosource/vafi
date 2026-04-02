"""E2E test: auth enforcement against deployed bridge."""

import os

import pytest


VTF_TOKEN = os.environ.get("VTF_TOKEN", "")
PROJECT_ID = os.environ.get("VTF_PROJECT_ID", "6udCSkejRVk0vO0k9dxaQ")


class TestE2EAuth:
    @pytest.mark.asyncio
    async def test_e2e_no_token_returns_401(self, e2e_client):
        resp = await e2e_client.post("/v1/prompt", json={"message": "hello", "role": "assistant", "project": PROJECT_ID})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_e2e_bad_token_returns_401(self, e2e_client):
        resp = await e2e_client.post(
            "/v1/prompt",
            json={"message": "hello", "role": "assistant", "project": PROJECT_ID},
            headers={"Authorization": "Token clearly-invalid-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.skipif(not VTF_TOKEN, reason="VTF_TOKEN not set")
    async def test_e2e_valid_token_passes_auth(self, e2e_client):
        """Valid token should get past auth (may fail on other grounds, but not 401)."""
        resp = await e2e_client.post(
            "/v1/prompt",
            json={"message": "hello", "role": "assistant", "project": PROJECT_ID},
            headers={"Authorization": f"Token {VTF_TOKEN}"},
            timeout=120,
        )
        assert resp.status_code != 401

    @pytest.mark.asyncio
    @pytest.mark.skipif(not VTF_TOKEN, reason="VTF_TOKEN not set")
    async def test_e2e_project_required(self, e2e_client):
        """Prompt without project returns 400."""
        resp = await e2e_client.post(
            "/v1/prompt",
            json={"message": "hello", "role": "assistant"},
            headers={"Authorization": f"Token {VTF_TOKEN}"},
        )
        assert resp.status_code == 400
