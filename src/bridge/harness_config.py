"""Harness boundary configuration loader.

Parses harnesses.yaml, roles.yaml, infra.yaml into typed dataclasses.
Used by bridge and controller to build pods and select output parsers
without hardcoding harness-specific values.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretMapping:
    secret: str
    env_map: dict[str, str]  # k8s secret key -> env var name


@dataclass(frozen=True)
class HarnessConfig:
    name: str
    image: str
    description: str
    output_format: str
    supports_rpc: bool = False
    secrets: list[SecretMapping] = field(default_factory=list)


@dataclass(frozen=True)
class RoleResources:
    requests_cpu: str = "500m"
    requests_memory: str = "1Gi"
    limits_cpu: str = "1"
    limits_memory: str = "2Gi"


@dataclass(frozen=True)
class RoleConfig:
    name: str
    description: str
    allowed_harnesses: list[str]
    default_harness: str
    env: dict[str, str] = field(default_factory=dict)
    resources: RoleResources = field(default_factory=RoleResources)


@dataclass(frozen=True)
class ReadinessProbe:
    command: list[str] = field(default_factory=lambda: ["test", "-f", "/tmp/ready"])
    initial_delay: int = 5
    period: int = 10


@dataclass(frozen=True)
class InfraConfig:
    agent_user: str = "agent"
    home_path: str = "/home/agent"
    sessions_path: str = "/sessions"
    ready_sentinel: str = "/tmp/ready"
    harness_scripts: str = "/opt/vf-harness"
    ssh_secret: str = "github-ssh"
    ssh_key_name: str = "ssh-privatekey"
    ssh_mount_path: str = "/home/agent/.ssh"
    sessions_pvc: str = "console-sessions"
    readiness_probe: ReadinessProbe = field(default_factory=ReadinessProbe)
    shared_env: dict[str, str] = field(default_factory=dict)
    template_env: dict[str, str] = field(default_factory=dict)


class ConfigError(Exception):
    pass


def load_harnesses(data: dict[str, Any]) -> dict[str, HarnessConfig]:
    result = {}
    for name, h in data.get("harnesses", {}).items():
        secrets = []
        for s in h.get("secrets", []):
            secrets.append(SecretMapping(
                secret=s["secret"],
                env_map=s.get("env_map", {}),
            ))
        result[name] = HarnessConfig(
            name=name,
            image=h["image"],
            description=h.get("description", ""),
            output_format=h.get("output_format", ""),
            supports_rpc=h.get("supports_rpc", False),
            secrets=secrets,
        )
    return result


def load_roles(data: dict[str, Any]) -> dict[str, RoleConfig]:
    result = {}
    for name, r in data.get("roles", {}).items():
        res = r.get("resources", {})
        req = res.get("requests", {})
        lim = res.get("limits", {})
        result[name] = RoleConfig(
            name=name,
            description=r.get("description", ""),
            allowed_harnesses=r.get("allowed_harnesses", []),
            default_harness=r.get("default_harness", ""),
            env=r.get("env", {}),
            resources=RoleResources(
                requests_cpu=req.get("cpu", "500m"),
                requests_memory=req.get("memory", "1Gi"),
                limits_cpu=lim.get("cpu", "1"),
                limits_memory=lim.get("memory", "2Gi"),
            ),
        )
    return result


def load_infra(data: dict[str, Any]) -> InfraConfig:
    i = data.get("infra", {})
    rp = i.get("readiness_probe", {})
    return InfraConfig(
        agent_user=i.get("agent_user", "agent"),
        home_path=i.get("home_path", "/home/agent"),
        sessions_path=i.get("sessions_path", "/sessions"),
        ready_sentinel=i.get("ready_sentinel", "/tmp/ready"),
        harness_scripts=i.get("harness_scripts", "/opt/vf-harness"),
        ssh_secret=i.get("ssh_secret", "github-ssh"),
        ssh_key_name=i.get("ssh_key_name", "ssh-privatekey"),
        ssh_mount_path=i.get("ssh_mount_path", "/home/agent/.ssh"),
        sessions_pvc=i.get("sessions_pvc", "console-sessions"),
        readiness_probe=ReadinessProbe(
            command=rp.get("command", ["test", "-f", "/tmp/ready"]),
            initial_delay=rp.get("initial_delay", 5),
            period=rp.get("period", 10),
        ),
        shared_env=i.get("shared_env", {}),
        template_env=i.get("template_env", {}),
    )


def validate_config(
    harnesses: dict[str, HarnessConfig],
    roles: dict[str, RoleConfig],
    infra: InfraConfig,
) -> None:
    errors = []

    for role_name, role in roles.items():
        for h in role.allowed_harnesses:
            if h not in harnesses:
                errors.append(f"Role '{role_name}' references unknown harness '{h}'")
        if role.default_harness not in role.allowed_harnesses:
            errors.append(f"Role '{role_name}' default_harness '{role.default_harness}' not in allowed_harnesses")

    for name, h in harnesses.items():
        if not h.image:
            errors.append(f"Harness '{name}' missing image")
        for s in h.secrets:
            if not s.secret:
                errors.append(f"Harness '{name}' has empty secret name")

    if errors:
        raise ConfigError("\n".join(errors))


def load_config_dir(config_dir: str) -> tuple[dict[str, HarnessConfig], dict[str, RoleConfig], InfraConfig]:
    """Load and validate all config files from a directory."""
    p = Path(config_dir)

    with open(p / "harnesses.yaml") as f:
        harnesses = load_harnesses(yaml.safe_load(f))

    with open(p / "roles.yaml") as f:
        roles = load_roles(yaml.safe_load(f))

    with open(p / "infra.yaml") as f:
        infra = load_infra(yaml.safe_load(f))

    validate_config(harnesses, roles, infra)
    logger.info(f"Loaded {len(harnesses)} harnesses, {len(roles)} roles from {config_dir}")
    return harnesses, roles, infra
