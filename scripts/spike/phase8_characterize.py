#!/usr/bin/env python3
"""Phase 8 — Step 1: characterization probe.

Runs a two-session probe against the deployed bridge to observe — without
asserting — whether session 2 spontaneously inherits anything from session 1,
and what shape the cxdb data takes.

Outputs:
  - JSON observations to tests/fixtures/cxdb/spike-baseline-observations.json
  - cxdb turn dump (if reachable) to tests/fixtures/cxdb/spike-baseline-session1-turns.json
  - human-readable progress to stdout

Usage:
  python3 scripts/spike/phase8_characterize.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "tests" / "fixtures" / "prompts"
OUTPUT_DIR = REPO_ROOT / "tests" / "fixtures" / "cxdb"

VTF_URL = os.environ.get("VTF_URL", "https://vtf.dev.viloforge.com")
BRIDGE_URL = os.environ.get("BRIDGE_URL", "https://bridge.dev.viloforge.com")
ADMIN_USER = os.environ.get("VTF_USERNAME", "admin")
ADMIN_PASS = os.environ.get("VTF_PASSWORD", "admin")
NAMESPACE = os.environ.get("BRIDGE_NAMESPACE", "vafi-dev")
ROLE = "architect"
PROMPT_TIMEOUT = 600  # seconds


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


async def get_admin_token() -> str:
    log("Logging in as admin and fetching API token...")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # GET to set CSRF cookie
        r = await client.get(f"{VTF_URL}/v1/auth/login")
        r.raise_for_status()
        csrf = client.cookies.get("csrftoken", "")
        # POST login
        r = await client.post(
            f"{VTF_URL}/v1/auth/login",
            json={"username": ADMIN_USER, "password": ADMIN_PASS},
            headers={"X-CSRFToken": csrf, "Referer": VTF_URL + "/"},
        )
        r.raise_for_status()
        # CSRF rotates on login
        csrf = client.cookies.get("csrftoken", csrf)
        # POST token
        r = await client.post(
            f"{VTF_URL}/v1/auth/token/",
            headers={"X-CSRFToken": csrf, "Referer": VTF_URL + "/"},
        )
        r.raise_for_status()
        return r.json()["token"]


async def create_project(token: str, name: str) -> dict:
    log(f"Creating project {name!r}...")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{VTF_URL}/v1/projects/",
            headers={"Authorization": f"Token {token}"},
            json={
                "name": name,
                "description": "Phase 8 session-continuity spike (auto-created, safe to delete)",
                "repo_url": "git@github.com:vilosource/vafi-smoke-test.git",
                "default_branch": "main",
            },
            timeout=30,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Project create failed {r.status_code}: {r.text[:300]}")
        return r.json()


async def acquire_lock(token: str, project_id: str) -> dict:
    log(f"Acquiring lock on project {project_id} as {ROLE}... (Pi cold start ~35s)")
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{BRIDGE_URL}/v1/lock",
            headers={"Authorization": f"Token {token}"},
            json={"project": project_id, "role": ROLE},
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Lock acquire failed {r.status_code}: {r.text[:500]}")
        lock = r.json()
        log(f"  -> lock acquired, session_id={lock.get('session_id', '<none>')!r}")
        return lock


async def send_prompt(token: str, project_id: str, message: str) -> dict:
    log(f"Sending prompt ({len(message)} chars)...")
    final_event: dict = {}
    events: list[dict] = []
    async with httpx.AsyncClient(timeout=PROMPT_TIMEOUT) as client:
        async with client.stream(
            "POST",
            f"{BRIDGE_URL}/v1/prompt/stream",
            headers={"Authorization": f"Token {token}"},
            json={"message": message, "project": project_id, "role": ROLE},
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(f"Prompt failed {resp.status_code}: {body[:500]!r}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events.append(ev)
                etype = ev.get("type", "?")
                if etype == "result":
                    final_event = ev
                elif etype in ("message", "tool_use", "tool_result", "error", "agent_end"):
                    log(f"  event: {etype}")
    log(f"  -> stream complete, {len(events)} events, result preview: {str(final_event.get('result', ''))[:120]!r}")
    return {"final": final_event, "events": events}


async def release_lock(token: str, project_id: str) -> None:
    log("Releasing lock...")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.request(
            "DELETE",
            f"{BRIDGE_URL}/v1/lock",
            headers={"Authorization": f"Token {token}"},
            json={"project": project_id, "role": ROLE},
        )
        log(f"  -> {r.status_code} {r.text[:200]}")


def kubectl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "-n", NAMESPACE, *args], capture_output=True, text=True, check=check)


def list_pods_for_project(project_id: str) -> list[dict]:
    """Return [{name, phase, volumes}] for pods labeled with this project."""
    r = kubectl("get", "pods", "-l", f"project={project_id}", "-o", "json", check=False)
    if r.returncode != 0:
        return []
    data = json.loads(r.stdout) if r.stdout.strip() else {"items": []}
    out = []
    for pod in data.get("items", []):
        meta = pod.get("metadata", {})
        spec = pod.get("spec", {})
        status = pod.get("status", {})
        out.append({
            "name": meta.get("name"),
            "phase": status.get("phase"),
            "node": spec.get("nodeName"),
            "labels": meta.get("labels", {}),
            "volumes": [
                {"name": v.get("name"), "type": next(iter(v.keys() - {"name"}), None)}
                for v in spec.get("volumes", [])
            ],
        })
    return out


def delete_pods_for_project(project_id: str) -> list[str]:
    pods = list_pods_for_project(project_id)
    deleted = []
    for p in pods:
        log(f"Deleting pod {p['name']}...")
        kubectl("delete", "pod", p["name"], "--wait=true", "--timeout=60s", check=False)
        deleted.append(p["name"])
    return deleted


async def get_session_records(token: str, project_id: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{VTF_URL}/v1/sessions/",
            headers={"Authorization": f"Token {token}"},
            params={"project": project_id},
            timeout=30,
        )
        if r.status_code != 200:
            log(f"  session-records query failed: {r.status_code} {r.text[:200]}")
            return []
        data = r.json()
        return data.get("results", data) if isinstance(data, dict) else data


async def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    obs: dict = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "vtf_url": VTF_URL,
        "bridge_url": BRIDGE_URL,
        "role": ROLE,
    }

    nonce = uuid.uuid4().hex[:8]
    project_name = f"spike-phase8-{nonce}"
    obs["project_name"] = project_name
    obs["nonce"] = nonce

    # Auth
    token = await get_admin_token()
    obs["auth"] = "admin token acquired"

    # Project
    project = await create_project(token, project_name)
    project_id = project["id"]
    obs["project_id"] = project_id
    log(f"Project created: {project_id}")

    prompts = {
        "session1": (PROMPTS_DIR / "baseline-session1.txt").read_text().strip(),
        "session2": (PROMPTS_DIR / "baseline-session2.txt").read_text().strip(),
    }

    # ==================== SESSION 1 ====================
    log("=" * 60)
    log("SESSION 1")
    log("=" * 60)
    lock1 = await acquire_lock(token, project_id)
    obs["session1_lock"] = lock1
    pods_after_lock1 = list_pods_for_project(project_id)
    obs["session1_pods_after_lock"] = pods_after_lock1
    log(f"Pods after session-1 lock: {len(pods_after_lock1)}")
    for p in pods_after_lock1:
        log(f"  - {p['name']} phase={p['phase']} volumes={[v['name']+':'+str(v['type']) for v in p['volumes']]}")

    s1 = await send_prompt(token, project_id, prompts["session1"])
    obs["session1_result"] = {
        "result_text": s1["final"].get("result", ""),
        "session_id": s1["final"].get("session_id", ""),
        "input_tokens": s1["final"].get("input_tokens"),
        "output_tokens": s1["final"].get("output_tokens"),
        "num_turns": s1["final"].get("num_turns"),
        "event_count": len(s1["events"]),
        "event_types": sorted(set(e.get("type", "?") for e in s1["events"])),
    }

    # Hard release: release lock + delete pod
    await release_lock(token, project_id)
    deleted = delete_pods_for_project(project_id)
    obs["session1_pods_deleted"] = deleted
    log(f"Pods deleted: {deleted}")

    # SessionRecord check
    log("Querying vtf for SessionRecord(s) after session-1 close...")
    records1 = await get_session_records(token, project_id)
    obs["session1_records"] = records1
    log(f"  -> {len(records1)} session record(s)")
    for rec in records1:
        log(f"     session_id={rec.get('session_id')!r:20} cxdb_context_id={rec.get('cxdb_context_id')!r}")

    # Brief pause to let everything settle
    log("Waiting 10s before session 2...")
    await asyncio.sleep(10)

    # ==================== SESSION 2 ====================
    log("=" * 60)
    log("SESSION 2 (no continuity wiring exists yet — expect Pi to NOT remember)")
    log("=" * 60)
    lock2 = await acquire_lock(token, project_id)
    obs["session2_lock"] = lock2
    pods_after_lock2 = list_pods_for_project(project_id)
    obs["session2_pods_after_lock"] = pods_after_lock2
    log(f"Pods after session-2 lock: {len(pods_after_lock2)}")
    for p in pods_after_lock2:
        log(f"  - {p['name']} phase={p['phase']}")

    s2 = await send_prompt(token, project_id, prompts["session2"])
    obs["session2_result"] = {
        "result_text": s2["final"].get("result", ""),
        "session_id": s2["final"].get("session_id", ""),
        "input_tokens": s2["final"].get("input_tokens"),
        "output_tokens": s2["final"].get("output_tokens"),
        "num_turns": s2["final"].get("num_turns"),
        "event_count": len(s2["events"]),
        "event_types": sorted(set(e.get("type", "?") for e in s2["events"])),
    }

    await release_lock(token, project_id)
    delete_pods_for_project(project_id)

    records2 = await get_session_records(token, project_id)
    obs["session2_records"] = records2

    # ==================== OBSERVATIONS ====================
    log("=" * 60)
    log("OBSERVATIONS SUMMARY")
    log("=" * 60)
    s1_text = obs["session1_result"]["result_text"]
    s2_text = obs["session2_result"]["result_text"]
    log(f"Session 1 final text: {s1_text[:200]!r}")
    log(f"Session 2 final text: {s2_text[:200]!r}")

    # Naive continuity check (observation, not assertion)
    facts = ["teal", "January 15", "Phoenix"]
    recalled = [f for f in facts if f.lower() in s2_text.lower()]
    obs["spontaneous_continuity"] = {
        "facts_planted": facts,
        "facts_recalled_in_session2": recalled,
        "verdict": "CONTINUITY_DETECTED" if len(recalled) >= 2 else "NO_CONTINUITY",
    }
    log(f"Spontaneous continuity: {obs['spontaneous_continuity']['verdict']} (recalled {len(recalled)}/{len(facts)})")

    out_path = OUTPUT_DIR / "spike-baseline-observations.json"
    out_path.write_text(json.dumps(obs, indent=2, default=str))
    log(f"Observations written to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
