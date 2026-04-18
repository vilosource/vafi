# vf-harness init-claude.sh — Claude Code setup.
# Sourced by /opt/vf-harness/init.sh. Runs as agent user.
#
# Auth sources (first match wins):
#   CLAUDE_CREDENTIALS   — full JSON blob written to ~/.claude/.credentials.json
#   ANTHROPIC_OAUTH_TOKEN — OAuth token
#   ANTHROPIC_API_KEY    — direct API key
#   ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL — z.ai or other Anthropic-compat proxy

if [ -n "${CLAUDE_CREDENTIALS:-}" ]; then
  mkdir -p "$HOME/.claude"
  echo "$CLAUDE_CREDENTIALS" > "$HOME/.claude/.credentials.json"
  chmod 600 "$HOME/.claude/.credentials.json"
  unset CLAUDE_CREDENTIALS
  echo >&2 "[claude] Auth: OAuth credentials"
elif [ -n "${ANTHROPIC_OAUTH_TOKEN:-}" ]; then
  echo >&2 "[claude] Auth: ANTHROPIC_OAUTH_TOKEN"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo >&2 "[claude] Auth: ANTHROPIC_API_KEY"
elif [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  echo >&2 "[claude] Auth: ANTHROPIC_AUTH_TOKEN (proxy: ${ANTHROPIC_BASE_URL:-unset})"
else
  echo >&2 "[claude] WARNING: No Claude auth configured"
fi

# Build ~/.claude.json with onboarding flags + mempalace MCP
python3 <<'PYEOF'
import json, os

cfg_path = os.path.expanduser("~/.claude.json")
try:
    with open(cfg_path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}

cfg["hasCompletedOnboarding"] = True
cfg["autoUpdates"] = False
cfg["installMethod"] = "npm"

servers = cfg.setdefault("mcpServers", {})
servers.setdefault("mempalace", {
    "command": "python3",
    "args": ["-m", "mempalace.mcp_server"],
})

mw_host = os.environ.get("MW_API_HOST", "")
if mw_host:
    servers["mediawiki"] = {
        "command": "mcp-mediawiki",
        "args": ["--transport", "stdio"],
        "env": {
            "MW_API_HOST": mw_host,
            "MW_API_PATH": os.environ.get("MW_API_PATH", "/"),
            "MW_USE_HTTPS": os.environ.get("MW_USE_HTTPS", "true"),
            "MW_BOT_USER": os.environ.get("MW_BOT_USER", ""),
            "MW_BOT_PASS": os.environ.get("MW_BOT_PASS", ""),
        },
    }

projects = cfg.setdefault("projects", {})
projects["/workspace"] = {
    "hasTrustDialogAccepted": True,
    "hasCompletedProjectOnboarding": True,
}

with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=2)

os.makedirs(os.path.expanduser("~/.claude"), exist_ok=True)
with open(os.path.expanduser("~/.claude/settings.json"), "w") as f:
    json.dump({"skipDangerousModePermissionPrompt": True}, f, indent=2)
PYEOF

# Writable runtime dirs Claude expects
for d in session-env projects plans history cache; do
  mkdir -p "$HOME/.claude/$d"
done

export VF_HARNESS=claude
