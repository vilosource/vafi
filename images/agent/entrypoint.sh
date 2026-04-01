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
    SESSIONS_DIR="${VF_SESSIONS_DIR:-/sessions}"
    PROJECT_SLUG="${VTF_PROJECT_SLUG:-}"

    # Workdir: /sessions/{project_slug} for existing projects, /sessions/greenfield for new
    if [ -n "$PROJECT_SLUG" ]; then
        WORKDIR="${SESSIONS_DIR}/${PROJECT_SLUG}"
    else
        WORKDIR="${SESSIONS_DIR}/greenfield"
    fi

    # Patch ~/.claude.json: skip onboarding + configure vtf MCP
    export WORKDIR
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
cfg['autoUpdates'] = False

workdir = os.environ.get('WORKDIR', '/sessions/greenfield')
projects = cfg.get('projects', {})
projects[workdir] = {
    'hasTrustDialogAccepted': True,
    'hasCompletedProjectOnboarding': True
}
cfg['projects'] = projects

mcp_url = os.environ.get('VF_VTF_MCP_URL', '')
vtf_token = os.environ.get('VF_VTF_TOKEN', '')
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

    # Write settings.json to skip the bypass-permissions confirmation prompt
    cat > /home/agent/.claude/settings.json <<'SETTINGS'
{
  "skipDangerousModePermissionPrompt": true
}
SETTINGS
    echo "Wrote ~/.claude/settings.json"

    # Clone project repo if URL provided, otherwise create empty workdir
    if [ -n "$REPO_URL" ]; then
        if [ ! -d "$WORKDIR/.git" ]; then
            echo "Cloning $REPO_URL (branch: $DEFAULT_BRANCH) to $WORKDIR"
            git clone --branch "$DEFAULT_BRANCH" --single-branch --depth 1 "$REPO_URL" "$WORKDIR"
        else
            echo "Repo already cloned at $WORKDIR"
        fi
    else
        echo "No repo URL — greenfield mode"
        mkdir -p "$WORKDIR"
    fi

    cd "$WORKDIR"

    # Write project CLAUDE.md so the architect has context about this session
    if [ ! -f CLAUDE.md ]; then
        VTF_API="${VTF_API_URL:-}"
        WORKPLAN_ID="${VTF_WORKPLAN_ID:-}"
        cat > CLAUDE.md <<CLAUDEMD
# Architect Session

You are an architect agent in the vafi fleet. You have MCP access to vtf (task tracker) for managing projects, workplans, and tasks.

## Project
$(if [ -n "$PROJECT_SLUG" ]; then echo "- **Project**: $PROJECT_SLUG"; else echo "- **Mode**: Greenfield (no project yet — help the user define and create one via vtf MCP)"; fi)
$(if [ -n "$REPO_URL" ]; then echo "- **Repository**: $REPO_URL (branch: $DEFAULT_BRANCH)"; fi)
$(if [ -n "$WORKPLAN_ID" ]; then echo "- **Workplan**: $WORKPLAN_ID"; fi)

## Tone and Behavior

You are a knowledgeable team member, not a tool discovering things for the first time. When the user asks about the project:
- Say "Let me refresh my knowledge of the project" or "Checking the current state" — not "I'll look up what project this is"
- Present findings as context you're updating, not discovering
- Lead with what matters: active work, blockers, what needs attention
- Don't narrate your tool calls — just do them and present the results naturally

## Available Tools

Use vtf MCP tools to:
- Browse existing workplans and tasks (vtf_board_overview, vtf_workplan_tree)
- Create and manage tasks (vtf_manage_task, vtf_manage_workplan)
- Search for tasks (vtf_search_tasks)
$(if [ -z "$PROJECT_SLUG" ]; then echo "- Create a new project (vtf_manage_workplan with new project)"; fi)

## Workflow

1. Understand what the user wants to build or change
2. Refresh project state via MCP (if project exists)
3. Break work into concrete, executable tasks
4. Create tasks in vtf with clear specs, acceptance criteria, and test commands
CLAUDEMD
        echo "Wrote project CLAUDE.md"
    fi

    # Write sentinel: signals readiness and stores workdir path for WebSocket proxy
    echo "$WORKDIR" > /tmp/ready
    echo "Architect ready at $WORKDIR"

    # Autonomous mode: run with prompt and exit
    if [ -n "${VF_ARCHITECT_PROMPT:-}" ]; then
        echo "Running architect in autonomous mode..."
        exec claude -p "$VF_ARCHITECT_PROMPT" --output-format json \
            --max-turns "${VF_MAX_TURNS:-50}" --dangerously-skip-permissions
    fi

    # Interactive mode: wait for WebSocket attach
    exec sleep infinity
fi

# --- Executor/Judge: run the controller loop ---
echo "Starting vafi controller..."
exec python3 -m controller