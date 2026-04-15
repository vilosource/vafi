"""Tests for hydrate_context.py — project context hydration script."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import httpx

# The script is standalone — import by manipulating path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "images" / "agent"))
import hydrate_context


class TestBuildContextMd:
    def test_full_success(self):
        """Full project data produces complete markdown."""
        project = {
            "name": "python-calc",
            "description": "A simple calculator project",
            "repo_url": "git@github.com:org/repo.git",
            "default_branch": "main",
            "tags": ["python", "demo"],
        }
        stats = {
            "total_tasks": 10,
            "completed_percentage": 40,
            "by_status": {"draft": 2, "todo": 3, "doing": 1, "done": 4},
        }
        workplans = [
            {"name": "Phase 1", "status": "active", "description": "Initial setup"},
            {"name": "Phase 2", "status": "archived", "description": "Old phase"},
        ]

        md = hydrate_context.build_context_md(project, stats, workplans)

        assert "# python-calc" in md
        assert "A simple calculator project" in md
        assert "**Total tasks**: 10 (40% complete)" in md
        assert "Draft: 2" in md
        assert "Done: 4" in md
        assert "### Phase 1" in md
        assert "Initial setup" in md
        # Archived workplan should not appear under Active
        assert "Phase 2" not in md
        assert "git@github.com:org/repo.git" in md
        assert "python, demo" in md
        assert "Last refreshed:" in md

    def test_no_project_data(self):
        """Handles None project gracefully."""
        md = hydrate_context.build_context_md(None, None, None)
        assert "# Unknown" in md
        assert "Last refreshed:" in md

    def test_no_stats(self):
        """Missing stats skips status section."""
        project = {"name": "test", "description": "", "repo_url": "", "tags": []}
        md = hydrate_context.build_context_md(project, None, None)
        assert "# test" in md
        assert "Total tasks" not in md

    def test_no_workplans(self):
        """Missing workplans skips workplan section."""
        project = {"name": "test", "description": "", "repo_url": "", "tags": []}
        md = hydrate_context.build_context_md(project, None, None)
        assert "Active Workplans" not in md

    def test_no_repo_url(self):
        """No repo_url skips repository section."""
        project = {"name": "test", "description": "", "repo_url": "", "tags": []}
        md = hydrate_context.build_context_md(project, None, None)
        assert "Repository" not in md

    def test_empty_tags(self):
        """Empty tags list skips tags section."""
        project = {"name": "test", "description": "", "repo_url": "", "tags": []}
        md = hydrate_context.build_context_md(project, None, None)
        assert "Tags" not in md


class TestFormatStatusLine:
    def test_mixed_statuses(self):
        stats = {"by_status": {"todo": 3, "doing": 1, "done": 5, "draft": 0}}
        line = hydrate_context.format_status_line(stats)
        assert "Todo: 3" in line
        assert "Doing: 1" in line
        assert "Done: 5" in line
        # Zero counts should be omitted
        assert "Draft" not in line

    def test_empty_statuses(self):
        stats = {"by_status": {}}
        line = hydrate_context.format_status_line(stats)
        assert line == "No tasks yet"


class TestRepoUrlValidation:
    """Repo URL must be validated before writing to /tmp/repo_url."""

    def test_https_url_accepted(self, tmp_path):
        from unittest.mock import MagicMock
        import re
        url = "https://github.com/org/repo.git"
        assert re.match(r"^(https?://|git@|ssh://)[^\s;|&$`]+$", url)

    def test_git_ssh_url_accepted(self, tmp_path):
        import re
        url = "git@github.com:org/repo.git"
        assert re.match(r"^(https?://|git@|ssh://)[^\s;|&$`]+$", url)

    def test_ssh_protocol_url_accepted(self, tmp_path):
        import re
        url = "ssh://git@github.com/org/repo.git"
        assert re.match(r"^(https?://|git@|ssh://)[^\s;|&$`]+$", url)

    def test_shell_injection_rejected(self, tmp_path):
        import re
        for url in [
            "$(whoami)",
            "; rm -rf /",
            "https://ok.com; evil",
            "git@host:repo`id`",
            "https://ok.com | cat /etc/passwd",
            "https://ok.com & background",
            "https://ok.com$HOME",
        ]:
            assert not re.match(r"^(https?://|git@|ssh://)[^\s;|&$`]+$", url), f"Should reject: {url}"

    def test_empty_url_rejected(self, tmp_path):
        import re
        assert not re.match(r"^(https?://|git@|ssh://)[^\s;|&$`]+$", "")

    def test_bare_path_rejected(self, tmp_path):
        import re
        assert not re.match(r"^(https?://|git@|ssh://)[^\s;|&$`]+$", "/tmp/local/repo")


class TestMainScript:
    def test_missing_env_vars_exits_cleanly(self, tmp_path):
        """Script exits 0 when env vars are missing."""
        with patch.dict(os.environ, {"VTF_API_URL": "", "VF_VTF_TOKEN": "", "VTF_PROJECT_SLUG": ""}, clear=False):
            with patch("sys.argv", ["hydrate_context.py", str(tmp_path)]):
                with pytest.raises(SystemExit) as exc_info:
                    hydrate_context.main()
                assert exc_info.value.code == 0
        # Should not have written anything
        assert not (tmp_path / "PROJECT_CONTEXT.md").exists()

    def test_no_args_exits_cleanly(self):
        """Script exits 0 when no workdir arg provided."""
        with patch("sys.argv", ["hydrate_context.py"]):
            with pytest.raises(SystemExit) as exc_info:
                hydrate_context.main()
            assert exc_info.value.code == 0

    def test_partial_api_failure(self, tmp_path):
        """Writes context even when some API calls fail."""
        project_resp = httpx.Response(200, json={
            "name": "partial-proj", "description": "Partial test",
            "repo_url": "", "default_branch": "main", "tags": [],
        })
        project_resp._request = httpx.Request("GET", "http://vtf:8000/v1/projects/partial-proj/")

        def mock_get(path, **kwargs):
            if "/stats" in path:
                raise httpx.ConnectError("timeout")
            elif "/workplans" in path:
                raise httpx.ConnectError("timeout")
            else:
                return project_resp

        mock_client = MagicMock()
        mock_client.get = mock_get
        mock_client.__enter__ = lambda s: mock_client
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.dict(os.environ, {
            "VTF_API_URL": "http://vtf:8000",
            "VF_VTF_TOKEN": "test-token",
            "VTF_PROJECT_SLUG": "partial-proj",
        }, clear=False):
            with patch("sys.argv", ["hydrate_context.py", str(tmp_path)]):
                with patch("hydrate_context.httpx.Client", return_value=mock_client):
                    hydrate_context.main()

        context = (tmp_path / "PROJECT_CONTEXT.md").read_text()
        assert "# partial-proj" in context
        assert "Partial test" in context
        # Stats and workplans sections should be absent (API failed)
        assert "Total tasks" not in context
        assert "Active Workplans" not in context
