"""WC-2/D2 — deterministic post-approve integration merge.

The composition primitive: merge a workgraph task's delivered branch
(``vafi/task-<id>``, the F7/F10 deliverable ref) into its milestone
integration branch and push. Conflict → abort → fail-loud (the caller
reports ``needs_attention``; WC-1/C3 + the C4 reaper own recovery).
Idempotent and re-entrant: an already-merged delivery is a no-op
success, so a controller retry (or a reaper race) is safe.

The integration branch *name* is owned by the SoR (WC-1/C1); this
module owns the git ref — creating it off the project default branch
on first use (the R0 split). No new branch-naming contract is invented;
``vafi/task-<id>`` is `gates.deliverable_branch`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IntegrationOutcome:
    """Result of an integration attempt. ``success`` maps directly to
    the WC-2 reporting seam (success ⇒ done; else ⇒ needs_attention)."""
    success: bool
    detail: str


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
    )


def integrate(
    repo_url: str,
    integration_branch: str,
    base_branch: str,
    task_branch: str,
    workdir: Path,
) -> IntegrationOutcome:
    """Merge ``task_branch`` into ``integration_branch`` and push.

    ``workdir`` must be an empty path; the repo is cloned into it (full
    history — a shallow clone cannot merge). ``base_branch`` is the
    project default, used only to create the integration branch the
    first time it is needed (idempotent thereafter).
    """
    try:
        _git(workdir.parent, "clone", repo_url, str(workdir))
    except subprocess.CalledProcessError as e:
        return IntegrationOutcome(False, f"clone failed: {e.stderr.strip()[:300]}")

    _git(workdir, "config", "user.email", "vafi-controller@viloforge")
    _git(workdir, "config", "user.name", "vafi-controller")

    # The deliverable branch must exist on origin (the F7/F10 gate
    # already asserted this at execution time; re-check to fail loud).
    if not _git(workdir, "ls-remote", "--heads", "origin", task_branch,
                check=False).stdout.strip():
        return IntegrationOutcome(
            False, f"deliverable branch '{task_branch}' not found on origin")

    # Establish the integration branch: track origin's if it exists,
    # else create it off the project default and publish it (the R0
    # split — controller owns the git ref).
    if _git(workdir, "ls-remote", "--heads", "origin", integration_branch,
            check=False).stdout.strip():
        _git(workdir, "checkout", "-B", integration_branch,
             f"origin/{integration_branch}")
    else:
        _git(workdir, "checkout", "-B", integration_branch,
             f"origin/{base_branch}")
        pub = _git(workdir, "push", "origin", integration_branch, check=False)
        if pub.returncode != 0:
            return IntegrationOutcome(
                False, f"could not create integration branch: "
                       f"{pub.stderr.strip()[:300]}")

    _git(workdir, "fetch", "origin", task_branch)
    task_sha = _git(workdir, "rev-parse", "FETCH_HEAD").stdout.strip()

    # Idempotent / re-entrant: already integrated ⇒ no-op success.
    if _git(workdir, "merge-base", "--is-ancestor", task_sha, "HEAD",
            check=False).returncode == 0:
        return IntegrationOutcome(
            True, f"already integrated ({task_sha[:8]})")

    merge = _git(workdir, "merge", "--no-ff", "-m",
                 f"wc2: integrate {task_branch} into {integration_branch}",
                 task_sha, check=False)
    if merge.returncode != 0:
        conflicts = _git(workdir, "diff", "--name-only",
                         "--diff-filter=U", check=False).stdout.strip()
        _git(workdir, "merge", "--abort", check=False)
        return IntegrationOutcome(
            False, f"merge conflict in: {conflicts or 'unknown'}")

    push = _git(workdir, "push", "origin", integration_branch, check=False)
    if push.returncode != 0:
        return IntegrationOutcome(
            False, f"push failed: {push.stderr.strip()[:300]}")

    head = _git(workdir, "rev-parse", "HEAD").stdout.strip()
    return IntegrationOutcome(
        True, f"integrated {task_branch} -> {integration_branch} @ {head[:8]}")
