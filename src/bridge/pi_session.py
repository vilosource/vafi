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
    vtf_api_url: str = "",
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
    if vtf_api_url:
        env["VTF_API_URL"] = vtf_api_url

    return env


class PiSession:
    """Manages a single Pi RPC interaction."""

    def __init__(self, config: PiSessionConfig):
        self.config = config

    def build_command(self) -> list[str]:
        """Build the Pi CLI command. Design spec: --mode rpc for all sessions."""
        cmd = [
            "pi",
            "--mode", "rpc",
            "--provider", self.config.provider,
            "--model", self.config.model,
            "--no-session",
        ]
        if self.config.methodology:
            cmd.extend(["--append-system-prompt", self.config.methodology])
        if self.config.thinking_level:
            cmd.extend(["--thinking", self.config.thinking_level])
        if self.config.max_turns > 0:
            cmd.extend(["--max-turns", str(self.config.max_turns)])
        return cmd

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
        """Spawn Pi in --mode rpc, send prompt, collect response, shutdown.

        Per design: ephemeral sessions use --mode rpc --no-session.
        Send prompt command via stdin, read events from stdout until agent_end,
        then send shutdown command.
        """
        cmd = self.build_command()
        logger.info(f"Ephemeral Pi RPC: {' '.join(cmd[:5])}...")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            from .pi_protocol import pi_handshake

            all_output_lines = []

            async def _write(data: bytes) -> None:
                process.stdin.write(data)
                await process.stdin.drain()

            async def _read() -> str | None:
                try:
                    line_bytes = await asyncio.wait_for(process.stdout.readline(), timeout=15)
                except asyncio.TimeoutError:
                    return None
                if not line_bytes:
                    return None
                line = line_bytes.decode("utf-8").rstrip("\n")
                return line if line.strip() else await _read()

            session_id = await pi_handshake(write_fn=_write, read_fn=_read)
            if session_id:
                all_output_lines.append(json.dumps({"type": "session", "id": session_id}))

            # Send prompt command via stdin
            prompt_cmd = json.dumps({"type": "prompt", "message": prompt}) + "\n"
            process.stdin.write(prompt_cmd.encode("utf-8"))
            await process.stdin.drain()

            # Read events until agent_end
            while True:
                try:
                    line_bytes = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=self.config.timeout,
                    )
                except asyncio.TimeoutError:
                    logger.error("Pi RPC read timed out")
                    process.kill()
                    await process.wait()
                    return {**self.parse_output(""), "error": "Pi process timed out"}

                if not line_bytes:
                    break  # EOF

                line = line_bytes.decode("utf-8").rstrip("\n")
                if not line.strip():
                    continue

                all_output_lines.append(line)
                event = parse_pi_event(line)
                if event and event.type == "agent_end":
                    break

            # Send shutdown
            try:
                shutdown_cmd = json.dumps({"type": "shutdown"}) + "\n"
                process.stdin.write(shutdown_cmd.encode("utf-8"))
                await process.stdin.drain()
                process.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass

            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

            return self.parse_output("\n".join(all_output_lines))

        except Exception as e:
            logger.error(f"Ephemeral Pi error: {e}")
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            return {**self.parse_output(""), "error": str(e)}

    async def stream_ephemeral(self, prompt: str, env: dict[str, str] | None = None) -> AsyncIterator[str]:
        """Spawn Pi in --mode rpc, yield JSONL lines as they arrive."""
        cmd = self.build_command()
        logger.info(f"Streaming ephemeral Pi RPC: {' '.join(cmd[:5])}...")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            from .pi_protocol import pi_handshake

            async def _write(data: bytes) -> None:
                process.stdin.write(data)
                await process.stdin.drain()

            async def _read() -> str | None:
                try:
                    line_bytes = await asyncio.wait_for(process.stdout.readline(), timeout=15)
                except asyncio.TimeoutError:
                    return None
                if not line_bytes:
                    return None
                line = line_bytes.decode("utf-8").rstrip("\n")
                return line if line.strip() else await _read()

            session_id = await pi_handshake(write_fn=_write, read_fn=_read)
            if session_id:
                yield json.dumps({"type": "session", "id": session_id})

            # Send prompt
            prompt_cmd = json.dumps({"type": "prompt", "message": prompt}) + "\n"
            process.stdin.write(prompt_cmd.encode("utf-8"))
            await process.stdin.drain()

            # Yield lines until agent_end
            while True:
                try:
                    line_bytes = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=self.config.timeout,
                    )
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "error", "message": "Pi process timed out"})
                    break

                if not line_bytes:
                    break

                line = line_bytes.decode("utf-8").rstrip("\n")
                if line.strip():
                    yield line
                    event = parse_pi_event(line)
                    if event and event.type == "agent_end":
                        break

            # Shutdown
            try:
                shutdown_cmd = json.dumps({"type": "shutdown"}) + "\n"
                process.stdin.write(shutdown_cmd.encode("utf-8"))
                await process.stdin.drain()
                process.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass

            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

        except Exception as e:
            logger.error(f"Streaming Pi error: {e}")
            yield json.dumps({"type": "error", "message": str(e)})
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass


# Required for json.dumps in prompt commands
import json
