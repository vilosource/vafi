#!/bin/bash
# Entrypoint for local and headless use. Runs as agent user (NO ROOT).
#
# Auth modes (auto-detected):
#   z.ai:    ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL env vars
#   OAuth:   CLAUDE_CREDENTIALS env var (JSON content, set by wrapper)
#   Neither: warning, no auth
#
# Env vars:
#   CLAUDE_CREDENTIALS     — contents of .credentials.json (set by wrapper)
#   ANTHROPIC_AUTH_TOKEN   — z.ai token
#   ANTHROPIC_BASE_URL     — z.ai endpoint
#   MW_API_HOST/PATH/...   — MediaWiki config (optional)
#   MEMPALACE_AUTO_INIT    — auto-init empty palace if "true"
set -e

# --- Auth ---

if [ -n "$ANTHROPIC_AUTH_TOKEN" ]; then
    echo >&2 "[developer] Auth: z.ai"
elif [ -n "$CLAUDE_CREDENTIALS" ]; then
    mkdir -p ~/.claude
    echo "$CLAUDE_CREDENTIALS" > ~/.claude/.credentials.json
    chmod 600 ~/.claude/.credentials.json
    unset CLAUDE_CREDENTIALS
    echo >&2 "[developer] Auth: OAuth"
else
    echo >&2 "[developer] WARNING: No auth configured"
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
}

# MediaWiki MCP (registered when MW_API_HOST is set)
mw_host = os.environ.get("MW_API_HOST", "")
if mw_host:
    mw_env = {}
    for key in ("MW_API_HOST", "MW_API_PATH", "MW_USE_HTTPS", "MW_BOT_USER", "MW_BOT_PASS"):
        val = os.environ.get(key, "")
        if val:
            mw_env[key] = val
    cfg["mcpServers"]["mediawiki"] = {
        "command": "mcp-mediawiki",
        "args": ["--transport", "stdio"],
        "env": mw_env,
    }

cfg["projects"] = {
    "/workspace": {
        "hasTrustDialogAccepted": True,
        "hasCompletedProjectOnboarding": True,
    }
}

with open(os.path.expanduser("~/.claude.json"), "w") as f:
    json.dump(cfg, f, indent=2)

settings = {
    "skipDangerousModePermissionPrompt": True,
    "hooks": {
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "mempalace hook run --hook stop --harness claude-code"
                    }
                ]
            }
        ],
        "PreCompact": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "mempalace hook run --hook precompact --harness claude-code"
                    }
                ]
            }
        ],
    },
}
os.makedirs(os.path.expanduser("~/.claude"), exist_ok=True)
with open(os.path.expanduser("~/.claude/settings.json"), "w") as f:
    json.dump(settings, f, indent=2)
PYEOF

# --- Ensure writable dirs for Claude Code runtime ---

for d in session-env projects plans history cache; do
    mkdir -p ~/.claude/$d
done

# --- glab (GitLab CLI) config ---

if [ -n "$GITLAB_TOKEN" ]; then
    mkdir -p ~/.config/glab-cli
    cat > ~/.config/glab-cli/config.yml << GLEOF
hosts:
  ${GITLAB_HOST:-gitlab.optiscangroup.com}:
    token: ${GITLAB_TOKEN}
    api_host: ${GITLAB_HOST:-gitlab.optiscangroup.com}
    api_protocol: https
    git_protocol: ssh
GLEOF
    chmod 600 ~/.config/glab-cli/config.yml
    echo >&2 "[developer] glab: configured for ${GITLAB_HOST:-gitlab.optiscangroup.com}"
fi

# --- Auto-init empty palace ---

if [ ! -d ~/.mempalace/palace ] && [ "${MEMPALACE_AUTO_INIT:-false}" = "true" ]; then
    echo >&2 "[developer] Auto-initializing empty palace"
    mempalace init /workspace --yes 2>/dev/null || true
fi

# --- Launch ---

cd /workspace
exec "$@"
