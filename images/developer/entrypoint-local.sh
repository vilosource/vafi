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

# --- Merge MCP servers and project trust into Claude Code config ---

python3 << 'PYEOF'
import json, os

config_path = os.path.expanduser("~/.claude.json")

# Load existing config if present (preserves Claude Code runtime state)
cfg = {}
if os.path.exists(config_path):
    with open(config_path) as f:
        cfg = json.load(f)

# Ensure required keys (only set if missing — don't overwrite Claude's own values)
cfg.setdefault("hasCompletedOnboarding", True)
cfg.setdefault("autoUpdates", False)

# MCP servers: rebuild every start to reflect current env vars
mcp = {
    "mempalace": {
        "command": "python3",
        "args": ["-m", "mempalace.mcp_server"]
    }
}

# MediaWiki MCP (registered when MW_API_HOST is set)
mw_host = os.environ.get("MW_API_HOST", "")
if mw_host:
    mw_env = {}
    for key in ("MW_API_HOST", "MW_API_PATH", "MW_USE_HTTPS", "MW_BOT_USER", "MW_BOT_PASS"):
        val = os.environ.get(key, "")
        if val:
            mw_env[key] = val
    mcp["mediawiki"] = {
        "command": "mcp-mediawiki",
        "args": ["--transport", "stdio"],
        "env": mw_env,
    }

# Playwright MCP (remote SSE server)
playwright_url = os.environ.get("PLAYWRIGHT_MCP_URL", "http://host.docker.internal:8931/sse")
if playwright_url:
    mcp["playwright"] = {
        "type": "sse",
        "url": playwright_url,
    }

cfg["mcpServers"] = mcp

# Project trust
cfg.setdefault("projects", {})
cfg["projects"]["/workspace"] = {
    "hasTrustDialogAccepted": True,
    "hasCompletedProjectOnboarding": True,
}

with open(config_path, "w") as f:
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

# --- CLAUDE.md: tell Claude about mempalace ---

cat > ~/.claude/CLAUDE.md << 'CLAUDEMD'
## Memory System: MemPalace

You have persistent memory across sessions via MemPalace MCP tools. Memories survive
container restarts. Use them proactively — don't wait to be asked.

### When to READ memory
- At the START of every session: search for relevant context before doing work.
- When the user mentions a topic: search to see if you already know about it.
- Before making decisions: check if past decisions or gotchas exist.

### When to WRITE memory
- When you discover something important: gotchas, decisions, architecture findings.
- When the user shares context: conventions, preferences, project structure.
- When a Stop hook fires: save key topics, decisions, quotes using the tools below.
- When a PreCompact hook fires: save EVERYTHING — context is about to be compressed.

### MCP Tools (use these, not CLI commands)

**Read/Search:**
- `mempalace_search` — find memories by query. Filter by wing/room for precision.
- `mempalace_list_wings` — see what knowledge domains exist.
- `mempalace_list_rooms` — see topics within a domain.

**Write:**
- `mempalace_add_drawer` — store a memory (facts, findings, summaries). Include source attribution.
- `mempalace_diary_write` — agent diary entries (your observations, session notes). Use topic for categorization.

**Knowledge Graph:**
- `mempalace_kg_add` — record relationships: "vafi uses asyncio", "vtf provides task_board_api".
- `mempalace_kg_query` — query relationships for an entity.
- `mempalace_kg_timeline` — see how an entity's relationships changed over time.

**Duplicates:**
- `mempalace_check_duplicate` — check before adding to avoid redundant entries.

### Auto-Save Hooks
The Stop hook fires every 15 messages. The PreCompact hook fires before context compression.
Both tell you to save — use `mempalace_add_drawer` and `mempalace_diary_write` to do so.
Save key topics, decisions, code patterns, and verbatim quotes. Organize by wing and room.
CLAUDEMD

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
