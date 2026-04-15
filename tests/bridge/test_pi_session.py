"""Tests for Pi RPC session management."""

import json

import pytest
from unittest.mock import AsyncMock, Mock, patch

from bridge.pi_session import PiSession, PiSessionConfig, ManagedProcess, build_pi_env
from bridge.pi_events import parse_pi_event
from bridge.roles import RoleConfig


class TestPiEvents:
    def test_parse_session_event(self):
        line = '{"type":"session","id":"sess-1","version":3}'
        event = parse_pi_event(line)
        assert event.type == "session"
        assert event.data["id"] == "sess-1"

    def test_parse_agent_end_event(self):
        line = json.dumps({
            "type": "agent_end",
            "messages": [
                {"role": "assistant", "content": [{"type": "text", "text": "done"}],
                 "usage": {"input": 54, "output": 5, "totalTokens": 100, "cost": {"total": 0.001}}}
            ]
        })
        event = parse_pi_event(line)
        assert event.type == "agent_end"
        assert event.data["messages"][0]["content"][0]["text"] == "done"

    def test_parse_turn_end_event(self):
        line = '{"type":"turn_end","message":{"role":"assistant"},"toolResults":[]}'
        event = parse_pi_event(line)
        assert event.type == "turn_end"

    def test_parse_text_delta_event(self):
        line = json.dumps({
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "hello"},
            "message": {"content": [{"type": "text", "text": "hello"}]}
        })
        event = parse_pi_event(line)
        assert event.type == "message_update"

    def test_parse_invalid_json_returns_none(self):
        event = parse_pi_event("not valid json")
        assert event is None

    def test_parse_empty_line_returns_none(self):
        event = parse_pi_event("")
        assert event is None


class TestManagedProcess:
    def test_dataclass_has_required_fields(self):
        """ManagedProcess must have all fields from design."""
        import asyncio
        import time
        mp = ManagedProcess(
            session_id="s1",
            project="proj",
            role="assistant",
            user="testuser",
            process=None,
            lock=asyncio.Lock(),
            started_at=time.monotonic(),
            last_activity=time.monotonic(),
            prompt_count=0,
        )
        assert mp.session_id == "s1"
        assert mp.project == "proj"
        assert mp.role == "assistant"
        assert mp.prompt_count == 0


class TestBuildPiEnv:
    def test_injects_vtf_mcp_vars(self):
        env = build_pi_env(
            project="my-proj",
            role="assistant",
            vtf_mcp_url="http://vtf-mcp:8002/mcp",
            vtf_token="tok-123",
            cxdb_mcp_url="http://cxdb-mcp:8090/mcp",
            otel_endpoint="",
        )
        assert env["VF_VTF_MCP_URL"] == "http://vtf-mcp:8002/mcp"
        assert env["VF_VTF_TOKEN"] == "tok-123"
        assert env["VTF_PROJECT_SLUG"] == "my-proj"
        assert env["VF_CXDB_MCP_URL"] == "http://cxdb-mcp:8090/mcp"

    def test_includes_otel_when_set(self):
        env = build_pi_env(
            project="p", role="r",
            vtf_mcp_url="", vtf_token="", cxdb_mcp_url="",
            otel_endpoint="http://otel:4318",
        )
        assert env["PI_OTEL_ENDPOINT"] == "http://otel:4318"

    def test_omits_empty_values(self):
        env = build_pi_env(
            project="p", role="r",
            vtf_mcp_url="", vtf_token="", cxdb_mcp_url="",
            otel_endpoint="",
        )
        assert "PI_OTEL_ENDPOINT" not in env
        assert "VF_VTF_MCP_URL" not in env

    def test_includes_vtf_api_url(self):
        env = build_pi_env(
            project="p", role="r",
            vtf_api_url="http://vtf-api:8000",
        )
        assert env["VTF_API_URL"] == "http://vtf-api:8000"

    def test_omits_vtf_api_url_when_empty(self):
        env = build_pi_env(
            project="p", role="r",
            vtf_api_url="",
        )
        assert "VTF_API_URL" not in env


class TestPiSession:
    def test_build_command_uses_rpc_mode(self):
        """Design spec: ephemeral uses --mode rpc --no-session."""
        config = PiSessionConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            methodology="/opt/vf-agent/methodologies/assistant.md",
        )
        session = PiSession(config)
        cmd = session.build_command()
        assert cmd[0] == "pi"
        assert "--mode" in cmd
        idx = cmd.index("--mode")
        assert cmd[idx + 1] == "rpc"
        assert "--no-session" in cmd
        assert "--provider" in cmd
        assert "--append-system-prompt" in cmd

    def test_build_command_with_thinking(self):
        config = PiSessionConfig(thinking_level="high")
        session = PiSession(config)
        cmd = session.build_command()
        assert "--thinking" in cmd
        assert "high" in cmd

    def test_build_command_with_max_turns(self):
        config = PiSessionConfig(max_turns=25)
        session = PiSession(config)
        cmd = session.build_command()
        assert "--max-turns" in cmd
        assert "25" in cmd

    def test_parse_output_extracts_input_tokens(self):
        """input_tokens must be parsed, not hardcoded to 0."""
        config = PiSessionConfig()
        session = PiSession(config)
        pi_output = "\n".join([
            '{"type":"session","id":"sess-abc","version":3}',
            '{"type":"turn_end","message":{"role":"assistant"},"toolResults":[]}',
            json.dumps({"type": "agent_end", "messages": [
                {"role": "assistant", "content": [{"type": "text", "text": "done"}],
                 "usage": {"input": 54, "output": 5, "totalTokens": 59, "cost": {"total": 0}}}
            ]}),
        ])
        result = session.parse_output(pi_output)
        assert result["input_tokens"] == 54
        assert result["output_tokens"] == 5
        assert result["total_tokens"] == 59

    def test_parse_output_session_and_turns(self):
        config = PiSessionConfig()
        session = PiSession(config)
        pi_output = "\n".join([
            '{"type":"session","id":"sess-abc","version":3}',
            '{"type":"turn_end","message":{},"toolResults":[]}',
            '{"type":"turn_end","message":{},"toolResults":[]}',
            json.dumps({"type": "agent_end", "messages": [
                {"role": "assistant", "content": [{"type": "text", "text": "All done"}],
                 "usage": {"input": 50, "output": 10, "totalTokens": 60, "cost": {"total": 0.005}}}
            ]}),
        ])
        result = session.parse_output(pi_output)
        assert result["session_id"] == "sess-abc"
        assert result["text"] == "All done"
        assert result["num_turns"] == 2

    def test_parse_output_empty(self):
        config = PiSessionConfig()
        session = PiSession(config)
        result = session.parse_output("")
        assert result["text"] == ""
        assert result["session_id"] is None
        assert result["num_turns"] == 0
        assert result["input_tokens"] == 0


class TestRoleConfigHarness:
    def test_role_has_harness_field(self):
        role = RoleConfig(session_type="ephemeral", harness="pi-rpc")
        assert role.harness == "pi-rpc"

    def test_role_harness_defaults(self):
        role = RoleConfig(session_type="ephemeral")
        assert role.harness == "pi-rpc"
