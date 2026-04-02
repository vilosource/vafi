#!/bin/bash
set -e
mkdir -p ~/.claude

python3 << 'PYEOF'
import json, os

cfg_path = os.path.expanduser("~/.claude.json")
try:
    with open(cfg_path) as f: cfg = json.load(f)
except: cfg = {}

cfg["hasCompletedOnboarding"] = True
cfg["theme"] = "dark"
cfg["autoUpdates"] = False

workdir = os.environ.get("WORKDIR", "/sessions/greenfield")
cfg.setdefault("projects", {})[workdir] = {
    "hasTrustDialogAccepted": True,
    "hasCompletedProjectOnboarding": True,
}

mcp_url = os.environ.get("VF_VTF_MCP_URL", "")
vtf_token = os.environ.get("VF_VTF_TOKEN", "")
project = os.environ.get("VTF_PROJECT_SLUG", "")
if mcp_url and vtf_token:
    headers = {"Authorization": f"Token {vtf_token}"}
    if project: headers["X-VTF-Project"] = project
    cfg.setdefault("mcpServers", {})["vtf"] = {"type": "http", "url": mcp_url, "headers": headers}

cxdb_mcp = os.environ.get("VF_CXDB_MCP_URL", "")
if cxdb_mcp:
    cfg.setdefault("mcpServers", {})["cxdb"] = {"type": "http", "url": cxdb_mcp}

with open(cfg_path, "w") as f: json.dump(cfg, f, indent=2)
PYEOF

cat > ~/.claude/settings.json << 'EOF'
{"skipDangerousModePermissionPrompt": true}
EOF

# Copy methodology for Claude auto-discovery
ROLE="${VF_AGENT_ROLE:-executor}"
METHODOLOGY="/opt/vf-agent/methodologies/${ROLE}.md"
if [ -f "$METHODOLOGY" ]; then
    cp "$METHODOLOGY" ~/.claude/CLAUDE.md
fi
