"""Bridge REPL — interactive chat with vafi agents via the bridge API.

Supports both ephemeral (assistant) and locked (architect) sessions.
For locked sessions: acquires lock on start, releases on exit.
"""

import argparse
import json
import os
import sys

import httpx


def main():
    parser = argparse.ArgumentParser(description="vafi bridge REPL")
    parser.add_argument("--url", default=os.environ.get("BRIDGE_URL", "https://bridge.dev.viloforge.com"))
    parser.add_argument("--token", default=os.environ.get("VTF_TOKEN", ""))
    parser.add_argument("--project", default=os.environ.get("VTF_PROJECT", ""))
    parser.add_argument("--role", default="assistant")
    parser.add_argument("--no-stream", action="store_true")
    args = parser.parse_args()

    if not args.token:
        print("Error: set VTF_TOKEN or pass --token", file=sys.stderr)
        sys.exit(1)
    if not args.project:
        print("Error: set VTF_PROJECT or pass --project", file=sys.stderr)
        sys.exit(1)

    stream = not args.no_stream
    headers = {"Authorization": f"Token {args.token}", "Content-Type": "application/json"}

    # Check if role is locked — acquire lock if needed
    locked = args.role in ("architect", "web_designer")
    lock_info = None

    if locked:
        lock_info = _acquire_lock(args.url, headers, args.project, args.role)
        if not lock_info:
            sys.exit(1)

    print(f"vafi bridge REPL")
    print(f"  endpoint: {args.url}")
    print(f"  role: {args.role}")
    print(f"  project: {args.project}")
    print(f"  streaming: {stream}")
    if lock_info:
        print(f"  session: {lock_info.get('session_id', '?')}")
    print(f"Type your message. Ctrl+D to exit.\n")

    try:
        while True:
            try:
                message = input(f"\033[1m> \033[0m")
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break

            if not message.strip():
                continue

            body = {"message": message, "role": args.role, "project": args.project}

            if stream:
                _stream_prompt(args.url, headers, body)
            else:
                _sync_prompt(args.url, headers, body)

            print()
    finally:
        if locked:
            _release_lock(args.url, headers, args.project, args.role)


def _acquire_lock(url: str, headers: dict, project: str, role: str) -> dict | None:
    print(f"Acquiring {role} lock for project {project}...")
    with httpx.Client(timeout=120) as client:
        resp = client.post(f"{url}/v1/lock", headers=headers, json={"project": project, "role": role})
        if resp.status_code == 200:
            lock = resp.json()
            print(f"Lock acquired (session: {lock.get('session_id', '?')[:8]}...)")
            return lock
        elif resp.status_code == 409:
            print(f"\033[31mLock conflict: {resp.json().get('detail', 'held by another user')}\033[0m")
            return None
        else:
            print(f"\033[31mLock failed: {resp.status_code} {resp.text}\033[0m")
            return None


def _release_lock(url: str, headers: dict, project: str, role: str):
    print(f"Releasing {role} lock...")
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.request("DELETE", f"{url}/v1/lock", headers=headers, json={"project": project, "role": role})
            if resp.status_code == 200:
                print("Lock released.")
            else:
                print(f"Release failed: {resp.status_code}")
    except Exception as e:
        print(f"Release error: {e}")


def _stream_prompt(url: str, headers: dict, body: dict):
    with httpx.Client(timeout=120) as client:
        with client.stream("POST", f"{url}/v1/prompt/stream", headers=headers, json=body) as resp:
            if resp.status_code != 200:
                resp.read()
                print(f"\033[31mError {resp.status_code}: {resp.text}\033[0m")
                return

            for line in resp.iter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event["type"] == "text_delta":
                    print(event["text"], end="", flush=True)
                elif event["type"] == "tool_use":
                    if event["status"] == "started":
                        print(f"\n\033[2m[{event['tool']}...]\033[0m", end="", flush=True)
                    else:
                        print(f"\033[2m[done]\033[0m", end="", flush=True)
                elif event["type"] == "result":
                    print()
                elif event["type"] == "error":
                    print(f"\n\033[31mError: {event.get('message', 'unknown')}\033[0m")


def _sync_prompt(url: str, headers: dict, body: dict):
    with httpx.Client(timeout=120) as client:
        resp = client.post(f"{url}/v1/prompt", headers=headers, json=body)
        if resp.status_code != 200:
            print(f"\033[31mError {resp.status_code}: {resp.text}\033[0m")
            return
        data = resp.json()
        print(data["result"])


if __name__ == "__main__":
    main()
