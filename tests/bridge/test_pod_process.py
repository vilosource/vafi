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
    async def test_pod_name_sanitized(self):
        """Pod name must be valid k8s label (lowercase, alphanumeric, hyphens)."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        spec = mgr.build_pod_spec(project="My_Project!", user="User.Name", role="architect", env_vars={})
        name = spec["metadata"]["name"]
        assert name.islower() or "-" in name
        assert all(c.isalnum() or c == "-" for c in name)

    def test_exec_command_uses_connect_sh(self):
        """Exec command uses /opt/vf-harness/connect.sh for all harnesses."""
        mgr = PodProcessManager(namespace="vafi-dev", image="img:latest")
        cmd = mgr.build_exec_command()
        assert cmd == ["/opt/vf-harness/connect.sh"]


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
