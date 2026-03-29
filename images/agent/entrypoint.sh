#!/bin/bash
set -euo pipefail

# Copy methodology to CLAUDE.md based on VF_AGENT_ROLE
AGENT_ROLE="${VF_AGENT_ROLE:-executor}"
METHODOLOGY_FILE="/opt/vf-agent/methodologies/${AGENT_ROLE}.md"

# Ensure .claude directory exists
mkdir -p /home/agent/.claude

if [ -f "$METHODOLOGY_FILE" ]; then
    echo "Setting up methodology for role: $AGENT_ROLE"
    cp "$METHODOLOGY_FILE" /home/agent/.claude/CLAUDE.md
else
    echo "Warning: No methodology found for role '$AGENT_ROLE'"
    echo "Available methodologies:"
    ls -1 /opt/vf-agent/methodologies/ || echo "None found"
fi

# Configure git identity for commits
git config --global user.name "vafi-agent"
git config --global user.email "vafi-agent@noreply.viloforge.com"

# Ensure sessions directory exists
mkdir -p "${VF_SESSIONS_DIR:-/sessions}"

# --- Architect role: interactive/autonomous planning, no controller ---
if [ "$AGENT_ROLE" = "architect" ]; then
    REPO_URL="${VF_REPO_URL:-}"
    DEFAULT_BRANCH="${VF_DEFAULT_BRANCH:-main}"
    WORKDIR="${VF_SESSIONS_DIR:-/sessions}/architect-$$"

    # Patch ~/.claude.json: skip onboarding + configure vtf MCP
    VTF_MCP_URL="${VF_VTF_MCP_URL:-}"
    VTF_TOKEN="${VF_VTF_TOKEN:-}"
    python3 -c "
import json, os

cfg_path = os.path.expanduser('~/.claude.json')
try:
    with open(cfg_path) as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}

cfg['hasCompletedOnboarding'] = True
cfg['theme'] = 'dark'

workdir = os.environ.get('WORKDIR', '/sessions/architect')
projects = cfg.get('projects', {})
projects[workdir] = {
    'hasTrustDialogAccepted': True,
    'hasCompletedProjectOnboarding': True
}
cfg['projects'] = projects

mcp_url = os.environ.get('VTF_MCP_URL', '')
vtf_token = os.environ.get('VTF_TOKEN', '')
if mcp_url and vtf_token:
    cfg['mcpServers'] = {
        'vtf': {
            'type': 'http',
            'url': mcp_url,
            'headers': {
                'Authorization': f'Token {vtf_token}'
            }
        }
    }

with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2)
" 2>&1 && echo "Patched ~/.claude.json" || echo "Warning: failed to patch ~/.claude.json"

    # Clone project repo if URL provided
    if [ -n "$REPO_URL" ]; then
        if [ ! -d "$WORKDIR/.git" ]; then
            echo "Cloning $REPO_URL (branch: $DEFAULT_BRANCH) to $WORKDIR"
            git clone --branch "$DEFAULT_BRANCH" --single-branch --depth 1 "$REPO_URL" "$WORKDIR"
        else
            echo "Repo already cloned at $WORKDIR"
        fi
        cd "$WORKDIR"
    fi

    # Autonomous mode: run with prompt and exit
    if [ -n "${VF_ARCHITECT_PROMPT:-}" ]; then
        echo "Running architect in autonomous mode..."
        exec claude -p "$VF_ARCHITECT_PROMPT" --output-format json \
            --max-turns "${VF_MAX_TURNS:-50}" --dangerously-skip-permissions
    fi

    # Interactive mode: wait for attach
    echo "Architect ready at ${WORKDIR:-$(pwd)}."
    echo "Attach with: kubectl exec -it <pod> -- bash -c 'cd ${WORKDIR:-$(pwd)} && claude'"
    exec sleep infinity
fi

# --- Executor/Judge: run the controller loop ---
echo "Starting vafi controller..."
exec python3 -m controller