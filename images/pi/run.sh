#!/bin/bash
set -e
PROMPT="${1:-$VF_PROMPT}"
ROLE="${VF_AGENT_ROLE:-executor}"
METHODOLOGY="/opt/vf-agent/methodologies/${ROLE}.md"

CMD=(pi -p "$PROMPT" --provider anthropic --model "${VF_PI_MODEL:-claude-sonnet-4-20250514}" --mode json --no-session)
[ -f "$METHODOLOGY" ] && CMD+=(--append-system-prompt "$METHODOLOGY")
[ -n "$VF_MAX_TURNS" ] && CMD+=(--max-turns "$VF_MAX_TURNS")

if [ -n "$VF_CXDB_URL" ]; then
    exec cxtx --url "$VF_CXDB_URL" --label "task:${VF_TASK_ID:-unknown}" "${CMD[@]}"
else
    exec "${CMD[@]}"
fi
