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

# Ensure sessions directory exists
mkdir -p "$VF_SESSIONS_DIR"

# Start the controller
echo "Starting vafi controller..."
exec python3 -m controller