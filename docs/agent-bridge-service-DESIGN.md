# Agent Bridge Service — Design

**Status:** Draft
**Date:** 2026-04-01
**Last Updated:** 2026-04-01 (gap analysis pass)
**Prerequisites:**
- agent-as-a-service-harness-REPORT.md (Pi RPC verified as persistent harness)
- agent-session-routing-RESEARCH.md (two session patterns: locked/ephemeral)
- vtf-user-management-DESIGN.md (identity models — not yet implemented, marked as assumptions)

## Purpose

The bridge service is the central proxy between external channels (Slack, mobile, web widget, webhooks) and agent processes. It handles:

1. Routing prompts to the correct agent session
2. Managing persistent Pi RPC processes for locked agents
3. Spawning ephemeral agent processes for unlocked agents
4. Translating channel-specific formats into a common protocol
5. Recording session invocations for cxdb traceability

## Blockers

These must be resolved before the bridge can be deployed. Each is a separate workstream.

| Blocker | Description | Workstream | Status |
|---------|-------------|------------|--------|
| B1: vtf user management | Token validation, ExternalIdentity, AgentLock, SessionRecord models | vtf-user-management-DESIGN.md (Phases 1-3) | In progress (another agent) |
| B2: vafi-pi agent image | Pi is NOT in the current vafi-agent image (verified: `pi` not found in architect-vafi-spike pod). Need a new or extended image with Pi installed. Auth pattern proven in vf-agents: mount `~/.pi/agent/auth.json` + `settings.json` from config-dir. | vafi-pi image design (separate doc) | Not started |
| B3: Pi MCP server connectivity | Not verified whether Pi `--mode rpc` can connect to HTTP MCP servers (vtf MCP, cxdb MCP). Pi uses an extension system, not env vars. Must spike to determine configuration mechanism. | Spike S1 | Not started |
| B4: Pi via kubectl exec relay | Not verified whether Pi's JSONL protocol survives k8s exec WebSocket framing. Required for locked agents running in pods. | Spike S2 | Not started |

## Assumptions

The following are NOT yet implemented. This design depends on them but can be built and tested with stubs until they exist.

| Assumption | Dependency | Status |
|------------|-----------|--------|
| A1: vtf has a token validation endpoint (`GET /v1/auth/validate/`) | vtf-user-management Phase 1 | Not implemented (B1) |
| A2: vtf has an ExternalIdentity model for Slack/mobile account linking | vtf-user-management Phase 2 | Not implemented (B1) |
| A3: vtf has an AgentLock model for exclusive session tracking | vtf-user-management Phase 3 | Not implemented (B1) |
| A4: vtf has a SessionRecord model for cxdb session indexing | vtf-user-management Phase 2 | Not implemented (B1) |
| A5: cxdb exposes an API for session trace creation/lookup | cxdb roadmap | Not verified |
| A6: Pi coding agent is available in agent pod images | vafi-pi image design | NOT available — Pi not in current vafi-agent image (B2) |
| A7: Pi `--mode rpc` supports all commands documented in rpc-mode.js | Spike results | Partially verified: `prompt`, `get_state` tested. Full command set not tested. |
| A8: Pi `--mode rpc` can connect to HTTP MCP servers | Spike S1 | NOT verified (B3) |
| A9: Pi JSONL protocol works via kubectl exec relay | Spike S2 | NOT verified (B4) |

## Spikes Required

| Spike | Question | Blocker? | Effort |
|-------|----------|----------|--------|
| S1: Pi MCP discovery | Can Pi in `--mode rpc` connect to vtf MCP (HTTP MCP server)? How is it configured — settings.json, `--extension` flag, or env var? | Yes (B3) | 1-2 hours |
| S2: Pi via kubectl exec | Can we relay JSONL stdin/stdout through k8s exec API to a Pi process in a pod? Does the k8s exec binary framing (channel prefix bytes) corrupt the JSONL stream? | Yes (B4) | 1-2 hours |
| S3: Pi crash recovery | Does Pi resume correctly from a session JSONL file after `kill -9`? Does it handle a truncated/corrupt last line? | No (production hardening) | 1 hour |

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

**Pi `--no-session` flag (verified from Pi 0.58.4 --help):**
- Exists: "Don't save session (ephemeral)"
- Suitable for unlocked agent spawn-per-request model

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

Locked agents run in agent pods. The bridge manages the pod lifecycle and communicates with Pi via kubectl exec stdin/stdout relay. **(Requires spike S2 to verify JSONL survives k8s exec framing.)**

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

### Requires Spike (before implementation)

| Gap | Issue | Spike |
|-----|-------|-------|
| Pi MCP connectivity | Pi uses extension system, not env vars. Unknown if/how Pi connects to HTTP MCP servers. | S1: Configure and test Pi → vtf MCP connection in `--mode rpc` |
| kubectl exec JSONL relay | K8s exec uses binary WebSocket frames with channel prefix bytes. Unknown if Pi's JSONL protocol survives this framing. | S2: Run Pi `--mode rpc` via kubectl exec, verify JSONL round-trip |

### Requires Spike (before production)

| Gap | Issue | Spike |
|-----|-------|-------|
| Pi crash recovery | If Pi dies mid-conversation, can it resume from JSONL session file? What about corrupt/truncated writes? | S3: Kill Pi with `kill -9`, restart with `--session-dir`, verify resume |

### External Blockers (separate workstreams)

| Blocker | What's needed | Workstream |
|---------|--------------|------------|
| vtf user management | Token validation, ExternalIdentity, AgentLock, SessionRecord models and endpoints | vtf-user-management-DESIGN.md Phases 1-3 (in progress) |
| vafi-pi agent image | Pi not in current vafi-agent image. Need image with Pi installed + auth config. Pattern exists in vf-agents Dockerfile.pi. | Separate design doc (not started) |

## What Can Be Built Now (Without vtf User Management)

| Component | Dependency | Can build now? |
|-----------|-----------|----------------|
| Bridge FastAPI skeleton with endpoints | None | Yes |
| Ephemeral process manager (local Pi spawn) | None | Yes |
| Ephemeral session spawn/terminate | None | Yes |
| Role configuration loader | None | Yes |
| Health endpoint with process state | None | Yes |
| Streaming response (NDJSON) | None | Yes |
| Concurrency limiter (semaphore) | None | Yes |
| Rate limiter (per-user) | None | Yes |
| Channel adapter interface (Protocol) | None | Yes |
| Auth middleware | Token validation (A1) | Stub with hardcoded token |
| Web ChatWidget | None (uses bridge API directly) | Yes |
| Session recording | SessionRecord (A4) | Stub with local log |
| Locked process manager (Pi in pods) | vafi-pi image (B2) + spike S2 | **No — blocked** |
| Lock manager with vtf persistence | AgentLock model (A3) | Stub in-memory only |
| Slack adapter identity resolution | ExternalIdentity (A2) | Stub identity only |
| Pi MCP tool access | Spike S1 | **No — blocked** |

The ephemeral path (assistant agent, local Pi) can be built and tested now with stubs. The locked path (architect in pods) is blocked on the vafi-pi image (B2) and spikes S1/S2. Both paths can proceed in parallel once blockers are resolved.

## Implementation Sequence

### Phase A: Ephemeral Path (no blockers)

1. **Spikes S1 + S2** — Verify Pi MCP connectivity and kubectl exec relay. Results determine Phase B feasibility.
2. **Bridge skeleton** — FastAPI app with role config, health endpoint, CORS, placeholder auth
3. **Ephemeral process manager** — Local PiSession class (from PoC), spawn/track/shutdown
4. **Prompt endpoint** — `/v1/prompt` and `/v1/prompt/stream` with ephemeral spawn, concurrency limiter, rate limiter
5. **Channel adapter interface** — Protocol class, registration mechanism
6. **Web ChatWidget** — React component in vtf web, calls bridge API directly

### Phase B: Locked Path (blocked on B2: vafi-pi image)

7. **vafi-pi image** — Create Pi-capable agent image with auth config (separate design)
8. **Pod process manager** — kubectl exec relay to Pi in agent pods
9. **Lock manager** — In-memory lock registry (stub), `/v1/lock` and `/v1/unlock` endpoints
10. **Locked session routing** — `/v1/prompt` routes to persistent Pi process when locked
11. **Timeout manager** — Background task for idle timeout and warnings

### Phase C: Integration (blocked on B1: vtf user management)

12. **Auth middleware** — Swap stub for real vtf token validation (A1)
13. **Lock persistence** — Swap in-memory lock for vtf AgentLock model (A3)
14. **Session recording** — Swap local log for vtf SessionRecord model (A4)
15. **Slack adapter** — Events webhook, real ExternalIdentity resolution (A2)
16. **vtf integration testing** — End-to-end with real auth, locks, sessions

### Dependency Graph

```
Spikes S1, S2 (no dependency)
    │
    ▼
Phase A: Ephemeral path (no dependency)
    │
    ├── B2: vafi-pi image (parallel)
    │       │
    │       ▼
    │   Phase B: Locked path
    │
    ├── B1: vtf user management (parallel, another agent)
    │       │
    │       ▼
    │   Phase C: Integration
    │
    ▼
Production deployment (all phases complete)
```
