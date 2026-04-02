"""Tests for bridge idle timeout."""

import asyncio
import time

import pytest

from bridge.lock_manager import LockManager, LockConflictError


class TestIdleTimeout:
    @pytest.mark.asyncio
    async def test_idle_timeout_triggers_cleanup(self):
        """Session past timeout should be cleaned up."""
        manager = LockManager(idle_timeout_seconds=1)
        # Simulate an active lock
        manager._locks["proj-1:architect"] = {
            "session_id": "s1", "project": "proj-1", "role": "architect",
            "user_id": 1, "username": "test", "locked_at": "2026-04-02T10:00:00Z",
            "last_activity": time.monotonic() - 10,  # 10 seconds ago
        }

        expired = manager.get_expired_locks()
        assert len(expired) == 1
        assert expired[0]["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_activity_resets_timeout(self):
        manager = LockManager(idle_timeout_seconds=60)
        manager._locks["proj-1:architect"] = {
            "session_id": "s1", "project": "proj-1", "role": "architect",
            "user_id": 1, "username": "test", "locked_at": "2026-04-02T10:00:00Z",
            "last_activity": time.monotonic(),  # just now
        }

        expired = manager.get_expired_locks()
        assert len(expired) == 0

    @pytest.mark.asyncio
    async def test_idle_timeout_releases_lock(self):
        manager = LockManager(idle_timeout_seconds=1)
        manager._locks["proj-1:architect"] = {
            "session_id": "s1", "project": "proj-1", "role": "architect",
            "user_id": 1, "username": "test", "locked_at": "2026-04-02T10:00:00Z",
            "last_activity": time.monotonic() - 10,
        }

        cleaned = manager.cleanup_expired()
        assert cleaned == 1
        assert "proj-1:architect" not in manager._locks
