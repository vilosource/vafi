"""Phase 8 integration tests: session continuity for the architect role.

Runs against the deployed bridge in vafi-dev. NOT collected by default —
mark with @pytest.mark.integration and run via:

    pytest tests/integration/test_session_continuity.py -m integration -v -s

Each test:
  1. Creates a UUID-suffixed vtf project
  2. Acquires architect lock → sends session-1 prompt
  3. Hard release: explicit DELETE + delete the pod
  4. Acquires architect lock again → sends session-2 prompt
  5. Asserts continuity behavior on the response
  6. Cleans up: pod + project deletion

Requires:
  - Network reachability to vtf.dev.viloforge.com and bridge.dev.viloforge.com
  - kubectl access to the vafi-dev namespace
  - Admin credentials (default admin/admin for dev)

Set VTF_USERNAME / VTF_PASSWORD env to override.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

VTF_URL = os.environ.get("VTF_URL", "https://vtf.dev.viloforge.com")
BRIDGE_URL = os.environ.get("BRIDGE_URL", "https://bridge.dev.viloforge.com")
ADMIN_USER = os.environ.get("VTF_USERNAME", "admin")
ADMIN_PASS = os.environ.get("VTF_PASSWORD", "admin")
NAMESPACE = os.environ.get("BRIDGE_NAMESPACE", "vafi-dev")
ROLE = "architect"

PROMPT_TIMEOUT = 600
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "prompts"


# ─── helpers ──────────────────────────────────────────────────────────────


def get_admin_token() -> str:
    with httpx.Client(follow_redirects=True) as client:
        r = client.get(f"{VTF_URL}/v1/auth/login")
        r.raise_for_status()
        csrf = client.cookies.get("csrftoken", "")
        r = client.post(
            f"{VTF_URL}/v1/auth/login",
            json={"username": ADMIN_USER, "password": ADMIN_PASS},
            headers={"X-CSRFToken": csrf, "Referer": VTF_URL + "/"},
        )
        r.raise_for_status()
        csrf = client.cookies.get("csrftoken", csrf)
        r = client.post(
            f"{VTF_URL}/v1/auth/token/",
            headers={"X-CSRFToken": csrf, "Referer": VTF_URL + "/"},
        )
        r.raise_for_status()
        return r.json()["token"]


def create_project(token: str, name: str) -> dict:
    with httpx.Client() as client:
        r = client.post(
            f"{VTF_URL}/v1/projects/",
            headers={"Authorization": f"Token {token}"},
            json={
                "name": name,
                "description": "Phase 8 integration test (auto-created, safe to delete)",
                "repo_url": "git@github.com:vilosource/vafi-smoke-test.git",
                "default_branch": "main",
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()


def delete_project(token: str, project_id: str) -> None:
    with httpx.Client() as client:
        client.delete(
            f"{VTF_URL}/v1/projects/{project_id}/",
            headers={"Authorization": f"Token {token}"},
            timeout=30,
        )


def acquire_lock(token: str, project_id: str) -> dict:
    with httpx.Client(timeout=180) as client:
        r = client.post(
            f"{BRIDGE_URL}/v1/lock",
            headers={"Authorization": f"Token {token}"},
            json={"project": project_id, "role": ROLE},
        )
        r.raise_for_status()
        return r.json()


def release_lock(token: str, project_id: str) -> None:
    with httpx.Client(timeout=60) as client:
        client.request(
            "DELETE",
            f"{BRIDGE_URL}/v1/lock",
            headers={"Authorization": f"Token {token}"},
            json={"project": project_id, "role": ROLE},
        )


def send_prompt(token: str, project_id: str, message: str) -> str:
    """Send prompt; return the final assistant text (may concatenate text_delta chunks)."""
    final_text = ""
    accumulated = ""
    with httpx.Client(timeout=PROMPT_TIMEOUT) as client:
        with client.stream(
            "POST",
            f"{BRIDGE_URL}/v1/prompt/stream",
            headers={"Authorization": f"Token {token}"},
            json={"message": message, "project": project_id, "role": ROLE},
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = ev.get("type")
                if etype == "text_delta":
                    accumulated += ev.get("text", "")
                elif etype == "result":
                    final_text = ev.get("result", "")
    return final_text or accumulated


def sanitized(project_id: str) -> str:
    """Mirror bridge's _sanitize_k8s_name: lowercase + non-alphanumeric → '-'."""
    s = project_id.lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    return s


def delete_pod_for_project(project_id: str) -> None:
    """Hard release: delete the architect pod so any in-memory Pi state vanishes."""
    label = f"vafi.viloforge.com/project={sanitized(project_id)}"
    subprocess.run(
        ["kubectl", "delete", "pod", "-n", NAMESPACE,
         "-l", label, "--wait=true", "--timeout=60s"],
        capture_output=True, text=True, check=False,
    )


def hard_release(token: str, project_id: str) -> None:
    """Explicit lock release + pod deletion → guarantees no Pi-memory carryover."""
    release_lock(token, project_id)
    delete_pod_for_project(project_id)
    time.sleep(3)  # let force_release callbacks settle


@pytest.fixture
def token() -> str:
    return get_admin_token()


@pytest.fixture
def fresh_project(token: str):
    nonce = uuid.uuid4().hex[:8]
    name = f"phase8-int-{nonce}"
    project = create_project(token, name)
    pid = project["id"]
    yield {"id": pid, "name": name, "nonce": nonce}
    # cleanup
    delete_pod_for_project(pid)
    delete_project(token, pid)


# ─── Test A: nonce plumbing ───────────────────────────────────────────────


@pytest.mark.integration
def test_a_nonce_plumbing(token, fresh_project):
    """A unique nonce planted in session 1 must be recallable verbatim in session 2.

    Confirms the data path: bridge writes Pi JSONL → build_prior_context.py
    extracts it → pi receives it via --append-system-prompt → pi recalls it.
    """
    pid = fresh_project["id"]
    nonce = fresh_project["nonce"].upper()

    s1_prompt = (PROMPTS_DIR / "test-a-plumbing-session1.txt").read_text().replace("{NONCE}", nonce)
    s2_prompt = (PROMPTS_DIR / "test-a-plumbing-session2.txt").read_text()

    # Session 1: plant the nonce
    acquire_lock(token, pid)
    s1_response = send_prompt(token, pid, s1_prompt)
    print(f"\n[Test A] session 1 response: {s1_response!r}")
    hard_release(token, pid)

    # Session 2: ask for the nonce
    acquire_lock(token, pid)
    s2_response = send_prompt(token, pid, s2_prompt)
    print(f"[Test A] session 2 response: {s2_response!r}")
    hard_release(token, pid)

    expected = f"ALPHA-7Z-{nonce}"
    assert expected in s2_response, (
        f"Expected nonce {expected!r} in session-2 response. Got: {s2_response!r}"
    )


# ─── Test B: task continuation ────────────────────────────────────────────


@pytest.mark.integration
def test_b_task_continuation(token, fresh_project):
    """Session 1 designs a BankAccount class; session 2 extends it without restating context.

    Confirms continuity is *useful*, not just present: the agent should
    recognize what BankAccount is from session 1 and add to it.
    """
    pid = fresh_project["id"]

    s1_prompt = (PROMPTS_DIR / "test-b-task-session1.txt").read_text()
    s2_prompt = (PROMPTS_DIR / "test-b-task-session2.txt").read_text()

    acquire_lock(token, pid)
    s1_response = send_prompt(token, pid, s1_prompt)
    print(f"\n[Test B] session 1 response (truncated): {s1_response[:300]!r}")
    hard_release(token, pid)

    acquire_lock(token, pid)
    s2_response = send_prompt(token, pid, s2_prompt)
    print(f"[Test B] session 2 response (truncated): {s2_response[:400]!r}")
    hard_release(token, pid)

    # Must reference the class established in session 1. `deposit`/`withdraw`
    # are implementation details that may or may not appear depending on
    # whether the agent replies with code or a summary — the load-bearing
    # assertion is "it remembered BankAccount at all."
    body = s2_response.lower()
    assert "bankaccount" in body, (
        f"Session-2 response missing 'BankAccount' from session 1 — continuity broken.\n"
        f"Full response: {s2_response!r}"
    )
    # Ideally the response also mentions the existing methods — log a
    # warning but don't fail if the agent chose a prose summary.
    for sym in ("deposit", "withdraw"):
        if sym not in body:
            print(f"[Test B] soft-note: '{sym}' not in response (agent summarized rather than restated code).")
