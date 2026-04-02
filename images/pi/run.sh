#!/bin/bash
set -e
PROMPT="${1:-$VF_PROMPT}"
ROLE="${VF_AGENT_ROLE:-executor}"
METHODOLOGY="/opt/vf-agent/methodologies/${ROLE}.md"

ARGS="-p \"$PROMPT\" --provider anthropic --model ${VF_PI_MODEL:-claude-sonnet-4-20250514} --mode json --no-session"
[ -f "$METHODOLOGY" ] && ARGS="$ARGS --append-system-prompt $METHODOLOGY"
[ -n "$VF_MAX_TURNS" ] && ARGS="$ARGS --max-turns $VF_MAX_TURNS"

if [ -n "$VF_CXDB_URL" ]; then
    exec cxtx --url "$VF_CXDB_URL" --label "task:${VF_TASK_ID:-unknown}" pi -- $ARGS
else
    exec pi $ARGS
fi
