# Agent Bridge Service — Design

**Status:** Ready for implementation (all blockers resolved 2026-04-02)
**Date:** 2026-04-01
**Last Updated:** 2026-04-02 (all blockers resolved)
**Prerequisites:**
- agent-as-a-service-harness-REPORT.md (Pi RPC verified as persistent harness)
- agent-session-routing-RESEARCH.md (two session patterns: locked/ephemeral)
- vtf-user-management-DESIGN.md (identity models — implemented, vtf commit 9300560)

## Purpose

The bridge service is the central proxy between external channels (Slack, mobile, web widget, webhooks) and agent processes. It handles:

1. Routing prompts to the correct agent session
2. Managing persistent Pi RPC processes for locked agents
3. Spawning ephemeral agent processes for unlocked agents
4. Translating channel-specific formats into a common protocol
5. Recording session invocations for cxdb traceability

## Blockers — ALL RESOLVED

| Blocker | Description | Resolution | Date |
|---------|-------------|------------|------|
| B1: vtf user management | Token validation, ExternalIdentity, AgentLock, SessionRecord, ProjectMembership, service accounts | vtf commit `9300560`: all 6 phases implemented (73 tests, 1289 total). `GET /v1/auth/validate/`, ExternalIdentity, AgentLock, ChannelProjectMapping, ProjectMembership, HasProjectMembership permission, create_service_account command. | 2026-04-02 |
| B2: vafi-pi agent image | Pi not in agent pods | `vafi-agent-pi` image built and deployed. Pi 0.59.0 + pi-mcp-adapter + cxtx. E2E verified: Pi executor claimed task, executed, passed gates, trace in cxdb. See [harness-images-ARCHITECTURE.md](harness-images-ARCHITECTURE.md). | 2026-04-02 |
| B3: Pi MCP server connectivity | Can Pi connect to HTTP MCP servers? | `pi-mcp-adapter` extension handles MCP via `~/.pi/agent/mcp.json`. Verified both stdio and HTTP/URL transports. Config: `{"mcpServers": {"vtf": {"url": "...", "lifecycle": "lazy"}}}`. | 2026-04-02 |
| B4: Pi kubectl exec JSONL relay | Does JSONL survive k8s exec framing? | All tests passed: basic integrity, rapid burst (5 commands), large payloads (up to 64KB), session consistency. No line splitting, merging, or corruption. | 2026-04-02 |

## Assumptions — Status

| Assumption | Dependency | Status |
|------------|-----------|--------|
| A1: vtf has a token validation endpoint (`GET /v1/auth/validate/`) | vtf-user-management Phase 1 | **Implemented** (vtf commit `9300560`) |
| A2: vtf has an ExternalIdentity model for Slack/mobile account linking | vtf-user-management Phase 2 | **Implemented** (vtf commit `9300560`) |
| A3: vtf has an AgentLock model for exclusive session tracking | vtf-user-management Phase 3 | **Implemented** (vtf commit `9300560`) |
| A4: vtf has a SessionRecord model for cxdb session indexing | vtf-user-management Phase 2 | **Implemented** (vtf commit `9300560`) |
| A5: cxdb exposes an API for session trace creation/lookup | cxdb roadmap | **Available** — cxdb HTTP API at `/v1/contexts`, cxdb-mcp service provides `cxdb_list_sessions` and `cxdb_session_summary` tools |
| A6: Pi coding agent is available in agent pod images | vafi-pi image | **Available** — `harbor.viloforge.com/vafi/vafi-agent-pi:33c11dc` |
| A7: Pi `--mode rpc` supports all commands documented in rpc-mode.js | Spike results | **Verified** — `prompt`, `get_state`, `get_available_models`, `set_model` tested |
| A8: Pi `--mode rpc` can connect to HTTP MCP servers | pi-mcp-adapter spike | **Verified** — `pi-mcp-adapter` extension with `mcp.json` config, HTTP URL transport works |
| A9: Pi JSONL protocol works via kubectl exec relay | S2 spike | **Verified** — all tests passed up to 64KB payloads |

## Spikes — Status

| Spike | Question | Result |
|-------|----------|--------|
| S1: Pi MCP discovery | Can Pi connect to HTTP MCP servers? How? | **RESOLVED**: `pi-mcp-adapter` extension, config via `~/.pi/agent/mcp.json`, supports `url` field for HTTP/StreamableHTTP transport. Install: `pi install npm:pi-mcp-adapter`. |
| S2: Pi via kubectl exec | Does JSONL survive k8s exec framing? | **RESOLVED**: All tests passed — basic, rapid burst, 64KB payloads, session consistency. Standard line-based readers work. |
| S3: Pi crash recovery | Does Pi resume from session file after kill? | **Not tested** (production hardening, not a blocker for initial deployment) |

## Verified Facts (from gap analysis)

**Pi cold start benchmark (measured 2026-04-01):**

| Phase | Time |
|-------|------|
| Process spawn | 1ms |
| Ready (get_state responds) | 945ms |
| First prompt response (LLM call) | 6,082ms |
| Total (spawn → first response) | 7,027ms |

Cold start is under 1 second. No warm pool needed for ephemeral agents.

**Pi LLM auth pattern (verified from vf-agents):**
- `Dockerfile.pi`: `npm install -g @mariozechner/pi-coding-agent@${version}`
- Auth files: `~/.pi/agent/auth.json` (credentials) + `settings.json` (provider/model config)
- Mounted from host config dir — pattern at `vf-agents/internal/adapter/pi.go:236-238`
- Current local config: github-copilot provider, claude-sonnet-4.6 model

**Pi `--no-session` flag (verified from Pi 0.59.0 --help):**
- Exists: "Don't save session (ephemeral)"
- Suitable for unlocked agent spawn-per-request model

**Pi MCP adapter (verified 2026-04-02):**
- Install: `pi install npm:pi-mcp-adapter` (baked into `vafi-pi` image)
- Config: `~/.pi/agent/mcp.json` with `mcpServers` object
- Supports `url` field for HTTP/StreamableHTTP transport (lazy/eager/keep-alive lifecycle)
- Proxy pattern: one `mcp()` tool (~200 tokens) instead of registering all MCP tools individually
- `directTools` option available for first-class tool registration

**Pi JSONL via kubectl exec (verified 2026-04-02):**
- Line integrity preserved for payloads up to 64KB
- No splitting, merging, or corruption through k8s exec WebSocket framing
- MCP adapter events (`extension_ui_request`) also survive intact
- Non-interactive exec (`kubectl exec` without `-it`) required — TTY mode would corrupt JSONL

**vtf user management (verified 2026-04-02, vtf commit 9300560):**
- `GET /v1/auth/validate/` — token validation, returns user profile + project list
- `ExternalIdentity` — links Slack/mobile accounts to vtf users
- `SessionRecord` — cxdb session indexing per user
- `AgentLock` — acquire/release/reconnect semantics for locked agents
- `ChannelProjectMapping` — resolves channel to project for routing
- `ProjectMembership` — access control on project-scoped endpoints
- `create_service_account` management command for bridge service auth
- `HasProjectMembership` permission class for enforcement

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Channels                                           │
│  ┌──────┐ ┌──────┐ ┌────────┐ ┌───────┐ ┌───────┐ │
│  │ Slack│ │Mobile│ │Web     │ │Webhook│ │vafi-  │ │
│  │ bot  │ │ app  │ │widget  │ │       │ │console│ │
│  └──┬───┘ └──┬───┘ └───┬────┘ └──┬────┘ └──┬────┘ │
│     │        │         │         │          │      │
│     └────────┴─────────┴─────────┴──────────┘      │
│                        │                            │
│              Channel Adapter Interface              │
│              (translates to BridgeRequest)           │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────┐
│  Bridge Service (FastAPI)                          │
│                                                    │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │ Auth        │  │ Router       │  │ Session   │ │
│  │ Middleware  │  │              │  │ Tracker   │ │
│  │             │  │ locked role? │  │           │ │
│  │ vtf token → │  │ ─yes→ lock  │  │ cxdb refs │ │
│  │ user identity│ │  mgr        │  │           │ │
│  │             │  │ ─no→ spawn  │  │           │ │
│  └─────────────┘  └──────────────┘  └───────────┘ │
│                                                    │
│  ┌────────────────────┐  ┌───────────────────────┐ │
│  │ Lock Manager       │  │ Process Manager       │ │
│  │                    │  │                       │ │
│  │ acquire/release    │  │ Persistent Pi RPC     │ │
│  │ check/timeout      │  │ processes (locked)    │ │
│  │ state in vtf DB    │  │                       │ │
│  │ (A3: AgentLock)    │  │ Ephemeral spawns      │ │
│  └────────────────────┘  │ (unlocked)            │ │
│                          └───────────────────────┘ │
└────────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
┌─────────────┐           ┌─────────────────┐
│ vtf API     │           │ Pi RPC processes │
│ (identity,  │           │ (stdin/stdout    │
│  locks,     │           │  JSONL protocol) │
│  sessions)  │           └─────────────────┘
└─────────────┘
```

## Bridge Service API

### Common Request/Response Models

```python
class BridgeRequest(BaseModel):
    """Common request format. Channel adapters translate into this."""
    message: str
    user_token: str                          # vtf API token (A1)
    project: str | None = None               # vtf project slug
    role: str = "assistant"                   # agent role
    channel: str = "web"                     # originating channel
    channel_context: dict = {}               # channel-specific metadata
    # e.g. {"slack_channel": "C123", "slack_thread_ts": "1234.5678"}

class BridgeResponse(BaseModel):
    """Common response format. Channel adapters translate from this."""
    result: str                              # agent's text response
    session_id: str                          # bridge session ID
    cxdb_context_id: int | None = None       # cxdb trace reference (A5)
    role: str
    project: str
    input_tokens: int = 0
    output_tokens: int = 0
    tool_uses: list[str] = []
    duration_ms: int = 0
    is_error: bool = False
    error_detail: str = ""
```

### Endpoints

#### Prompting

**POST `/v1/prompt`** — Send a prompt to an agent. Routes to locked or ephemeral session based on role.

Request: `BridgeRequest`
Response: `BridgeResponse`

Behavior:
1. Validate user_token against vtf (A1) → get user identity
2. Resolve project (explicit, channel mapping, or reject)
3. Determine if role is locked type
4. If locked: check lock → route to persistent Pi process → collect response
5. If unlocked: spawn ephemeral Pi process → send prompt → collect response → terminate
6. Record SessionRecord in vtf (A4)
7. Return BridgeResponse

Status codes:
- 200: Success
- 401: Invalid token
- 403: User not authorized for project
- 409: Lock held by another user (locked roles only)
- 503: Agent process unavailable
- 504: Agent response timeout

**POST `/v1/prompt/stream`** — Same as above but streams NDJSON events.

Request: `BridgeRequest`
Response: `StreamingResponse` (application/x-ndjson)

Event types streamed:
```json
{"type": "session_start", "session_id": "...", "role": "...", "project": "..."}
{"type": "agent_event", "data": {...}}   // raw Pi RPC events
{"type": "text_delta", "text": "..."}    // extracted text for simple clients
{"type": "tool_use", "tool": "bash", "status": "started|completed"}
{"type": "result", "result": "...", "input_tokens": 0, "output_tokens": 0}
{"type": "error", "message": "..."}
```

Simple clients (mobile, Slack) can filter for `text_delta` and `result` only. Rich clients (web widget) can render full `agent_event` stream.

#### Lock Management (Locked Roles Only)

**POST `/v1/lock`** — Acquire exclusive lock for a project + role.

```python
class LockRequest(BaseModel):
    user_token: str
    project: str
    role: str          # must be a locked role (e.g. "architect")

class LockResponse(BaseModel):
    session_id: str
    project: str
    role: str
    locked_at: str     # ISO timestamp
```

Behavior:
1. Validate user_token → get user identity
2. Check if role is a locked type (from config)
3. Check if lock exists for (project, role):
   - No lock → create lock (A3), spawn persistent Pi process, return session_id
   - Lock by same user → return existing session_id (reconnect)
   - Lock by different user → 409 with lock holder info
4. Pi process spawned with project context (repo clone, methodology, MCP tools)

Status codes:
- 200: Lock acquired (or reconnected)
- 401: Invalid token
- 403: User not authorized for project
- 409: Lock held by another user

**DELETE `/v1/lock`** — Release lock.

```python
class UnlockRequest(BaseModel):
    user_token: str
    project: str
    role: str
```

Behavior:
1. Validate user_token
2. Verify user holds this lock
3. Stop Pi process (graceful shutdown via `{"type": "shutdown"}`)
4. Delete lock record (A3)
5. Record final SessionRecord (A4)

Status codes:
- 200: Released
- 401: Invalid token
- 403: User does not hold this lock
- 404: No lock exists

**GET `/v1/locks`** — List active locks.

Query params: `project` (optional), `role` (optional)
Response: List of active locks with holder info, age, last activity.

```json
[
  {
    "project": "vtf",
    "role": "architect",
    "user": "jason",
    "session_id": "abc-123",
    "locked_at": "2026-04-01T10:00:00Z",
    "last_activity": "2026-04-01T11:30:00Z"
  }
]
```

No auth required for listing (visibility). Auth required for acquire/release.

#### Session History

**GET `/v1/sessions`** — List session records for a user.

Query params: `project` (optional), `role` (optional), `since` (optional, ISO date)
Auth: user_token header

Response: List of SessionRecord entries (A4) with cxdb references.

```json
[
  {
    "session_id": "abc-123",
    "project": "vtf",
    "role": "assistant",
    "channel": "slack",
    "started_at": "2026-04-01T10:00:00Z",
    "ended_at": "2026-04-01T10:02:30Z",
    "cxdb_context_id": 42,
    "summary": "Cancelled task 42, updated sprint status"
  }
]
```

#### Health

**GET `/v1/health`** — Service health.

```json
{
  "status": "ok",
  "active_locked_sessions": 2,
  "active_ephemeral_sessions": 0,
  "pi_processes": [
    {
      "session_id": "abc-123",
      "project": "vtf",
      "role": "architect",
      "user": "jason",
      "uptime_seconds": 5400,
      "prompt_count": 12,
      "message_count": 24,
      "is_alive": true
    }
  ]
}
```

## Process Manager

Manages Pi RPC processes — both persistent (locked) and ephemeral (unlocked).

**Key design decision (from gap analysis):** Locked agents run Pi inside agent pods (via kubectl exec), not as local subprocesses on the bridge. This reuses existing pod infrastructure (SSH keys, repo clone, workdir PVC, entrypoint setup). Ephemeral agents run Pi as local subprocesses on the bridge pod (no repo needed — operates through MCP tools only).

| Agent type | Where Pi runs | Why |
|-----------|--------------|-----|
| Locked (architect, web designer) | Inside agent pod via kubectl exec | Needs repo access, SSH keys, persistent workdir. Pod infrastructure handles this. |
| Ephemeral (assistant) | Local subprocess on bridge pod | No repo needed. Uses MCP tools for vtf/cxdb queries and mutations. Fast startup. |

### Persistent Processes (Locked Agents)

Locked agents run in agent pods. The bridge manages the pod lifecycle and communicates with Pi via kubectl exec stdin/stdout relay. (Spike S2 verified: JSONL survives k8s exec framing intact.)

**Lifecycle:**

```
Lock acquired
    │
    ▼
Bridge creates/reuses agent pod (via k8s API or vafi-console pod API)
    │  Pod entrypoint: clone repo, configure Pi auth, write /tmp/ready
    │  Pod image: vafi-pi (B2 — not yet built)
    │
    ▼
Bridge opens kubectl exec to pod: pi --mode rpc --session-dir /sessions/{project}/
    │  stdin/stdout relayed via k8s exec WebSocket (same pattern as vafi-console terminal)
    │
    ▼
Pi process running inside pod (JSONL via kubectl exec relay)
    │
    ├── prompt commands from bridge (relayed through kubectl exec)
    ├── get_state queries for health checks
    ├── auto-compaction (Pi built-in, enabled by default)
    ├── repo access via Pi's bash/read/edit tools (workdir in pod)
    │
    ▼  (on lock release or timeout)
shutdown command → Pi exits → kubectl exec disconnects
    │
    ▼
Session file persisted at /sessions/{project}/*.jsonl (on pod's PVC)
Pod stays alive (sleep infinity) — available for reconnection
```

**Process table (in-memory):**

```python
@dataclass
class ManagedProcess:
    session_id: str
    project: str
    role: str
    user: str
    process: asyncio.subprocess.Process
    lock: asyncio.Lock           # serializes prompt access
    response_queue: asyncio.Queue
    reader_task: asyncio.Task
    started_at: float
    last_activity: float
    prompt_count: int

# Keyed by session_id
processes: dict[str, ManagedProcess] = {}
```

**Health monitoring:**
- Background task checks `is_alive` for all processes every 60 seconds
- If process died unexpectedly → log error, clean up lock record, notify user
- Queries `get_state` to monitor message count and compaction status

**Timeout:**
- Configurable idle timeout (default: 4 hours)
- Background task checks `last_activity` for all locked processes
- `last_activity` > timeout/2 → send warning to user via originating channel
- `last_activity` > timeout → graceful shutdown, release lock

### Ephemeral Processes (Unlocked Agents)

Simpler model — spawn per request, terminate after response.

```
Prompt arrives
    │
    ▼
spawn_ephemeral(project, role)
    │  pi --mode rpc --no-session
    │  Env: same as persistent
    │
    ▼
Send prompt command → collect until agent_end → return result
    │
    ▼
shutdown command → process exits
```

**Concurrency:** Multiple ephemeral processes can run simultaneously (no lock). Each prompt gets its own process with its own asyncio.Lock (effectively no contention).

**ASSUMPTION:** `--no-session` prevents Pi from writing session files for ephemeral interactions. Verified: Pi 0.58.4 `--help` shows `--no-session` flag exists with description "Don't save session (ephemeral)".

### Process Spawning Configuration

Both persistent and ephemeral processes need environment configuration:

```python
def build_pi_env(project: str, role: str) -> dict:
    """Build environment for Pi RPC process."""
    return {
        # Pi configuration
        "PI_MODEL": "claude-sonnet-4.6",           # or from role config
        # vtf MCP access
        "VF_VTF_MCP_URL": settings.vtf_mcp_url,
        "VF_VTF_TOKEN": settings.vtf_api_token,
        "VTF_PROJECT_SLUG": project,
        # cxdb MCP access (if available)
        "VF_CXDB_MCP_URL": settings.cxdb_mcp_url,
        # Observability
        "PI_OTEL_ENDPOINT": settings.otel_endpoint,
        "PI_OTEL_PROTOCOL": "http/protobuf",
    }

def build_pi_command(role: str, persistent: bool, session_dir: str = "") -> list[str]:
    """Build Pi RPC launch command."""
    cmd = ["pi", "--mode", "rpc"]
    if not persistent:
        cmd.append("--no-session")
    if session_dir:
        cmd.extend(["--session-dir", session_dir])
    # Role-specific methodology
    methodology = ROLE_METHODOLOGIES.get(role)
    if methodology:
        cmd.extend(["--append-system-prompt", methodology])
    return cmd
```

**ASSUMPTION:** Pi's `--append-system-prompt` can load a methodology file. Verified: Pi 0.58.4 `--help` shows `--append-system-prompt <text>  Append text or file contents to the system prompt`. The flag accepts file contents.

### Process Recovery on Bridge Restart

If the bridge service restarts:
1. All in-memory process references are lost
2. Lock records in vtf survive (they're in the database, A3)
3. On startup, bridge queries vtf for active locks
4. For each active lock:
   - Pi session file exists at `/sessions/{project}/{user}/` → spawn Pi with `--session-dir` to resume
   - Pi session file missing → mark lock as stale, notify user, release
5. Ephemeral processes: nothing to recover (they were per-request)

**ASSUMPTION:** Pi's `--session-dir` combined with `--mode rpc` will auto-continue the most recent session in that directory. NOT verified — needs testing. Fallback: spawn fresh Pi process, load cxdb summary as context.

## Channel Adapter Interface

Channel adapters translate between channel-specific protocols and the bridge's common `BridgeRequest`/`BridgeResponse` format.

### Interface Contract

```python
class ChannelAdapter(Protocol):
    """Interface that all channel adapters implement."""

    async def start(self) -> None:
        """Start listening for channel events (e.g., Slack Events API subscription)."""
        ...

    async def stop(self) -> None:
        """Stop listening, clean up connections."""
        ...

    async def send_response(self, channel_context: dict, response: BridgeResponse) -> None:
        """Send a response back to the originating channel.

        channel_context contains channel-specific routing info
        (e.g., Slack channel ID + thread timestamp).
        """
        ...

    async def send_notification(self, channel_context: dict, message: str) -> None:
        """Send a notification (e.g., lock timeout warning) to the channel."""
        ...
```

The adapter does NOT call the bridge API directly. Instead, the bridge registers adapters and calls them:

```python
# Bridge startup
bridge.register_adapter("slack", SlackAdapter(config))
bridge.register_adapter("mobile", MobileAdapter(config))

# When a Slack message arrives:
# 1. SlackAdapter receives Slack event
# 2. SlackAdapter translates to BridgeRequest (resolves identity via A2)
# 3. SlackAdapter calls bridge.handle_prompt(request)
# 4. Bridge processes, returns BridgeResponse
# 5. Bridge calls adapter.send_response(channel_context, response)
```

### Identity Resolution Per Adapter

Each adapter resolves identity differently. The bridge doesn't care how — it receives a `user_token` in the BridgeRequest.

| Adapter | Identity resolution | Token source |
|---------|-------------------|-------------|
| Web widget | vtf session cookie → auth code → exchange | Auth code flow (existing) |
| Mobile | vtf API token stored in app | App login flow |
| Slack | Slack user ID → ExternalIdentity lookup (A2) → vtf token | Account linking |
| WhatsApp | Phone number → ExternalIdentity lookup (A2) → vtf token | Account linking |
| Webhook | Service token in header | Pre-configured |

**ASSUMPTION:** For Slack and WhatsApp, the adapter looks up the vtf user via ExternalIdentity, then uses a bridge-internal service token to act on behalf of that user. The bridge validates the user's project access via vtf but doesn't need the user's personal token. This avoids storing user tokens in the ExternalIdentity table.

Alternative: Store a vtf token per external identity. Simpler for the bridge but requires token management (expiry, refresh).

### Slack Adapter (First Concrete Adapter)

**Inbound (Slack → Bridge):**

1. Slack Events API sends HTTP POST to bridge's `/slack/events` webhook
2. Adapter extracts: `slack_user_id`, `channel_id`, `text`, `thread_ts`
3. Adapter resolves identity: `ExternalIdentity.lookup(provider="slack", external_id=slack_user_id)` (A2)
   - Not linked → respond in Slack: "Run `/vtf link` to connect your account"
4. Adapter resolves project: `ChannelProjectMapping.lookup(provider="slack", channel_id=channel_id)`
   - No mapping → check if text mentions a project explicitly
   - Still no project → respond: "Which project? Use `@architect project-name` or configure this channel."
5. Adapter builds `BridgeRequest(message=text, user_token=..., project=..., role=..., channel="slack", channel_context={"slack_channel": channel_id, "thread_ts": thread_ts})`
6. Calls `bridge.handle_prompt(request)`

**Outbound (Bridge → Slack):**

1. Bridge calls `adapter.send_response(channel_context, response)`
2. Adapter formats response for Slack (markdown → Slack mrkdwn, code blocks, etc.)
3. Posts to Slack channel, in the thread if `thread_ts` provided
4. For streaming: posts initial message, then edits with updates (Slack `chat.update`)

**Slash commands:**

| Command | Action |
|---------|--------|
| `/vtf link` | Initiates account linking flow |
| `/vtf lock <project> <role>` | Acquires agent lock |
| `/vtf unlock <project> <role>` | Releases agent lock |
| `/vtf status` | Shows active locks and recent sessions |

### Web Widget Adapter

The vtf web UI already has a ConsoleWidget (iframe). The bridge adds a second mode: chat widget instead of terminal.

**Approach:** New React component `ChatWidget` alongside existing `ConsoleWidget`. Same floating/docked/minimized behavior. Instead of an iframe to vafi-console, it renders a chat interface that communicates with the bridge via `/v1/prompt/stream`.

```
vtf Web UI
├── ConsoleWidget (existing) → vafi-console iframe → terminal
└── ChatWidget (new) → bridge /v1/prompt/stream → agent response
```

The ChatWidget:
- Authenticates using the existing vtf session (auth code pattern or direct API token)
- Sends prompts as `POST /v1/prompt/stream` with `user_token`
- Renders streamed `text_delta` events as chat bubbles
- Shows tool use indicators ("Agent is running bash...")
- For locked roles: shows lock status, acquire/release controls

**ASSUMPTION:** The ChatWidget can be built as a standard React component using fetch + ReadableStream for NDJSON parsing. No WebSocket needed — HTTP streaming (server-sent events pattern) is sufficient for the chat use case.

### Mobile Adapter

Not a server-side adapter — the mobile app is a direct HTTP client to the bridge.

**The mobile app:**
1. Authenticates with vtf (login flow → receives API token)
2. Stores token securely on device
3. Calls bridge API directly: `POST /v1/prompt` with token
4. For voice: speech-to-text on device → text prompt → bridge
5. Bridge response → text-to-speech on device (optional)

No server-side adapter component needed. The bridge API is the adapter.

### vafi-console as Adapter (Migration Path)

vafi-console currently owns the terminal experience. In the bridge architecture, it becomes one of several adapters. Two migration options:

**Option A: Coexistence**
- vafi-console continues to serve terminal sessions (xterm.js, kubectl exec)
- Bridge serves chat/prompt sessions (HTTP API)
- Both authenticate via vtf
- Both can interact with the same project (different interfaces, different sessions)
- vtf web UI offers both: "Open Terminal" (console) and "Chat with Architect" (bridge)

**Option B: Bridge absorbs console**
- Bridge manages pod lifecycle (currently vafi-console's job)
- Bridge exposes WebSocket terminal endpoint (proxies kubectl exec)
- vafi-console is deprecated
- One service handles all agent interactions

**Recommendation: Option A for now.** vafi-console works, is deployed, and the terminal experience is valuable for deep interactive work. The bridge handles the new chat/prompt use cases. They coexist, sharing vtf identity and pods.

Long-term, Option B may make sense if maintaining two services becomes a burden. But that's a future decision.

## Role Configuration

Extends the existing `roles.yaml` pattern from vafi-console with bridge-specific fields:

```yaml
# Bridge role configuration
roles:
  architect:
    session_type: locked           # locked | ephemeral
    harness: pi-rpc                # pi-rpc | claude-cli
    idle_timeout_hours: 4
    methodology: /opt/vf-agent/methodologies/architect.md
    mcp_tools:
      - vtf
      - cxdb
      - grafana                    # optional, for infra queries
    model: claude-sonnet-4.6
    thinking_level: medium
    description: "Interactive planning and design sessions"

  web_designer:
    session_type: locked
    harness: pi-rpc
    idle_timeout_hours: 4
    methodology: /opt/vf-agent/methodologies/web-designer.md
    mcp_tools:
      - vtf
    model: claude-sonnet-4.6
    description: "Web design and UX planning"

  assistant:
    session_type: ephemeral
    harness: pi-rpc
    methodology: /opt/vf-agent/methodologies/assistant.md
    mcp_tools:
      - vtf
      - cxdb
      - grafana
    model: claude-sonnet-4.6
    thinking_level: low            # faster for simple operations
    description: "Task management, status queries, quick operations"

  executor:
    session_type: ephemeral        # managed by vafi controller, not bridge
    harness: claude-cli            # uses claude -p for richer tool set
    description: "Autonomous task execution"

  judge:
    session_type: ephemeral        # managed by vafi controller, not bridge
    harness: claude-cli
    description: "Code review and test verification"
```

**Note:** Executor and judge are listed for completeness but are managed by the vafi controller, not the bridge. The bridge handles human-facing agents (architect, assistant, web_designer). The controller handles autonomous agents (executor, judge).

## Deployment

### Where the Bridge Runs

The bridge is a standalone service in the `vafi-dev` / `vafi-prod` namespace, alongside vafi-console.

```
vafi-dev namespace:
├── vafi-console (existing) — terminal access
├── vafi-bridge (new) — chat/prompt access
├── vafi-executor-* — executor pods (managed by controller)
├── vafi-judge-* — judge pods (managed by controller)
└── vafi-cxdb — trace storage
```

The bridge does NOT run inside agent pods. It's a separate service that spawns Pi processes as subprocesses (for locked agents) or uses the bridge PoC pattern (spawn + terminate).

**ASSUMPTION:** Pi processes spawned by the bridge run on the same node as the bridge pod. For locked agents, this means the bridge pod needs sufficient memory for multiple Pi processes (~500MB each). On Fuji (16GB), this limits concurrent locked sessions to ~5-10. Acceptable for current scale.

**Alternative:** Bridge spawns Pi in separate pods (like vafi-console spawns Claude pods). More scalable but more complex. Deferred to when scale requires it.

### Configuration

```yaml
# Bridge service settings (env vars)
BRIDGE_PORT: 8080
BRIDGE_LOG_LEVEL: INFO

# vtf integration
VTF_API_URL: http://vtf-api.vtf-dev.svc.cluster.local:8000
VTF_API_TOKEN: <service token>
VTF_MCP_URL: http://vtf-mcp.vtf-dev.svc.cluster.local:8002/mcp

# cxdb integration
CXDB_MCP_URL: http://vafi-cxdb.vafi-dev.svc.cluster.local:9010

# Session storage
SESSIONS_DIR: /sessions               # PVC mount for persistent sessions
ROLES_CONFIG: /app/config/roles.yaml

# Timeouts
LOCKED_IDLE_TIMEOUT_HOURS: 4
EPHEMERAL_TIMEOUT_SECONDS: 120

# Slack adapter (optional)
SLACK_BOT_TOKEN: xoxb-...
SLACK_SIGNING_SECRET: ...
```

## Gap Analysis and Resolutions

Identified during design review (2026-04-01). Each gap classified as design fix, blocker, or spike.

### Resolved by Design

| Gap | Issue | Resolution |
|-----|-------|-----------|
| Process model for locked agents | Design said Pi runs locally on bridge pod, but architect needs repo access, SSH keys, workdir | **Revised:** Locked agents run Pi inside agent pods via kubectl exec. Bridge manages pod lifecycle. Ephemeral agents stay local. |
| BridgeRequest auth model | `user_token` in request body conflated external auth (web/mobile tokens) with adapter-resolved identity (Slack) | **Revised:** External API uses `Authorization: Bearer` header. Adapters resolve to `user_id` internally. Both converge to `ResolvedRequest(user_id, username, ...)` inside the bridge. |
| Concurrency limits | No back-pressure for ephemeral requests — burst could OOM bridge | `MAX_CONCURRENT_EPHEMERAL` setting with `asyncio.Semaphore`. Default 5. Returns 503 when full. Health endpoint exposes available slots. |
| Rate limiting | No rate limiting mentioned | Per-user sliding window (10 prompts/min). Returns 429 with `Retry-After`. Per-project budget tracking deferred to v2. |
| Timeout warning delivery | Warning sent to last-used channel — user may have moved | v1: warn on last-used channel. v2: warn on all linked channels via ExternalIdentity. Acceptable for v1 — timeout is visible when user tries to use expired lock. |
| CORS for web widget | ChatWidget calls bridge from browser — needs CORS | CORS middleware allowing vtf origins. Token moved to `Authorization` header for consistency. |
| Pi LLM auth | How does bridge-spawned Pi authenticate to LLM provider? | Mount `~/.pi/agent/auth.json` + `settings.json` from k8s secret. Pattern proven in vf-agents. For locked agents in pods: pod entrypoint handles it (B2). |

### Resolved by Benchmark

| Gap | Issue | Result |
|-----|-------|--------|
| Ephemeral startup cost | Is Pi cold start too slow for per-request spawn? | **945ms to ready.** Under 1 second. No warm pool needed. |

### Resolved by Spike (2026-04-02)

| Gap | Issue | Result |
|-----|-------|--------|
| Pi MCP connectivity | Pi uses extension system, not env vars. | `pi-mcp-adapter` extension handles MCP. Config via `~/.pi/agent/mcp.json`. HTTP URL transport verified. |
| kubectl exec JSONL relay | K8s exec uses binary WebSocket frames with channel prefix bytes. | JSONL survives intact. Tested: basic, rapid burst, 64KB payloads, session consistency. |

### Requires Spike (before production)

| Gap | Issue | Spike |
|-----|-------|-------|
| Pi crash recovery | If Pi dies mid-conversation, can it resume from JSONL session file? What about corrupt/truncated writes? | S3: Kill Pi with `kill -9`, restart with `--session-dir`, verify resume |

### External Blockers — ALL RESOLVED

| Blocker | What's needed | Resolution |
|---------|--------------|------------|
| vtf user management | Token validation, ExternalIdentity, AgentLock, SessionRecord | **Implemented** (vtf commit `9300560`, 6 phases, 73 tests) |
| vafi-pi agent image | Pi in agent pods | **Implemented** (`vafi-agent-pi:33c11dc`, E2E verified) |

## What Can Be Built Now

All blockers are resolved. Every component can be built with real dependencies (no stubs needed).

| Component | Dependency | Status |
|-----------|-----------|--------|
| Bridge FastAPI skeleton with endpoints | None | Ready |
| Ephemeral process manager (local Pi spawn) | None | Ready |
| Locked process manager (Pi in pods) | vafi-pi image, kubectl exec relay | **Unblocked** (both verified) |
| Lock manager with vtf persistence | AgentLock model | **Unblocked** (vtf commit `9300560`) |
| Auth middleware | Token validation endpoint | **Unblocked** (vtf `GET /v1/auth/validate/`) |
| Session recording | SessionRecord model | **Unblocked** (vtf commit `9300560`) |
| Slack adapter identity resolution | ExternalIdentity model | **Unblocked** (vtf commit `9300560`) |
| Pi MCP tool access | pi-mcp-adapter | **Unblocked** (spike verified) |
| Web ChatWidget | None (uses bridge API) | Ready |
| Role configuration, health, streaming, rate limiting | None | Ready |

## Implementation Sequence

### Phase A: Core Service + Ephemeral Path

All dependencies resolved. Can build with real vtf auth from the start.

1. **Bridge skeleton** — FastAPI app with role config loader, health endpoint, CORS
2. **Auth middleware** — vtf token validation via `GET /v1/auth/validate/` (real, not stub)
3. **Ephemeral process manager** — Local PiSession class, spawn/track/shutdown
4. **Prompt endpoint** — `/v1/prompt` and `/v1/prompt/stream` with ephemeral spawn, concurrency limiter, rate limiter
5. **Session recording** — vtf SessionRecord model (real, not stub)
6. **Channel adapter interface** — Protocol class, registration mechanism

### Phase B: Locked Path

7. **Pod process manager** — kubectl exec relay to Pi in `vafi-agent-pi` pods
8. **Lock manager** — vtf AgentLock model for persistence, `/v1/lock` and `/v1/unlock` endpoints
9. **Locked session routing** — `/v1/prompt` routes to persistent Pi process when locked
10. **Timeout manager** — Background task for idle timeout and warnings

### Phase C: Channels + UI

11. **Web ChatWidget** — React component in vtf web, calls bridge API directly
12. **Slack adapter** — Events webhook, ExternalIdentity resolution, slash commands
13. **End-to-end testing** — Full flow: Slack message → bridge → Pi → vtf → response

### Dependency Graph

```
Phase A: Core + ephemeral (no blockers)
    │
    ├── Phase B: Locked path (can start after step 4)
    │
    └── Phase C: Channels + UI (can start after step 6)
            │
            ▼
    Production deployment (all phases complete)
```

All three phases can overlap. Phase B can start once the prompt endpoint works (step 4). Phase C can start once the adapter interface exists (step 6).
