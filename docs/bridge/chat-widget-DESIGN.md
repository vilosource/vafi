# ChatWidget — Design

---
status: active
last_verified: 2026-04-17
---

**Date:** 2026-04-13
**Scope:** Phase C of the agent bridge service — web chat interface in vtf

> **Phases 1–7 complete.** Phases 8–9 (cxdb session continuity + display history) remain.
**Prerequisites:**
- [agent-bridge-service-DESIGN.md](agent-bridge-service-DESIGN.md) (bridge API, locked/ephemeral sessions)
- Bridge Phase A+B implemented and deployed

## Problem

To interact with a vafi architect agent today, you open a terminal via vafi-console. This works for deep interactive sessions but is heavy for quick conversations. There's no way to chat with an agent from the vtf web UI without opening a full terminal.

## Solution

A ChatGPT-style chat widget embedded in the vtf web UI. Opens alongside the existing ConsoleWidget. Uses the bridge API's locked sessions to maintain a persistent conversation with a Pi architect agent that has full repo access, MCP tools, and conversation context across turns.

## User Flow

```
1. User is on a project page in vtf
2. Clicks "Chat with Architect" button
3. ChatWidget opens (floating, docked, or minimized — same modes as ConsoleWidget)
4. Widget checks GET /v1/locks — do I already have a lock?
   - Yes → reconnect to existing session
   - No → acquire lock (POST /v1/lock, project + role=architect)
5. User types a message, presses Enter
6. POST /v1/prompt/stream with message + token
7. NDJSON events stream back:
   - text_delta → rendered as assistant message, chunk by chunk
   - tool_use → "Agent is running bash..." indicator
   - result → message complete, input enabled
8. User types next message (same locked session, full context preserved)
9. On widget close: prompt to release lock or keep session alive
10. On tab close: beforeunload sends DELETE /v1/lock (best effort)
11. If release fails: idle timeout (4h) cleans up automatically
```

## Architecture

```
vtf Web UI (React)
├── ConsoleWidget (existing) → iframe → vafi-console → terminal
└── ChatWidget (new) → fetch → bridge API → Pi RPC in pod
        │
        ├── ChatWidgetContext (state: layout, messages, lock, status)
        ├── ChatWindow (message list + input)
        │     ├── MessageList (scrollable, auto-scroll)
        │     │     ├── UserMessage (right-aligned, user text)
        │     │     └── AssistantMessage (left-aligned, streamed markdown)
        │     │           ├── ToolUseIndicator ("Running bash...")
        │     │           └── ThinkingIndicator (shimmer animation)
        │     └── ChatInput (auto-resize textarea, Enter to send)
        └── ChatTitleBar (project name, lock status, layout controls)
```

## Bridge API Usage

### Lock Lifecycle

```typescript
// On widget open — check for existing lock
const locks = await apiGet('/v1/locks?project=vtf&role=architect');
const myLock = locks.find(l => l.user === currentUser);

if (myLock) {
  // Reconnect — bridge returns existing session
  setSessionId(myLock.session_id);
} else {
  // Acquire new lock
  const lock = await apiPost('/v1/lock', {
    project: projectSlug,
    role: 'architect',
  });
  setSessionId(lock.session_id);
}

// On widget close — user chooses
if (userWantsToRelease) {
  await apiDelete('/v1/lock', { project: projectSlug, role: 'architect' });
}
// else: lock stays, user can reconnect later
```

### Streaming Prompts

```typescript
async function sendMessage(message: string) {
  const response = await fetch(`${BRIDGE_URL}/v1/prompt/stream`, {
    method: 'POST',
    headers: {
      'Authorization': `Token ${localStorage.getItem('vtf_token')}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      project: projectSlug,
      role: 'architect',
    }),
  });

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop()!; // keep incomplete line in buffer

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);

      switch (event.type) {
        case 'session_start':
          // session confirmed
          break;
        case 'text_delta':
          appendToCurrentMessage(event.text);
          break;
        case 'tool_use':
          showToolIndicator(event.tool, event.status);
          break;
        case 'agent_event':
          // raw Pi events — ignore for v1, useful for debugging
          break;
        case 'result':
          finalizeMessage(event);
          break;
        case 'error':
          showError(event.message);
          break;
      }
    }
  }
}
```

### Auth

The ChatWidget uses the **same auth pattern as the vtf web app** — not the ConsoleWidget's auth code flow.

```
localStorage.getItem('vtf_token') → Authorization: Token <token> → bridge API
```

The bridge validates tokens against vtf's `GET /v1/auth/validate/` endpoint. No new auth mechanism needed.

## Component Design

### ChatWidgetContext

Mirrors ConsoleWidgetContext pattern. Manages:

```typescript
interface ChatWidgetState {
  isOpen: boolean;
  layout: 'floating' | 'docked' | 'minimized';
  position: { x: number; y: number };
  size: { width: number; height: number };
  dockWidth: number;
  // Chat-specific
  sessionId: string | null;
  lockStatus: 'disconnected' | 'acquiring' | 'connected' | 'error';
  messages: ChatMessage[];
  isStreaming: boolean;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  toolUses?: { tool: string; status: 'started' | 'completed' }[];
  tokenUsage?: { input: number; output: number };
}
```

**Persistence:**
- Layout/position/size → `localStorage` key `vtf_chat_widget` (same as ConsoleWidget pattern)
- Messages → `localStorage` key `vtf_chat_messages_{project}_{sessionId}` — survives page refresh
- On lock release → clear stored messages for that session

### ChatWindow

The main chat area. Two sub-components:

**MessageList:**
- Scrollable container with `overflow-y: auto`
- Auto-scroll to bottom on new messages using `scrollIntoView({ behavior: 'smooth' })`
- Smart scroll: don't auto-scroll if user has scrolled up (track with IntersectionObserver on a sentinel div at the bottom)
- Each message renders markdown via `react-markdown` + `react-syntax-highlighter` for code blocks
- Memoize message components to prevent re-parsing markdown on every stream chunk

**ChatInput:**
- Auto-resizing textarea via `react-textarea-autosize`
- Enter to send, Shift+Enter for newline
- Disabled while streaming (re-enabled on `result` event)
- Character count or token estimate (optional, v2)

### AssistantMessage

Renders streamed content progressively:

```
┌─────────────────────────────────────────┐
│ 🤖 Architect                           │
│                                         │
│ I'll look at the task board for this    │
│ project.                                │
│                                         │
│ ┌─ Running bash ──────────────────────┐ │
│ │ kb work show vtf                    │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ There are 3 tasks in progress:          │
│ - TASK-42: Fix login redirect           │
│ - TASK-43: Add rate limiting            │
│ - TASK-44: Update docs                  │
│                                         │
│                        input: 54 out: 89│
└─────────────────────────────────────────┘
```

**Tool use indicators:**
- `tool_use` event with `status: 'started'` → show "Running {tool}..." with shimmer animation
- `tool_use` event with `status: 'completed'` → collapse or show result summary
- Multiple concurrent tool uses → stacked indicators

### ChatTitleBar

```
┌─────────────────────────────────────────────────┐
│ 💬 vtf — Architect          ● Connected   ▬ □ ✕ │
└─────────────────────────────────────────────────┘
  project   role            lock status    layout controls
```

- Lock status indicator: green dot = connected, yellow = acquiring, red = error, grey = disconnected
- Layout controls: minimize (▬), toggle float/dock (□), close (✕)
- Close button prompts: "Release session?" with options: "Release" (deletes lock) or "Keep alive" (minimizes)

## Widget Lifecycle

### Opening

```
isOpen = false → user clicks "Chat with Architect"
  → isOpen = true, lockStatus = 'acquiring'
  → GET /v1/locks (check existing)
  → if existing lock for user: reconnect, lockStatus = 'connected'
  → if no lock: POST /v1/lock, lockStatus = 'connected'
  → if lock held by other: show "Locked by {user} since {time}", lockStatus = 'error'
  → load messages from localStorage (if session matches)
```

### Closing

```
user clicks ✕
  → if lockStatus === 'connected':
      → prompt: "Release architect session?"
        → "Release": DELETE /v1/lock, clear messages, isOpen = false
        → "Keep alive": layout = 'minimized' (lock stays, user can reconnect)
        → "Cancel": do nothing
  → else: isOpen = false
```

### Tab Close

```
window.addEventListener('beforeunload', () => {
  if (lockStatus === 'connected') {
    // Best-effort release — navigator.sendBeacon doesn't support DELETE,
    // so use fetch with keepalive flag
    fetch(`${BRIDGE_URL}/v1/lock`, {
      method: 'DELETE',
      headers: { 'Authorization': `Token ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: projectSlug, role: 'architect' }),
      keepalive: true,
    });
  }
});
```

If this fails (network issue, browser kills it), the idle timeout (4h) cleans up.

### Reconnection

User had a lock, closed the widget (kept alive), opens it again:
1. `GET /v1/locks` finds their existing lock
2. Bridge returns existing session_id
3. Messages loaded from localStorage
4. Next prompt goes to the same Pi process with full context

User had a lock, bridge restarted:
1. Bridge recovery reconnected to the pod on startup
2. Same flow as above — lock exists in vtf, session restored

## New Dependencies

```json
{
  "react-markdown": "^9.0.0",
  "react-syntax-highlighter": "^15.5.0",
  "react-textarea-autosize": "^8.5.0"
}
```

No chat framework needed. The component is simple enough to build with these three libraries + Tailwind.

## File Structure

```
vtaskforge/web/src/
├── components/
│   ├── ConsoleWidget.tsx          (existing, unchanged)
│   ├── ChatWidget.tsx             (new — widget shell, 3 layout modes)
│   ├── ChatWindow.tsx             (new — message list + input)
│   ├── ChatMessage.tsx            (new — single message rendering)
│   ├── ChatInput.tsx              (new — auto-resize textarea)
│   └── ChatTitleBar.tsx           (new — title, status, controls)
├── contexts/
│   ├── ConsoleWidgetContext.tsx    (existing, unchanged)
│   └── ChatWidgetContext.tsx       (new — state, actions, localStorage)
├── hooks/
│   └── useBridgeStream.ts         (new — NDJSON fetch + parse)
└── api/
    ├── client.ts                  (existing, unchanged)
    └── bridge.ts                  (new — lock/unlock/prompt API calls)
```

## Integration Points

### Where the button lives

Add "Chat with Architect" alongside existing "Open Terminal" in project pages:

```typescript
// ProjectDashboard.tsx or TaskPage.tsx
const { open: openChat } = useChatWidget();
const { open: openConsole } = useConsoleWidget();

<button onClick={() => openConsole({ role: 'architect', project: slug })}>
  Open Terminal
</button>
<button onClick={() => openChat({ project: slug })}>
  Chat with Architect
</button>
```

### App.tsx mounting

```typescript
// App.tsx — add ChatWidgetProvider alongside ConsoleWidgetProvider
<ConsoleWidgetProvider>
  <ChatWidgetProvider>
    <AppLayout>
      <Routes>...</Routes>
    </AppLayout>
    <ConsoleWidget />
    <ChatWidget />
  </ChatWidgetProvider>
</ConsoleWidgetProvider>
```

### Docked mode — layout adjustment

Same pattern as ConsoleWidget. When ChatWidget is docked, main content gets `marginRight`:

```typescript
// AppLayout.tsx
const { isDocked: consoleDocked, dockWidth: consoleDockWidth } = useConsoleWidget();
const { isDocked: chatDocked, dockWidth: chatDockWidth } = useChatWidget();
const totalMargin = (consoleDocked ? consoleDockWidth : 0) + (chatDocked ? chatDockWidth : 0);

<main style={{ marginRight: totalMargin }}>
```

## Session Continuity

### Where conversation data lives

| Location | What's stored | Implemented? | Survives process death? |
|----------|-------------|-------------|----------------------|
| **Pi in-process memory** | Full conversation (all turns, tool results, thinking) | Yes — this is how Pi works | No |
| **cxdb** | Full conversation as a DAG of turns: `user_input` (with text), `assistant_turn` (with tool_calls and text), `tool_result` (with content and call_id) | Yes — cxdb is deployed, `src/cxdb/` package exists, cxdb MCP server running in vafi-dev | Yes |
| **vtf SessionRecords** | Metadata: who, when, project, role, cxdb_context_id | Yes — bridge writes via `session_recorder.py` | Yes |
| **Browser localStorage** | Display messages (what user sees in the widget) | To be built | Yes (on that browser only) |

cxdb is the source of truth for conversation history. It is designed for this purpose — from the cxdb integration design: *"cxdb stores the full conversation history of every agent session — an immutable DAG of every API call, tool use, decision, and outcome."*

### Session end scenarios

**1. User closes widget, keeps lock alive ("Keep alive")**
- Pi process stays running in the pod, lock stays in vtf
- User reopens widget → `GET /v1/locks` finds their lock → reconnects to same Pi process
- Pi has full conversation context in memory — no data loss
- Works until idle timeout (4 hours, configurable via `LOCKED_IDLE_TIMEOUT_SECONDS`)

**2. User releases the lock ("Release")**
- Pi gets `shutdown` command, process exits
- Lock deleted from vtf, SessionRecord finalized with `cxdb_context_id`
- cxdb retains the full conversation trace

**3. Idle timeout fires (no activity for 4 hours)**
- Same as release — Pi shutdown, lock deleted, SessionRecord finalized

**4. Pod eviction / crash / bridge restart**
- Pi process dies, in-memory context lost
- Bridge recovery on restart: queries vtf for active locks, checks if pod exists. If pod exists and is running, opens new exec to it (but Pi process is gone). If pod is gone, releases stale lock.
- cxdb retains the full conversation trace from before the crash

### Resuming a previous conversation

When a user starts a new session after a previous one ended, the bridge can load prior context from cxdb. The infrastructure for this exists:

**What is implemented today:**
- The bridge records `cxdb_context_id` in vtf SessionRecords after each prompt (`session_recorder.py`)
- The cxdb MCP server (deployed at `cxdb-mcp` in vafi-dev) provides 4 tools: `cxdb_session_summary`, `cxdb_session_breadcrumbs`, `cxdb_get_turns`, `cxdb_list_sessions`
- The `src/cxdb/` package provides: `CxdbClient` (async HTTP), `parse_turns()`, `extract_tool_events()`, `extract_structured()` (summary extraction)
- Pi agents already have cxdb MCP access — the bridge injects `VF_CXDB_MCP_URL` into Pi's environment

**What is designed but not yet wired for the chat widget:**
- On new session for a project where a prior session exists:
  1. Bridge queries vtf SessionRecords for the last session's `cxdb_context_id`
  2. Bridge calls `src/cxdb/` to build a context summary (tiered loading from cxdb integration design):
     - **Tier 1 (~800 tokens):** Structured summary — what was discussed, what was decided, key files touched
     - **Tier 2 (~3K tokens):** Breadcrumbs — step-by-step tool-use timeline
     - **Tier 3 (variable):** Selective turns — specific parts of the conversation on demand
  3. Bridge injects the summary into Pi's session via `--append-system-prompt` with a preamble: "This is a continuation of a previous session. Here is what was discussed:"
  4. Pi starts with prior context — the agent knows what happened before

**What the user sees:**
- Chat widget queries vtf for prior sessions on this project
- If prior session exists: loads display history from cxdb turns (user messages + assistant responses)
- Messages rendered in the widget so the user can scroll back and see the previous conversation
- New messages append below

**Unverified assumptions:**
- `assistant_turn.text` population in interactive sessions: All cxdb spike data (spike0 report) was from executor sessions where `turn.text` was often empty. Interactive architect sessions via the bridge may behave differently since the prompt flow is different. This needs verification by running a chat session through the bridge and inspecting the cxdb turns.
- Pi `--session-dir` resume: Whether Pi can resume from its own JSONL session files after process restart has never been tested (spike S3 in the bridge design doc). If this works, it provides a simpler resume path for cases where the same pod is reused. This is a separate concern from cxdb-based resume — the two are complementary.

## What This Does NOT Cover

- **Slack adapter** — separate Phase C item, different design
- **Mobile app** — direct HTTP client, no vtf web component needed
- **Multiple simultaneous chats** — one chat per project; multi-chat requires UX design
- **File uploads / image attachments** — not in scope
- **Voice input** — not in scope

## Implementation Sequence

| Phase | What | Depends on | Status | Commit |
|-------|------|-----------|--------|--------|
| 1 | `bridge.ts` API client + `useBridgeStream` hook | Nothing | ✅ Done | vtf:`c5b3fe9` |
| 2 | `ChatWidgetContext` + `ChatWidget` shell (3 layout modes) | Phase 1 | ✅ Done | vtf:`c5b3fe9` |
| 3 | `ChatWindow` + `ChatMessage` + `ChatInput` | Phase 2 | ✅ Done | vtf:`c5b3fe9` |
| 4 | Lock lifecycle (acquire/reconnect/release) | Phase 3 | ✅ Done | vtf:`c5b3fe9` |
| 5 | Streaming integration (NDJSON → messages) | Phase 4 | ✅ Done | vtf:`c5b3fe9` |
| 6 | Polish: tool indicators, markdown, auto-scroll, beforeunload | Phase 5 | ✅ Done | vtf:`c5b3fe9` + `783a708` |
| 7 | Integration: buttons in project pages, App.tsx mount | Phase 6 | ✅ Done | vtf:`c5b3fe9` + `66d45c5` |
| 8 | Session continuity: load prior session from cxdb on new lock acquire | Phase 7 | ❌ Not started | — |
| 9 | Display history: render prior conversation from cxdb turns in widget | Phase 8 | ❌ Not started | — |

### Definition of Done

A user on a vtf project page can:
1. Click "Chat with Architect" → widget opens, lock acquired
2. Type a message → streamed response with markdown rendering
3. See tool use indicators when agent runs bash/edit/read
4. Send follow-up messages with full conversation context
5. Close widget → prompted to release or keep alive
6. Reopen widget → reconnects to existing session (if lock still alive)
7. Refresh page → messages restored from localStorage, session still alive
8. Start a new session after release → agent has context from the previous session via cxdb
9. See previous conversation messages rendered in the widget from cxdb history
