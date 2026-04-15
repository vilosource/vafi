"""Pod-based Pi process manager for locked sessions.

Per design: locked agents run Pi inside agent pods via kubectl exec.
The bridge creates pods, opens exec connections, and relays JSONL
commands/events through the exec WebSocket.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator

from .pi_events import parse_pi_event

logger = logging.getLogger(__name__)


def _sanitize_k8s_name(s: str) -> str:
    """Sanitize a string for use in k8s resource names."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    return s[:63] if s else "unnamed"


class PodProcessManager:
    """Manages pod lifecycle and exec connections for locked sessions."""

    def __init__(self, namespace: str, image: str, sessions_pvc: str = "console-sessions"):
        self.namespace = namespace
        self.image = image
        self.sessions_pvc = sessions_pvc

    def build_pod_spec(
        self,
        project: str,
        user: str,
        role: str,
        env_vars: dict[str, str],
    ) -> dict[str, Any]:
        """Build a k8s Pod spec for a locked agent session."""
        name = _sanitize_k8s_name(f"{role}-{project}-{user}")

        env = [{"name": k, "value": v} for k, v in env_vars.items()]

        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
                "labels": {
                    "app.kubernetes.io/name": "vafi",
                    "app.kubernetes.io/component": f"locked-{role}",
                    "vafi.viloforge.com/project": _sanitize_k8s_name(project),
                    "vafi.viloforge.com/user": _sanitize_k8s_name(user),
                },
            },
            "spec": {
                "containers": [{
                    "name": "pi-agent",
                    "image": self.image,
                    "imagePullPolicy": "Always",
                    "command": ["sleep", "infinity"],
                    "env": env,
                    "resources": {
                        "requests": {"memory": "1Gi", "cpu": "500m"},
                        "limits": {"memory": "2Gi", "cpu": "1000m"},
                    },
                    "volumeMounts": [
                        {"name": "sessions", "mountPath": "/sessions"},
                        {"name": "github-ssh", "mountPath": "/home/agent/.ssh", "readOnly": True},
                    ],
                }],
                "volumes": [
                    {
                        "name": "sessions",
                        "persistentVolumeClaim": {"claimName": self.sessions_pvc},
                    },
                    {
                        "name": "github-ssh",
                        "secret": {"secretName": "github-ssh", "defaultMode": 0o400},
                    },
                ],
                "restartPolicy": "Never",
                "imagePullSecrets": [{"name": "harbor-registry"}],
            },
        }

    def build_exec_command(
        self,
        project: str,
        methodology: str = "",
        provider: str = "anthropic",
        model: str = "claude-sonnet-4-20250514",
        thinking_level: str = "medium",
    ) -> list[str]:
        """Build Pi exec command for a locked session.

        Writes Pi config (models.json, mcp.json), hydrates project
        context, clones repo if needed, then starts Pi in RPC mode.
        """
        sanitized = _sanitize_k8s_name(project)
        pi_args = "--mode rpc"
        session_dir = f"/sessions/{sanitized}/"
        pi_args += f" --session-dir {session_dir} --provider {provider} --model {model}"
        if methodology:
            pi_args += f" --append-system-prompt {methodology}"
        if thinking_level:
            pi_args += f" --thinking {thinking_level}"

        # Write Pi config files (settings.json, models.json, mcp.json)
        pi_config = "python3 /opt/vf-agent/pi_config.py 1>&2"

        # Hydrate project context from VTF API
        hydrate = (
            f"python3 /opt/vf-agent/hydrate_context.py"
            f" /sessions/{sanitized}/ 1>&2 || true"
        )

        # Clone repo if hydration found a repo_url and .git doesn't exist yet
        # Uses -- to prevent flag injection from repo URL
        clone = (
            f"cd /sessions/{sanitized}/ &&"
            f" if [ ! -d .git ] && [ -f /tmp/repo_url ]; then"
            f" git clone --depth 1 -- \"$(cat /tmp/repo_url)\" . 1>&2 || true; fi"
        )

        return [
            "bash", "-c",
            f"{pi_config}; {hydrate}; {clone}; exec pi {pi_args}",
        ]

    async def create_and_exec(
        self,
        spec: dict[str, Any],
        command: list[str],
    ) -> "PodExecConnection":
        """Create pod (if needed) and open exec connection in a single flow.

        Uses one WsApiClient for both pod management and exec to avoid
        issues with multiple kubernetes client instances conflicting.
        """
        from kubernetes_asyncio import client as k8s_client, config as k8s_config
        from kubernetes_asyncio.stream import WsApiClient

        k8s_config.load_incluster_config()

        pod_name = spec["metadata"]["name"]
        namespace = spec["metadata"]["namespace"]

        # Phase 1: Ensure pod exists and is running
        api = k8s_client.ApiClient()
        try:
            v1 = k8s_client.CoreV1Api(api)

            try:
                existing = await v1.read_namespaced_pod(pod_name, namespace)
                if existing.status.phase in ("Running", "Pending"):
                    logger.info(f"Pod {pod_name} already exists ({existing.status.phase})")
                else:
                    raise k8s_client.exceptions.ApiException(status=404)
            except k8s_client.exceptions.ApiException as e:
                if e.status != 404:
                    raise
                logger.info(f"Creating pod {pod_name} in {namespace}")
                await v1.create_namespaced_pod(namespace, spec)

            # Wait for ready
            for _ in range(60):
                pod = await v1.read_namespaced_pod(pod_name, namespace)
                if pod.status.phase == "Running":
                    logger.info(f"Pod {pod_name} is running")
                    break
                await asyncio.sleep(1)
            else:
                raise TimeoutError(f"Pod {pod_name} not ready after 60s")
        finally:
            await api.close()

        # Phase 2: Open exec WebSocket (fresh client, no interference)
        ws_client = WsApiClient()
        v1_ws = k8s_client.CoreV1Api(ws_client)

        logger.info(f"Opening exec to pod {pod_name}: {' '.join(command[:5])}")

        ws_ctx = await v1_ws.connect_get_namespaced_pod_exec(
            pod_name,
            self.namespace,
            command=command,
            container="pi-agent",
            stdin=True,
            stdout=True,
            stderr=True,
            _preload_content=False,
        )

        ws = await ws_ctx.__aenter__()
        logger.info(f"Exec WebSocket opened to pod {pod_name}")

        return PodExecConnection(ws=ws, ws_ctx=ws_ctx, ws_client=ws_client, _buffer="")

    async def exec_on_pod(self, pod_name: str, command: list[str]) -> "PodExecConnection":
        """Open exec connection to an existing running pod."""
        from kubernetes_asyncio import client as k8s_client, config as k8s_config
        from kubernetes_asyncio.stream import WsApiClient

        k8s_config.load_incluster_config()
        ws_client = WsApiClient()
        v1_ws = k8s_client.CoreV1Api(ws_client)

        logger.info(f"Opening exec to existing pod {pod_name}: {' '.join(command[:5])}")

        ws_ctx = await v1_ws.connect_get_namespaced_pod_exec(
            pod_name,
            self.namespace,
            command=command,
            container="pi-agent",
            stdin=True,
            stdout=True,
            stderr=True,
            _preload_content=False,
        )

        ws = await ws_ctx.__aenter__()
        logger.info(f"Exec WebSocket opened to pod {pod_name}")
        return PodExecConnection(ws=ws, ws_ctx=ws_ctx, ws_client=ws_client, _buffer="")


@dataclass
class PodExecConnection:
    """Wraps a k8s exec WebSocket connection for JSONL communication.

    The k8s exec protocol uses binary frames with a channel prefix byte:
    0=stdin, 1=stdout, 2=stderr, 3=error, 4=resize.
    """
    ws: Any
    ws_ctx: Any
    ws_client: Any
    _buffer: str = ""

    async def read_stdout(self) -> bytes:
        """Read a line from stdout. Handles k8s exec binary framing.

        The k8s v4 exec protocol can send either BINARY or TEXT frames
        depending on the server version. Both use the same channel prefix:
        first byte/char is the channel number (0=stdin, 1=stdout, 2=stderr).
        """
        import aiohttp

        while True:
            # Check buffer for complete line
            if "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                return line.encode("utf-8")

            # Read next WebSocket message
            logger.debug(f"read_stdout: waiting for ws message (buffer={len(self._buffer)} chars)")
            msg = await self.ws.receive()
            logger.debug(f"read_stdout: got msg type={msg.type} len={len(msg.data) if msg.data else 0}")
            if msg.type == aiohttp.WSMsgType.BINARY:
                if len(msg.data) >= 2:
                    channel = msg.data[0]
                    payload = msg.data[1:]
                    if channel == 1:  # stdout
                        self._buffer += payload.decode("utf-8", errors="replace")
                    elif channel == 2:  # stderr
                        logger.info(f"Pod stderr: {payload.decode('utf-8', errors='replace').strip()}")
                    elif channel == 3:  # error channel
                        logger.warning(f"Pod error channel: {payload.decode('utf-8', errors='replace').strip()}")
            elif msg.type == aiohttp.WSMsgType.TEXT:
                # v4 protocol may send TEXT frames with channel as first char
                if len(msg.data) >= 2:
                    channel = ord(msg.data[0])
                    payload = msg.data[1:]
                    if channel == 1:  # stdout
                        self._buffer += payload
                    elif channel == 2:  # stderr
                        logger.info(f"Pod stderr (text): {payload.strip()}")
                    elif channel == 3:  # error channel
                        logger.warning(f"Pod error channel (text): {payload.strip()}")
            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                return b""

    async def write_stdin(self, data: bytes) -> None:
        """Write to stdin (channel 0). Prepends channel byte."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        # Channel 0 = stdin
        frame = bytes([0]) + data
        await self.ws.send_bytes(frame)

    async def close(self) -> None:
        """Close the exec connection."""
        try:
            await self.ws_ctx.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            await self.ws_client.close()
        except Exception:
            pass


class PodSession:
    """Manages a Pi RPC session inside a pod via exec connection.

    Uses a background reader task to keep the WebSocket alive and
    an asyncio.Queue to collect events when a prompt is active.
    """

    def __init__(
        self,
        ws: Any,
        session_id: str | None = None,
        on_close: Any | None = None,
    ):
        self.ws = ws
        self.session_id = session_id
        self.on_close = on_close  # async callable, invoked when reader loop exits
        self.lock = asyncio.Lock()
        self.prompt_count = 0
        self._alive = True
        self._event_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._collecting = False  # True when a prompt is waiting for events

    @property
    def is_alive(self) -> bool:
        """Whether the exec connection is still active."""
        return self._alive

    async def _reader_loop(self) -> None:
        """Background task: read from exec WebSocket, enqueue lines."""
        logger.info(f"Reader loop started for session {self.session_id}")
        try:
            while True:
                try:
                    data = await self.ws.read_stdout()
                except Exception as e:
                    logger.warning(f"Reader loop read error for {self.session_id}: {e}")
                    break
                if not data:
                    logger.info(f"Reader loop EOF for {self.session_id}")
                    break
                line = data.decode("utf-8").strip() if isinstance(data, bytes) else data.strip()
                if line:
                    await self._event_queue.put(line)
        except asyncio.CancelledError:
            logger.info(f"Reader loop cancelled for {self.session_id}")
        finally:
            self._alive = False
            logger.info(f"Reader loop ended for {self.session_id}")
            await self._event_queue.put(None)  # Signal EOF
            if self.on_close:
                try:
                    await self.on_close()
                except Exception as e:
                    logger.warning(f"on_close callback failed for {self.session_id}: {e}")

    def start_reader(self) -> None:
        """Start the background reader task."""
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def initialize(self) -> None:
        """Start reader, send get_state to get session ID."""
        from .pi_protocol import pi_handshake

        self.start_reader()

        async def _read_line() -> str | None:
            line = await asyncio.wait_for(self._event_queue.get(), timeout=120)
            if line is None:
                raise RuntimeError("Pi process exited before becoming ready")
            return line

        self.session_id = await pi_handshake(
            write_fn=self.ws.write_stdin,
            read_fn=_read_line,
        )
        logger.info(f"Pi session initialized: {self.session_id}")

    async def send_prompt(self, message: str) -> dict[str, Any]:
        """Send a prompt and collect the full response."""
        async with self.lock:
            self.prompt_count += 1

            # Send prompt command
            cmd = json.dumps({"type": "prompt", "message": message}) + "\n"
            await self.ws.write_stdin(cmd.encode("utf-8"))

            # Collect events from queue until agent_end
            lines = []
            if self.session_id:
                lines.append(json.dumps({"type": "session", "id": self.session_id}))

            while True:
                try:
                    line = await asyncio.wait_for(self._event_queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    logger.error("Locked prompt timed out waiting for response")
                    break
                if line is None:
                    break
                lines.append(line)
                event = parse_pi_event(line)
                if event and event.type == "agent_end":
                    break

            from .pi_session import PiSession, PiSessionConfig
            parser = PiSession(PiSessionConfig())
            return parser.parse_output("\n".join(lines))

    async def stream_prompt(self, message: str) -> AsyncIterator[str]:
        """Send a prompt and yield JSONL lines as they arrive."""
        if not self._alive:
            yield json.dumps({"type": "error", "message": "Session expired. Please reconnect."})
            return

        async with self.lock:
            self.prompt_count += 1

            if self.session_id:
                yield json.dumps({"type": "session", "id": self.session_id})

            cmd = json.dumps({"type": "prompt", "message": message}) + "\n"
            await self.ws.write_stdin(cmd.encode("utf-8"))

            while True:
                try:
                    line = await asyncio.wait_for(self._event_queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "error", "message": "Locked prompt timed out"})
                    break
                if line is None:
                    break
                yield line
                event = parse_pi_event(line)
                if event and event.type == "agent_end":
                    break
                # Pi doesn't send agent_end per prompt in locked RPC mode.
                # Detect completion via final assistant message with stopReason.
                if event and event.type == "message":
                    msg = event.data.get("message", {})
                    if msg.get("role") == "assistant" and msg.get("stopReason") in ("stop", "end_turn"):
                        break

    async def shutdown(self) -> None:
        """Send shutdown command to Pi and stop reader."""
        try:
            cmd = json.dumps({"type": "shutdown"}) + "\n"
            await self.ws.write_stdin(cmd.encode("utf-8"))
        except Exception:
            pass
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
