# Harness Images Architecture

How vafi builds and runs agent images for different AI harnesses (Claude Code, Pi).

## Image hierarchy

```
vafi-base (node:20-bookworm-slim + git, python, agent user)
├── vafi-claude (+ claude code CLI + cxtx)
│   └── vafi-agent        (+ controller + methodologies + entrypoint)
└── vafi-pi    (+ pi 0.59.0 + pi-mcp-adapter + cxtx)
    └── vafi-agent-pi     (+ controller + methodologies + entrypoint)
```

Each layer has a clear responsibility:

| Layer | What it adds | Dockerfile |
|-------|-------------|------------|
| `vafi-base` | OS packages, node runtime, `agent` user (UID 1001), workdir separation (`$HOME` != workdir) | `images/base/Dockerfile` |
| `vafi-claude` | Claude Code CLI, cxtx binary (trace capture) | `images/claude/Dockerfile` |
| `vafi-pi` | Pi coding agent 0.59.0, pi-mcp-adapter, cxtx binary | `images/pi/Dockerfile` |
| `vafi-agent` / `vafi-agent-pi` | Python controller, methodologies, templates, entrypoint | `images/agent/Dockerfile` |

The agent Dockerfile is **parameterized** — one Dockerfile builds both variants:

```bash
# Claude executor (default)
docker build --build-arg HARNESS_IMAGE=vafi/vafi-claude:latest -t vafi/vafi-agent:latest -f images/agent/Dockerfile .

# Pi executor
docker build --build-arg HARNESS_IMAGE=vafi/vafi-pi:latest -t vafi/vafi-agent-pi:latest -f images/agent/Dockerfile .
```

## Harness selection

The controller selects the harness at runtime via `VF_HARNESS` environment variable:

| `VF_HARNESS` | CLI binary | Image | Notes |
|-------------|-----------|-------|-------|
| `claude` (default) | `claude` | `vafi-agent` | Requires `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL` |
| `pi` | `pi` | `vafi-agent-pi` | Requires `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` |

Both harnesses use the same controller code, same WorkSource protocol, same gate execution, and same task lifecycle. The only differences are CLI invocation and output parsing.

## How each harness works

### Claude Code

**Startup** (entrypoint):
1. Copies methodology to `~/.claude/CLAUDE.md` (auto-discovered by Claude)
2. *(Architect role only)* Patches `~/.claude.json` with onboarding flags, MCP server config, theme
3. *(Architect role only)* Writes `~/.claude/settings.json` with `skipDangerousModePermissionPrompt: true`

For executor/judge roles, only step 1 applies — the controller invokes Claude with `--dangerously-skip-permissions` directly.

**Invocation** (controller):
```
cxtx --url $CXDB_URL --label task:$TASK_ID claude -- \
  -p "$PROMPT" --output-format json --dangerously-skip-permissions --max-turns 50
```

**Output**: Single JSON object on stdout:
```json
{
  "session_id": "sess-abc",
  "result": "Task completed successfully",
  "is_error": false,
  "total_cost_usd": 0.05,
  "num_turns": 3
}
```

**Key behaviors**:
- `--dangerously-skip-permissions` required — without it, Claude shows a TUI permission prompt that blocks headless execution
- `--output-format json` produces a single JSON summary after execution completes
- Claude auto-discovers `CLAUDE.md` from `~/.claude/` (user-level) and `$CWD/CLAUDE.md` (project-level)
- MCP servers configured in `~/.claude.json` under `mcpServers` key

### Pi Coding Agent

**Startup** (entrypoint):
1. Writes `~/.pi/agent/models.json` with provider, model, and z.ai base URL from env vars
2. Writes `~/.pi/agent/mcp.json` with vtf and cxdb MCP server URLs (if configured)
3. `pi-mcp-adapter` package is pre-installed in the image (registered in `~/.pi/agent/settings.json`)
4. Methodology is NOT copied to a file — delivered via `--append-system-prompt` flag at invocation

**Invocation** (controller):
```
cxtx --url $CXDB_URL --label task:$TASK_ID pi -- \
  -p "$PROMPT" --provider anthropic --model claude-sonnet-4-20250514 \
  --mode json --no-session --max-turns 50 \
  --append-system-prompt /opt/vf-agent/methodologies/executor.md
```

**Output**: Streaming JSONL (one event per line):
```
{"type":"session","id":"sess-abc","version":3}
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"message_start","message":{...}}
{"type":"message_update","assistantMessageEvent":{...}}
{"type":"message_end","message":{...,"usage":{"totalTokens":500}}}
{"type":"turn_end","message":{...},"toolResults":[...]}
{"type":"agent_end","messages":[...]}
```

The controller parses this stream, extracting:
- Session ID from the `session` event
- Turn count from `turn_end` events
- Completion text and token usage from the last assistant message in `agent_end`

**Key behaviors**:
- No permission prompt in headless mode — Pi is headless-safe by default (no `--dangerously-skip-permissions` equivalent needed)
- `--mode json` produces streaming JSONL events (not a single summary)
- Pi does NOT auto-discover methodology files — must use `--append-system-prompt` or `--system-prompt`
- MCP servers configured via `pi-mcp-adapter` extension, reading `~/.pi/agent/mcp.json`
- Pi needs explicit `--provider` and `--model` flags (Claude resolves from env vars automatically)
- Models and API endpoints configured in `~/.pi/agent/models.json` (supports `baseUrl` for z.ai proxy)

## Trace capture (cxtx)

Both harnesses use `cxtx` for trace capture to cxdb. cxtx acts as a local proxy, intercepting API calls between the harness and the LLM provider.

| Harness | cxtx subcommand | What it intercepts |
|---------|----------------|-------------------|
| Claude | `cxtx claude` | Anthropic Messages API calls |
| Pi | `cxtx pi` | Dual-protocol: both Anthropic and OpenAI API calls |

When `VF_CXDB_URL` is set, the controller wraps the harness invocation with cxtx. When empty, cxtx is skipped and the harness runs directly.

## Configuration files per harness

### Claude

| File | Written by | Purpose | Roles |
|------|-----------|---------|-------|
| `~/.claude/CLAUDE.md` | Entrypoint | Role methodology (executor/judge/architect) | All |
| `~/.claude.json` | Entrypoint | Onboarding flags, MCP servers, theme, autoUpdates | Architect only |
| `~/.claude/settings.json` | Entrypoint | `skipDangerousModePermissionPrompt` | Architect only |

### Pi

| File | Written by | Purpose |
|------|-----------|---------|
| `~/.pi/agent/settings.json` | Image build | Package list (`pi-mcp-adapter`) |
| `~/.pi/agent/models.json` | Entrypoint | Provider config, model, API base URL |
| `~/.pi/agent/mcp.json` | Entrypoint | MCP server endpoints (vtf, cxdb) |

Pi methodology is delivered via `--append-system-prompt` flag, not a config file.

## Environment variables

### Shared (both harnesses)

| Variable | Default | Purpose |
|----------|---------|---------|
| `VF_HARNESS` | `claude` | Harness selection |
| `VF_AGENT_ROLE` | `executor` | Agent role: executor, judge, architect |
| `VF_AGENT_TAGS` | `executor` | Comma-separated tags for task matching |
| `VF_VTF_API_URL` | (k8s DNS) | vtf API endpoint |
| `VF_VTF_TOKEN` | | vtf authentication token |
| `VF_CXDB_URL` | | cxdb endpoint for cxtx trace capture (empty = disabled) |
| `VF_CXDB_MCP_URL` | | cxdb MCP server URL (written to Pi mcp.json and Claude architect mcpServers) |
| `VF_VTF_MCP_URL` | | vtf MCP server URL (written to Pi mcp.json and Claude architect mcpServers) |
| `VF_MAX_TURNS` | `50` | Max LLM turns per task |
| `VF_TASK_TIMEOUT` | `600` | Seconds before task execution is killed |

### Pi-specific

| Variable | Default | Purpose |
|----------|---------|---------|
| `VF_PI_PROVIDER` | `anthropic` | LLM provider for Pi |
| `VF_PI_MODEL` | `claude-sonnet-4-20250514` | Model ID for Pi |
| `ANTHROPIC_API_KEY` | | API key (Pi reads this env var directly) |
| `ANTHROPIC_BASE_URL` | | API proxy URL (written to models.json for Pi) |

### Claude-specific

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_AUTH_TOKEN` | | z.ai API key (Claude reads this env var) |
| `ANTHROPIC_BASE_URL` | | z.ai proxy URL (Claude reads this env var) |

## Output parsing comparison

| Aspect | Claude | Pi |
|--------|--------|-----|
| Output format | Single JSON object | Streaming JSONL |
| Session ID | `output.session_id` | `session` event `.id` |
| Completion text | `output.result` | Last assistant message in `agent_end` |
| Cost | `output.total_cost_usd` | `usage.cost.total` (0 via z.ai proxy) |
| Turn count | `output.num_turns` | Count of `turn_end` events |
| Error detection | `output.is_error` | Exit code only (Pi has no `is_error` field) |
| Infrastructure failure | Exit code != 0 | Exit code != 0 |

## Adding a new harness

To add support for a third harness (e.g., Codex, Gemini CLI):

1. Create `images/<harness>/Dockerfile` building on `vafi-base`
2. Add cxtx if the harness is supported by cxtx (check `cxtx --help` for subcommands)
3. Add `_build_<harness>_command()` to `invoker.py`
4. Add `_parse_<harness>_output()` to `invoker.py`
5. Add entrypoint branch in `entrypoint.sh` for config file generation
6. Add config fields to `AgentConfig` if the harness needs provider/model flags
7. Build: `docker build --build-arg HARNESS_IMAGE=vafi/vafi-<harness>:latest -t vafi/vafi-agent-<harness>:latest`
8. Deploy with `VF_HARNESS=<harness>` env var

The controller, WorkSource protocol, gate execution, task lifecycle, and reporting are completely harness-agnostic. Only CLI invocation and output parsing change.
