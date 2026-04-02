"""Pi RPC session management.

Handles spawning Pi processes in --mode rpc, sending prompts via JSONL
stdin, and collecting responses from stdout. Used for both ephemeral
(spawn-per-request) and persistent (locked) sessions.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .pi_events import parse_pi_event

logger = logging.getLogger(__name__)


@dataclass
class PiSessionConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    thinking_level: str = "medium"
    methodology: str = ""
    max_turns: int = 50
    timeout: int = 120


@dataclass
class ManagedProcess:
    """Tracks a running Pi RPC process — ephemeral or persistent."""
    session_id: str
    project: str
    role: str
    user: str
    process: Any  # asyncio.subprocess.Process or exec WebSocket
    lock: asyncio.Lock
    started_at: float
    last_activity: float
    prompt_count: int = 0


def build_pi_env(
    project: str,
    role: str,
    vtf_mcp_url: str = "",
    vtf_token: str = "",
    cxdb_mcp_url: str = "",
    otel_endpoint: str = "",
) -> dict[str, str]:
    """Build environment variables for a Pi RPC process per design spec."""
    env = dict(os.environ)
    env["VTF_PROJECT_SLUG"] = project

    if vtf_mcp_url:
        env["VF_VTF_MCP_URL"] = vtf_mcp_url
    if vtf_token:
        env["VF_VTF_TOKEN"] = vtf_token
    if cxdb_mcp_url:
        env["VF_CXDB_MCP_URL"] = cxdb_mcp_url
    if otel_endpoint:
        env["PI_OTEL_ENDPOINT"] = otel_endpoint
        env["PI_OTEL_PROTOCOL"] = "http/protobuf"

    return env


class PiSession:
    """Manages a single Pi RPC interaction."""

    def __init__(self, config: PiSessionConfig):
        self.config = config

    def build_command(self) -> list[str]:
        """Build harness command. Uses /opt/vf-harness/run.sh for headless invocation."""
        return ["/opt/vf-harness/run.sh"]

    def parse_output(self, stdout: str) -> dict[str, Any]:
        """Parse Pi JSONL output into structured result."""
        session_id = None
        text = ""
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        cost_usd = 0.0
        num_turns = 0
        tool_uses: list[str] = []

        for line in stdout.strip().split("\n") if stdout.strip() else []:
            event = parse_pi_event(line)
            if event is None:
                continue

            if event.type == "session":
                session_id = event.data.get("id")
            elif event.type == "turn_end":
                num_turns += 1
            elif event.type == "tool_execution_start":
                tool_uses.append(event.data.get("toolName", "unknown"))
            elif event.type == "agent_end":
                messages = event.data.get("messages", [])
                for msg in reversed(messages):
                    if msg.get("role") == "assistant":
                        content = msg.get("content", [])
                        if content:
                            text = content[-1].get("text", "")
                        usage = msg.get("usage", {})
                        input_tokens = usage.get("input", 0)
                        output_tokens = usage.get("output", 0)
                        total_tokens = usage.get("totalTokens", 0)
                        cost_usd = usage.get("cost", {}).get("total", 0.0)
                        break

        return {
            "session_id": session_id,
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "num_turns": num_turns,
            "tool_uses": tool_uses,
        }

    async def run_ephemeral(self, prompt: str, env: dict[str, str] | None = None) -> dict[str, Any]:
        """Run harness via /opt/vf-harness/run.sh with VF_PROMPT env var.

        One-shot execution: set prompt in env, run script, read JSONL stdout.
        No RPC handshake — run.sh runs the harness CLI and exits.
        """
        cmd = self.build_command()
        logger.info(f"Ephemeral harness: {' '.join(cmd)}...")

        run_env = dict(env or os.environ)
        run_env["VF_PROMPT"] = prompt

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=run_env,
        )

        try:
            all_output_lines = []

            while True:
                try:
                    line_bytes = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=self.config.timeout,
                    )
                except asyncio.TimeoutError:
                    logger.error("Harness read timed out")
                    process.kill()
                    await process.wait()
                    return {**self.parse_output(""), "error": "Harness process timed out"}

                if not line_bytes:
                    break  # EOF — process exited

                line = line_bytes.decode("utf-8").rstrip("\n")
                if not line.strip():
                    continue

                all_output_lines.append(line)
                event = parse_pi_event(line)
                if event and event.type == "agent_end":
                    break

            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

            return self.parse_output("\n".join(all_output_lines))

        except Exception as e:
            logger.error(f"Ephemeral harness error: {e}")
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            return {**self.parse_output(""), "error": str(e)}

    async def stream_ephemeral(self, prompt: str, env: dict[str, str] | None = None) -> AsyncIterator[str]:
        """Run harness via run.sh, yield JSONL lines as they arrive."""
        cmd = self.build_command()
        logger.info(f"Streaming ephemeral harness: {' '.join(cmd)}...")

        run_env = dict(env or os.environ)
        run_env["VF_PROMPT"] = prompt

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=run_env,
        )

        try:
            while True:
                try:
                    line_bytes = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=self.config.timeout,
                    )
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "error", "message": "Harness process timed out"})
                    break

                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8").rstrip("\n")
                if line.strip():
                    yield line
                    event = parse_pi_event(line)
                    if event and event.type == "agent_end":
                        break

            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

        except Exception as e:
            logger.error(f"Streaming harness error: {e}")
            yield json.dumps({"type": "error", "message": str(e)})
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass


# Required for json.dumps in prompt commands
import json
