#!/bin/bash
# Entrypoint for local and headless use.
#
# Auth modes (auto-detected):
#   z.ai:  ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL env vars
#   OAuth: mount ~/.claude/.credentials.json → /home/agent/.claude-host-credentials.json:ro
#
# Mounts:
#   credentials  → /home/agent/.claude-host-credentials.json:ro  (OAuth only)
#   mempalace    → /home/agent/.mempalace
#   workdir      → /workspace
set -e

AGENT_HOME=/home/agent
mkdir -p "$AGENT_HOME/.claude"

# --- Auth ---

if [ -n "$ANTHROPIC_AUTH_TOKEN" ]; then
    echo >&2 "[mempalace] Auth: z.ai (ANTHROPIC_AUTH_TOKEN)"
elif [ -f "$AGENT_HOME/.claude-host-credentials.json" ]; then
    cp "$AGENT_HOME/.claude-host-credentials.json" "$AGENT_HOME/.claude/.credentials.json"
    chown agent:agent "$AGENT_HOME/.claude/.credentials.json"
    echo >&2 "[mempalace] Auth: OAuth (.credentials.json)"
else
    echo >&2 "[mempalace] WARNING: No auth configured (no ANTHROPIC_AUTH_TOKEN, no .credentials.json)"
fi

# --- Build minimal Claude Code config from scratch ---

python3 << 'PYEOF'
import json, os

# ~/.claude.json — minimal, no host state
cfg = {
    "hasCompletedOnboarding": True,
    "autoUpdates": False,
    "installMethod": "npm",
    "mcpServers": {
        "mempalace": {
            "command": "python3",
            "args": ["-m", "mempalace.mcp_server"]
        }
    },
    "projects": {
        "/workspace": {
            "hasTrustDialogAccepted": True,
            "hasCompletedProjectOnboarding": True,
        }
    },
}

cfg_path = "/home/agent/.claude.json"
with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)
os.chown(cfg_path, 1001, 1001)

# ~/.claude/settings.json — permissions only
settings = {"skipDangerousModePermissionPrompt": True}
settings_path = "/home/agent/.claude/settings.json"
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
os.chown(settings_path, 1001, 1001)
PYEOF

# --- Ensure writable dirs for Claude Code runtime ---

for d in session-env projects plans history cache; do
    mkdir -p "$AGENT_HOME/.claude/$d"
    chown agent:agent "$AGENT_HOME/.claude/$d"
done

# --- Launch ---

mkdir -p /workspace
chown agent:agent /workspace

# Pass z.ai env vars through to the agent user's environment
EXPORT_VARS=""
[ -n "$ANTHROPIC_AUTH_TOKEN" ] && EXPORT_VARS="export ANTHROPIC_AUTH_TOKEN='$ANTHROPIC_AUTH_TOKEN'; "
[ -n "$ANTHROPIC_BASE_URL" ] && EXPORT_VARS="${EXPORT_VARS}export ANTHROPIC_BASE_URL='$ANTHROPIC_BASE_URL'; "

CMD="${EXPORT_VARS}cd /workspace"
if [ $# -gt 0 ]; then
    CMD="$CMD && exec $(printf '%q ' "$@")"
else
    CMD="$CMD && exec bash"
fi

exec su -s /bin/bash agent -c "$CMD"
