#!/bin/bash
# vf-harness run.sh — non-interactive one-shot prompt.
# Dispatches on $VF_HARNESS. Output is JSON by default so callers can parse.
# If $VF_CXDB_URL is set, wraps the invocation with cxtx to capture traces.
set -e

PROMPT="${1:-$VF_PROMPT}"
[ -z "$PROMPT" ] && { echo >&2 "[run] No prompt (arg or \$VF_PROMPT)"; exit 2; }

HARNESS="${VF_HARNESS:-claude}"

case "$HARNESS" in
  claude)
    CMD=(claude -p "$PROMPT" --output-format json --dangerously-skip-permissions)
    [ -n "${VF_MAX_TURNS:-}" ] && CMD+=(--max-turns "$VF_MAX_TURNS")
    ;;
  pi)
    CMD=(pi -p "$PROMPT" --mode json)
    # init-pi.sh sets VF_PI_PROVIDER + VF_PI_MODEL based on detected auth.
    # Passing them explicitly overrides pi's auto-discovery of conflicting
    # env vars (e.g. an OpenRouter OPENAI_API_KEY shadowing google).
    [ -n "${VF_PI_PROVIDER:-}" ] && CMD+=(--provider "$VF_PI_PROVIDER")
    [ -n "${VF_PI_MODEL:-}" ]    && CMD+=(--model "$VF_PI_MODEL")
    ;;
  gemini)
    CMD=(gemini -p "$PROMPT" -y --output-format json)
    ;;
  *)
    echo >&2 "[run] Unknown VF_HARNESS=$HARNESS"
    exit 2
    ;;
esac

if [ -n "${VF_CXDB_URL:-}" ]; then
  exec cxtx --url "$VF_CXDB_URL" --label "task:${VF_TASK_ID:-unknown}" "${CMD[@]}"
else
  exec "${CMD[@]}"
fi
