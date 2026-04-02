#!/bin/bash
set -e
PROMPT="${1:-$VF_PROMPT}"
ARGS="-p \"$PROMPT\" --output-format json --dangerously-skip-permissions"
[ -n "$VF_MAX_TURNS" ] && ARGS="$ARGS --max-turns $VF_MAX_TURNS"

if [ -n "$VF_CXDB_URL" ]; then
    exec cxtx --url "$VF_CXDB_URL" --label "task:${VF_TASK_ID:-unknown}" claude -- $ARGS
else
    exec claude $ARGS
fi
