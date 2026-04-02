#!/bin/bash
WORKDIR=$(cat /tmp/ready 2>/dev/null || echo /home/agent)
cd "$WORKDIR"

DIR_KEY=$(pwd | sed 's|/|-|g')
if [ -d "$HOME/.claude/projects/$DIR_KEY" ]; then
    exec claude --continue --dangerously-skip-permissions
else
    exec claude --dangerously-skip-permissions
fi
