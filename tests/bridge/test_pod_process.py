"""Tests for pod-based Pi process manager (locked sessions)."""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from bridge.pod_process import PodProcessManager, PodSession


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
        """Exec command writes models.json and mcp.json inline."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        cmd = mgr.build_exec_command(project="my-proj")
        script = cmd[2]
        assert "models.json" in script
        assert "mcp.json" in script
        # Should NOT reference init.sh
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
        """Exec command clones repo if /tmp/repo_url exists and .git doesn't."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        cmd = mgr.build_exec_command(project="my-proj")
        script = cmd[2]
        assert "git clone" in script
        assert "/tmp/repo_url" in script
        assert "! -d .git" in script


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
