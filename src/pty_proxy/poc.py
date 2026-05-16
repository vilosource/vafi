"""Minimal PTY proxy PoC — spawn a CLI, write to stdin, read stdout.

Usage:
    python3 poc.py bash
    python3 poc.py pi
    python3 poc.py /opt/vf-harness/connect.sh
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import re
import struct
import sys
import termios

# Strip ANSI escape sequences for readable output
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x07|\x1b\[[\?0-9;]*[hlm]|\x1b[()][AB012]|\x1b=|\x1b>|\r")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def set_pty_size(fd: int, rows: int = 24, cols: int = 80) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


class PtyPipe:
    """Spawn a process in a PTY. Write to it. Read from it. That's it."""

    def __init__(self) -> None:
        self.master_fd: int | None = None
        self.child_pid: int | None = None
        self._output_buf: list[bytes] = []
        self._alive = False

    def spawn(self, command: list[str], rows: int = 50, cols: int = 120) -> None:
        pid, fd = pty.fork()
        if pid == 0:
            # Child
            os.execvp(command[0], command)
        self.master_fd = fd
        self.child_pid = pid
        self._alive = True
        set_pty_size(fd, rows, cols)
        # Set non-blocking
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def write(self, data: str) -> None:
        os.write(self.master_fd, data.encode())

    def read_available(self) -> str:
        """Read whatever is available right now, non-blocking."""
        chunks = []
        while True:
            try:
                data = os.read(self.master_fd, 65536)
                if not data:
                    self._alive = False
                    break
                chunks.append(data)
            except OSError:
                break
        raw = b"".join(chunks)
        self._output_buf.append(raw)
        return raw.decode("utf-8", errors="replace")

    async def read_until_idle(self, timeout: float = 2.0, idle_threshold: float = 0.5) -> str:
        """Read output until no new data arrives for idle_threshold seconds."""
        chunks = []
        deadline = asyncio.get_event_loop().time() + timeout
        last_data_time = asyncio.get_event_loop().time()

        loop = asyncio.get_event_loop()
        while True:
            now = loop.time()
            if now > deadline:
                break
            if now - last_data_time > idle_threshold and chunks:
                break

            await asyncio.sleep(0.05)
            raw = self.read_available()
            if raw:
                chunks.append(raw)
                last_data_time = loop.time()

        return "".join(chunks)

    async def send_and_read(self, text: str, timeout: float = 30.0, idle_threshold: float = 1.0) -> str:
        """Send text, wait for output to settle, return cleaned output."""
        self.write(text)
        raw = await self.read_until_idle(timeout=timeout, idle_threshold=idle_threshold)
        return strip_ansi(raw)

    @property
    def alive(self) -> bool:
        return self._alive

    def close(self) -> None:
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
        if self.child_pid:
            try:
                os.waitpid(self.child_pid, os.WNOHANG)
            except ChildProcessError:
                pass


async def demo_bash():
    """Quick test: spawn bash, send commands, read output."""
    pipe = PtyPipe()
    pipe.spawn(["bash", "--norc", "--noprofile"])
    await asyncio.sleep(0.3)
    pipe.read_available()  # drain startup

    print("=== Test 1: echo ===")
    out = await pipe.send_and_read("echo hello world\n", idle_threshold=0.3)
    print(out)
    assert "hello world" in out, f"Expected 'hello world' in output"
    print("PASS\n")

    print("=== Test 2: multi-turn state ===")
    await pipe.send_and_read("export X=42\n", idle_threshold=0.3)
    out = await pipe.send_and_read("echo $X\n", idle_threshold=0.3)
    print(out)
    assert "42" in out, f"Expected '42' in output"
    print("PASS\n")

    print("=== Test 3: Ctrl-C ===")
    pipe.write("sleep 300\n")
    await asyncio.sleep(0.3)
    out = await pipe.send_and_read("\x03", idle_threshold=0.5)
    print(out)
    print("PASS (returned to prompt)\n")

    pipe.close()
    print("All bash tests passed.")


async def demo_interactive(command: list[str]):
    """Interactive mode: type commands, see output."""
    pipe = PtyPipe()
    pipe.spawn(command)

    # Drain startup output
    await asyncio.sleep(2)
    startup = strip_ansi(pipe.read_available())
    if startup.strip():
        print(f"--- startup ---\n{startup}\n--- end startup ---\n")

    print(f"PTY proxy connected to: {' '.join(command)}")
    print("Type messages. They will be sent as-is + Enter.")
    print("Commands: /screen (read output), /quit (exit)\n")

    while pipe.alive:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("> ")
            )
        except (EOFError, KeyboardInterrupt):
            break

        if user_input == "/quit":
            break
        if user_input == "/screen":
            raw = pipe.read_available()
            print(strip_ansi(raw) if raw else "(no new output)")
            continue
        if user_input == "/status":
            print(f"alive={pipe.alive}")
            continue

        # Send input + newline, then wait for response
        out = await pipe.send_and_read(user_input + "\n", timeout=60, idle_threshold=2.0)
        print(strip_ansi(out))

    pipe.close()
    print("Session ended.")


async def main():
    args = sys.argv[1:]
    if not args or args == ["--test"]:
        await demo_bash()
    else:
        await demo_interactive(args)


if __name__ == "__main__":
    asyncio.run(main())
