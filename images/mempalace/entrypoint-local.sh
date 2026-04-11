#!/bin/bash
# Entrypoint for local interactive use (not k8s).
# Copies host ~/.claude auth into the container, injects mempalace MCP,
# then drops to the agent user to run Claude Code.
#
# Expects mounts:
#   ~/.claude       → /home/agent/.claude-host:ro
#   ~/.claude.json  → /home/agent/.claude-host.json:ro
#   mempalace vol   → /home/agent/.mempalace
#   workdir         → /workspace
set -e

AGENT_HOME=/home/agent

# Copy .claude.json (lives at ~/ not inside ~/.claude/)
if [ -f "$AGENT_HOME/.claude-host.json" ]; then
    cp "$AGENT_HOME/.claude-host.json" "$AGENT_HOME/.claude.json"
    chown agent:agent "$AGENT_HOME/.claude.json"
fi

# Copy credential and settings files (root needed to read mode-600 .credentials.json)
mkdir -p "$AGENT_HOME/.claude"
for f in .credentials.json settings.json; do
    if [ -f "$AGENT_HOME/.claude-host/$f" ]; then
        cp "$AGENT_HOME/.claude-host/$f" "$AGENT_HOME/.claude/$f"
        chown agent:agent "$AGENT_HOME/.claude/$f"
    fi
done

# Symlink remaining subdirs (plugins, agents, etc.)
if [ -d "$AGENT_HOME/.claude-host" ]; then
    for item in "$AGENT_HOME/.claude-host"/*/; do
        [ -d "$item" ] || continue
        name=$(basename "$item")
        [ ! -e "$AGENT_HOME/.claude/$name" ] && ln -s "$item" "$AGENT_HOME/.claude/$name" 2>/dev/null || true
    done
fi

# Inject mempalace MCP + trust workspace
python3 << 'PYEOF'
import json, os

cfg_path = "/home/agent/.claude.json"
try:
    with open(cfg_path) as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}

cfg.setdefault("mcpServers", {})["mempalace"] = {
    "command": "python3",
    "args": ["-m", "mempalace.mcp_server"]
}

cfg["hasCompletedOnboarding"] = True
cfg.setdefault("projects", {})["/workspace"] = {
    "hasTrustDialogAccepted": True,
    "hasCompletedProjectOnboarding": True,
}

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

os.chown(cfg_path, 1001, 1001)
PYEOF

# Ensure workspace exists
mkdir -p /workspace
chown agent:agent /workspace

# Build the command string for su
CMD="cd /workspace"
if [ $# -gt 0 ]; then
    CMD="$CMD && exec $(printf '%q ' "$@")"
else
    CMD="$CMD && exec bash"
fi

# Drop to agent user and exec the command
exec su -s /bin/bash agent -c "$CMD"
