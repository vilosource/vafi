"""Agent Bridge Service — FastAPI application."""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict

import httpx

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .auth import require_auth, check_project_membership
from .lock_manager import LockManager, LockConflictError
from .models import BridgeRequest, BridgeResponse, LockRequest, UnlockRequest
from .pi_events import parse_pi_event
from .pi_session import PiSession, PiSessionConfig, build_pi_env
from .pod_process import PodProcessManager, PodSession
from .roles import load_roles, RoleConfig

BRIDGE_NAMESPACE = os.environ.get("BRIDGE_NAMESPACE", "vafi-dev")
AGENT_PI_IMAGE = os.environ.get("AGENT_PI_IMAGE", "harbor.viloforge.com/vafi/vafi-agent-pi:latest")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MAX_CONCURRENT_EPHEMERAL = int(os.environ.get("MAX_CONCURRENT_EPHEMERAL", "5"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))

# Bridge config from env
VTF_MCP_URL = os.environ.get("VTF_MCP_URL", "")
VTF_API_TOKEN = os.environ.get("VTF_API_TOKEN", "")
CXDB_MCP_URL = os.environ.get("CXDB_MCP_URL", "")
OTEL_ENDPOINT = os.environ.get("PI_OTEL_ENDPOINT", "")
SESSIONS_DIR = os.environ.get("SESSIONS_DIR", "/sessions")

VTF_CORS_ORIGINS = [
    "https://vtf.dev.viloforge.com",
    "https://vtf.viloforge.com",
]


def _setup_pi_config() -> None:
    """Write Pi config files if ANTHROPIC_BASE_URL is set."""
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    if not base_url:
        return
    pi_dir = os.path.expanduser("~/.pi/agent")
    os.makedirs(pi_dir, exist_ok=True)
    models_path = os.path.join(pi_dir, "models.json")
    if not os.path.exists(models_path):
        cfg = {"providers": {"anthropic": {
            "baseUrl": base_url,
            "api": "anthropic-messages",
            "apiKey": "ANTHROPIC_API_KEY",
            "models": [{"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"}],
        }}}
        with open(models_path, "w") as f:
            json.dump(cfg, f, indent=2)
        logger.info(f"Wrote Pi models.json with baseUrl={base_url}")


class RateLimiter:
    """Per-user sliding window rate limiter."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[int, list[float]] = defaultdict(list)

    def check(self, user_id: int) -> bool:
        """Return True if request is allowed, False if rate limited."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        # Remove old entries
        self._requests[user_id] = [t for t in self._requests[user_id] if t > cutoff]
        if len(self._requests[user_id]) >= self.max_requests:
            return False
        self._requests[user_id].append(now)
        return True


def _build_pi_session(role_config: RoleConfig | None, project: str) -> tuple[PiSession, dict[str, str]]:
    """Build PiSession and env vars from role config."""
    pi_config = PiSessionConfig(
        provider="anthropic",
        model=role_config.model if role_config else "claude-sonnet-4-20250514",
        thinking_level=role_config.thinking_level if role_config else "medium",
        methodology=role_config.methodology if role_config else "",
        max_turns=50,
    )
    env = build_pi_env(
        project=project,
        role=role_config.session_type if role_config else "assistant",
        vtf_mcp_url=VTF_MCP_URL,
        vtf_token=VTF_API_TOKEN,
        cxdb_mcp_url=CXDB_MCP_URL,
        otel_endpoint=OTEL_ENDPOINT,
    )
    return PiSession(pi_config), env


def create_app(roles_config: str | None = None) -> FastAPI:
    _setup_pi_config()
    app = FastAPI(title="vafi-bridge", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=VTF_CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Load roles
    config_path = roles_config or os.environ.get("ROLES_CONFIG", "")
    roles: dict[str, RoleConfig] = {}
    if config_path and os.path.exists(config_path):
        roles = load_roles(config_path)

    # Concurrency limiter
    ephemeral_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EPHEMERAL)

    # Rate limiter
    rate_limiter = RateLimiter(max_requests=RATE_LIMIT_PER_MINUTE, window_seconds=60)

    # Lock manager
    use_vtf_locks = bool(os.environ.get("VTF_API_TOKEN", ""))
    lock_manager = LockManager(
        idle_timeout_seconds=int(os.environ.get("LOCKED_IDLE_TIMEOUT_SECONDS", "14400")),
        use_vtf=use_vtf_locks,
    )

    # Background task for idle timeout cleanup
    async def _idle_timeout_loop():
        while True:
            await asyncio.sleep(60)
            try:
                expired = lock_manager.get_expired_locks()
                for lock in expired:
                    session = lock_manager.get_session(lock["project"], lock["role"])
                    if session:
                        try:
                            await session.shutdown()
                        except Exception:
                            pass
                cleaned = lock_manager.cleanup_expired()
                if cleaned:
                    logger.info(f"Idle timeout: cleaned {cleaned} expired lock(s)")
            except Exception as e:
                logger.error(f"Idle timeout loop error: {e}")

    @app.on_event("startup")
    async def startup():
        asyncio.create_task(_idle_timeout_loop())

    def _validate_prompt_request(body: BridgeRequest, user: dict) -> RoleConfig | None:
        """Common validation for prompt and prompt/stream endpoints."""
        if not body.project:
            raise HTTPException(status_code=400, detail="Project is required")

        check_project_membership(user, body.project)

        role_config = roles.get(body.role)
        if role_config is None and roles:
            raise HTTPException(status_code=400, detail=f"Unknown role: {body.role}")

        if role_config and role_config.session_type == "locked":
            # Check if user holds a lock for this project+role
            lock = lock_manager.get_lock_for_user(user["user_id"], body.project, body.role)
            if not lock:
                raise HTTPException(status_code=409, detail="Locked role requires a lock. Use POST /v1/lock first.")

        if not rate_limiter.check(user["user_id"]):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": "60"},
            )

        return role_config

    @app.get("/v1/health")
    async def health():
        pi_processes = []
        for key, lock in lock_manager._locks.items():
            session = lock_manager._sessions.get(key)
            pi_processes.append({
                "session_id": lock.get("session_id", ""),
                "project": lock.get("project", ""),
                "role": lock.get("role", ""),
                "user": lock.get("username", ""),
                "prompt_count": session.prompt_count if session else 0,
                "is_alive": session is not None and session._reader_task is not None and not session._reader_task.done(),
            })
        return {
            "status": "ok",
            "active_locked_sessions": len(lock_manager._locks),
            "active_ephemeral_sessions": MAX_CONCURRENT_EPHEMERAL - ephemeral_semaphore._value,
            "pi_processes": pi_processes,
        }

    @app.post("/v1/prompt")
    async def prompt(body: BridgeRequest, request: Request):
        user = await require_auth(request)
        role_config = _validate_prompt_request(body, user)

        # Locked path: route to persistent PodSession
        if role_config and role_config.session_type == "locked":
            pod_session = lock_manager.get_session(body.project, body.role)
            if not pod_session:
                raise HTTPException(status_code=503, detail="Locked session not ready")

            start_time = time.monotonic()
            result = await pod_session.send_prompt(body.message)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            lock_manager.touch(body.project, body.role)

            return BridgeResponse(
                result=result.get("text", ""),
                session_id=result.get("session_id") or "",
                role=body.role,
                project=body.project,
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                tool_uses=result.get("tool_uses", []),
                duration_ms=duration_ms,
                is_error=False,
                error_detail="",
            )

        # Ephemeral path
        acquired = ephemeral_semaphore._value > 0
        if not acquired:
            raise HTTPException(status_code=503, detail="Too many concurrent requests")

        async with ephemeral_semaphore:
            start_time = time.monotonic()
            session, env = _build_pi_session(role_config, body.project)
            result = await session.run_ephemeral(body.message, env=env)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            # Design: timeout returns 504
            if result.get("error") and "timed out" in result.get("error", "").lower():
                raise HTTPException(status_code=504, detail=result["error"])

            if result.get("error"):
                raise HTTPException(status_code=502, detail=result["error"])

            return BridgeResponse(
                result=result.get("text", ""),
                session_id=result.get("session_id") or "",
                role=body.role,
                project=body.project,
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                tool_uses=result.get("tool_uses", []),
                duration_ms=duration_ms,
                is_error=False,
                error_detail="",
            )

    # Pod process manager for locked sessions
    pod_manager = PodProcessManager(namespace=BRIDGE_NAMESPACE, image=AGENT_PI_IMAGE)

    @app.post("/v1/lock")
    async def acquire_lock(body: LockRequest, request: Request):
        user = await require_auth(request)
        check_project_membership(user, body.project)

        role_config = roles.get(body.role)
        if role_config is None or role_config.session_type != "locked":
            raise HTTPException(status_code=400, detail=f"Role '{body.role}' is not a locked role")

        try:
            lock = await lock_manager.acquire(user, body.project, body.role)
        except LockConflictError as e:
            raise HTTPException(status_code=409, detail=f"Lock held by {e.holder}")

        # If session already exists (reconnect), return immediately
        existing_session = lock_manager.get_session(body.project, body.role)
        if existing_session:
            return lock

        # Create pod and open exec connection
        try:
            env_vars = build_pi_env(
                project=body.project, role=body.role,
                vtf_mcp_url=VTF_MCP_URL, vtf_token=VTF_API_TOKEN,
                cxdb_mcp_url=CXDB_MCP_URL, otel_endpoint=OTEL_ENDPOINT,
            )
            # Add API keys from bridge pod env
            for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
                val = os.environ.get(key, "")
                if val:
                    env_vars[key] = val

            pod_spec = pod_manager.build_pod_spec(
                project=body.project, user=user["username"],
                role=body.role, env_vars=env_vars,
            )
            pod_name = await pod_manager.create_or_get_pod(pod_spec)

            exec_cmd = pod_manager.build_exec_command(
                project=body.project,
                methodology=role_config.methodology if role_config else "",
                provider="anthropic",
                model=role_config.model if role_config else "claude-sonnet-4-20250514",
                thinking_level=role_config.thinking_level if role_config else "medium",
            )
            exec_conn = await pod_manager.exec_pi(pod_name, exec_cmd)

            pod_session = PodSession(ws=exec_conn, session_id=None)
            await pod_session.initialize()
            lock_manager.set_session(body.project, body.role, pod_session)

            # Update lock with real session_id from Pi
            if pod_session.session_id:
                lock["session_id"] = pod_session.session_id

        except Exception as e:
            logger.error(f"Failed to create pod session: {e}")
            await lock_manager.release(user, body.project, body.role)
            raise HTTPException(status_code=503, detail=f"Failed to start agent session: {str(e)}")

        return lock

    @app.delete("/v1/lock")
    async def release_lock(body: UnlockRequest, request: Request):
        user = await require_auth(request)

        # Shutdown Pi session if exists
        pod_session = lock_manager.get_session(body.project, body.role)
        if pod_session:
            try:
                await pod_session.shutdown()
            except Exception:
                pass

        released = await lock_manager.release(user, body.project, body.role)
        if not released:
            raise HTTPException(status_code=404, detail="No lock found or not the owner")
        return {"released": True}

    @app.get("/v1/locks")
    async def list_locks():
        return await lock_manager.list_locks()

    @app.get("/v1/sessions")
    async def list_sessions(request: Request):
        """Proxy to vtf GET /v1/profile/sessions/ (read-only)."""
        user = await require_auth(request)
        vtf_url = os.environ.get("VTF_API_URL", "http://vtf-api.vtf-dev.svc.cluster.local:8000")
        auth_header = request.headers.get("Authorization", "")
        params = {}
        for key in ("project", "role", "since"):
            val = request.query_params.get(key)
            if val:
                params[key] = val
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{vtf_url}/v1/profile/sessions/",
                headers={"Authorization": auth_header},
                params=params,
                timeout=10,
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch sessions")
            return resp.json()

    @app.post("/v1/prompt/stream")
    async def prompt_stream(body: BridgeRequest, request: Request):
        user = await require_auth(request)
        role_config = _validate_prompt_request(body, user)

        # Locked streaming path
        if role_config and role_config.session_type == "locked":
            pod_session = lock_manager.get_session(body.project, body.role)
            if not pod_session:
                raise HTTPException(status_code=503, detail="Locked session not ready")

            async def generate_locked():
                async for line in pod_session.stream_prompt(body.message):
                    event = parse_pi_event(line)
                    if event is None:
                        continue
                    yield json.dumps({"type": "agent_event", "data": event.data}) + "\n"
                    if event.type == "session":
                        yield json.dumps({"type": "session_start", "session_id": event.data.get("id"), "role": body.role, "project": body.project or ""}) + "\n"
                    elif event.type == "message_update":
                        ae = event.data.get("assistantMessageEvent", {})
                        if ae.get("type") == "text_delta":
                            delta = ae.get("delta", "")
                            if delta:
                                yield json.dumps({"type": "text_delta", "text": delta}) + "\n"
                    elif event.type == "agent_end":
                        messages = event.data.get("messages", [])
                        for msg in reversed(messages):
                            if msg.get("role") == "assistant":
                                content = msg.get("content", [])
                                final_text = content[-1].get("text", "") if content else ""
                                usage = msg.get("usage", {})
                                yield json.dumps({"type": "result", "result": final_text, "session_id": pod_session.session_id or "", "input_tokens": usage.get("input", 0), "output_tokens": usage.get("output", 0), "num_turns": 0}) + "\n"
                                break
                lock_manager.touch(body.project, body.role)

            return StreamingResponse(generate_locked(), media_type="application/x-ndjson")

        # Ephemeral streaming path
        if not ephemeral_semaphore._value:
            raise HTTPException(status_code=503, detail="Too many concurrent requests")

        session, env = _build_pi_session(role_config, body.project)

        async def generate():
            async with ephemeral_semaphore:
                session_id = None
                num_turns = 0
                final_text = ""
                input_tokens = 0
                output_tokens = 0

                async for line in session.stream_ephemeral(body.message, env=env):
                    event = parse_pi_event(line)
                    if event is None:
                        continue

                    # Always emit raw event for rich clients (design spec)
                    yield json.dumps({"type": "agent_event", "data": event.data}) + "\n"

                    if event.type == "session":
                        session_id = event.data.get("id")
                        yield json.dumps({"type": "session_start", "session_id": session_id, "role": body.role, "project": body.project or ""}) + "\n"

                    elif event.type == "message_update":
                        ae = event.data.get("assistantMessageEvent", {})
                        if ae.get("type") == "text_delta":
                            delta = ae.get("delta", "")
                            if delta:
                                yield json.dumps({"type": "text_delta", "text": delta}) + "\n"

                    elif event.type == "tool_execution_start":
                        tool_name = event.data.get("toolName", "unknown")
                        yield json.dumps({"type": "tool_use", "tool": tool_name, "status": "started"}) + "\n"

                    elif event.type == "tool_execution_end":
                        tool_name = event.data.get("toolName", "unknown")
                        yield json.dumps({"type": "tool_use", "tool": tool_name, "status": "completed"}) + "\n"

                    elif event.type == "turn_end":
                        num_turns += 1

                    elif event.type == "error":
                        yield json.dumps({"type": "error", "message": event.data.get("message", "unknown error")}) + "\n"

                    elif event.type == "agent_end":
                        messages = event.data.get("messages", [])
                        for msg in reversed(messages):
                            if msg.get("role") == "assistant":
                                content = msg.get("content", [])
                                if content:
                                    final_text = content[-1].get("text", "")
                                usage = msg.get("usage", {})
                                input_tokens = usage.get("input", 0)
                                output_tokens = usage.get("output", 0)
                                break

                yield json.dumps({
                    "type": "result",
                    "result": final_text,
                    "session_id": session_id or "",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "num_turns": num_turns,
                }) + "\n"

        return StreamingResponse(generate(), media_type="application/x-ndjson")

    return app
