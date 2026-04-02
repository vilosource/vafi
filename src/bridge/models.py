"""Request/response models for bridge API."""

from pydantic import BaseModel


class BridgeRequest(BaseModel):
    message: str
    project: str | None = None
    role: str = "assistant"
    channel: str = "web"
    channel_context: dict = {}


class LockRequest(BaseModel):
    project: str
    role: str


class UnlockRequest(BaseModel):
    project: str
    role: str


class BridgeResponse(BaseModel):
    result: str
    session_id: str
    cxdb_context_id: int | None = None
    role: str
    project: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_uses: list[str] = []
    duration_ms: int = 0
    is_error: bool = False
    error_detail: str = ""
