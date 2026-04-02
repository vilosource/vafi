"""Phase 0: Verify harness scripts exist and are executable in container images.

These tests run against built Docker images. They will FAIL until the scripts
are created and the Dockerfiles are updated to COPY them.
"""

import subprocess

import pytest

CLAUDE_IMAGE = "vafi/vafi-agent:latest"
PI_IMAGE = "vafi/vafi-agent-pi:latest"
SCRIPTS = ["init.sh", "connect.sh", "run.sh"]
HARNESS_PATH = "/opt/vf-harness"


def _docker_test(image: str, flag: str, path: str) -> bool:
    """Run `test <flag> <path>` inside the container image."""
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "test", image, flag, path],
        capture_output=True,
        timeout=30,
    )
    return result.returncode == 0


class TestClaudeHarnessScripts:
    """Claude image has init.sh, connect.sh, run.sh at /opt/vf-harness/."""

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_script_exists(self, script):
        path = f"{HARNESS_PATH}/{script}"
        assert _docker_test(CLAUDE_IMAGE, "-f", path), (
            f"{path} does not exist in {CLAUDE_IMAGE}"
        )

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_script_executable(self, script):
        path = f"{HARNESS_PATH}/{script}"
        assert _docker_test(CLAUDE_IMAGE, "-x", path), (
            f"{path} is not executable in {CLAUDE_IMAGE}"
        )


class TestPiHarnessScripts:
    """Pi image has init.sh, connect.sh, run.sh at /opt/vf-harness/."""

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_script_exists(self, script):
        path = f"{HARNESS_PATH}/{script}"
        assert _docker_test(PI_IMAGE, "-f", path), (
            f"{path} does not exist in {PI_IMAGE}"
        )

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_script_executable(self, script):
        path = f"{HARNESS_PATH}/{script}"
        assert _docker_test(PI_IMAGE, "-x", path), (
            f"{path} is not executable in {PI_IMAGE}"
        )
