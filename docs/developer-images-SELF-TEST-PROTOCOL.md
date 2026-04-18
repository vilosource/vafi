# Developer Images — Self-Test Protocol for Claude

**Audience:** Claude (or another AI agent) operating the host shell.
**Purpose:** Allow an AI operator to autonomously start, smoke-test, and drive
`vafi-developer:<harness>` containers via headless modes and JSON output —
without needing a human to interpret TTY output.

This protocol complements the interactive launchers (`vfdev`/`ogcli`/`ogdr`/`pidev`).
Those require a TTY and are for human use. **This protocol is for non-TTY automation.**

---

## Invariants you can rely on

Every `vafi-developer:<harness>` image guarantees:

| Property | Value |
|---|---|
| OS | Debian 12 (bookworm) |
| User | `agent` (uid 1001, gid 1001) |
| WorkDir | `/workspace` |
| ENTRYPOINT | `/opt/vf-harness/init.sh` (sets up auth, MCP config; then `exec "$@"`) |
| CMD | `bash` (default — overridable) |
| `$VF_HARNESS` | `claude` / `pi` / `gemini` (matches the leaf tag) |
| Headless runner | `/opt/vf-harness/run.sh "<prompt>"` — dispatches per harness, emits JSON |
| Universal tools | `claude` xor `pi` xor `gemini` in `$PATH`; plus `python3`, `mempalace`, `kubectl`, `terraform`, `helm`, `gh`, `glab`, `go`, `uv`, `docker`, `ripgrep`, `jq` |
| Mempalace | Importable: `python3 -c "import mempalace"` |

---

## Core invocation pattern

```bash
docker run --rm -i \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  -v "$(pwd):/workspace" \
  vafi/vafi-developer:<harness> \
  /opt/vf-harness/run.sh "your prompt here"
```

Key flags:

- **`--rm`** — container is ephemeral; no state left behind.
- **`-i`** (NOT `-t`) — interactive stdin without a TTY. Required for JSON streaming to parse cleanly; `-t` corrupts output with escape sequences.
- **`-v "$(pwd):/workspace"`** — bind-mount your scratch dir so the harness can read/write files.
- **`/opt/vf-harness/run.sh`** — the generic dispatcher; sets up JSON output and skip-permission flags per harness. Runs exactly one prompt and exits.

---

## Per-harness headless invocations

All three harnesses accept a non-interactive prompt with JSON output. The
`/opt/vf-harness/run.sh` wrapper normalizes the flag differences — prefer it
over calling the CLI directly.

### Claude Code

```bash
# Via the wrapper (recommended):
docker run --rm -i -e ANTHROPIC_API_KEY="$KEY" -v "$(pwd):/workspace" \
  vafi/vafi-developer:claude \
  /opt/vf-harness/run.sh "List files in /workspace"

# Direct invocation:
docker run --rm -i -e ANTHROPIC_API_KEY="$KEY" -v "$(pwd):/workspace" \
  vafi/vafi-developer:claude \
  claude -p "List files in /workspace" \
    --output-format json \
    --dangerously-skip-permissions \
    --max-turns 10
```

- Output: single JSON object on stdout, `{"session_id":…, "result":"…", "is_error":false, "total_cost_usd":…, "num_turns":…}`.
- Stream each message as it arrives: replace `--output-format json` with `--output-format stream-json`. Each line of stdout is a JSON event. Use `jq -cr '.type' ` to tag.

### Pi

```bash
docker run --rm -i -e GEMINI_API_KEY="$KEY" -v "$(pwd):/workspace" \
  vafi/vafi-developer:pi \
  /opt/vf-harness/run.sh "Summarize pyproject.toml"

# Direct:
docker run --rm -i -e ANTHROPIC_API_KEY="$KEY" -v "$(pwd):/workspace" \
  vafi/vafi-developer:pi \
  pi -p "Summarize pyproject.toml" --mode json
```

- Output: single JSON object on stdout with `result`, `session_id` (if session kept), tool-call log.
- Pi does **not** have a `--dangerously-skip-permissions` equivalent. Its tool set is opt-in via `--tools <list>`; default is `read,bash,edit,write`. To sandbox further: `--tools read,grep,find,ls`.

### Gemini

```bash
docker run --rm -i -e GEMINI_API_KEY="$KEY" -v "$(pwd):/workspace" \
  vafi/vafi-developer:gemini \
  /opt/vf-harness/run.sh "What's in this repo?"

# Direct:
docker run --rm -i -e GEMINI_API_KEY="$KEY" -v "$(pwd):/workspace" \
  vafi/vafi-developer:gemini \
  gemini -p "What's in this repo?" -y --output-format json
```

- Output: single JSON object on stdout.
- `-y` (yolo) auto-approves tool calls. Alternative: `--approval-mode yolo | auto_edit | plan | default`.

---

## Pi multi-turn sessions

### Preferred: `--session-dir` + `--continue` (works from shell one-liners)

For any multi-turn pi test where you just need context to persist across calls, use a session directory and `--continue`:

```bash
SESS=$(mktemp -d); chmod 777 "$SESS"

# Turn 1: plant context
docker run --rm -i -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  -v "$SESS:/sessions" \
  vafi/vafi-developer:pi \
  pi -p "Remember this: XYZ123. Reply: ok" --mode json --session-dir /sessions

# Turn 2: --continue reads the latest session from /sessions
docker run --rm -i -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  -v "$SESS:/sessions" \
  vafi/vafi-developer:pi \
  pi -p "What exact string did I ask you to remember?" --mode json --session-dir /sessions --continue
```

Verified working 2026-04-17: the recall returns the plant verbatim across two independent `docker run` invocations.

### Low-level: `pi --mode rpc` (for in-process bridge use)

Pi also has a persistent RPC mode that keeps a single process alive and accepts bidirectional messages on stdio. The protocol is **not** JSON-RPC 2.0 — it uses Pi's own envelope:

```
→ stdin:  {"type": "get_state"}
← stdout: {"type":"response","command":"get_state","data":{"sessionId":"…"}}
→ stdin:  {"type": "prompt", "message": "Hello"}
← stdout: NDJSON events (same shape as --mode json) terminating in {"type":"agent_end",...}
→ stdin:  {"type": "prompt", "message": "follow-up"}
← stdout: (NDJSON again, session continues)
→ stdin:  {"type": "shutdown"}
```

**Gotcha**: piping all commands at once on stdin can cause pi to consume `shutdown` before completing later prompts. Proper RPC driving requires reading until `agent_end` before sending the next prompt — not a one-liner. Reference implementation: `src/bridge/pi_session.py` + `pi_protocol.py` in this repo.

For ad-hoc multi-turn testing, prefer the `--session-dir`+`--continue` approach above.

Claude and Gemini do **not** offer equivalent RPC modes. For multi-turn with those:
- Claude: `--continue` / `--resume` against a persisted `~/.claude/` dir via bind-mount.
- Gemini: `--resume latest` / `--resume <index>` against a persisted `~/.gemini/` dir via bind-mount.

---

## Auth injection

| Env var | Consumed by | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude, Pi (Anthropic provider) | Direct API key |
| `ANTHROPIC_OAUTH_TOKEN` | Claude, Pi | OAuth alternative |
| `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL` | Claude, Pi | For z.ai or other Anthropic-compat proxies |
| `CLAUDE_CREDENTIALS` | Claude (vafi pattern) | JSON blob; `init-claude.sh` writes it to `~/.claude/.credentials.json` |
| `GEMINI_API_KEY` | Gemini native, Pi (google provider — default) | |
| `OPENAI_API_KEY` | Pi (OpenAI provider) | |
| `GROQ_API_KEY` | Pi (Groq provider) | |

Always pass with `-e VAR="$VAR"` — do NOT use `-e VAR` alone (that only exports the name, not the value).

For passing the Claude credentials file:
```bash
-e CLAUDE_CREDENTIALS="$(cat ~/.claude/.credentials.json)"
```

---

## Common runbooks

### R1. Verify an image boots and is healthy

```bash
docker run --rm --entrypoint="" vafi/vafi-developer:claude bash -c '
  set -e
  echo "== harness =="; claude --version
  echo "== mempalace =="; python3 -c "import mempalace; print(mempalace.__version__)"
  echo "== tools =="; which kubectl terraform helm gh go
  echo "== VF_HARNESS =="; echo "$VF_HARNESS"
'
```

### R2. One-shot prompt with JSON result, parse with jq

```bash
RESULT=$(docker run --rm -i \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v "$(pwd):/workspace" \
  vafi/vafi-developer:claude \
  /opt/vf-harness/run.sh "What is the purpose of $(basename $(pwd))?" 2>/dev/null)
echo "$RESULT" | jq -r '.result // .response // .final'
```

### R3. Stream each message as it arrives

```bash
docker run --rm -i \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v "$(pwd):/workspace" \
  vafi/vafi-developer:claude \
  claude -p "Analyze this code" \
    --output-format stream-json \
    --dangerously-skip-permissions \
  | while read -r line; do
      type=$(echo "$line" | jq -r '.type // empty')
      case "$type" in
        message) echo "$line" | jq -r '.message.content' ;;
        tool_use) echo ">> tool: $(echo "$line" | jq -r '.name')" ;;
        result) echo "<< done: $(echo "$line" | jq -r '.result')" ;;
      esac
    done
```

### R4. Run an arbitrary command inside the container (bypass harness)

```bash
# Get a shell inside with all tools, no harness auto-launch:
docker run --rm -it --entrypoint=bash \
  -v "$(pwd):/workspace" \
  vafi/vafi-developer:claude

# Or run a single shell command:
docker run --rm --entrypoint=bash \
  -v "$(pwd):/workspace" \
  vafi/vafi-developer:claude \
  -c "kubectl get ns && terraform version"
```

### R5. Compare all three harnesses on the same prompt

```bash
PROMPT="Name three Python best practices."
for h in claude pi gemini; do
  echo "=== $h ==="
  docker run --rm -i \
    -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
    -e GEMINI_API_KEY="$GEMINI_API_KEY" \
    vafi/vafi-developer:$h \
    /opt/vf-harness/run.sh "$PROMPT" 2>/dev/null | jq -r '.result // .message // .'
done
```

### R6. Use pi RPC for a two-turn session

```bash
{
  echo '{"jsonrpc":"2.0","id":1,"method":"prompt","params":{"message":"remember the number 42"}}'
  sleep 2
  echo '{"jsonrpc":"2.0","id":2,"method":"prompt","params":{"message":"what number did i ask you to remember?"}}'
} | docker run --rm -i \
    -e GEMINI_API_KEY="$GEMINI_API_KEY" \
    vafi/vafi-developer:pi \
    pi --mode rpc
```

### R7. Run the full smoke-test suite (structural, offline)

```bash
~/GitHub/vafi/scripts/smoke-test-developer.sh         # all three leaves
~/GitHub/vafi/scripts/smoke-test-developer.sh claude  # one leaf
```

### R8. Run the full prompt-test suite (API-calling, content-verified)

```bash
# All three harnesses × 3 tests (hello, math, workspace read) plus pi multi-turn
~/GitHub/vafi/scripts/prompt-test-developer.sh

# Single harness
~/GitHub/vafi/scripts/prompt-test-developer.sh gemini
```

Expected output (10/10 verified 2026-04-17 against claude 2.1.112 / pi 0.67.6 / gemini 0.38.1):
```
=== vafi/vafi-developer:claude (prompt tests) ===
  ok — T1 hello → "protocol ok"
  ok — T2 math → answer contains 25
  ok — T3 workspace read → response contains marker
=== vafi/vafi-developer:pi (prompt tests) ===
  ok — T1 hello → "protocol ok"
  ok — T2 math → answer contains 25
  ok — T3 workspace read → response contains marker
  ok — T4 pi multi-turn session → recalled across --continue
=== vafi/vafi-developer:gemini (prompt tests) ===
  ok — T1 hello → "protocol ok"
  ok — T2 math → answer contains 25
  ok — T3 workspace read → response contains marker
=== Summary: 10 passed, 0 failed, 0 skipped ===
```

---

## Output parsing — JSON shapes

### Claude `--output-format json`

```json
{
  "session_id": "sess-abc",
  "result": "The assistant's final text reply",
  "is_error": false,
  "total_cost_usd": 0.021,
  "num_turns": 3,
  "duration_ms": 8412
}
```

### Pi `--mode json` — NDJSON (streaming events, not a single object)

Unlike Claude and Gemini, Pi emits **newline-delimited JSON (NDJSON)** — one JSON event per line. The last line is a `{"type":"agent_end", ...}` event with all messages. This was empirically verified 2026-04-17 on pi 0.67.6.

```
{"type":"session","version":3,"id":"…","timestamp":"…","cwd":"/workspace"}
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"message_start","message":{"role":"user","content":[...]}}
{"type":"message_end","message":{...}}
{"type":"message_start","message":{"role":"assistant","content":[]}}
{"type":"message_update","assistantMessageEvent":{"type":"thinking_start","contentIndex":0,"partial":{...}}}
…  (many message_update events as the model streams)
{"type":"message_end","message":{"role":"assistant","content":[{"type":"thinking",...},{"type":"text","text":"…"}],…}}
{"type":"agent_end","messages":[...all messages...]}
```

**Extract final text** from the last line:

```bash
tail -1 | jq -r '(.messages[-1].content // []) | map(select(.type=="text")) | map(.text) | join("\n")'
```

A universal extractor that handles both formats:

```bash
_extract_text() {
  local input; input=$(cat)
  if printf '%s' "$input" | tail -1 | jq -e '.type == "agent_end"' >/dev/null 2>&1; then
    # Pi NDJSON
    printf '%s' "$input" | tail -1 | jq -r '(.messages[-1].content // []) | map(select(.type=="text")) | map(.text) | join("\n")'
  else
    # Claude or Gemini single-JSON
    printf '%s' "$input" | jq -r '.result // .response // .final // .message // ""'
  fi
}
```

### Gemini `--output-format json`

```json
{
  "session_id": "…",
  "response": "The assistant's final text reply",
  "stats": {
    "models": { "<model-id>": { "api": {...}, "tokens": {...} } }
  }
}
```

Note Gemini uses **`response`**, not `result`. Use a jq fallback chain:
`jq -r '.result // .response // .final // .message // "(unknown format)"'`.

Exact field names can drift with new CLI releases. Check the harness version
in the leaf tag (`vafi-developer:claude-2.1.112`) and the CLI's own `--help`
to confirm.

---

## Gotchas & mitigations

| Gotcha | Symptom | Fix |
|---|---|---|
| `-t` flag causes mangled JSON | jq can't parse output | Use `-i` only (no `-t`) |
| Auth env var not forwarded | `[harness] WARNING: No auth configured` in stderr | Pass `-e VAR="$VAR"` — `$VAR` must be set in the outer shell |
| `/workspace` readonly inside | Tool calls fail with EACCES | Bind-mount with `-v "$PWD":/workspace` (no `:ro`); ensure host dir is world-writable or owned by uid 1001 |
| Harness prompts for permission anyway | Container hangs indefinitely | Ensure the wrapper `/opt/vf-harness/run.sh` is used, or pass `--dangerously-skip-permissions` (Claude) / `-y` (Gemini) / `--no-session` (Pi) |
| Prompt contains shell metacharacters | Partial prompt sent to harness | Single-quote the prompt; avoid command substitution inside double-quoted prompt unless intentional |
| Claude exceeds max turns silently | `is_error: true, result: "max_turns exceeded"` | Increase `--max-turns` or split the task |
| Mempalace MCP fails to start | Stderr "connection refused" on first prompt | Run once with `-e MEMPALACE_AUTO_INIT=true`; palace dir is created under the bind-mount |
| Network `vafi-mcp` missing | MCP server queries time out | Start the shared network first: `docker network create vafi-mcp` (or set it up via vafi helm chart); `run.sh` still works for plain prompts |

---

## When to use which harness

For AI-agent self-operation, practical differences:

- **Claude** — best at code-edit tasks, best tool-use, longest context, most mature streaming. Default choice for editing / reviewing code.
- **Pi** — only harness with true RPC mode; best for persistent multi-turn agent flows. Also the most flexible on provider choice (google, anthropic, openai, groq).
- **Gemini** — fast, cheap. Good for quick classification / summarization / shell pipelines. Output quality varies more than Claude.

---

## Minimum recipe to test a harness end-to-end

Copy-paste block:

```bash
HARNESS="${HARNESS:-claude}"
PROMPT="${PROMPT:-Say hello in one sentence.}"

case "$HARNESS" in
  claude) AUTH=(-e "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}") ;;
  pi|gemini) AUTH=(-e "GEMINI_API_KEY=${GEMINI_API_KEY:-}") ;;
esac

docker run --rm -i "${AUTH[@]}" \
  -v "$(pwd):/workspace" \
  vafi/vafi-developer:$HARNESS \
  /opt/vf-harness/run.sh "$PROMPT" \
  | tee /tmp/last-harness-output.json \
  | jq -r '.result // .response // .final // .message // .'
```

Sets env, runs the universal wrapper, saves raw JSON, prints the final text.

**Verified working 2026-04-17:** The gemini path of this recipe returned
`"protocol ok"` end-to-end against `vafi-developer:gemini-0.38.1`.

---

## See also

- `docs/developer-images-DESIGN.md` — architecture & rationale.
- `docs/developer-images-S1-REPORT.md` — per-harness install recipes, flag reference.
- `scripts/smoke-test-developer.sh` — ready-made validation script.
- `images/developer/vf-harness/run.sh` — source of the headless dispatcher (inspect to understand exactly what flags are passed).
