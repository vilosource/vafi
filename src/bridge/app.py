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
from .pod_process import PodProcessManager, PodSession, _sanitize_k8s_name
from .roles import load_roles, RoleConfig
from .session_recorder import SessionRecorder
from lib.pi_session_history import collect_prior_turns, apply_age_cap

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

    # Session recorder
    vtf_api_url = os.environ.get("VTF_API_URL", "http://vtf-api.vtf-dev.svc.cluster.local:8000")
    vtf_token = os.environ.get("VTF_API_TOKEN", "")
    session_recorder = SessionRecorder(vtf_api_url=vtf_api_url, vtf_token=vtf_token) if vtf_token else None

    # Lock manager
    use_vtf_locks = bool(vtf_token)
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
                cleaned = await lock_manager.cleanup_expired()
                if cleaned:
                    logger.info(f"Idle timeout: cleaned {cleaned} expired lock(s)")
            except Exception as e:
                logger.error(f"Idle timeout loop error: {e}")

    async def _recover_locks():
        """B11: On startup, query vtf for active locks and reconnect to existing pods."""
        if not lock_manager.use_vtf:
            return
        try:
            from .vtf_locks import vtf_list_locks
            active_locks = await vtf_list_locks()
            if not active_locks:
                logger.info("Recovery: no active locks in vtf")
                return

            logger.info(f"Recovery: found {len(active_locks)} active lock(s) in vtf")
            for vtf_lock in active_locks:
                project = vtf_lock.get("project_id", "")
                role_name = vtf_lock.get("role", "")
                username = vtf_lock.get("user", "")
                vtf_pk = vtf_lock.get("id")

                key = lock_manager._key(project, role_name)

                # Check if pod still exists
                try:
                    from .pod_process import _sanitize_k8s_name
                    pod_name = _sanitize_k8s_name(f"{role_name}-{project}-{username}")

                    from kubernetes_asyncio import client as k8s_client, config as k8s_config
                    k8s_config.load_incluster_config()
                    async with k8s_client.ApiClient() as api:
                        v1 = k8s_client.CoreV1Api(api)
                        pod = await v1.read_namespaced_pod(pod_name, BRIDGE_NAMESPACE)
                        if pod.status.phase != "Running":
                            logger.warning(f"Recovery: pod {pod_name} not running ({pod.status.phase}), releasing lock")
                            from .vtf_locks import vtf_release_lock
                            await vtf_release_lock(vtf_pk)
                            continue

                    # Pod exists and is running — try to open exec and reconnect
                    role_config = roles.get(role_name)
                    exec_cmd = pod_manager.build_exec_command(
                        project=project,
                        methodology=role_config.methodology if role_config else "",
                        provider="anthropic",
                        model=role_config.model if role_config else "claude-sonnet-4-20250514",
                        thinking_level=role_config.thinking_level if role_config else "medium",
                    )
                    exec_conn = await pod_manager.exec_on_pod(pod_name, exec_cmd)

                    from .pod_process import PodSession

                    async def _on_recovered_close(p=project, r=role_name):
                        logger.info(f"Recovered session closed for {p}:{r}, releasing lock")
                        await lock_manager.force_release(p, r)

                    pod_session = PodSession(
                        ws=exec_conn, session_id=vtf_lock.get("session_id"),
                        on_close=_on_recovered_close,
                    )
                    await pod_session.initialize()

                    lock_manager._locks[key] = {
                        "session_id": pod_session.session_id or vtf_lock.get("session_id", ""),
                        "project": project,
                        "role": role_name,
                        "user_id": vtf_lock.get("user_id", 0),
                        "username": username,
                        "locked_at": vtf_lock.get("created_at", ""),
                        "last_activity": time.monotonic(),
                        "vtf_pk": vtf_pk,
                    }
                    lock_manager.set_session(project, role_name, pod_session)
                    logger.info(f"Recovery: reconnected lock {key} (pod={pod_name})")

                except Exception as e:
                    logger.warning(f"Recovery: failed to reconnect lock {key}: {e}. Releasing.")
                    try:
                        from .vtf_locks import vtf_release_lock
                        await vtf_release_lock(vtf_pk)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Recovery failed: {e}")

    @app.on_event("startup")
    async def startup():
        asyncio.create_task(_idle_timeout_loop())
        await _recover_locks()

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
            if not pod_session.is_alive:
                await lock_manager.force_release(body.project, body.role)
                raise HTTPException(status_code=503, detail="Session expired. Please reconnect.")

            start_time = time.monotonic()
            result = await pod_session.send_prompt(body.message)
            duration_ms = int((time.monotonic() - start_time) * 1000)
            lock_manager.touch(body.project, body.role)

            if session_recorder:
                await session_recorder.record(
                    user_id=user["user_id"], project_id=body.project,
                    role=body.role, channel=body.channel,
                    session_id=result.get("session_id") or "",
                )

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

            if session_recorder:
                await session_recorder.record(
                    user_id=user["user_id"], project_id=body.project,
                    role=body.role, channel=body.channel,
                    session_id=result.get("session_id") or "",
                )

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
    sessions_pvc = os.environ.get("SESSIONS_PVC_NAME", "console-sessions")
    pod_manager = PodProcessManager(
        namespace=BRIDGE_NAMESPACE, image=AGENT_PI_IMAGE,
        sessions_pvc=sessions_pvc,
    )

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
                vtf_api_url=vtf_api_url,
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

            exec_cmd = pod_manager.build_exec_command(
                project=body.project,
                methodology=role_config.methodology if role_config else "",
                provider="anthropic",
                model=role_config.model if role_config else "claude-sonnet-4-20250514",
                thinking_level=role_config.thinking_level if role_config else "medium",
            )
            exec_conn = await pod_manager.create_and_exec(pod_spec, exec_cmd)

            async def _on_session_close():
                logger.info(f"Session closed for {body.project}:{body.role}, releasing lock")
                await lock_manager.force_release(body.project, body.role)

            pod_session = PodSession(ws=exec_conn, session_id=None, on_close=_on_session_close)
            await pod_session.initialize()
            lock_manager.set_session(body.project, body.role, pod_session)

            # Update lock with real session_id from Pi
            if pod_session.session_id:
                lock["session_id"] = pod_session.session_id
                # Sync to vtf database so heartbeat checks match
                if lock_manager.use_vtf and lock.get("vtf_pk"):
                    from .vtf_locks import vtf_update_lock
                    try:
                        await vtf_update_lock(lock["vtf_pk"], pod_session.session_id)
                    except Exception as e:
                        logger.warning(f"Failed to sync session_id to vtf: {e}")

                # Phase 9 Pre-Phase 0a: write SessionRecord so the history
                # endpoint can later attribute this session_id to the user.
                # Non-fatal — recording failure must not break lock acquire.
                if session_recorder:
                    try:
                        await session_recorder.record(
                            user_id=user["user_id"],
                            project_id=body.project,
                            role=body.role,
                            channel="web",
                            session_id=pod_session.session_id,
                            ended_at=None,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to record SessionRecord on acquire: {e}")

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
    async def list_locks(request: Request):
        project = request.query_params.get("project")
        role = request.query_params.get("role")
        return await lock_manager.list_locks(project_id=project, role=role)

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

    @app.get("/v1/sessions/history")
    async def sessions_history(request: Request):
        """Phase 9: return project-scoped architect conversation history.

        Reads Pi JSONL files from the PVC-mounted /sessions/{lowercased-project}/,
        joins against vtf SessionRecord to attribute each user message to its
        sender. Assistant messages are the architect's voice — not user-attributable.
        """
        from datetime import datetime, timezone

        user = await require_auth(request)
        project = request.query_params.get("project")
        role = request.query_params.get("role", "architect")
        try:
            limit = int(request.query_params.get("limit", "20"))
        except ValueError:
            limit = 20
        try:
            max_age_days = int(request.query_params.get("max_age_days", "14"))
        except ValueError:
            max_age_days = 14

        if not project:
            raise HTTPException(status_code=400, detail="'project' query parameter is required")
        check_project_membership(user, project)

        # 1) Collect Pi JSONL turns from the PVC.
        from pathlib import Path
        slug = _sanitize_k8s_name(project)
        # Read env at request-time so tests can monkey-patch SESSIONS_DIR.
        sessions_root = os.environ.get("SESSIONS_DIR", SESSIONS_DIR)
        session_dir = Path(sessions_root) / slug
        turns = collect_prior_turns(session_dir, max_sessions=10)
        turns = apply_age_cap(turns, datetime.now(timezone.utc).isoformat(), max_age_days)
        truncated = False
        # Cap to limit pairs (each pair = user+assistant). limit * 2 messages total.
        if len(turns) > limit:
            turns = turns[-limit:]
            truncated = True

        # 2) Fetch vtf SessionRecords for this project + role to map session_id -> username.
        sid_to_user: dict[str, dict] = {}
        vtf_url = os.environ.get("VTF_API_URL", "http://vtf-api.vtf-dev.svc.cluster.local:8000")
        auth_header = request.headers.get("Authorization", "")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{vtf_url}/v1/sessions/project/{project}/",
                    headers={"Authorization": auth_header},
                    params={"role": role},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for rec in data.get("results", []):
                        sid = rec.get("session_id")
                        if sid:
                            sid_to_user[sid] = {
                                "username": rec.get("username"),
                                "user_id": rec.get("user_id"),
                            }
                else:
                    logger.warning(f"vtf /v1/sessions/project returned {resp.status_code}")
        except Exception as e:
            # Non-fatal — return turns without attribution rather than failing the whole request.
            logger.warning(f"vtf SessionRecord fetch failed: {e}")

        # 3) Flatten turns into message-level list, attributing user messages.
        messages = []
        for ts, user_text, asst_text, sid in turns:
            attrib = sid_to_user.get(sid, {})
            messages.append({
                "role": "user",
                "text": user_text,
                "timestamp": ts,
                "session_id": sid,
                "username": attrib.get("username"),
            })
            messages.append({
                "role": "assistant",
                "text": asst_text,
                "timestamp": ts,
                "session_id": sid,
                "username": None,
            })

        return {
            "turns": messages,
            "truncated": truncated,
        }

    @app.post("/v1/prompt/stream")
    async def prompt_stream(body: BridgeRequest, request: Request):
        user = await require_auth(request)
        role_config = _validate_prompt_request(body, user)

        # Locked streaming path
        if role_config and role_config.session_type == "locked":
            pod_session = lock_manager.get_session(body.project, body.role)
            if not pod_session:
                raise HTTPException(status_code=503, detail="Locked session not ready")
            if not pod_session.is_alive:
                await lock_manager.force_release(body.project, body.role)
                raise HTTPException(status_code=503, detail="Session expired. Please reconnect.")

            async def generate_locked():
                num_turns = 0
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
                                final_text = content[-1].get("text", "") if content else ""
                                usage = msg.get("usage", {})
                                yield json.dumps({"type": "result", "result": final_text, "session_id": pod_session.session_id or "", "input_tokens": usage.get("input", 0), "output_tokens": usage.get("output", 0), "num_turns": num_turns}) + "\n"
                                break
                        break
                    elif event.type == "message":
                        # Pi doesn't send agent_end per prompt in locked RPC mode.
                        # Detect completion via final assistant message with stopReason.
                        msg = event.data.get("message", {})
                        if msg.get("role") == "assistant" and msg.get("stopReason") in ("stop", "end_turn"):
                            content = msg.get("content", [])
                            final_text = ""
                            for c in reversed(content):
                                if c.get("type") == "text":
                                    final_text = c.get("text", "")
                                    break
                            usage = msg.get("usage", {})
                            yield json.dumps({"type": "result", "result": final_text, "session_id": pod_session.session_id or "", "input_tokens": usage.get("input", 0), "output_tokens": usage.get("output", 0), "num_turns": num_turns}) + "\n"
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
