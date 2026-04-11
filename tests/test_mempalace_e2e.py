"""
E2E tests for the vafi-claude-mempalace container image.

Uses the Claude Agent SDK to send prompts and observe tool calls
programmatically. Runs against a Docker container with mempalace
MCP tools registered.

Requirements:
    pip install claude-agent-sdk pytest pytest-asyncio

Usage:
    pytest tests/test_mempalace_e2e.py -v

Environment:
    ANTHROPIC_AUTH_TOKEN  — z.ai auth token (from vafi-secrets)
    ANTHROPIC_BASE_URL   — z.ai endpoint (default: https://api.z.ai/api/anthropic)
    MEMPALACE_IMAGE      — container image (default: vafi/vafi-claude-mempalace:latest)
"""

import asyncio
import os
import subprocess
import tempfile
import uuid

import pytest
import pytest_asyncio

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    query,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

IMAGE = os.environ.get("MEMPALACE_IMAGE", "vafi/vafi-claude-mempalace:latest")
AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")

pytestmark = pytest.mark.skipif(not AUTH_TOKEN, reason="ANTHROPIC_AUTH_TOKEN not set")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def docker_run(palace: str, workdir: str = "/workspace", extra_env: dict | None = None):
    """Build docker run args for a mempalace container."""
    name = f"mp-e2e-{uuid.uuid4().hex[:8]}"
    cmd = [
        "docker", "run", "--rm", "-d",
        "--name", name,
        "-v", f"{os.environ['HOME']}/.claude:/home/agent/.claude-host:ro",
        "-v", f"{os.environ['HOME']}/.claude.json:/home/agent/.claude-host.json:ro",
        "-v", f"mempalace-e2e-{palace}:/home/agent/.mempalace",
    ]
    if workdir:
        cmd += ["-v", f"{workdir}:/workspace"]
    cmd += [
        "--entrypoint", "/opt/mempalace/entrypoint-local.sh",
        IMAGE,
        "sleep", "infinity",
    ]
    container_id = subprocess.check_output(cmd, text=True).strip()
    return name, container_id


def docker_stop(name: str):
    subprocess.run(["docker", "stop", name], capture_output=True)


def docker_exec_claude(container_name: str, prompt: str, max_turns: int = 5) -> str:
    """Run claude headless inside a running container and return JSON result."""
    result = subprocess.run(
        [
            "docker", "exec", "-u", "agent", container_name,
            "claude", "-p", prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions",
            "--max-turns", str(max_turns),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout


def sdk_options(**overrides) -> ClaudeAgentOptions:
    """Build SDK options with z.ai auth and mempalace MCP."""
    defaults = dict(
        max_turns=5,
        permission_mode="bypassPermissions",
        mcp_servers={
            "mempalace": {
                "command": "python3",
                "args": ["-m", "mempalace.mcp_server"],
            }
        },
        allowed_tools=["mcp__mempalace__*", "Bash", "Read"],
        env={
            "ANTHROPIC_AUTH_TOKEN": AUTH_TOKEN,
            "ANTHROPIC_BASE_URL": BASE_URL,
        },
    )
    defaults.update(overrides)
    return ClaudeAgentOptions(**defaults)


async def collect_messages(prompt: str, **opts):
    """Send a prompt via SDK and collect all messages."""
    messages = []
    async for msg in query(prompt=prompt, options=sdk_options(**opts)):
        messages.append(msg)
    return messages


def get_result(messages) -> str:
    """Extract final result text from message list."""
    for msg in reversed(messages):
        if isinstance(msg, ResultMessage):
            return msg.result or ""
    return ""


def get_tool_calls(messages) -> list[str]:
    """Extract tool names called during the session."""
    tools = []
    for msg in messages:
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if hasattr(block, "name"):
                    tools.append(block.name)
    return tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def palace_a():
    """A test palace volume, cleaned up after module."""
    name = f"e2e-{uuid.uuid4().hex[:8]}"
    yield name
    subprocess.run(["docker", "volume", "rm", f"mempalace-e2e-{name}"],
                    capture_output=True)


@pytest.fixture(scope="module")
def palace_b():
    """A second isolated palace volume."""
    name = f"e2e-{uuid.uuid4().hex[:8]}"
    yield name
    subprocess.run(["docker", "volume", "rm", f"mempalace-e2e-{name}"],
                    capture_output=True)


@pytest.fixture(scope="module")
def container_a(palace_a):
    """Running container with palace A."""
    name, _ = docker_run(palace_a)
    yield name
    docker_stop(name)


@pytest.fixture(scope="module")
def container_b(palace_b):
    """Running container with palace B (isolated)."""
    name, _ = docker_run(palace_b)
    yield name
    docker_stop(name)


# ---------------------------------------------------------------------------
# Tests — SDK based (run locally, no container needed)
# ---------------------------------------------------------------------------


class TestSDK:
    """Tests using the Claude Agent SDK directly (no container)."""

    @pytest.mark.asyncio
    async def test_sdk_basic_response(self):
        """SDK can send a prompt and get a response."""
        messages = await collect_messages(
            "Reply with exactly: MEMPALACE_SDK_OK",
            max_turns=1,
            mcp_servers={},
            allowed_tools=[],
        )
        result = get_result(messages)
        assert "MEMPALACE_SDK_OK" in result

    @pytest.mark.asyncio
    async def test_sdk_mempalace_search_tool_called(self):
        """SDK observes mempalace_search being called."""
        messages = await collect_messages(
            'Use the mempalace_search tool with query "test" and wing "default". '
            "Report what you find."
        )
        tools = get_tool_calls(messages)
        assert any("mempalace_search" in t for t in tools), f"Expected mempalace_search in {tools}"

    @pytest.mark.asyncio
    async def test_sdk_mempalace_diary_write_read(self):
        """SDK observes diary write followed by diary read."""
        marker = f"sdk-marker-{uuid.uuid4().hex[:8]}"
        messages = await collect_messages(
            f'Use mempalace_diary_write with agent_name "sdk-test" '
            f'entry "{marker}" topic "testing". '
            f'Then use mempalace_diary_read with agent_name "sdk-test". '
            f"Report what you see.",
            max_turns=10,
        )
        tools = get_tool_calls(messages)
        assert any("mempalace_diary_write" in t for t in tools), f"diary_write not called: {tools}"
        assert any("mempalace_diary_read" in t for t in tools), f"diary_read not called: {tools}"
        result = get_result(messages)
        assert marker in result, f"Marker {marker} not in result"

    @pytest.mark.asyncio
    async def test_sdk_mempalace_kg_add_query(self):
        """SDK observes knowledge graph add and query."""
        entity = f"test-entity-{uuid.uuid4().hex[:6]}"
        messages = await collect_messages(
            f'Use mempalace_kg_add with subject "{entity}" predicate "is_a" '
            f'object "e2e_test" valid_from "2026-01-01". '
            f'Then use mempalace_kg_query with entity "{entity}". '
            f"Report the result.",
            max_turns=10,
        )
        tools = get_tool_calls(messages)
        assert any("mempalace_kg_add" in t for t in tools), f"kg_add not called: {tools}"
        assert any("mempalace_kg_query" in t for t in tools), f"kg_query not called: {tools}"


# ---------------------------------------------------------------------------
# Tests — Container based (verify image, auth, persistence)
# ---------------------------------------------------------------------------


class TestContainer:
    """Tests that run Claude Code inside the Docker container."""

    def test_container_claude_auth(self, container_a):
        """Claude Code authenticates via mounted ~/.claude credentials."""
        result = subprocess.run(
            ["docker", "exec", "-u", "agent", container_a, "claude", "auth", "status"],
            capture_output=True,
            text=True,
        )
        assert '"loggedIn": true' in result.stdout.lower() or '"loggedin": true' in result.stdout.lower()

    def test_container_mempalace_cli(self, container_a):
        """mempalace CLI works inside the container."""
        result = subprocess.run(
            ["docker", "exec", "-u", "agent", container_a, "mempalace", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "MemPalace" in result.stdout

    def test_container_mcp_registered(self, container_a):
        """mempalace MCP server is registered in Claude config."""
        result = subprocess.run(
            [
                "docker", "exec", "-u", "agent", container_a,
                "python3", "-c",
                "import json; "
                "d=json.load(open('/home/agent/.claude.json')); "
                "print('mempalace' in d.get('mcpServers', {}))",
            ],
            capture_output=True,
            text=True,
        )
        assert "True" in result.stdout

    def test_container_headless_execution(self, container_a):
        """Claude Code runs headless with JSON output inside container."""
        import json

        output = docker_exec_claude(container_a, "Reply with exactly: CONTAINER_OK")
        data = json.loads(output)
        assert not data.get("is_error", False)
        assert "CONTAINER_OK" in data.get("result", "")

    def test_container_mempalace_tools_available(self, container_a):
        """Claude Code can call mempalace MCP tools inside container."""
        import json

        output = docker_exec_claude(
            container_a,
            "Use the mempalace_status tool and tell me how many drawers exist. "
            "Reply with the number only.",
            max_turns=5,
        )
        data = json.loads(output)
        assert not data.get("is_error", False)

    def test_palace_isolation(self, container_a, container_b):
        """Data in palace A is not visible from palace B."""
        import json

        marker = f"isolation-{uuid.uuid4().hex[:8]}"

        # Write to palace A
        docker_exec_claude(
            container_a,
            f'Use mempalace_diary_write with agent_name "isolator" '
            f'entry "{marker}" topic "isolation".',
        )

        # Read from palace B — should not find it
        output = docker_exec_claude(
            container_b,
            'Use mempalace_diary_read with agent_name "isolator". '
            f'Does it contain "{marker}"? Reply FOUND or NOT_FOUND only.',
        )
        data = json.loads(output)
        assert "NOT_FOUND" in data.get("result", ""), "Palace isolation violated"

    def test_workspace_mount_writable(self, palace_a):
        """Files created in /workspace appear on the host."""
        with tempfile.TemporaryDirectory() as tmpdir:
            name, _ = docker_run(palace_a, workdir=tmpdir)
            try:
                docker_exec_claude(
                    name,
                    'Create a file /workspace/e2e-proof.txt containing "mp-ok". '
                    "Use bash. Reply DONE.",
                )
                proof = os.path.join(tmpdir, "e2e-proof.txt")
                assert os.path.exists(proof), "File not created on host"
                assert "mp-ok" in open(proof).read()
            finally:
                docker_stop(name)
