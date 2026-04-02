"""Auth middleware for bridge service.

Validates tokens against vtf's GET /v1/auth/validate/ endpoint.
"""

import os
from typing import Any

import httpx
from fastapi import Request, HTTPException


VTF_API_URL = os.environ.get("VTF_API_URL", "http://vtf-api.vtf-dev.svc.cluster.local:8000")


async def validate_token(token: str) -> dict[str, Any] | None:
    """Validate a token against vtf and return user info, or None if invalid."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{VTF_API_URL}/v1/auth/validate/",
                headers={"Authorization": f"Token {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except httpx.RequestError:
            return None


async def require_auth(request: Request) -> dict[str, Any]:
    """Extract and validate auth token from request. Raises 401/403."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Token "):
        raise HTTPException(status_code=401, detail="Authorization token required")

    token = auth_header[6:]  # Strip "Token " prefix
    user = await validate_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user


def check_project_membership(user: dict[str, Any], project_id: str) -> None:
    """Check that user has membership in the requested project. Raises 403."""
    if user.get("is_staff"):
        return  # Staff bypass

    projects = user.get("projects", [])
    member_projects = {p["project_id"] for p in projects}
    if project_id not in member_projects:
        raise HTTPException(status_code=403, detail="Not a member of this project")
