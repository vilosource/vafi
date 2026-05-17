"""Integration tests for the F7/F10 delivery gate against a *real* git origin.

Hermetic: uses on-disk bare git repos (no network, no forge). Reproduces the
F10 ghost (local commit, never pushed) and proves the synthesized delivery
gate now catches it. See docs/f7-f10-delivery-gate-DESIGN.md.

Pyramid level: integration (real git subprocess, real GateRunner.run_gates).
Collected by default — it is hermetic, unlike tests/integration/* which
require deployed services.
"""

import subprocess
from pathlib import Path

import pytest

from controller.gates import GateRunner
from controller.types import TaskInfo, RepoInfo

TASK_ID = "abc123"
BRANCH = "main"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def origin_and_workdir(tmp_path):
    """A bare 'origin' repo with one commit on `main`, cloned into a workdir
    (mimics the controller's pod clone)."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    workdir = tmp_path / "task-workdir"

    origin.mkdir()
    _git(origin, "init", "--bare", "-b", BRANCH, ".")

    seed.mkdir()
    _git(seed, "init", "-b", BRANCH, ".")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / "README.md").write_text("seed\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "origin", BRANCH)

    _git(tmp_path, "clone", str(origin), str(workdir))
    _git(workdir, "config", "user.email", "t@t")
    _git(workdir, "config", "user.name", "t")
    return origin, workdir


def _task(test_command=None):
    return TaskInfo(
        id=TASK_ID,
        title="t",
        spec="s",
        project_id="p",
        test_command=test_command,
        needs_review=False,
        assigned_to=None,
    )


async def _delivery_passed(workdir: Path) -> bool:
    repo = RepoInfo(url="unused", branch=BRANCH)
    runner = GateRunner.from_task(_task(None), repo)
    results = await runner.run_gates(workdir, _task(None))
    delivery = [r for r in results if r.name == "deliverable-pushed"]
    assert delivery, "delivery gate must always be present (F7)"
    return delivery[0].passed


@pytest.mark.asyncio
async def test_no_branch_pushed_fails(origin_and_workdir):
    """F7: empty workdir, nothing pushed ⇒ delivery gate FAILS (no vacuous pass)."""
    _, workdir = origin_and_workdir
    assert await _delivery_passed(workdir) is False


@pytest.mark.asyncio
async def test_branch_equal_to_base_fails(origin_and_workdir):
    """Branch pushed but identical to base (no new commits) ⇒ FAILS."""
    origin, workdir = origin_and_workdir
    _git(workdir, "push", "origin", f"{BRANCH}:refs/heads/vafi/task-{TASK_ID}")
    assert await _delivery_passed(workdir) is False


@pytest.mark.asyncio
async def test_local_commit_not_pushed_fails(origin_and_workdir):
    """F10 reproduction: agent commits locally but never pushes ⇒ FAILS
    (this is the ghost the documented test_command mitigation missed)."""
    _, workdir = origin_and_workdir
    _git(workdir, "checkout", "-b", f"vafi/task-{TASK_ID}")
    (workdir / "primes.py").write_text("def is_prime(n): ...\n")
    _git(workdir, "add", "-A")
    _git(workdir, "commit", "-m", "local only")
    assert await _delivery_passed(workdir) is False


@pytest.mark.asyncio
async def test_branch_pushed_with_new_commit_passes(origin_and_workdir):
    """Deliverable durably pushed to origin ahead of base ⇒ PASSES."""
    _, workdir = origin_and_workdir
    _git(workdir, "checkout", "-b", f"vafi/task-{TASK_ID}")
    (workdir / "primes.py").write_text("def is_prime(n): ...\n")
    _git(workdir, "add", "-A")
    _git(workdir, "commit", "-m", "deliverable")
    _git(workdir, "push", "origin", f"vafi/task-{TASK_ID}")
    assert await _delivery_passed(workdir) is True
