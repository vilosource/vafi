"""Session recording — posts SessionRecords to vtf after each prompt."""

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


class SessionRecorder:
    """Records agent interactions in vtf SessionRecord model."""

    def __init__(self, vtf_api_url: str, vtf_token: str):
        self.vtf_api_url = vtf_api_url
        self.vtf_token = vtf_token

    async def record(
        self,
        user_id: int,
        project_id: str,
        role: str,
        channel: str = "web",
        session_id: str = "",
        cxdb_context_id: int | None = None,
        ended_at: str | None = None,
    ) -> None:
        """Post a SessionRecord to vtf POST /v1/sessions/."""
        body = {
            "user_id": user_id,
            "project_id": project_id,
            "role": role,
            "channel": channel,
        }
        if session_id:
            body["session_id"] = session_id
        if cxdb_context_id is not None:
            body["cxdb_context_id"] = cxdb_context_id
        # ended_at: pass through if given; otherwise leave unset so vtf stores null.
        # (Previously this defaulted to now(), which caused acquire-time records
        #  to look immediately-ended — breaks Phase 9 attribution UX.)
        if ended_at:
            body["ended_at"] = ended_at

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.vtf_api_url}/v1/sessions/",
                    headers={"Authorization": f"Token {self.vtf_token}"},
                    json=body,
                    timeout=10,
                )
                if resp.status_code in (200, 201):
                    logger.info(f"Recorded session: project={project_id} role={role} session={session_id}")
                else:
                    logger.warning(f"Failed to record session: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.warning(f"Session recording failed: {e}")
