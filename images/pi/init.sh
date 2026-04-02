#!/bin/bash
set -e
mkdir -p ~/.pi/agent

python3 << 'PYEOF'
import json, os

base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
model = os.environ.get("VF_PI_MODEL", "claude-sonnet-4-20250514")
cfg = {"providers": {"anthropic": {
    "baseUrl": base_url, "api": "anthropic-messages",
    "apiKey": "ANTHROPIC_API_KEY",
    "models": [{"id": model}],
}}}
with open(os.path.expanduser("~/.pi/agent/models.json"), "w") as f:
    json.dump(cfg, f, indent=2)

servers = {}
vtf_mcp = os.environ.get("VF_VTF_MCP_URL", "")
cxdb_mcp = os.environ.get("VF_CXDB_MCP_URL", "")
if vtf_mcp: servers["vtf"] = {"url": vtf_mcp, "lifecycle": "lazy"}
if cxdb_mcp: servers["cxdb"] = {"url": cxdb_mcp, "lifecycle": "lazy"}
if servers:
    with open(os.path.expanduser("~/.pi/agent/mcp.json"), "w") as f:
        json.dump({"mcpServers": servers}, f, indent=2)
PYEOF
