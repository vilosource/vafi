"""Tests for harness boundary configuration loader."""

import pytest
import yaml

from bridge.harness_config import (
    ConfigError,
    load_harnesses,
    load_infra,
    load_roles,
    validate_config,
)


@pytest.fixture
def harnesses_data():
    return yaml.safe_load("""
harnesses:
  claude:
    image: harbor.viloforge.com/vafi/vafi-agent:abc123
    description: Claude Code CLI
    output_format: claude_json
    supports_rpc: false
    secrets:
      - secret: vafi-secrets
        env_map:
          anthropic-auth-token: ANTHROPIC_AUTH_TOKEN
          anthropic-base-url: ANTHROPIC_BASE_URL
  pi:
    image: harbor.viloforge.com/vafi/vafi-agent-pi:abc123
    description: Pi coding agent
    output_format: pi_jsonl
    supports_rpc: true
    secrets:
      - secret: vafi-secrets
        env_map:
          anthropic-auth-token: ANTHROPIC_API_KEY
""")


@pytest.fixture
def roles_data():
    return yaml.safe_load("""
roles:
  architect:
    description: Interactive planning
    allowed_harnesses: [pi, claude]
    default_harness: pi
    env:
      VF_AGENT_ROLE: architect
    resources:
      requests: {cpu: "500m", memory: "1Gi"}
      limits: {cpu: "1", memory: "2Gi"}
  executor:
    description: Task execution
    allowed_harnesses: [claude, pi]
    default_harness: claude
    env:
      VF_AGENT_ROLE: executor
""")


@pytest.fixture
def infra_data():
    return yaml.safe_load("""
infra:
  agent_user: agent
  home_path: /home/agent
  sessions_path: /sessions
  ready_sentinel: /tmp/ready
  harness_scripts: /opt/vf-harness
  ssh_secret: github-ssh
  ssh_key_name: ssh-privatekey
  ssh_mount_path: /home/agent/.ssh
  sessions_pvc: console-sessions
  readiness_probe:
    command: ["test", "-f", "/tmp/ready"]
    initial_delay: 5
    period: 10
  shared_env:
    GIT_SSH_COMMAND: "ssh -i /home/agent/.ssh/id_rsa -o StrictHostKeyChecking=no"
""")


class TestLoadHarnesses:
    def test_load_both(self, harnesses_data):
        h = load_harnesses(harnesses_data)
        assert "claude" in h
        assert "pi" in h

    def test_harness_has_image(self, harnesses_data):
        h = load_harnesses(harnesses_data)
        assert h["claude"].image == "harbor.viloforge.com/vafi/vafi-agent:abc123"
        assert h["pi"].image == "harbor.viloforge.com/vafi/vafi-agent-pi:abc123"

    def test_secret_env_map_claude(self, harnesses_data):
        h = load_harnesses(harnesses_data)
        mapping = h["claude"].secrets[0].env_map
        assert mapping["anthropic-auth-token"] == "ANTHROPIC_AUTH_TOKEN"

    def test_secret_env_map_pi(self, harnesses_data):
        h = load_harnesses(harnesses_data)
        mapping = h["pi"].secrets[0].env_map
        assert mapping["anthropic-auth-token"] == "ANTHROPIC_API_KEY"

    def test_output_format(self, harnesses_data):
        h = load_harnesses(harnesses_data)
        assert h["claude"].output_format == "claude_json"
        assert h["pi"].output_format == "pi_jsonl"

    def test_supports_rpc(self, harnesses_data):
        h = load_harnesses(harnesses_data)
        assert h["claude"].supports_rpc is False
        assert h["pi"].supports_rpc is True


class TestLoadRoles:
    def test_load_both(self, roles_data):
        r = load_roles(roles_data)
        assert "architect" in r
        assert "executor" in r

    def test_allowed_harnesses(self, roles_data):
        r = load_roles(roles_data)
        assert r["architect"].allowed_harnesses == ["pi", "claude"]

    def test_default_harness(self, roles_data):
        r = load_roles(roles_data)
        assert r["architect"].default_harness == "pi"
        assert r["executor"].default_harness == "claude"

    def test_role_env(self, roles_data):
        r = load_roles(roles_data)
        assert r["architect"].env["VF_AGENT_ROLE"] == "architect"

    def test_resources(self, roles_data):
        r = load_roles(roles_data)
        assert r["architect"].resources.requests_cpu == "500m"


class TestLoadInfra:
    def test_has_paths(self, infra_data):
        i = load_infra(infra_data)
        assert i.home_path == "/home/agent"
        assert i.sessions_path == "/sessions"
        assert i.ssh_mount_path == "/home/agent/.ssh"

    def test_readiness_probe(self, infra_data):
        i = load_infra(infra_data)
        assert i.readiness_probe.command == ["test", "-f", "/tmp/ready"]
        assert i.readiness_probe.initial_delay == 5

    def test_shared_env(self, infra_data):
        i = load_infra(infra_data)
        assert "GIT_SSH_COMMAND" in i.shared_env


class TestValidation:
    def test_valid_config_passes(self, harnesses_data, roles_data, infra_data):
        h = load_harnesses(harnesses_data)
        r = load_roles(roles_data)
        i = load_infra(infra_data)
        validate_config(h, r, i)  # should not raise

    def test_role_references_invalid_harness(self, harnesses_data, infra_data):
        bad_roles = yaml.safe_load("""
roles:
  test:
    description: test
    allowed_harnesses: [nonexistent]
    default_harness: nonexistent
""")
        h = load_harnesses(harnesses_data)
        r = load_roles(bad_roles)
        i = load_infra(infra_data)
        with pytest.raises(ConfigError, match="unknown harness"):
            validate_config(h, r, i)

    def test_default_not_in_allowed(self, harnesses_data, infra_data):
        bad_roles = yaml.safe_load("""
roles:
  test:
    description: test
    allowed_harnesses: [claude]
    default_harness: pi
""")
        h = load_harnesses(harnesses_data)
        r = load_roles(bad_roles)
        i = load_infra(infra_data)
        with pytest.raises(ConfigError, match="not in allowed_harnesses"):
            validate_config(h, r, i)

    def test_harness_missing_image(self, roles_data, infra_data):
        bad_h_data = yaml.safe_load("""
harnesses:
  broken:
    image: ""
    output_format: raw
""")
        h = load_harnesses(bad_h_data)
        # Need roles that reference this harness
        r_data = yaml.safe_load("""
roles:
  test:
    description: test
    allowed_harnesses: [broken]
    default_harness: broken
""")
        r = load_roles(r_data)
        i = load_infra(infra_data)
        with pytest.raises(ConfigError, match="missing image"):
            validate_config(h, r, i)
