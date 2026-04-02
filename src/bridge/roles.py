"""Role configuration for bridge service."""

from dataclasses import dataclass, field

import yaml


@dataclass
class RoleConfig:
    session_type: str  # "locked" or "ephemeral"
    harness: str = "pi-rpc"  # "pi-rpc" or "claude-cli"
    model: str = "claude-sonnet-4-20250514"
    thinking_level: str = "medium"
    methodology: str = ""
    mcp_tools: list[str] = field(default_factory=list)
    description: str = ""
    idle_timeout_hours: int = 4


def load_roles(config_path: str) -> dict[str, RoleConfig]:
    """Load role configuration from YAML file."""
    with open(config_path) as f:
        data = yaml.safe_load(f)

    roles = {}
    for name, cfg in data.get("roles", {}).items():
        roles[name] = RoleConfig(
            session_type=cfg["session_type"],
            harness=cfg.get("harness", "pi-rpc"),
            model=cfg.get("model", "claude-sonnet-4-20250514"),
            thinking_level=cfg.get("thinking_level", "medium"),
            methodology=cfg.get("methodology", ""),
            mcp_tools=cfg.get("mcp_tools", []),
            description=cfg.get("description", ""),
            idle_timeout_hours=cfg.get("idle_timeout_hours", 4),
        )
    return roles
