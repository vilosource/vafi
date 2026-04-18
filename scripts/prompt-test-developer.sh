#!/usr/bin/env bash
# Prompt-based test suite for vafi-developer:<harness> images.
#
# Unlike smoke-test-developer.sh (structural, offline), this script actually
# talks to each harness CLI via /opt/vf-harness/run.sh and verifies that the
# full stack works end-to-end: auth injection → CLI invocation → JSON output
# parse → expected content.
#
# Tests per harness:
#   T1. Hello          — auth works, JSON parseable, non-empty response
#   T2. Math sanity    — response contains "25" for "32-7"
#   T3. Workspace read — tool-use works, response mentions the marker we wrote
#   T4. (pi only) RPC  — multi-turn context preservation over JSON-RPC
#
# Auth env vars read from host:
#   GEMINI_API_KEY           — gemini + pi (default google provider)
#   ANTHROPIC_API_KEY        — claude + pi (anthropic provider)
#   ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL — claude + pi via Anthropic-compat proxy
#   CLAUDE_CREDENTIALS (auto-derived from ~/.claude/.credentials.json) — claude OAuth
#
# Usage:
#   ./prompt-test-developer.sh                    # all harnesses (skips missing auth)
#   ./prompt-test-developer.sh claude             # single harness
#   ./prompt-test-developer.sh claude gemini      # subset
#
# Environment:
#   VAFI_REGISTRY=vafi         # image registry prefix
#   PROMPT_TEST_VERBOSE=1      # print full JSON + stderr for every test
#   PROMPT_TEST_TIMEOUT=120    # seconds per prompt (default 120)

set -uo pipefail

REGISTRY="${VAFI_REGISTRY:-vafi}"
TIMEOUT="${PROMPT_TEST_TIMEOUT:-120}"
VERBOSE="${PROMPT_TEST_VERBOSE:-0}"

# Scratch workspace with marker file for T3
WS=$(mktemp -d)
chmod 777 "$WS"
MARKER_CONTENT="VAFIDEV_PROMPT_MARKER_9c8e2f"
echo "$MARKER_CONTENT" > "$WS/marker.txt"
trap 'rm -rf "$WS"' EXIT

PASS=0
FAIL=0
SKIP=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_print_header() {
  echo
  echo "=== $1 ==="
}

_report() {
  local status="$1"; shift
  local label="$1"; shift
  case "$status" in
    PASS) echo "  ok    — $label"; PASS=$((PASS+1)) ;;
    FAIL) echo "  FAIL  — $label"; FAIL=$((FAIL+1)) ;;
    SKIP) echo "  skip  — $label"; SKIP=$((SKIP+1)) ;;
  esac
  if [ -n "${1:-}" ]; then echo "        $1"; fi
}

# Return the auth env args (as a space-separated list of -e flags) for a harness.
# Skips the harness if required auth is missing.
_auth_args_or_skip() {
  local harness="$1"
  local -a args=()
  case "$harness" in
    claude)
      if [ -f "$HOME/.claude/.credentials.json" ]; then
        args+=(-e "CLAUDE_CREDENTIALS=$(cat "$HOME/.claude/.credentials.json")")
      elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        args+=(-e "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
      elif [ -n "${ANTHROPIC_OAUTH_TOKEN:-}" ]; then
        args+=(-e "ANTHROPIC_OAUTH_TOKEN=$ANTHROPIC_OAUTH_TOKEN")
      elif [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
        args+=(-e "ANTHROPIC_AUTH_TOKEN=$ANTHROPIC_AUTH_TOKEN"
               -e "ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-https://api.anthropic.com}")
      else
        return 1
      fi
      ;;
    pi)
      # Pi accepts any of several providers; prefer GEMINI (matches host env).
      if [ -n "${GEMINI_API_KEY:-}" ]; then
        args+=(-e "GEMINI_API_KEY=$GEMINI_API_KEY")
      elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        args+=(-e "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY")
      elif [ -n "${OPENAI_API_KEY:-}" ]; then
        args+=(-e "OPENAI_API_KEY=$OPENAI_API_KEY")
      else
        return 1
      fi
      ;;
    gemini)
      if [ -n "${GEMINI_API_KEY:-}" ]; then
        args+=(-e "GEMINI_API_KEY=$GEMINI_API_KEY")
      else
        return 1
      fi
      ;;
  esac
  # Print on stdout for capture
  printf '%s\n' "${args[@]}"
}

# Run a prompt via /opt/vf-harness/run.sh and capture raw JSON stdout.
# Args: harness, prompt. Stdout: raw JSON. Stderr: init log.
_run_prompt() {
  local harness="$1"; shift
  local prompt="$1"; shift
  local image="${REGISTRY}/vafi-developer:${harness}"

  # Read auth-args lines into array
  local -a auth
  mapfile -t auth < <(_auth_args_or_skip "$harness") || return 2

  timeout "$TIMEOUT" docker run --rm -i \
    "${auth[@]}" \
    -v "$WS:/workspace" \
    "$image" \
    /opt/vf-harness/run.sh "$prompt"
}

# Extract the assistant's final text from whichever format this harness uses.
# Handles both:
#   - Single-JSON (claude/gemini): {"result":"..."} or {"response":"..."}
#   - NDJSON stream (pi --mode json): last line is {"type":"agent_end","messages":[...]}
#     where the last message is the assistant with content[{type:text, text:"..."}]
_extract_text() {
  local input; input=$(cat)
  local lines; lines=$(printf '%s' "$input" | wc -l)
  if [ "$lines" -gt 0 ] && printf '%s' "$input" | tail -1 | jq -e '.type == "agent_end"' >/dev/null 2>&1; then
    # Pi NDJSON: get all text entries from the last message
    printf '%s' "$input" | tail -1 | jq -r '
      (.messages[-1].content // []) |
      map(select(.type == "text")) |
      map(.text) |
      join("\n")
    '
  else
    printf '%s' "$input" | jq -r '.result // .response // .final // .message // ""'
  fi
}

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

test_hello() {
  local harness="$1"
  local out rc text
  out=$(_run_prompt "$harness" "Respond with exactly two words: protocol ok" 2>/tmp/prompt-test-$harness-hello.err)
  rc=$?
  if [ "$rc" -eq 2 ]; then
    _report SKIP "T1 hello (no auth available)"
    return
  fi
  if [ "$rc" -ne 0 ]; then
    _report FAIL "T1 hello (docker run rc=$rc, timeout? see /tmp/prompt-test-$harness-hello.err)"
    return
  fi
  text=$(printf '%s' "$out" | _extract_text)
  if [ -z "$text" ]; then
    _report FAIL "T1 hello (empty text after extraction)"
    [ "$VERBOSE" = "1" ] && { echo "--- stdout (first 400 chars) ---"; printf '%s' "$out" | head -c 400; echo; }
    return
  fi
  # Content check: must contain the expected two-word phrase
  if echo "$text" | grep -qi "protocol ok"; then
    _report PASS "T1 hello → \"$(echo "$text" | head -c 80)\""
  else
    _report FAIL "T1 hello (response didn't contain 'protocol ok': \"$(echo "$text" | head -c 120)\")"
  fi
}

test_math() {
  local harness="$1"
  local out rc text
  out=$(_run_prompt "$harness" "Respond with only the single number that is the answer to 32 minus 7. No words, no punctuation, no explanation." 2>/tmp/prompt-test-$harness-math.err)
  rc=$?
  if [ "$rc" -eq 2 ]; then
    _report SKIP "T2 math (no auth available)"
    return
  fi
  if [ "$rc" -ne 0 ]; then
    _report FAIL "T2 math (docker run rc=$rc)"
    return
  fi
  text=$(echo "$out" | _extract_text)
  if echo "$text" | grep -qE '\b25\b'; then
    _report PASS "T2 math → answer contains 25"
  else
    _report FAIL "T2 math (no 25 in response: \"$(echo "$text" | head -c 100)\")"
  fi
}

test_workspace_read() {
  local harness="$1"
  local out rc text
  # Ask the harness to read /workspace/marker.txt and include its content in
  # the response. This exercises tool-use (bash/read tool).
  out=$(_run_prompt "$harness" \
    "Read the file /workspace/marker.txt and include its contents verbatim in your response." \
    2>/tmp/prompt-test-$harness-ws.err)
  rc=$?
  if [ "$rc" -eq 2 ]; then
    _report SKIP "T3 workspace read (no auth available)"
    return
  fi
  if [ "$rc" -ne 0 ]; then
    _report FAIL "T3 workspace read (docker run rc=$rc)"
    return
  fi
  text=$(echo "$out" | _extract_text)
  if echo "$text" | grep -q "$MARKER_CONTENT"; then
    _report PASS "T3 workspace read → response contains marker"
  else
    _report FAIL "T3 workspace read (marker not in response: \"$(echo "$text" | head -c 150)\")"
  fi
}

test_pi_multiturn() {
  # Multi-turn context preservation via --session-dir (most reliable way to
  # test pi's cross-turn memory without coordinating RPC stdin timing).
  #
  # Note: pi also supports --mode rpc for persistent sessions (see
  # src/bridge/pi_session.py). That requires bidirectional IO with proper
  # sequencing — tested by the vafi bridge integration suite, not here.
  local harness=pi
  local image="${REGISTRY}/vafi-developer:${harness}"
  local -a auth
  mapfile -t auth < <(_auth_args_or_skip "$harness") || {
    _report SKIP "T4 pi multi-turn session (no auth available)"
    return
  }

  local memory_tag="PI_MEM_$(date +%s)_$$"
  local sess_dir; sess_dir=$(mktemp -d)
  chmod 777 "$sess_dir"

  # Turn 1: plant a memory, use --mode json (single-shot JSON, NOT the NDJSON
  # streaming mode) and --session-dir to persist.
  timeout "$TIMEOUT" docker run --rm -i \
    "${auth[@]}" -v "$WS:/workspace" -v "$sess_dir:/sessions" \
    "$image" pi -p "Remember this exact string: $memory_tag. Reply only with: ok" \
      --mode json --session-dir /sessions >/tmp/pi-mt1.out 2>/tmp/pi-mt1.err
  local rc1=$?

  if [ "$rc1" -ne 0 ]; then
    _report FAIL "T4 pi multi-turn session (turn 1 failed rc=$rc1)"
    [ "$VERBOSE" = "1" ] && cat /tmp/pi-mt1.err | head -20
    rm -rf "$sess_dir"; return
  fi

  # Turn 2: --continue reads the latest session from --session-dir.
  timeout "$TIMEOUT" docker run --rm -i \
    "${auth[@]}" -v "$WS:/workspace" -v "$sess_dir:/sessions" \
    "$image" pi -p "Repeat the exact string I asked you to remember. Reply with only that string." \
      --mode json --session-dir /sessions --continue >/tmp/pi-mt2.out 2>/tmp/pi-mt2.err
  local rc2=$?

  if [ "$rc2" -ne 0 ]; then
    _report FAIL "T4 pi multi-turn session (turn 2 failed rc=$rc2)"
    [ "$VERBOSE" = "1" ] && cat /tmp/pi-mt2.err | head -20
    rm -rf "$sess_dir"; return
  fi

  local recall; recall=$(cat /tmp/pi-mt2.out | _extract_text)
  rm -rf "$sess_dir"

  if echo "$recall" | grep -q "$memory_tag"; then
    _report PASS "T4 pi multi-turn session → \"$memory_tag\" recalled across --continue"
  else
    _report FAIL "T4 pi multi-turn session (memory not in recall: \"$(echo "$recall" | head -c 120)\")"
  fi
}

test_harness() {
  local harness="$1"
  _print_header "${REGISTRY}/vafi-developer:${harness} (prompt tests)"
  if ! docker image inspect "${REGISTRY}/vafi-developer:${harness}" >/dev/null 2>&1; then
    _report SKIP "image missing"
    return
  fi
  test_hello "$harness"
  test_math "$harness"
  test_workspace_read "$harness"
  [ "$harness" = "pi" ] && test_pi_multiturn
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
  if [ $# -eq 0 ]; then
    test_harness claude
    test_harness pi
    test_harness gemini
  else
    for h in "$@"; do test_harness "$h"; done
  fi

  echo
  echo "=== Summary: $PASS passed, $FAIL failed, $SKIP skipped ==="
  [ "$FAIL" -eq 0 ]
}

main "$@"
