"""E2E test: locked session lifecycle against deployed bridge.

Tests the full flow: acquire lock → pod created → prompt routed to locked Pi → release.
"""

import asyncio
import os

import pytest


VTF_TOKEN = os.environ.get("VTF_TOKEN", "")
PROJECT_ID = os.environ.get("VTF_PROJECT_ID", "6udCSkejRVk0vO0k9dxaQ")


@pytest.fixture(autouse=True)
async def cleanup_locked_pods():
    """Clean up locked architect pods between tests."""
    yield
    # After each test, delete locked pods so the next test starts fresh
    import subprocess
    subprocess.run(
        ["kubectl", "delete", "pod", "-n", "vafi-dev", "-l", "app.kubernetes.io/component=locked-architect", "--wait=false"],
        capture_output=True, timeout=10,
    )
    await asyncio.sleep(2)


@pytest.mark.skipif(not VTF_TOKEN, reason="VTF_TOKEN not set")
class TestE2ELocks:
    @pytest.mark.asyncio
    async def test_e2e_lock_acquire_and_release(self, e2e_client):
        """AC-3: Acquire lock, verify it exists, release it."""
        headers = {"Authorization": f"Token {VTF_TOKEN}"}

        # Acquire
        resp = await e2e_client.post(
            "/v1/lock",
            json={"project": PROJECT_ID, "role": "architect"},
            headers=headers,
            timeout=120,
        )
        assert resp.status_code == 200, f"Lock acquire failed: {resp.status_code} {resp.text}"
        lock = resp.json()
        assert lock["session_id"], "Expected session_id from lock"
        assert lock["role"] == "architect"

        # List — should see our lock
        resp = await e2e_client.get("/v1/locks")
        assert resp.status_code == 200
        locks = resp.json()
        assert any(l["role"] == "architect" for l in locks), f"Lock not in list: {locks}"

        # Release
        resp = await e2e_client.request(
            "DELETE", "/v1/lock",
            json={"project": PROJECT_ID, "role": "architect"},
            headers=headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_e2e_locked_prompt(self, e2e_client):
        """AC-3: Acquire lock, send prompt to locked session, get response, release."""
        headers = {"Authorization": f"Token {VTF_TOKEN}"}

        # Acquire lock
        resp = await e2e_client.post(
            "/v1/lock",
            json={"project": PROJECT_ID, "role": "architect"},
            headers=headers,
            timeout=120,
        )
        assert resp.status_code == 200, f"Lock acquire failed: {resp.status_code} {resp.text}"

        try:
            # Send prompt to locked session
            resp = await e2e_client.post(
                "/v1/prompt",
                json={"message": "Reply with exactly: LOCKED_SESSION_OK", "role": "architect", "project": PROJECT_ID},
                headers=headers,
                timeout=120,
            )
            assert resp.status_code == 200, f"Locked prompt failed: {resp.status_code} {resp.text}"
            data = resp.json()
            assert data["result"], "Expected non-empty result from locked session"
            assert data["is_error"] is False
        finally:
            # Always release
            await e2e_client.request(
                "DELETE", "/v1/lock",
                json={"project": PROJECT_ID, "role": "architect"},
                headers=headers,
            )
