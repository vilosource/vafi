#!/bin/bash
# Entrypoint for local and headless use.
#
# Auth modes (auto-detected):
#   z.ai:  ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL env vars → no host mount needed
#   OAuth: mounted ~/.claude with .credentials.json → subscription auth
#
# Expects mounts:
#   ~/.claude       → /home/agent/.claude-host:ro   (OAuth mode only)
#   ~/.claude.json  → /home/agent/.claude-host.json:ro
#   mempalace vol   → /home/agent/.mempalace
#   workdir         → /workspace
set -e

AGENT_HOME=/home/agent
mkdir -p "$AGENT_HOME/.claude"

# --- Auth ---

if [ -n "$ANTHROPIC_AUTH_TOKEN" ]; then
    # z.ai mode: auth via env vars, no OAuth credentials needed.
    # Claude Code reads ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL directly.
    echo >&2 "[mempalace] Auth: z.ai (ANTHROPIC_AUTH_TOKEN)"
else
    # OAuth mode: copy credentials from mounted host .claude dir.
    if [ -f "$AGENT_HOME/.claude-host/.credentials.json" ]; then
        cp "$AGENT_HOME/.claude-host/.credentials.json" "$AGENT_HOME/.claude/.credentials.json"
        chown agent:agent "$AGENT_HOME/.claude/.credentials.json"
        echo >&2 "[mempalace] Auth: OAuth (.credentials.json)"
    else
        echo >&2 "[mempalace] WARNING: No auth configured (no ANTHROPIC_AUTH_TOKEN, no .credentials.json)"
    fi
fi

# --- Claude Code config ---

# Copy .claude.json from host mount (if available) as base config
if [ -f "$AGENT_HOME/.claude-host.json" ]; then
    cp "$AGENT_HOME/.claude-host.json" "$AGENT_HOME/.claude.json"
    chown agent:agent "$AGENT_HOME/.claude.json"
fi

# Copy settings.json (needed for skipDangerousModePermissionPrompt regardless of auth mode)
if [ -f "$AGENT_HOME/.claude-host/settings.json" ]; then
    cp "$AGENT_HOME/.claude-host/settings.json" "$AGENT_HOME/.claude/settings.json"
    chown agent:agent "$AGENT_HOME/.claude/settings.json"
fi

# Symlink host subdirs (plugins, agents, etc.)
# Skip dirs that Claude Code needs to write to — create those as real dirs instead.
WRITABLE_DIRS="session-env projects plans history cache"
if [ -d "$AGENT_HOME/.claude-host" ]; then
    for item in "$AGENT_HOME/.claude-host"/*/; do
        [ -d "$item" ] || continue
        name=$(basename "$item")
        skip=false
        for w in $WRITABLE_DIRS; do [ "$name" = "$w" ] && skip=true; done
        if [ "$skip" = "false" ] && [ ! -e "$AGENT_HOME/.claude/$name" ]; then
            ln -s "$item" "$AGENT_HOME/.claude/$name" 2>/dev/null || true
        fi
    done
fi

# Ensure writable dirs exist for Claude Code runtime
for d in $WRITABLE_DIRS; do
    mkdir -p "$AGENT_HOME/.claude/$d"
    chown agent:agent "$AGENT_HOME/.claude/$d"
done

# --- Mempalace MCP + workspace trust ---

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
cfg["autoUpdates"] = False
cfg.setdefault("projects", {})["/workspace"] = {
    "hasTrustDialogAccepted": True,
    "hasCompletedProjectOnboarding": True,
}

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

os.chown(cfg_path, 1001, 1001)
PYEOF

# --- Launch ---

mkdir -p /workspace
chown agent:agent /workspace

# Pass z.ai env vars through to the agent user's environment
EXPORT_VARS=""
[ -n "$ANTHROPIC_AUTH_TOKEN" ] && EXPORT_VARS="export ANTHROPIC_AUTH_TOKEN='$ANTHROPIC_AUTH_TOKEN'; "
[ -n "$ANTHROPIC_BASE_URL" ] && EXPORT_VARS="${EXPORT_VARS}export ANTHROPIC_BASE_URL='$ANTHROPIC_BASE_URL'; "

# Build the command string
CMD="${EXPORT_VARS}cd /workspace"
if [ $# -gt 0 ]; then
    CMD="$CMD && exec $(printf '%q ' "$@")"
else
    CMD="$CMD && exec bash"
fi

# Drop to agent user and exec the command
exec su -s /bin/bash agent -c "$CMD"
