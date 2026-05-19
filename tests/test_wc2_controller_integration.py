"""WC-2 — controller integration mechanics (vafi).

D1 per-task base_ref clone; D2 deterministic post-approve merge of the
deliverable branch (vafi/task-<id>) into the milestone integration
branch under the WC-1 slot; fail-loud on conflict; idempotent.
"""

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from controller.integration import IntegrationOutcome, integrate
from controller.types import RepoInfo, TaskInfo


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, path: str, content: str, msg: str) -> None:
    (repo / path).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)


@pytest.fixture
def origin(tmp_path):
    """Bare origin with `main` (one commit) + a deliverable branch
    `vafi/task-T1` that adds a non-conflicting file."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main", ".")
    seed.mkdir()
    _git(seed, "init", "-b", "main", ".")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    _commit(seed, "README.md", "seed\n", "seed")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "origin", "main")
    # deliverable branch off main
    _git(seed, "checkout", "-b", "vafi/task-T1")
    _commit(seed, "feature.py", "print('hello')\n", "T1 work")
    _git(seed, "push", "origin", "vafi/task-T1")
    return origin, tmp_path


# --- D2: integrate() git helper (real git) -------------------------------

class TestIntegrateHelper:
    def test_clean_merge_succeeds_and_pushes(self, origin):
        origin_path, tmp = origin
        out = integrate(str(origin_path), "vafi/wg-ms1", "main",
                        "vafi/task-T1", tmp / "wd1")
        assert out.success, out.detail
        # integration branch now exists on origin and carries the file
        check = tmp / "verify"
        _git(tmp, "clone", "-b", "vafi/wg-ms1", str(origin_path), str(check))
        assert (check / "feature.py").exists()

    def test_idempotent_second_run_is_noop_success(self, origin):
        origin_path, tmp = origin
        integrate(str(origin_path), "vafi/wg-ms1", "main",
                  "vafi/task-T1", tmp / "wd1")
        out2 = integrate(str(origin_path), "vafi/wg-ms1", "main",
                         "vafi/task-T1", tmp / "wd2")
        assert out2.success
        assert "already integrated" in out2.detail

    def test_conflict_fails_loud_and_aborts(self, origin):
        origin_path, tmp = origin
        # Pre-create the integration branch with a conflicting feature.py
        wd0 = tmp / "wd0"
        _git(tmp, "clone", str(origin_path), str(wd0))
        _git(wd0, "config", "user.email", "t@t")
        _git(wd0, "config", "user.name", "t")
        _git(wd0, "checkout", "-b", "vafi/wg-ms1", "origin/main")
        _commit(wd0, "feature.py", "CONFLICTING\n", "int-side")
        _git(wd0, "push", "origin", "vafi/wg-ms1")
        before = _git(wd0, "rev-parse", "origin/vafi/wg-ms1")

        out = integrate(str(origin_path), "vafi/wg-ms1", "main",
                        "vafi/task-T1", tmp / "wd1")
        assert out.success is False
        assert "feature.py" in out.detail
        # integration branch on origin is unchanged (abort worked)
        wd2 = tmp / "wd2"
        _git(tmp, "clone", str(origin_path), str(wd2))
        assert _git(wd2, "rev-parse", "origin/vafi/wg-ms1") == before

    def test_missing_deliverable_branch_fails(self, origin):
        origin_path, tmp = origin
        out = integrate(str(origin_path), "vafi/wg-ms1", "main",
                        "vafi/task-NOPE", tmp / "wd1")
        assert out.success is False
        assert "not found on origin" in out.detail


# --- D1: get_task_repo_info ---------------------------------------------

class TestGetTaskRepoInfo:
    @pytest.mark.asyncio
    async def test_base_ref_used_when_present(self):
        from controller.worksources.vtf import VtfWorkSource
        ws = VtfWorkSource(client=AsyncMock())
        ws._client.projects.get = AsyncMock(
            return_value=type("P", (), {"repo_url": "u", "default_branch": "main"})()
        )
        task = TaskInfo(id="t", title="t", spec="", project_id="p",
                        test_command={}, needs_review=False,
                        assigned_to=None, base_ref="vafi/wg-ms1")
        repo = await ws.get_task_repo_info(task)
        assert repo == RepoInfo(url="u", branch="vafi/wg-ms1")

    @pytest.mark.asyncio
    async def test_empty_base_ref_falls_back_to_project_default(self):
        from controller.worksources.vtf import VtfWorkSource
        ws = VtfWorkSource(client=AsyncMock())
        ws._client.projects.get = AsyncMock(
            return_value=type("P", (), {"repo_url": "u", "default_branch": "develop"})()
        )
        task = TaskInfo(id="t", title="t", spec="", project_id="p",
                        test_command={}, needs_review=False,
                        assigned_to=None, base_ref="")
        repo = await ws.get_task_repo_info(task)
        assert repo.branch == "develop"


# --- D2: controller _poll_and_integrate flow ----------------------------

class TestPollAndIntegrate:
    @pytest.mark.asyncio
    async def test_services_integration_and_reports_outcome(self, monkeypatch):
        from controller import controller as ctrl_mod
        from tests.test_controller import MockWorkSource

        ws = MockWorkSource()
        task = TaskInfo(id="T9", title="t", spec="", project_id="p",
                        test_command={}, needs_review=False,
                        assigned_to=None, base_ref="vafi/wg-ms1")
        ws.list_integrations = AsyncMock(return_value=[task])
        ws.get_task_repo_info = AsyncMock(
            return_value=RepoInfo(url="u", branch="vafi/wg-ms1"))
        ws.get_repo_info = AsyncMock(
            return_value=RepoInfo(url="u", branch="main"))

        captured = {}
        monkeypatch.setattr(
            ctrl_mod, "integrate",
            lambda *a, **k: IntegrationOutcome(True, "integrated @ abc1234"),
        )

        from controller.config import AgentConfig
        c = ctrl_mod.Controller(
            work_source=ws,
            config=AgentConfig(agent_id="a", agent_role="executor",
                               harness="claude", agent_tags=[]),
        )
        c._agent_info = type("A", (), {"id": "a"})()
        await c._poll_and_integrate()

        ws.report_integration_result.assert_awaited_once()
        args = ws.report_integration_result.await_args
        assert args.args[0] == "T9"
        assert args.args[1] is True  # success

    @pytest.mark.asyncio
    async def test_noop_when_no_integrations(self):
        from controller import controller as ctrl_mod
        from controller.config import AgentConfig
        from tests.test_controller import MockWorkSource

        ws = MockWorkSource()
        ws.list_integrations = AsyncMock(return_value=[])
        c = ctrl_mod.Controller(
            work_source=ws,
            config=AgentConfig(agent_id="a", agent_role="executor",
                               harness="claude", agent_tags=[]),
        )
        c._agent_info = type("A", (), {"id": "a"})()
        await c._poll_and_integrate()
        ws.report_integration_result.assert_not_awaited()
