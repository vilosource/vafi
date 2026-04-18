#!/usr/bin/env bash
# Verifies that mempalace state is shared across all three harnesses within a
# single context (e.g., ogcli claude and ogcli pi see the same drawers).
#
# Method:
#   1. Pick a context (default OG) and read its palace drawer count directly
#      via python3 + mempalace library (ground truth from disk).
#   2. For each harness, launch a container with the context bind-mount and
#      have it call mempalace_status via its MCP tool, then compare.
#
# Usage:
#   ./mempalace-shared-test.sh              # test OG (default)
#   ./mempalace-shared-test.sh VF           # test VF context
#   ./mempalace-shared-test.sh all          # test all four contexts

set -uo pipefail

REGISTRY="${VAFI_REGISTRY:-vafi}"
TIMEOUT="${MEMPALACE_TEST_TIMEOUT:-180}"

PASS=0
FAIL=0
SKIP=0

_report() {
  local status="$1" label="$2" detail="${3:-}"
  case "$status" in
    PASS) echo "  ok    — $label${detail:+ → $detail}"; PASS=$((PASS+1)) ;;
    FAIL) echo "  FAIL  — $label${detail:+ → $detail}"; FAIL=$((FAIL+1)) ;;
    SKIP) echo "  skip  — $label${detail:+ ($detail)}"; SKIP=$((SKIP+1)) ;;
  esac
}

# Ground-truth drawer count via direct mempalace Python API
get_palace_count() {
  local ctx_home="$1"
  # Write the probe to a temp file (avoid heredoc quoting issues in a function).
  local probe="/tmp/mp-count-$$-$RANDOM.py"
  printf '%s\n' \
    'from mempalace.mcp_server import tool_status' \
    's = tool_status()' \
    'print(s.get("total_drawers", 0))' \
    > "$probe"

  local out
  out=$(docker run --rm --entrypoint="" \
    -v "$ctx_home:/home/agent" -u agent \
    -v "$probe:/tmp/mp-count.py" \
    "${REGISTRY}/vafi-developer:claude" \
    python3 /tmp/mp-count.py 2>&1)
  rm -f "$probe"
  # Return the last line of output (the integer, or error if it failed)
  echo "$out" | tail -1
}

# Ask a harness to call mempalace_status via MCP and return the drawer count it sees
harness_palace_count() {
  local harness="$1" ctx_home="$2" ctx_ws="$3"
  local image="${REGISTRY}/vafi-developer:${harness}"

  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "IMAGE_MISSING"; return
  fi

  local auth=()
  case "$harness" in
    claude)
      if [ -f "$HOME/.claude/.credentials.json" ]; then
        auth+=(-e "CLAUDE_CREDENTIALS=$(cat "$HOME/.claude/.credentials.json")")
      elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        auth+=(-e "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
      else
        echo "NO_AUTH"; return
      fi
      ;;
    pi|gemini)
      [ -n "${GEMINI_API_KEY:-}" ] && auth+=(-e "GEMINI_API_KEY=$GEMINI_API_KEY") || { echo "NO_AUTH"; return; }
      ;;
  esac

  local prompt="Call the mempalace_status tool and respond with ONLY the integer value of total_drawers. No other text, no formatting, just the number."
  local raw
  raw=$(timeout "$TIMEOUT" docker run --rm -i \
    "${auth[@]}" \
    -v "$ctx_home:/home/agent" \
    -v "$ctx_ws:/workspace" \
    "$image" \
    /opt/vf-harness/run.sh "$prompt" 2>/dev/null)

  # Pi returns NDJSON; others return single JSON. Extract text then find an integer.
  local text
  if printf '%s' "$raw" | tail -1 | jq -e '.type == "agent_end"' >/dev/null 2>&1; then
    text=$(printf '%s' "$raw" | tail -1 | jq -r '(.messages[-1].content // []) | map(select(.type=="text")) | map(.text) | join("\n")' 2>/dev/null)
  else
    text=$(printf '%s' "$raw" | jq -r '.result // .response // .final // ""' 2>/dev/null)
  fi

  # Find the first integer in the response
  echo "$text" | grep -oE '[0-9]+' | head -1
}

test_context() {
  local ctx="$1"
  local ctx_home="$HOME/$ctx/home/agent"
  local ctx_ws="$HOME/$ctx/workspace"

  echo
  echo "=== Context: $ctx (root: $HOME/$ctx) ==="

  if [ ! -d "$ctx_home" ]; then
    _report SKIP "$ctx" "no home dir"
    return
  fi

  local truth
  truth=$(get_palace_count "$ctx_home")
  if ! [[ "$truth" =~ ^[0-9]+$ ]]; then
    _report FAIL "$ctx ground truth" "couldn't read palace ($truth)"
    return
  fi
  echo "  ground truth: $truth drawers on disk"

  for h in claude pi gemini; do
    local got; got=$(harness_palace_count "$h" "$ctx_home" "$ctx_ws")
    case "$got" in
      IMAGE_MISSING) _report SKIP "$ctx × $h" "image missing" ;;
      NO_AUTH)       _report SKIP "$ctx × $h" "no auth" ;;
      "")            _report FAIL "$ctx × $h" "empty response" ;;
      "$truth")      _report PASS "$ctx × $h" "$got drawers (matches)" ;;
      *)
        # Non-matching number — harness saw a different palace
        _report FAIL "$ctx × $h" "saw $got, expected $truth (MISMATCH)" ;;
    esac
  done
}

main() {
  local target="${1:-OG}"
  if [ "$target" = "all" ]; then
    for c in VF OG DR PI; do test_context "$c"; done
  else
    test_context "$target"
  fi

  echo
  echo "=== Summary: $PASS passed, $FAIL failed, $SKIP skipped ==="
  [ "$FAIL" -eq 0 ]
}

main "$@"
