"""vtf AgentLock API client for persistent lock management."""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

VTF_API_URL = os.environ.get("VTF_API_URL", "http://vtf-api.vtf-dev.svc.cluster.local:8000")
VTF_API_TOKEN = os.environ.get("VTF_API_TOKEN", "")


async def vtf_acquire_lock(project_id: str, role: str, session_id: str = "", user_id: int | None = None) -> dict[str, Any]:
    """POST /v1/locks/ — acquire or reconnect a lock in vtf."""
    body: dict[str, Any] = {"project_id": project_id, "role": role, "session_id": session_id}
    if user_id is not None:
        body["user_id"] = user_id
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{VTF_API_URL}/v1/locks/",
            headers={"Authorization": f"Token {VTF_API_TOKEN}"},
            json=body,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 201:
            return resp.json()
        elif resp.status_code == 409:
            detail = resp.json().get("detail", "Lock held by another user")
            raise LockConflictError(detail)
        else:
            raise Exception(f"vtf lock acquire failed: {resp.status_code} {resp.text}")


async def vtf_update_lock(lock_pk: int, session_id: str) -> bool:
    """PATCH /v1/locks/<pk>/ — update session_id after Pi handshake."""
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{VTF_API_URL}/v1/locks/{lock_pk}/",
            headers={"Authorization": f"Token {VTF_API_TOKEN}"},
            json={"session_id": session_id},
            timeout=10,
        )
        return resp.status_code == 200


async def vtf_release_lock(lock_pk: int) -> bool:
    """DELETE /v1/locks/<pk>/ — release a lock in vtf."""
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{VTF_API_URL}/v1/locks/{lock_pk}/",
            headers={"Authorization": f"Token {VTF_API_TOKEN}"},
            timeout=10,
        )
        return resp.status_code == 200


async def vtf_list_locks(project_id: str | None = None) -> list[dict[str, Any]]:
    """GET /v1/locks/ — list active locks from vtf."""
    async with httpx.AsyncClient() as client:
        params = {}
        if project_id:
            params["project_id"] = project_id
        resp = await client.get(
            f"{VTF_API_URL}/v1/locks/",
            headers={"Authorization": f"Token {VTF_API_TOKEN}"},
            params=params,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("results", [])
        return []


class LockConflictError(Exception):
    """Raised when a lock is held by another user."""
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)
