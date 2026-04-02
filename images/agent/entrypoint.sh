#!/bin/bash
set -euo pipefail

AGENT_ROLE="${VF_AGENT_ROLE:-executor}"

git config --global user.name "vafi-agent"
git config --global user.email "vafi-agent@noreply.viloforge.com"

mkdir -p "${VF_SESSIONS_DIR:-/sessions}"

# --- Architect: clone repo, init harness, wait for terminal ---
if [ "$AGENT_ROLE" = "architect" ]; then
    PROJECT_SLUG="${VTF_PROJECT_SLUG:-}"
    SESSIONS_DIR="${VF_SESSIONS_DIR:-/sessions}"

    if [ -n "$PROJECT_SLUG" ]; then
        WORKDIR="${SESSIONS_DIR}/${PROJECT_SLUG}"
    else
        WORKDIR="${SESSIONS_DIR}/greenfield"
    fi
    export WORKDIR

    REPO_URL="${VF_REPO_URL:-}"
    DEFAULT_BRANCH="${VF_DEFAULT_BRANCH:-main}"
    if [ -n "$REPO_URL" ] && [ ! -d "$WORKDIR/.git" ]; then
        git clone --branch "$DEFAULT_BRANCH" --single-branch --depth 1 "$REPO_URL" "$WORKDIR"
    else
        mkdir -p "$WORKDIR"
    fi

    # Harness self-config (image provides this)
    [ -f /opt/vf-harness/init.sh ] && source /opt/vf-harness/init.sh

    # Autonomous mode
    if [ -n "${VF_ARCHITECT_PROMPT:-}" ]; then
        export VF_PROMPT="$VF_ARCHITECT_PROMPT"
        exec /opt/vf-harness/run.sh
    fi

    echo "$WORKDIR" > /tmp/ready
    exec sleep infinity
fi

# --- Executor/Judge: init harness, run controller ---
[ -f /opt/vf-harness/init.sh ] && source /opt/vf-harness/init.sh
exec python3 -m controller
