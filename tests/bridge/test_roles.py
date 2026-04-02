"""Tests for bridge role configuration."""

import pytest
from bridge.roles import load_roles, RoleConfig


SAMPLE_ROLES_YAML = """
roles:
  architect:
    session_type: locked
    model: claude-sonnet-4-20250514
    thinking_level: medium
    methodology: /opt/vf-agent/methodologies/architect.md
    mcp_tools:
      - vtf
      - cxdb
    description: Interactive planning

  assistant:
    session_type: ephemeral
    model: claude-sonnet-4-20250514
    thinking_level: low
    methodology: /opt/vf-agent/methodologies/assistant.md
    mcp_tools:
      - vtf
    description: Quick operations
"""


@pytest.fixture
def roles(tmp_path):
    config_file = tmp_path / "roles.yaml"
    config_file.write_text(SAMPLE_ROLES_YAML)
    return load_roles(str(config_file))


class TestRoleConfiguration:
    def test_load_roles_from_yaml(self, roles):
        assert "architect" in roles
        assert "assistant" in roles
        assert isinstance(roles["architect"], RoleConfig)

    def test_role_session_type(self, roles):
        assert roles["architect"].session_type == "locked"
        assert roles["assistant"].session_type == "ephemeral"

    def test_role_model_config(self, roles):
        arch = roles["architect"]
        assert arch.model == "claude-sonnet-4-20250514"
        assert arch.thinking_level == "medium"
        assert arch.methodology == "/opt/vf-agent/methodologies/architect.md"

    def test_role_mcp_tools(self, roles):
        assert "vtf" in roles["architect"].mcp_tools
        assert "cxdb" in roles["architect"].mcp_tools
        assert "cxdb" not in roles["assistant"].mcp_tools
