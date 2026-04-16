"""Lock management for persistent agent sessions.

Hybrid approach: vtf AgentLock API for lock persistence (survives bridge restart),
in-memory dict for active PodSession references (process state).
"""

import time
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LockConflictError(Exception):
    """Raised when a lock is held by another user."""

    def __init__(self, holder: str):
        self.holder = holder
        super().__init__(f"Lock held by {holder}")


class LockManager:
    """Manages agent locks with vtf persistence and in-memory sessions."""

    def __init__(self, idle_timeout_seconds: int = 14400, use_vtf: bool = False):
        self._locks: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, Any] = {}  # key -> PodSession
        self.idle_timeout_seconds = idle_timeout_seconds
        self.use_vtf = use_vtf

    def _key(self, project: str, role: str) -> str:
        return f"{project}:{role}"

    async def acquire(self, user: dict[str, Any], project: str, role: str) -> dict[str, Any]:
        """Acquire a lock. Persists to vtf if configured."""
        key = self._key(project, role)

        if self.use_vtf:
            return await self._acquire_vtf(user, project, role, key)
        return await self._acquire_memory(user, project, role, key)

    async def _acquire_memory(self, user: dict, project: str, role: str, key: str) -> dict[str, Any]:
        existing = self._locks.get(key)
        if existing:
            if existing["user_id"] == user["user_id"]:
                existing["last_activity"] = time.monotonic()
                return existing
            raise LockConflictError(existing["username"])

        import uuid
        lock = {
            "session_id": str(uuid.uuid4()),
            "project": project,
            "role": role,
            "user_id": user["user_id"],
            "username": user["username"],
            "locked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "last_activity": time.monotonic(),
        }
        self._locks[key] = lock
        logger.info(f"Acquired lock {key} for user {user['username']} (memory)")
        return lock

    async def _acquire_vtf(self, user: dict, project: str, role: str, key: str) -> dict[str, Any]:
        from .vtf_locks import vtf_acquire_lock, LockConflictError as VtfConflict

        # Check if we already have this lock in memory (reconnect within same bridge instance)
        existing = self._locks.get(key)
        if existing and existing["user_id"] == user["user_id"]:
            existing["last_activity"] = time.monotonic()
            return existing

        try:
            vtf_lock = await vtf_acquire_lock(project, role, user_id=user["user_id"])
            lock = {
                "session_id": vtf_lock.get("session_id", ""),
                "project": project,
                "role": role,
                "user_id": user["user_id"],
                "username": user["username"],
                "locked_at": vtf_lock.get("created_at", ""),
                "last_activity": time.monotonic(),
                "vtf_pk": vtf_lock.get("id"),
            }
            self._locks[key] = lock
            logger.info(f"Acquired lock {key} for user {user['username']} (vtf pk={lock.get('vtf_pk')})")
            return lock
        except VtfConflict as e:
            raise LockConflictError(e.detail)

    async def release(self, user: dict[str, Any], project: str, role: str) -> bool:
        """Release a lock."""
        key = self._key(project, role)
        existing = self._locks.get(key)
        if not existing:
            return False
        if existing["user_id"] != user["user_id"]:
            return False

        # Release in vtf if configured
        if self.use_vtf and "vtf_pk" in existing:
            from .vtf_locks import vtf_release_lock
            await vtf_release_lock(existing["vtf_pk"])

        del self._locks[key]
        self._sessions.pop(key, None)
        logger.info(f"Released lock {key}")
        return True

    async def force_release(self, project: str, role: str) -> bool:
        """Release a lock without ownership check. Used for cleanup on pod death."""
        key = self._key(project, role)
        existing = self._locks.get(key)
        if not existing:
            return False

        if self.use_vtf and "vtf_pk" in existing:
            from .vtf_locks import vtf_release_lock
            try:
                await vtf_release_lock(existing["vtf_pk"])
            except Exception as e:
                logger.warning(f"Failed to release vtf lock {existing['vtf_pk']}: {e}")

        del self._locks[key]
        self._sessions.pop(key, None)
        logger.info(f"Force-released lock {key}")
        return True

    async def list_locks(self, project_id: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
        """List active locks, optionally filtered by project and/or role."""
        if self.use_vtf:
            from .vtf_locks import vtf_list_locks
            locks = await vtf_list_locks(project_id=project_id)
            if role:
                locks = [l for l in locks if l.get("role") == role]
            return locks

        result = []
        for v in self._locks.values():
            if project_id and v["project"] != project_id:
                continue
            if role and v["role"] != role:
                continue
            result.append({
                "project": v["project"],
                "role": v["role"],
                "user": v["username"],
                "session_id": v["session_id"],
                "locked_at": v["locked_at"],
            })
        return result

    def get_expired_locks(self) -> list[dict[str, Any]]:
        """Return locks that have exceeded idle timeout."""
        now = time.monotonic()
        return [
            lock for lock in self._locks.values()
            if now - lock["last_activity"] > self.idle_timeout_seconds
        ]

    async def cleanup_expired(self) -> int:
        """Remove expired locks (including VTF). Returns count of cleaned."""
        expired = self.get_expired_locks()
        for lock in expired:
            key = self._key(lock["project"], lock["role"])
            if self.use_vtf and "vtf_pk" in lock:
                from .vtf_locks import vtf_release_lock
                try:
                    await vtf_release_lock(lock["vtf_pk"])
                except Exception as e:
                    logger.warning(f"Failed to release expired vtf lock {lock['vtf_pk']}: {e}")
            del self._locks[key]
            self._sessions.pop(key, None)
            logger.info(f"Expired lock {key} (user: {lock['username']})")
        return len(expired)

    def touch(self, project: str, role: str) -> None:
        """Update last_activity for a lock."""
        key = self._key(project, role)
        if key in self._locks:
            self._locks[key]["last_activity"] = time.monotonic()

    def set_session(self, project: str, role: str, session: Any) -> None:
        """Associate a PodSession with a lock."""
        self._sessions[self._key(project, role)] = session

    def get_session(self, project: str, role: str) -> Any | None:
        """Get the PodSession for a lock, or None."""
        return self._sessions.get(self._key(project, role))

    def get_lock_for_user(self, user_id: int, project: str, role: str) -> dict[str, Any] | None:
        """Get lock if held by this user."""
        key = self._key(project, role)
        lock = self._locks.get(key)
        if lock and lock["user_id"] == user_id:
            return lock
        return None
