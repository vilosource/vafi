"""Phase 7: Prove that adding a new harness requires zero code changes."""

import subprocess
from pathlib import Path

import yaml


CONFIG_DIR = Path(__file__).parent.parent / "config"


class TestZeroCodeProof:
    def test_no_python_files_modified(self):
        """After adding bash-agent, no .py files were modified."""
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True,
            cwd=Path(__file__).parent.parent,
        )
        py_files = [f for f in result.stdout.strip().split("\n") if f.endswith(".py")]
        assert py_files == [] or py_files == [""], f"Python files modified: {py_files}"

    def test_bash_agent_in_harness_config(self):
        """bash-agent appears in loaded harness config."""
        with open(CONFIG_DIR / "harnesses.yaml") as f:
            data = yaml.safe_load(f)
        assert "bash-agent" in data["harnesses"]
        assert data["harnesses"]["bash-agent"]["output_format"] == "raw_text"

    def test_bash_agent_in_role_allowed(self):
        """architect role allows bash-agent harness."""
        with open(CONFIG_DIR / "roles.yaml") as f:
            data = yaml.safe_load(f)
        assert "bash-agent" in data["roles"]["architect"]["allowed_harnesses"]

    def test_bash_agent_scripts_exist(self):
        """bash-agent image directory has all 3 scripts."""
        img_dir = Path(__file__).parent.parent / "images" / "bash-agent"
        assert (img_dir / "init.sh").exists()
        assert (img_dir / "connect.sh").exists()
        assert (img_dir / "run.sh").exists()
        assert (img_dir / "Dockerfile").exists()
