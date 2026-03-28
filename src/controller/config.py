"""Agent configuration from environment variables."""

import os
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Configuration for a vafi controller instance.

    All values read from VF_* environment variables with sensible defaults.
    """

    agent_id: str = ""
    agent_role: str = "executor"
    agent_tags: list[str] = field(default_factory=lambda: ["executor"])

    vtf_api_url: str = "http://vtf-api.vafi-system.svc.cluster.local:8000"
    vtf_token: str = ""
    poll_interval: int = 30

    task_timeout: int = 600
    max_rework: int = 3
    max_turns: int = 50
    heartbeat_interval: int = 300

    sessions_dir: str = "/sessions"

    cxdb_url: str = ""
    cxdb_public_url: str = ""

    @classmethod
    def from_env(cls) -> "AgentConfig":
        tags_str = os.environ.get("VF_AGENT_TAGS", "executor")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]

        return cls(
            agent_id=os.environ.get("VF_AGENT_ID", ""),
            agent_role=os.environ.get("VF_AGENT_ROLE", "executor"),
            agent_tags=tags,
            vtf_api_url=os.environ.get("VF_VTF_API_URL", cls.vtf_api_url),
            vtf_token=os.environ.get("VF_VTF_TOKEN", ""),
            poll_interval=int(os.environ.get("VF_POLL_INTERVAL", "30")),
            task_timeout=int(os.environ.get("VF_TASK_TIMEOUT", "600")),
            max_rework=int(os.environ.get("VF_MAX_REWORK", "3")),
            max_turns=int(os.environ.get("VF_MAX_TURNS", "50")),
            heartbeat_interval=int(os.environ.get("VF_HEARTBEAT_INTERVAL", "300")),
            sessions_dir=os.environ.get("VF_SESSIONS_DIR", "/sessions"),
            cxdb_url=os.environ.get("VF_CXDB_URL", ""),
            cxdb_public_url=os.environ.get("VF_CXDB_PUBLIC_URL", ""),
        )

    def display(self) -> str:
        lines = [
            "vafi controller configuration:",
            f"  agent_id:           {self.agent_id or '(auto)'}",
            f"  agent_role:         {self.agent_role}",
            f"  agent_tags:         {', '.join(self.agent_tags)}",
            f"  vtf_api_url:        {self.vtf_api_url}",
            f"  vtf_token:          {'***' if self.vtf_token else '(none)'}",
            f"  poll_interval:      {self.poll_interval}s",
            f"  task_timeout:       {self.task_timeout}s",
            f"  max_rework:         {self.max_rework}",
            f"  max_turns:          {self.max_turns}",
            f"  heartbeat_interval: {self.heartbeat_interval}s",
            f"  sessions_dir:       {self.sessions_dir}",
            f"  cxdb_url:          {self.cxdb_url or '(disabled)'}",
            f"  cxdb_public_url:   {self.cxdb_public_url or '(same as cxdb_url)'}",
        ]
        return "\n".join(lines)
