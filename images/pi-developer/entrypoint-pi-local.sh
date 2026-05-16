#!/bin/bash
# Entrypoint for PI developer container (local and headless use).
# Runs as agent user (NO ROOT).
#
# Auth modes (auto-detected):
#   z.ai:    ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL env vars
#   API key: ANTHROPIC_API_KEY env var
#   Neither: warning, no auth
#
# Env vars:
#   ANTHROPIC_AUTH_TOKEN   — z.ai token
#   ANTHROPIC_BASE_URL     — z.ai endpoint (default: https://api.z.ai/api/anthropic)
#   ANTHROPIC_API_KEY      — direct Anthropic API key
#   VF_PI_PROVIDER         — LLM provider (default: anthropic)
#   VF_PI_MODEL            — model ID (default: claude-sonnet-4-20250514)
#   MW_API_HOST/PATH/...   — MediaWiki config (optional)
#   GITLAB_TOKEN/HOST      — GitLab CLI config (optional)
#   MEMPALACE_AUTO_INIT    — auto-init empty palace if "true"
set -e

# --- Ensure PI config survives bind mount ---
# When /home/agent is bind-mounted, image-baked files in ~/.pi/agent/ are hidden.
# Restore settings.json (pi-mcp-adapter registration) and extensions from image.

mkdir -p ~/.pi/agent/extensions

# settings.json: ensure pi-mcp-adapter is registered (merge, don't overwrite)
python3 << 'PYEOF'
import json, os

settings_path = os.path.expanduser("~/.pi/agent/settings.json")
settings = {}
if os.path.exists(settings_path):
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except (json.JSONDecodeError, IOError):
        settings = {}

packages = settings.get("packages", [])
if "npm:pi-mcp-adapter" not in packages:
    packages.append("npm:pi-mcp-adapter")
settings["packages"] = packages

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
PYEOF

# Extension: copy from image staging path (always update to latest)
cp /opt/pi-developer/extensions/mempalace-hooks.ts ~/.pi/agent/extensions/mempalace-hooks.ts 2>/dev/null || true

# --- Auth ---

if [ -n "$ANTHROPIC_AUTH_TOKEN" ]; then
    python3 << 'PYEOF'
import json, os

provider = os.environ.get('VF_PI_PROVIDER', 'anthropic')
model = os.environ.get('VF_PI_MODEL', 'claude-sonnet-4-20250514')
base_url = os.environ.get('ANTHROPIC_BASE_URL', 'https://api.z.ai/api/anthropic')

models = {
    "providers": {
        provider: {
            "api": "anthropic-messages",
            "apiKey": "ANTHROPIC_AUTH_TOKEN",
            "models": [{"id": model, "name": model}],
            "baseUrl": base_url,
        }
    }
}

os.makedirs(os.path.expanduser("~/.pi/agent"), exist_ok=True)
with open(os.path.expanduser("~/.pi/agent/models.json"), "w") as f:
    json.dump(models, f, indent=2)
PYEOF
    echo >&2 "[pi-developer] Auth: z.ai"
elif [ -n "$ANTHROPIC_API_KEY" ]; then
    echo >&2 "[pi-developer] Auth: direct API key"
else
    echo >&2 "[pi-developer] WARNING: No auth configured"
fi

# --- MCP servers (merge into mcp.json) ---

python3 << 'PYEOF'
import json, os

mcp_path = os.path.expanduser("~/.pi/agent/mcp.json")

# Load existing (may have been persisted from previous session via bind mount)
cfg = {}
if os.path.exists(mcp_path):
    try:
        with open(mcp_path) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, IOError):
        cfg = {}

servers = cfg.get("mcpServers", {})

# MemPalace (always)
servers["mempalace"] = {
    "command": "python3",
    "args": ["-m", "mempalace.mcp_server"],
    "lifecycle": "eager",
}

# MediaWiki (conditional)
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
        "lifecycle": "eager",
    }

cfg["mcpServers"] = servers
os.makedirs(os.path.dirname(mcp_path), exist_ok=True)
with open(mcp_path, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF

# --- System prompt (MemPalace instructions) ---
# PI auto-discovers ~/.pi/agent/APPEND_SYSTEM.md
cp /opt/pi-developer/APPEND_SYSTEM.md ~/.pi/agent/APPEND_SYSTEM.md 2>/dev/null || true

# --- glab (GitLab CLI) config ---

if [ -n "${GITLAB_TOKEN:-}" ]; then
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
    echo >&2 "[pi-developer] glab: configured for ${GITLAB_HOST:-gitlab.optiscangroup.com}"
fi

# --- MemPalace auto-init ---

if [ ! -d ~/.mempalace/palace ] && [ "${MEMPALACE_AUTO_INIT:-false}" = "true" ]; then
    echo >&2 "[pi-developer] Auto-initializing empty palace"
    mempalace init /workspace --yes 2>/dev/null || true
fi

# --- Launch ---

cd /workspace
exec "$@"
