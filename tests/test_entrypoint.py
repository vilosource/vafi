"""Phase 2: Verify entrypoint.sh is harness-agnostic."""

from pathlib import Path


ENTRYPOINT = Path(__file__).parent.parent / "images" / "agent" / "entrypoint.sh"


class TestEntrypoint:
    def test_no_harness_names(self):
        """entrypoint.sh contains zero occurrences of harness names as logic branches."""
        content = ENTRYPOINT.read_text()
        # No 'claude' anywhere (the old entrypoint had claude-specific branches)
        assert "claude" not in content.lower(), "Found 'claude' in entrypoint.sh"
        # No 'pi' as a harness name (in quotes or as variable value)
        # Allow 'pi' in paths like /opt/vf-harness but not as harness branching
        assert '"pi"' not in content, 'Found \'"pi"\' in entrypoint.sh'
        assert "= pi" not in content, "Found '= pi' in entrypoint.sh"
        assert "HARNESS" not in content, "Found 'HARNESS' in entrypoint.sh"

    def test_sources_init_sh(self):
        """entrypoint.sh sources /opt/vf-harness/init.sh."""
        content = ENTRYPOINT.read_text()
        assert "/opt/vf-harness/init.sh" in content

    def test_autonomous_uses_run_sh(self):
        """entrypoint.sh calls /opt/vf-harness/run.sh for autonomous mode."""
        content = ENTRYPOINT.read_text()
        assert "/opt/vf-harness/run.sh" in content

    def test_no_models_json(self):
        """entrypoint.sh does not write models.json (harness's job now)."""
        content = ENTRYPOINT.read_text()
        assert "models.json" not in content

    def test_no_claude_json(self):
        """entrypoint.sh does not write .claude.json (harness's job now)."""
        content = ENTRYPOINT.read_text()
        assert ".claude.json" not in content
        assert "settings.json" not in content
