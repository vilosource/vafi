#!/usr/bin/env bash
# E2E tests for the vafi-claude-mempalace container image.
# Runs Claude Code headless (--output-format json) to verify:
#   1. Container boots and Claude Code works
#   2. Mempalace MCP tools are registered and callable
#   3. Mempalace search, diary, and knowledge graph work
#   4. Palace isolation between volumes
#   5. Workspace mount works
#
# Usage:
#   ./tests/test_mempalace_e2e.sh                    # use local image
#   MEMPALACE_IMAGE=harbor.viloforge.com/... ./tests/test_mempalace_e2e.sh  # use remote
set -euo pipefail

IMAGE="${MEMPALACE_IMAGE:-vafi/vafi-claude-mempalace:latest}"
PASS=0
FAIL=0
TESTS=()

# --- Helpers ---

run_claude() {
    # Run a headless Claude Code prompt inside the mempalace container.
    # Args: palace_name prompt [extra_docker_args...]
    local palace="$1" prompt="$2"
    shift 2
    docker run --rm \
        -v "${HOME}/.claude:/home/agent/.claude-host:ro" \
        -v "${HOME}/.claude.json:/home/agent/.claude-host.json:ro" \
        -v "mempalace-e2e-${palace}:/home/agent/.mempalace" \
        --entrypoint /opt/mempalace/entrypoint-local.sh \
        "$@" \
        "$IMAGE" \
        claude -p "$prompt" --output-format json --dangerously-skip-permissions --max-turns 5 2>/dev/null
}

extract_result() {
    # Extract the result field from Claude Code JSON output.
    python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('result',''))" 2>/dev/null
}

assert_contains() {
    local test_name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -qi "$needle"; then
        echo "  PASS: $test_name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $test_name"
        echo "    expected to contain: $needle"
        echo "    got: ${haystack:0:200}"
        FAIL=$((FAIL + 1))
    fi
    TESTS+=("$test_name")
}

assert_not_contains() {
    local test_name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -qi "$needle"; then
        echo "  FAIL: $test_name"
        echo "    expected NOT to contain: $needle"
        FAIL=$((FAIL + 1))
    else
        echo "  PASS: $test_name"
        PASS=$((PASS + 1))
    fi
    TESTS+=("$test_name")
}

assert_json_ok() {
    local test_name="$1" json_output="$2"
    if echo "$json_output" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if not d.get('is_error') else 1)" 2>/dev/null; then
        echo "  PASS: $test_name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $test_name (is_error=true or invalid JSON)"
        echo "    output: ${json_output:0:200}"
        FAIL=$((FAIL + 1))
    fi
    TESTS+=("$test_name")
}

cleanup() {
    echo ""
    echo "Cleaning up test volumes..."
    docker volume rm mempalace-e2e-test1 mempalace-e2e-test2 mempalace-e2e-isolated 2>/dev/null || true
}
trap cleanup EXIT

# --- Tests ---

echo "============================================"
echo "  MemPalace E2E Tests"
echo "  Image: $IMAGE"
echo "============================================"
echo ""

# Clean slate
docker volume rm mempalace-e2e-test1 mempalace-e2e-test2 mempalace-e2e-isolated 2>/dev/null || true

# -----------------------------------------------
echo "T1: Claude Code executes bash commands"
# -----------------------------------------------
OUTPUT=$(run_claude test1 "Run this bash command and return only the output: pwd")
assert_json_ok "T1: JSON response valid" "$OUTPUT"
RESULT=$(echo "$OUTPUT" | extract_result)
assert_contains "T1: pwd returns /workspace" "$RESULT" "/workspace"

# -----------------------------------------------
echo "T2: Mempalace MCP tools are registered"
# -----------------------------------------------
OUTPUT=$(run_claude test1 "List all available MCP tools from the mempalace server. Return ONLY the tool names, one per line.")
assert_json_ok "T2: JSON response valid" "$OUTPUT"
RESULT=$(echo "$OUTPUT" | extract_result)
assert_contains "T2: mempalace_search tool exists" "$RESULT" "mempalace_search"
assert_contains "T2: mempalace_diary_write tool exists" "$RESULT" "mempalace_diary_write"
assert_contains "T2: mempalace_kg_add tool exists" "$RESULT" "mempalace_kg_add"

# -----------------------------------------------
echo "T3: Mempalace diary write and read"
# -----------------------------------------------
OUTPUT=$(run_claude test1 'Use the mempalace_diary_write tool to write a diary entry for agent_name "executor" with entry "E2E test marker: kiwi-fruit-42" and topic "testing". Then use mempalace_diary_read for agent_name "executor" and confirm the entry exists. Reply with the word CONFIRMED if you see the entry.')
assert_json_ok "T3: JSON response valid" "$OUTPUT"
RESULT=$(echo "$OUTPUT" | extract_result)
assert_contains "T3: diary entry confirmed" "$RESULT" "CONFIRMED"

# -----------------------------------------------
echo "T4: Mempalace diary persists across sessions"
# -----------------------------------------------
OUTPUT=$(run_claude test1 'Use the mempalace_diary_read tool for agent_name "executor". Does the diary contain the text "kiwi-fruit-42"? Reply FOUND or NOT_FOUND.')
assert_json_ok "T4: JSON response valid" "$OUTPUT"
RESULT=$(echo "$OUTPUT" | extract_result)
assert_contains "T4: diary persists across sessions" "$RESULT" "FOUND"

# -----------------------------------------------
echo "T5: Mempalace knowledge graph"
# -----------------------------------------------
OUTPUT=$(run_claude test1 'Use the mempalace_kg_add tool with subject "vafi", predicate "uses", object "asyncio", valid_from "2026-01-01". Then use mempalace_kg_query with entity "vafi". Reply with the word SUCCESS if the triple was added and found.')
assert_json_ok "T5: JSON response valid" "$OUTPUT"
RESULT=$(echo "$OUTPUT" | extract_result)
assert_contains "T5: KG triple added and queried" "$RESULT" "SUCCESS"

# -----------------------------------------------
echo "T6: Palace isolation — separate volumes"
# -----------------------------------------------
# Write to isolated palace
OUTPUT=$(run_claude isolated 'Use mempalace_diary_write for agent_name "tester" with entry "secret-isolation-marker-99" and topic "isolation". Reply WRITTEN when done.')
assert_json_ok "T6a: write to isolated palace" "$OUTPUT"

# Search in test1 palace — should NOT find it
OUTPUT=$(run_claude test1 'Use mempalace_diary_read for agent_name "tester". Does it contain "secret-isolation-marker-99"? Reply FOUND or NOT_FOUND.')
RESULT=$(echo "$OUTPUT" | extract_result)
assert_contains "T6b: isolated data not in default palace" "$RESULT" "NOT_FOUND"

# Search in isolated palace — should find it
OUTPUT=$(run_claude isolated 'Use mempalace_diary_read for agent_name "tester". Does it contain "secret-isolation-marker-99"? Reply FOUND or NOT_FOUND.')
RESULT=$(echo "$OUTPUT" | extract_result)
assert_contains "T6c: isolated data in its own palace" "$RESULT" "FOUND"

# -----------------------------------------------
echo "T7: Workspace mount is writable"
# -----------------------------------------------
TMPDIR=$(mktemp -d)
OUTPUT=$(docker run --rm \
    -v "${HOME}/.claude:/home/agent/.claude-host:ro" \
    -v "${HOME}/.claude.json:/home/agent/.claude-host.json:ro" \
    -v "mempalace-e2e-test2:/home/agent/.mempalace" \
    -v "$TMPDIR:/workspace" \
    --entrypoint /opt/mempalace/entrypoint-local.sh \
    "$IMAGE" \
    claude -p 'Create a file called hello.txt containing "mempalace-e2e-ok". Use the bash tool. Reply CREATED when done.' \
    --output-format json --dangerously-skip-permissions --max-turns 3 2>/dev/null)
assert_json_ok "T7: JSON response valid" "$OUTPUT"
if [ -f "$TMPDIR/hello.txt" ]; then
    CONTENT=$(cat "$TMPDIR/hello.txt")
    assert_contains "T7: file persists on host" "$CONTENT" "mempalace-e2e-ok"
else
    echo "  FAIL: T7: hello.txt not created on host"
    FAIL=$((FAIL + 1))
    TESTS+=("T7: file persists on host")
fi
rm -rf "$TMPDIR"

# --- Summary ---

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed (${#TESTS[@]} total)"
echo "============================================"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
