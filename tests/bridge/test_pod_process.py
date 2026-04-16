"""Tests for pod-based Pi process manager (locked sessions)."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from bridge.pod_process import PodProcessManager, PodSession, PodExecConnection


class TestPodProcessManager:
    @pytest.mark.asyncio
    async def test_create_pod_spec(self):
        """Pod spec uses vafi-agent-pi image and correct env vars."""
        mgr = PodProcessManager(
            namespace="vafi-dev",
            image="harbor.viloforge.com/vafi/vafi-agent-pi:latest",
        )
        spec = mgr.build_pod_spec(
            project="my-proj",
            user="testuser",
            role="architect",
            env_vars={"ANTHROPIC_API_KEY": "test-key"},
        )
        assert spec["metadata"]["name"].startswith("architect-my-proj-testuser")
        assert spec["spec"]["containers"][0]["image"] == "harbor.viloforge.com/vafi/vafi-agent-pi:latest"
        assert spec["spec"]["containers"][0]["command"] == ["sleep", "infinity"]
        # Env vars present
        env_names = [e["name"] for e in spec["spec"]["containers"][0]["env"]]
        assert "ANTHROPIC_API_KEY" in env_names

    @pytest.mark.asyncio
    async def test_pod_spec_uses_pvc(self):
        """Pod spec mounts sessions PVC instead of emptyDir."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest", sessions_pvc="console-sessions")
        spec = mgr.build_pod_spec(project="proj", user="user", role="architect", env_vars={})
        volumes = spec["spec"]["volumes"]
        sessions_vol = next(v for v in volumes if v["name"] == "sessions")
        assert "persistentVolumeClaim" in sessions_vol
        assert sessions_vol["persistentVolumeClaim"]["claimName"] == "console-sessions"
        # Should NOT have emptyDir for sessions
        assert "emptyDir" not in sessions_vol

    @pytest.mark.asyncio
    async def test_pod_spec_has_ssh_secret(self):
        """Pod spec mounts github-ssh secret for git clone."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        spec = mgr.build_pod_spec(project="proj", user="user", role="architect", env_vars={})
        volumes = spec["spec"]["volumes"]
        ssh_vol = next(v for v in volumes if v["name"] == "github-ssh")
        assert ssh_vol["secret"]["secretName"] == "github-ssh"
        # Volume mount should be readonly
        mounts = spec["spec"]["containers"][0]["volumeMounts"]
        ssh_mount = next(m for m in mounts if m["name"] == "github-ssh")
        assert ssh_mount["readOnly"] is True
        assert ssh_mount["mountPath"] == "/home/agent/.ssh"

    @pytest.mark.asyncio
    async def test_pod_spec_has_home_emptydir(self):
        """Pod spec has ephemeral home volume for agent config."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        spec = mgr.build_pod_spec(project="proj", user="user", role="architect", env_vars={})
        volumes = spec["spec"]["volumes"]
        home_vol = next(v for v in volumes if v["name"] == "home")
        assert "emptyDir" in home_vol

    @pytest.mark.asyncio
    async def test_pod_spec_custom_pvc_name(self):
        """PVC name is configurable via constructor."""
        mgr = PodProcessManager(namespace="ns", image="img:latest", sessions_pvc="custom-pvc")
        spec = mgr.build_pod_spec(project="proj", user="user", role="architect", env_vars={})
        volumes = spec["spec"]["volumes"]
        sessions_vol = next(v for v in volumes if v["name"] == "sessions")
        assert sessions_vol["persistentVolumeClaim"]["claimName"] == "custom-pvc"

    @pytest.mark.asyncio
    async def test_pod_name_sanitized(self):
        """Pod name must be valid k8s label (lowercase, alphanumeric, hyphens)."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        spec = mgr.build_pod_spec(project="My_Project!", user="User.Name", role="architect", env_vars={})
        name = spec["metadata"]["name"]
        assert name.islower() or "-" in name
        assert all(c.isalnum() or c == "-" for c in name)

    @pytest.mark.asyncio
    async def test_exec_command_uses_rpc_mode(self):
        """Pi exec command uses bash -c wrapper with --mode rpc and --session-dir."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        cmd = mgr.build_exec_command(
            project="my-proj",
            methodology="/opt/vf-agent/methodologies/architect.md",
        )
        assert cmd[0] == "bash"
        assert cmd[1] == "-c"
        script = cmd[2]
        assert "--mode rpc" in script
        assert "--session-dir" in script

    @pytest.mark.asyncio
    async def test_exec_command_writes_pi_config(self):
        """Exec command delegates to pi_config.py (writes models.json, mcp.json)."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        cmd = mgr.build_exec_command(project="my-proj")
        script = cmd[2]
        assert "pi_config.py" in script
        # Should NOT reference init.sh (retired when pi_config was extracted)
        assert "init.sh" not in script

    @pytest.mark.asyncio
    async def test_exec_command_includes_hydration(self):
        """Exec command runs hydrate_context.py before Pi starts."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        cmd = mgr.build_exec_command(project="my-proj")
        script = cmd[2]
        assert "hydrate_context.py" in script
        assert "/sessions/my-proj/" in script
        # Hydration output goes to stderr (stdout reserved for Pi RPC)
        assert "1>&2" in script
        # Non-fatal
        assert "|| true" in script

    @pytest.mark.asyncio
    async def test_exec_command_includes_conditional_clone(self):
        """Exec command clones repo into /sessions/{slug}/repo/ when repo_url present."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        cmd = mgr.build_exec_command(project="my-proj")
        script = cmd[2]
        assert "git clone" in script
        assert "/tmp/repo_url" in script
        # Clones into repo/ subdirectory (not session dir itself) so it
        # doesn't collide with accumulating Pi .jsonl session files.
        assert "/sessions/my-proj/repo/" in script
        # Guard against re-clone when .git already exists in the repo/ subdir.
        assert "repo/.git" in script

    @pytest.mark.asyncio
    async def test_exec_command_two_phase_hydrate(self):
        """Hydrate runs twice: once for repo_url before clone, once for full context after."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        cmd = mgr.build_exec_command(project="my-proj")
        script = cmd[2]
        assert "--repo-url-only" in script
        # Full-context hydration points at the repo/ subdir so
        # PROJECT_CONTEXT.md lands inside the cloned checkout.
        assert "hydrate_context.py /sessions/my-proj/repo/" in script

    @pytest.mark.asyncio
    async def test_exec_command_cd_into_repo(self):
        """Pi runs with cwd inside the repo so bash tools operate on project source."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        cmd = mgr.build_exec_command(project="my-proj")
        script = cmd[2]
        assert "cd /sessions/my-proj/repo/ && exec pi" in script


class TestPodSession:
    @pytest.mark.asyncio
    async def test_send_prompt_and_collect(self):
        """PodSession sends prompt via exec stdin and collects response."""
        # For PodSession with reader task, we feed events through the queue directly
        session = PodSession(ws=AsyncMock(), session_id="locked-sess-1")

        # Pre-populate the event queue with the expected events
        events = [
            json.dumps({"type": "response", "command": "prompt", "success": True}),
            json.dumps({"type": "agent_start"}),
            json.dumps({"type": "turn_start"}),
            json.dumps({"type": "turn_end", "message": {"role": "assistant"}, "toolResults": []}),
            json.dumps({"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": "Hello"}], "usage": {"input": 50, "output": 5, "totalTokens": 55, "cost": {"total": 0}}}]}),
        ]
        for e in events:
            await session._event_queue.put(e)

        result = await session.send_prompt("Hello")

        assert result["text"] == "Hello"
        assert result["session_id"] == "locked-sess-1"
        assert result["num_turns"] == 1

    @pytest.mark.asyncio
    async def test_session_id_from_get_state(self):
        """Session ID is extracted from get_state response on initialize."""
        mock_ws = AsyncMock()

        session = PodSession(ws=mock_ws, session_id=None)

        # Put the get_state response in the queue (simulating the reader task)
        get_state_resp = json.dumps({"type": "response", "command": "get_state", "success": True, "data": {"sessionId": "from-get-state"}})
        await session._event_queue.put(get_state_resp)

        # Mock start_reader to not actually start a task (no real ws)
        session.start_reader = lambda: None
        await session.initialize()

        assert session.session_id == "from-get-state"

    @pytest.mark.asyncio
    async def test_stream_prompt_breaks_on_message_stop(self):
        """stream_prompt terminates when assistant message has stopReason='stop'."""
        session = PodSession(ws=AsyncMock(), session_id="sess-1")
        session._alive = True

        events = [
            json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Hi"}}),
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi"}], "stopReason": "stop", "usage": {"input": 10, "output": 2}}}),
            # This should NOT be yielded — stream should have broken already
            json.dumps({"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "next"}]}}),
        ]
        for e in events:
            await session._event_queue.put(e)

        collected = []
        async for line in session.stream_prompt("hello"):
            collected.append(line)

        # Should have: session event + 2 yielded lines (message_update + message with stop)
        # The third event (user message) should NOT appear
        types = [json.loads(l).get("type") for l in collected]
        assert "session" in types  # session_id yield
        assert "message_update" in types
        assert any(
            json.loads(l).get("type") == "message"
            and json.loads(l).get("message", {}).get("stopReason") == "stop"
            for l in collected
        )
        # The user message after stop should NOT be in collected
        assert not any(
            json.loads(l).get("message", {}).get("role") == "user"
            for l in collected
        )

    @pytest.mark.asyncio
    async def test_stream_prompt_breaks_on_agent_end(self):
        """stream_prompt still terminates on agent_end (backward compatible)."""
        session = PodSession(ws=AsyncMock(), session_id="sess-1")
        session._alive = True

        events = [
            json.dumps({"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": "Done"}], "usage": {"input": 10, "output": 2}}]}),
            json.dumps({"type": "should_not_appear"}),
        ]
        for e in events:
            await session._event_queue.put(e)

        collected = []
        async for line in session.stream_prompt("hello"):
            collected.append(line)

        types = [json.loads(l).get("type") for l in collected]
        assert "agent_end" in types
        assert "should_not_appear" not in types

    @pytest.mark.asyncio
    async def test_stream_prompt_breaks_on_end_turn(self):
        """stream_prompt terminates on stopReason='end_turn' as well."""
        session = PodSession(ws=AsyncMock(), session_id="sess-1")
        session._alive = True

        events = [
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}], "stopReason": "end_turn", "usage": {"input": 5, "output": 1}}}),
        ]
        for e in events:
            await session._event_queue.put(e)

        collected = []
        async for line in session.stream_prompt("hi"):
            collected.append(line)

        # Should terminate cleanly with session + message
        assert len(collected) == 2  # session yield + message

    @pytest.mark.asyncio
    async def test_stream_prompt_does_not_break_on_tooluse_message(self):
        """stream_prompt does NOT break on assistant message with stopReason='toolUse'."""
        session = PodSession(ws=AsyncMock(), session_id="sess-1")
        session._alive = True

        events = [
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "toolCall"}], "stopReason": "toolUse"}}),
            json.dumps({"type": "message", "message": {"role": "toolResult", "content": [{"type": "text", "text": "result"}]}}),
            json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done"}], "stopReason": "stop", "usage": {"input": 10, "output": 5}}}),
        ]
        for e in events:
            await session._event_queue.put(e)

        collected = []
        async for line in session.stream_prompt("do something"):
            collected.append(line)

        # All 3 events should be yielded (plus session), then break on stop
        types = [json.loads(l).get("type") for l in collected]
        assert types.count("message") == 3  # toolUse msg + toolResult + stop msg


class TestPodExecConnectionReadStdout:
    """Tests for PodExecConnection.read_stdout empty-line handling."""

    @pytest.mark.asyncio
    async def test_read_stdout_skips_empty_lines(self):
        """read_stdout skips empty lines and returns next non-empty line."""
        import aiohttp

        # Simulate ws that sends "line1\n\n\nline2\n" in one frame
        mock_ws = AsyncMock()
        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.BINARY
        # Channel 1 (stdout) + payload with embedded empty lines
        msg.data = bytes([1]) + b'{"type":"event1"}\n\n\n{"type":"event2"}\n'
        mock_ws.receive = AsyncMock(return_value=msg)

        conn = PodExecConnection(ws=mock_ws, ws_ctx=MagicMock(), ws_client=MagicMock())

        line1 = await conn.read_stdout()
        assert line1 == b'{"type":"event1"}'

        line2 = await conn.read_stdout()
        assert line2 == b'{"type":"event2"}'

    @pytest.mark.asyncio
    async def test_read_stdout_eof_on_ws_close(self):
        """read_stdout returns b'' on WebSocket close (true EOF)."""
        import aiohttp

        mock_ws = AsyncMock()
        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.CLOSE
        mock_ws.receive = AsyncMock(return_value=msg)

        conn = PodExecConnection(ws=mock_ws, ws_ctx=MagicMock(), ws_client=MagicMock())
        result = await conn.read_stdout()
        assert result == b""
