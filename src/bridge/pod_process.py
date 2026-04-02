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

    def __init__(self, namespace: str, image: str):
        self.namespace = namespace
        self.image = image

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
                    "name": "agent",
                    "image": self.image,
                    "command": ["sleep", "infinity"],
                    "env": env,
                    "resources": {
                        "requests": {"memory": "256Mi", "cpu": "100m"},
                        "limits": {"memory": "1Gi", "cpu": "1000m"},
                    },
                    "volumeMounts": [{
                        "name": "sessions",
                        "mountPath": "/sessions",
                    }],
                }],
                "volumes": [{
                    "name": "sessions",
                    "emptyDir": {},
                }],
                "restartPolicy": "Never",
                "imagePullSecrets": [{"name": "harbor-registry"}],
            },
        }

    def build_exec_command(self) -> list[str]:
        """Build exec command for a locked session.

        Uses the standard connect script from the harness image.
        The init.sh already ran at pod startup, so config is ready.
        """
        return ["/opt/vf-harness/connect.sh"]

    async def create_or_get_pod(self, spec: dict[str, Any]) -> str:
        """Create pod if it doesn't exist, return pod name.

        Uses kubernetes_asyncio to interact with the k8s API.
        """
        from kubernetes_asyncio import client as k8s_client, config as k8s_config

        k8s_config.load_incluster_config()
        async with k8s_client.ApiClient() as api:
            v1 = k8s_client.CoreV1Api(api)
            pod_name = spec["metadata"]["name"]
            namespace = spec["metadata"]["namespace"]

            try:
                existing = await v1.read_namespaced_pod(pod_name, namespace)
                if existing.status.phase in ("Running", "Pending"):
                    logger.info(f"Pod {pod_name} already exists ({existing.status.phase})")
                    return pod_name
            except k8s_client.exceptions.ApiException as e:
                if e.status != 404:
                    raise

            # Create pod
            logger.info(f"Creating pod {pod_name} in {namespace}")
            await v1.create_namespaced_pod(namespace, spec)

            # Wait for ready
            for _ in range(60):
                pod = await v1.read_namespaced_pod(pod_name, namespace)
                if pod.status.phase == "Running":
                    logger.info(f"Pod {pod_name} is running")
                    return pod_name
                await asyncio.sleep(1)

            raise TimeoutError(f"Pod {pod_name} not ready after 60s")

    async def exec_pi(self, pod_name: str, command: list[str]) -> "PodExecConnection":
        """Open kubectl exec connection to Pi in the pod.

        Returns a PodExecConnection that provides read_stdout/write_stdin.
        The connection uses the k8s exec WebSocket with binary framing
        (channel prefix bytes: 0=stdin, 1=stdout, 2=stderr).
        """
        from kubernetes_asyncio import client as k8s_client, config as k8s_config
        from kubernetes_asyncio.stream import WsApiClient

        k8s_config.load_incluster_config()
        ws_client = WsApiClient()
        v1 = k8s_client.CoreV1Api(ws_client)

        logger.info(f"Opening exec to pod {pod_name}: {' '.join(command[:5])}")

        ws_ctx = await v1.connect_get_namespaced_pod_exec(
            pod_name,
            self.namespace,
            command=command,
            container="agent",
            stdin=True,
            stdout=True,
            stderr=True,
            _preload_content=False,
        )

        # Enter the async context manager to get the actual WebSocket.
        # IMPORTANT: We must keep ws_client and ws_ctx alive for the lifetime
        # of the session. The PodExecConnection holds references to prevent GC.
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
        """Read a line from stdout. Handles k8s exec binary framing."""
        import aiohttp

        while True:
            # Check buffer for complete line
            if "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                return line.encode("utf-8")

            # Read next WebSocket message
            msg = await self.ws.receive()
            if msg.type == aiohttp.WSMsgType.BINARY:
                if len(msg.data) >= 2:
                    channel = msg.data[0]
                    payload = msg.data[1:]
                    if channel == 1:  # stdout
                        self._buffer += payload.decode("utf-8", errors="replace")
                    # Skip stderr (channel 2) and others
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

    def __init__(self, ws: Any, session_id: str | None = None):
        self.ws = ws
        self.session_id = session_id
        self.lock = asyncio.Lock()
        self.prompt_count = 0
        self._event_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None
        self._collecting = False  # True when a prompt is waiting for events

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
                    logger.debug(f"Reader enqueued event for {self.session_id}: {line[:80]}")
                    await self._event_queue.put(line)
        except asyncio.CancelledError:
            logger.info(f"Reader loop cancelled for {self.session_id}")
        finally:
            logger.info(f"Reader loop ended for {self.session_id}")
            await self._event_queue.put(None)  # Signal EOF

    def start_reader(self) -> None:
        """Start the background reader task."""
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def initialize(self) -> None:
        """Start reader, send get_state to get session ID."""
        self.start_reader()

        cmd = json.dumps({"type": "get_state"}) + "\n"
        await self.ws.write_stdin(cmd.encode("utf-8"))

        # Read events from queue until we get the get_state response
        while True:
            line = await asyncio.wait_for(self._event_queue.get(), timeout=15)
            if line is None:
                break
            event = parse_pi_event(line)
            if event and event.type == "response" and event.data.get("command") == "get_state":
                self.session_id = event.data.get("data", {}).get("sessionId")
                break
            # Skip extension_ui_request and other init events

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
