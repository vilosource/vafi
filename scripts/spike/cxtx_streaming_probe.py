#!/usr/bin/env python3
"""Spike: Pi-RPC streaming behavior — raw vs cxtx-wrapped.

Run inside an architect pod where ANTHROPIC_API_KEY and the pi+cxtx binaries
are available.

Usage:
    python3 cxtx_streaming_probe.py raw
    python3 cxtx_streaming_probe.py cxtx

Outputs JSON stats to stdout (last line) and human-readable progress above.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

PROMPT = (
    "Count from 1 to 30, one number per line. Output only the numbers, nothing else."
)
MODEL = "claude-sonnet-4-20250514"
PROVIDER = "anthropic"


def cxdb_url() -> str:
    host = os.environ.get("VAFI_CXDB_SERVICE_HOST", "vafi-cxdb.vafi-dev.svc.cluster.local")
    port = os.environ.get("VAFI_CXDB_SERVICE_PORT_HTTP", "80")
    return f"http://{host}:{port}"


def build_cmd(mode: str, label_value: str) -> list[str]:
    pi_args = [
        "pi", "--mode", "rpc", "--no-session",
        "--provider", PROVIDER, "--model", MODEL,
    ]
    if mode == "raw":
        return pi_args
    if mode == "cxtx":
        return [
            "cxtx", "--url", cxdb_url(),
            "--label", f"spike-streaming:{label_value}",
            "pi", "--",
            "--mode", "rpc", "--no-session",
            "--provider", PROVIDER, "--model", MODEL,
        ]
    raise SystemExit(f"unknown mode: {mode}")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "raw"
    label = sys.argv[2] if len(sys.argv) > 2 else f"run-{int(time.time())}"

    cmd = build_cmd(mode, label)
    print(f"[spike] mode={mode} label={label}", flush=True)
    print(f"[spike] cmd: {' '.join(cmd)}", flush=True)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    t_start = time.monotonic()
    session_seen_at = None
    text_deltas: list[tuple[float, str]] = []
    all_events: list[tuple[float, str]] = []
    final_text = ""
    session_id = ""
    completion_reason = ""

    prompt_sent = False
    prompt_sent_at = None
    handshake_sent = False

    def send(obj: dict) -> None:
        proc.stdin.write((json.dumps(obj) + "\n").encode())
        proc.stdin.flush()

    # Send get_state handshake immediately
    send({"type": "get_state"})
    handshake_sent = True
    print(f"[  0.00s] sent get_state handshake", flush=True)

    while True:
        line = proc.stdout.readline()
        if not line:
            break
        t = time.monotonic() - t_start
        try:
            ev = json.loads(line.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"[{t:6.2f}s] non-JSON: {line[:80]!r}", flush=True)
            continue

        etype = ev.get("type", "?")
        all_events.append((t, etype))

        # Handshake response: get_state returns session id
        if etype == "response" and ev.get("command") == "get_state" and not prompt_sent:
            # data may be at top level or nested
            data_field = ev.get("data", {})
            session_id = data_field.get("sessionId", "") or ev.get("sessionId", "")
            session_seen_at = t
            print(f"[{t:6.2f}s] handshake response, session_id={session_id!r}", flush=True)
            send({"type": "prompt", "message": PROMPT})
            prompt_sent = True
            prompt_sent_at = t
            continue

        if etype == "message_update":
            # NOTE: pi RPC raw line has assistantMessageEvent at top level
            ae = ev.get("assistantMessageEvent", {})
            ae_type = ae.get("type", "")
            if ae_type == "text_delta":
                delta = ae.get("delta", "")
                text_deltas.append((t, delta))
                final_text += delta
                if len(text_deltas) <= 3 or len(text_deltas) % 10 == 0:
                    print(f"[{t:6.2f}s] text_delta #{len(text_deltas)} ({len(delta)} chars)", flush=True)
            elif len(all_events) <= 30:
                print(f"[{t:6.2f}s] message_update.ae.type={ae_type!r} top_keys={sorted(ev.keys())}", flush=True)
            continue

        if etype == "message" and len(all_events) <= 30:
            msg = ev.get("message", {})
            print(f"[{t:6.2f}s] message role={msg.get('role')!r} stopReason={msg.get('stopReason')!r} top_keys={sorted(ev.keys())}", flush=True)

        if etype == "message":
            msg = ev.get("message", {})
            if msg.get("role") == "assistant":
                stop = msg.get("stopReason", "")
                if stop in ("stop", "end_turn"):
                    completion_reason = f"message:{stop}"
                    # Extract final text from message content
                    content = msg.get("content", [])
                    for c in reversed(content):
                        if c.get("type") == "text" and c.get("text"):
                            if not final_text:
                                final_text = c["text"]
                            break
                    print(f"[{t:6.2f}s] message complete stopReason={stop}", flush=True)
                    break
            continue

        if etype == "agent_end":
            completion_reason = "agent_end"
            print(f"[{t:6.2f}s] agent_end", flush=True)
            break

        if etype == "error":
            print(f"[{t:6.2f}s] ERROR: {ev}", flush=True)
            completion_reason = "error"
            break

    # Send shutdown
    try:
        send({"type": "shutdown"})
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass

    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)

    stderr_tail = proc.stderr.read().decode(errors="replace")[-500:] if proc.stderr else ""

    # Stats
    inter_chunk_ms: list[float] = []
    if len(text_deltas) >= 2:
        for i in range(1, len(text_deltas)):
            inter_chunk_ms.append((text_deltas[i][0] - text_deltas[i - 1][0]) * 1000)

    def median(xs: list[float]) -> float:
        if not xs:
            return 0.0
        s = sorted(xs)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    stats = {
        "mode": mode,
        "label": label,
        "cmd": cmd,
        "completion_reason": completion_reason,
        "session_id": session_id,
        "session_ready_at_s": session_seen_at,
        "prompt_sent_at_s": prompt_sent_at,
        "first_text_delta_s": text_deltas[0][0] if text_deltas else None,
        "last_text_delta_s": text_deltas[-1][0] if text_deltas else None,
        "time_to_first_token_s": (text_deltas[0][0] - prompt_sent_at) if text_deltas and prompt_sent_at else None,
        "text_delta_count": len(text_deltas),
        "all_event_count": len(all_events),
        "all_event_types": sorted(set(t for _, t in all_events)),
        "inter_chunk_ms_count": len(inter_chunk_ms),
        "inter_chunk_ms_min": min(inter_chunk_ms) if inter_chunk_ms else None,
        "inter_chunk_ms_median": median(inter_chunk_ms),
        "inter_chunk_ms_max": max(inter_chunk_ms) if inter_chunk_ms else None,
        "final_text_len": len(final_text),
        "final_text_preview": final_text[:300],
        "stderr_tail": stderr_tail,
    }

    print()
    print("=== STATS ===")
    print(f"  completion: {stats['completion_reason']}")
    print(f"  text_delta count: {stats['text_delta_count']}")
    print(f"  time-to-first-token: {stats['time_to_first_token_s']}")
    print(f"  inter-chunk ms (min/median/max): {stats['inter_chunk_ms_min']}/{stats['inter_chunk_ms_median']:.1f}/{stats['inter_chunk_ms_max']}")
    print(f"  final text preview: {stats['final_text_preview'][:120]!r}")
    if stderr_tail:
        print(f"  stderr tail: {stderr_tail[-200:]!r}")
    print()
    print("__STATS_JSON__:" + json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
