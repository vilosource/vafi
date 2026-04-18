#!/usr/bin/env bash
# End-to-end test — drives each context launcher (vfdev/ogcli/ogdr/pidev) with
# each harness (claude/pi/gemini) exactly the way a user would, and verifies the
# agent actually responds to a real prompt.
#
# This complements:
#   - smoke-test-developer.sh   — structural checks inside the image
#   - prompt-test-developer.sh  — harness validation bypassing the launcher
#
# This test proves that when a USER types `vfdev claude`, the launcher's env
# injection + image selection + entrypoint dispatch + harness auth all connect,
# and the agent can answer a simple prompt ("What day is it?").
#
# Requires:
#   - ~/.claude/vf-launchers.sh sourced into the running shell (or available)
#   - Context dirs (~/VF, ~/OG, ~/DR, ~/PI) already set up with uid 1001 ownership
#   - Host env has appropriate auth (GEMINI_API_KEY + ~/.claude/.credentials.json)
#
# Usage:
#   ./launcher-test-developer.sh                       # all 4 × 3 = 12 combinations
#   ./launcher-test-developer.sh vfdev                 # single launcher × all harnesses
#   ./launcher-test-developer.sh vfdev claude          # single combo
#
# Environment:
#   LAUNCHER_TEST_TIMEOUT=180    # seconds per invocation
#   LAUNCHER_TEST_VERBOSE=1      # print full JSON + stderr on fail

set -uo pipefail

TIMEOUT="${LAUNCHER_TEST_TIMEOUT:-180}"
VERBOSE="${LAUNCHER_TEST_VERBOSE:-0}"
REGISTRY="${VAFI_REGISTRY:-vafi}"

# Source launchers
if [ -z "${_VAFI_DEV_SOURCED:-}" ]; then
  if [ -f "$HOME/.claude/vf-launchers.sh" ]; then
    . "$HOME/.claude/vf-launchers.sh"
  else
    echo "ERROR: ~/.claude/vf-launchers.sh not found" >&2
    exit 1
  fi
fi

# Regex for a weekday word, case-insensitive.
WEEKDAY_RE='(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)'

PASS=0
FAIL=0
SKIP=0

# Universal text extractor — handles Claude/Gemini single-JSON and Pi NDJSON.
_extract_text() {
  local input; input=$(cat)
  if printf '%s' "$input" | tail -1 | jq -e '.type == "agent_end"' >/dev/null 2>&1; then
    printf '%s' "$input" | tail -1 \
      | jq -r '(.messages[-1].content // []) | map(select(.type=="text")) | map(.text) | join("\n")'
  else
    printf '%s' "$input" | jq -r '.result // .response // .final // .message // ""'
  fi
}

_report() {
  local status="$1" label="$2" detail="${3:-}"
  case "$status" in
    PASS) echo "  ok    — $label${detail:+ → $detail}"; PASS=$((PASS+1)) ;;
    FAIL) echo "  FAIL  — $label${detail:+ → $detail}"; FAIL=$((FAIL+1)) ;;
    SKIP) echo "  skip  — $label${detail:+ ($detail)}"; SKIP=$((SKIP+1)) ;;
  esac
}

test_combo() {
  local launcher="$1" harness="$2"
  local label="${launcher} ${harness}"
  local prompt="What is the current day of the week? Reply with ONLY a single English word like Monday, Tuesday, etc. No other text."

  if ! command -v "$launcher" >/dev/null 2>&1; then
    _report SKIP "$label" "launcher function not defined"
    return
  fi

  local raw; raw=$(mktemp)
  local err; err=$(mktemp)

  # </dev/null ensures no TTY; launcher auto-detects and uses -i only.
  # Must wrap with `bash -c` so timeout (a binary) can execute a shell function.
  # Prompt is passed through $1 to avoid quoting headaches.
  timeout "$TIMEOUT" bash -c '
    . "$HOME/.claude/vf-launchers.sh"
    "$1" "$2" /opt/vf-harness/run.sh "$3"
  ' _ "$launcher" "$harness" "$prompt" </dev/null >"$raw" 2>"$err"
  local rc=$?

  if [ "$rc" -ne 0 ]; then
    local hint=""
    grep -q "No auth configured" "$err" 2>/dev/null && hint="no auth forwarded for $harness"
    grep -q "not a TTY" "$err" 2>/dev/null && hint="TTY flag issue"
    grep -q "pull access denied\|manifest unknown" "$err" 2>/dev/null && hint="image missing"
    _report FAIL "$label" "rc=$rc${hint:+, $hint}"
    if [ "$VERBOSE" = "1" ]; then
      echo "  --- stderr ---"; head -30 "$err" | sed 's/^/    /'
      echo "  --- stdout ---"; head -30 "$raw" | sed 's/^/    /'
    fi
    rm -f "$raw" "$err"
    return
  fi

  local text; text=$(cat "$raw" | _extract_text)
  rm -f "$raw" "$err"

  if [ -z "$text" ]; then
    _report FAIL "$label" "empty response after extraction"
    return
  fi

  if echo "$text" | grep -qiE "$WEEKDAY_RE"; then
    _report PASS "$label" "\"$(echo "$text" | tr -d '\n' | head -c 80)\""
  else
    _report FAIL "$label" "no weekday word in response: \"$(echo "$text" | tr -d '\n' | head -c 120)\""
  fi
}

test_launcher() {
  local launcher="$1"; shift
  echo
  echo "=== $launcher ==="
  if [ $# -gt 0 ]; then
    for h in "$@"; do test_combo "$launcher" "$h"; done
  else
    test_combo "$launcher" claude
    test_combo "$launcher" pi
    test_combo "$launcher" gemini
  fi
}

# --- Dispatch verification (no real docker runs; stubs docker to inspect args) ---
# Ensures the launcher wiring is correct:
#   - default CMD is /opt/vf-harness/connect.sh
#   - `launcher <harness> bash` overrides to bash
#   - pin syntax routes to the pinned tag

_captured_image=""
_captured_cmd=""
_stub_docker() {
  docker() {
    if [ "$1" = "network" ]; then return 1; fi
    if [ "$1" = "run" ]; then
      shift
      _captured_image=""; _captured_cmd=""
      local seen=false
      for a in "$@"; do
        if [ "$seen" = true ]; then
          _captured_cmd="${_captured_cmd:+$_captured_cmd }$a"
        elif [[ "$a" == */vafi-developer:* ]] || [[ "$a" == vafi-developer:* ]]; then
          _captured_image="$a"; seen=true
        fi
      done
      return 0
    fi
  }
  export -f docker
}

test_dispatch() {
  local label="$1" cmd="$2" expected_image_suffix="$3" expected_cmd="$4"
  _captured_image=""; _captured_cmd=""
  eval "$cmd" >/dev/null 2>&1 || true
  local ok_img=false ok_cmd=false
  [[ "$_captured_image" == *"$expected_image_suffix" ]] && ok_img=true
  [ "$_captured_cmd" = "$expected_cmd" ] && ok_cmd=true
  if $ok_img && $ok_cmd; then
    _report PASS "dispatch: $label" "image ends :${expected_image_suffix##*:}, cmd=[$expected_cmd]"
  else
    _report FAIL "dispatch: $label" "image=$_captured_image cmd=[$_captured_cmd]"
  fi
}

run_dispatch_tests() {
  echo
  echo "=== Launcher dispatch (stubbed docker) ==="
  _stub_docker
  # Default harness, no cmd → connect.sh
  test_dispatch "ogcli (no args)"       "ogcli"               ":claude"         "/opt/vf-harness/connect.sh"
  test_dispatch "vfdev (no args)"       "vfdev"               ":claude"         "/opt/vf-harness/connect.sh"
  test_dispatch "pidev (no args)"       "pidev"               ":pi"             "/opt/vf-harness/connect.sh"
  # Explicit harness, no cmd → connect.sh
  test_dispatch "ogcli claude"          "ogcli claude"        ":claude"         "/opt/vf-harness/connect.sh"
  test_dispatch "ogcli pi"              "ogcli pi"            ":pi"             "/opt/vf-harness/connect.sh"
  test_dispatch "ogcli gemini"          "ogcli gemini"        ":gemini"         "/opt/vf-harness/connect.sh"
  # Override cmd with bash
  test_dispatch "ogcli claude bash"     "ogcli claude bash"   ":claude"         "bash"
  # Pinned version
  test_dispatch "ogcli claude:2.1.112"  "ogcli claude:2.1.112" ":claude-2.1.112" "/opt/vf-harness/connect.sh"
  # Explicit run.sh for headless use
  test_dispatch "vfdev pi run.sh hi"    "vfdev pi /opt/vf-harness/run.sh hi" ":pi" "/opt/vf-harness/run.sh hi"
  # Unset docker stub
  unset -f docker
}

# --- connect.sh wiring verification ---
# Two complementary checks per harness:
#   (a) connect.sh has the right case branch and references the correct binary
#   (b) the harness binary is installed and in $PATH
# The full runtime behavior is already covered by the launcher-level day-of-week
# test (12 combos) — this just pins down the "user drops directly into the CLI"
# contract without depending on CLI-specific flag quirks.
test_connect_source() {
  local harness="$1"
  local image="${REGISTRY}/vafi-developer:${harness}"
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    _report SKIP "connect.sh → $harness" "image missing"; return
  fi

  # Pull connect.sh content + check the binary is in $PATH — all in one container run.
  local probe
  probe=$(docker run --rm --entrypoint="" "$image" bash -c "
    cat /opt/vf-harness/connect.sh
    echo '===BIN==='
    command -v $harness || echo MISSING
  " 2>&1)

  local script_part binary_path
  script_part=$(echo "$probe" | sed -n '1,/^===BIN===$/{/^===BIN===$/!p;}')
  binary_path=$(echo "$probe" | awk '/^===BIN===$/{flag=1; next} flag')

  # Check case branch exists and execs the right binary
  local has_branch=false has_exec=false
  echo "$script_part" | grep -qE "^  $harness\)" && has_branch=true
  echo "$script_part" | grep -qE "exec $harness " && has_exec=true

  if [ "$has_branch" = true ] && [ "$has_exec" = true ] && [ "$binary_path" != "MISSING" ]; then
    _report PASS "connect.sh → $harness" "branch OK, binary at $binary_path"
  else
    local why=""
    [ "$has_branch" = false ] && why="${why:+$why, }no branch"
    [ "$has_exec" = false ] && why="${why:+$why, }no 'exec $harness'"
    [ "$binary_path" = "MISSING" ] && why="${why:+$why, }binary missing from PATH"
    _report FAIL "connect.sh → $harness" "$why"
  fi
}

run_connect_tests() {
  echo
  echo "=== connect.sh wiring (source branch + binary reachable) ==="
  test_connect_source claude
  test_connect_source pi
  test_connect_source gemini
}

main() {
  echo "Launcher-level end-to-end tests — all 4 × 3 combinations drive the"
  echo "full user path: launcher → env injection → image → harness → response."

  if [ $# -eq 0 ]; then
    run_dispatch_tests
    run_connect_tests
    test_launcher vfdev
    test_launcher ogcli
    test_launcher ogdr
    test_launcher pidev
  elif [ $# -eq 1 ] && [ "$1" = "dispatch" ]; then
    run_dispatch_tests
  elif [ $# -eq 1 ] && [ "$1" = "connect" ]; then
    run_connect_tests
  elif [ $# -eq 1 ]; then
    test_launcher "$1"
  else
    local launcher="$1"; shift
    test_launcher "$launcher" "$@"
  fi

  echo
  echo "=== Summary: $PASS passed, $FAIL failed, $SKIP skipped ==="
  [ "$FAIL" -eq 0 ]
}

main "$@"
