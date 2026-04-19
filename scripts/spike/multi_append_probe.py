#!/usr/bin/env python3
"""Verify Pi accepts multiple --append-system-prompt flags.

Plants two distinctive phrases (one per file), asks Pi to report which it sees.
Runs inside the architect pod.
"""
import json
import subprocess
import sys
import time

PROMPT = (
    "Look at your system prompt. Reply with ONE LINE containing exactly these "
    "two phrases, separated by a single space, in the order you find them: "
    "(1) the phrase that follows FIRST_ANCHOR_ALPHA, and (2) the phrase that "
    "follows SECOND_ANCHOR_BETA. If you cannot find one of them, write UNKNOWN "
    "in its place. Do not include anything else in your reply."
)

def run(cmd, label):
    print(f"\n=== {label} ===", flush=True)
    print(f"cmd: {' '.join(cmd)}", flush=True)
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)

    def send(obj):
        proc.stdin.write((json.dumps(obj) + "\n").encode())
        proc.stdin.flush()

    send({"type": "get_state"})
    prompt_sent = False
    final_text = ""
    accumulated_delta = ""
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            ev = json.loads(line.decode())
        except Exception:
            continue
        etype = ev.get("type")
        if etype == "response" and ev.get("command") == "get_state" and not prompt_sent:
            send({"type": "prompt", "message": PROMPT})
            prompt_sent = True
            continue
        if etype == "message_update":
            ae = ev.get("assistantMessageEvent", {})
            if ae.get("type") == "text_delta":
                accumulated_delta += ae.get("delta", "")
            continue
        if etype == "message":
            msg = ev.get("message", {})
            if msg.get("role") == "assistant" and msg.get("stopReason") in ("stop", "end_turn"):
                for c in reversed(msg.get("content", [])):
                    if c.get("type") == "text" and c.get("text"):
                        final_text = c["text"]
                        break
                break
        if etype == "agent_end":
            break
    if not final_text:
        final_text = accumulated_delta

    try:
        send({"type": "shutdown"})
        proc.stdin.close()
    except Exception:
        pass
    proc.wait(timeout=10)
    elapsed = time.monotonic() - t0
    print(f"elapsed: {elapsed:.1f}s", flush=True)
    print(f"response: {final_text!r}", flush=True)
    return final_text


MODEL = ["--provider", "anthropic", "--model", "claude-sonnet-4-20250514"]

# Single flag baseline (sanity)
single = run(
    ["pi", "--mode", "rpc", "--no-session", *MODEL,
     "--append-system-prompt", "/tmp/asp1.md"],
    "SINGLE-FLAG: only asp1",
)

# Two flags
double = run(
    ["pi", "--mode", "rpc", "--no-session", *MODEL,
     "--append-system-prompt", "/tmp/asp1.md",
     "--append-system-prompt", "/tmp/asp2.md"],
    "DOUBLE-FLAG: asp1 + asp2",
)

print("\n=== SUMMARY ===")
print(f"single:  {single!r}")
print(f"double:  {double!r}")

# Naive verdict
has_first_in_single = "thunder-peach" in single.lower()
has_first_in_double = "thunder-peach" in double.lower()
has_second_in_double = "velvet-lantern" in double.lower()
print(f"single sees thunder-peach: {has_first_in_single}")
print(f"double sees thunder-peach: {has_first_in_double}")
print(f"double sees velvet-lantern: {has_second_in_double}")

if has_first_in_double and has_second_in_double:
    print("\nVERDICT: Pi accepts multiple --append-system-prompt flags. Plan proceeds unchanged.")
elif has_second_in_double and not has_first_in_double:
    print("\nVERDICT: Pi only honors the LAST --append-system-prompt. Plan pivots: script must merge methodology + prior-context.")
elif has_first_in_double and not has_second_in_double:
    print("\nVERDICT: Pi only honors the FIRST --append-system-prompt. Plan pivots: methodology must come LAST.")
else:
    print("\nVERDICT: Inconclusive. Pi ignored both flags; likely behaves weirdly. Investigate.")
