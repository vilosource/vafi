#!/bin/bash
# Entrypoint for local and headless use. Runs as agent user (NO ROOT).
#
# Auth modes (auto-detected):
#   z.ai:    ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL env vars
#   OAuth:   CLAUDE_CREDENTIALS env var (JSON content, set by wrapper)
#   Neither: warning, no auth
set -e

# --- Auth ---

if [ -n "$ANTHROPIC_AUTH_TOKEN" ]; then
    echo >&2 "[mempalace] Auth: z.ai"
elif [ -n "$CLAUDE_CREDENTIALS" ]; then
    mkdir -p ~/.claude
    echo "$CLAUDE_CREDENTIALS" > ~/.claude/.credentials.json
    chmod 600 ~/.claude/.credentials.json
    unset CLAUDE_CREDENTIALS
    echo >&2 "[mempalace] Auth: OAuth"
else
    echo >&2 "[mempalace] WARNING: No auth configured"
fi

# --- Build minimal Claude Code config from scratch ---

python3 << 'PYEOF'
import json, os

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

with open(os.path.expanduser("~/.claude.json"), "w") as f:
    json.dump(cfg, f, indent=2)

settings = {"skipDangerousModePermissionPrompt": True}
os.makedirs(os.path.expanduser("~/.claude"), exist_ok=True)
with open(os.path.expanduser("~/.claude/settings.json"), "w") as f:
    json.dump(settings, f, indent=2)
PYEOF

# --- Ensure writable dirs for Claude Code runtime ---

for d in session-env projects plans history cache; do
    mkdir -p ~/.claude/$d
done

# --- Launch ---

cd /workspace
exec "$@"
