#!/usr/bin/env python3
"""Write Pi agent config files from environment variables.

Usage: python3 pi_config.py

Reads env vars:
  VF_PI_PROVIDER     — LLM provider name (default: anthropic)
  VF_PI_MODEL        — model ID (default: claude-sonnet-4-20250514)
  ANTHROPIC_BASE_URL — custom API base URL (optional)
  VF_VTF_MCP_URL     — VTF MCP server endpoint (optional)
  VF_VTF_TOKEN       — VTF MCP auth token (required with VF_VTF_MCP_URL)
  VTF_PROJECT_SLUG   — project slug for X-VTF-Project header (optional)
  VF_CXDB_MCP_URL    — CXDB MCP server endpoint (optional)

Writes:
  ~/.pi/agent/settings.json  — packages list (preserves pi-mcp-adapter)
  ~/.pi/agent/models.json    — provider/model config with optional baseUrl
  ~/.pi/agent/mcp.json       — MCP server endpoints (only if URLs provided)

All output to stderr. Non-fatal on error.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any


def log(msg: str) -> None:
    print(f"[pi-config] {msg}", file=sys.stderr)


def main() -> None:
    config_dir = Path.home() / ".pi" / "agent"
    config_dir.mkdir(parents=True, exist_ok=True)

    # settings.json — merge (don't overwrite) so pi-mcp-adapter registration
    # written by `pi install npm:pi-mcp-adapter` at image build time survives.
    settings_path = config_dir / "settings.json"
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            settings = {}
    packages = settings.get("packages", [])
    if "npm:pi-mcp-adapter" not in packages:
        packages.append("npm:pi-mcp-adapter")
    settings["packages"] = packages
    settings_path.write_text(json.dumps(settings, indent=2))

    # models.json — provider config
    provider = os.environ.get("VF_PI_PROVIDER", "anthropic")
    model = os.environ.get("VF_PI_MODEL", "claude-sonnet-4-20250514")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")

    provider_cfg = {
        "api": "anthropic-messages",
        "apiKey": "ANTHROPIC_API_KEY",
        "models": [{"id": model, "name": model}],
    }
    if base_url:
        provider_cfg["baseUrl"] = base_url

    models = {"providers": {provider: provider_cfg}}
    models_path = config_dir / "models.json"
    models_path.write_text(json.dumps(models, indent=2))

    # mcp.json — MCP server endpoints (only written if at least one URL is set)
    vtf_mcp = os.environ.get("VF_VTF_MCP_URL", "")
    vtf_token = os.environ.get("VF_VTF_TOKEN", "")
    project_slug = os.environ.get("VTF_PROJECT_SLUG", "")
    cxdb_mcp = os.environ.get("VF_CXDB_MCP_URL", "")
    servers = {}
    if vtf_mcp:
        entry: dict[str, Any] = {"url": vtf_mcp, "lifecycle": "lazy"}
        if vtf_token:
            headers = {"Authorization": f"Token {vtf_token}"}
            if project_slug:
                headers["X-VTF-Project"] = project_slug
            entry["headers"] = headers
        servers["vtf"] = entry
    if cxdb_mcp:
        servers["cxdb"] = {"url": cxdb_mcp, "lifecycle": "lazy"}
    if servers:
        mcp_path = config_dir / "mcp.json"
        mcp_path.write_text(json.dumps({"mcpServers": servers}, indent=2))

    log(f"Wrote Pi config to {config_dir}")


if __name__ == "__main__":
    main()
