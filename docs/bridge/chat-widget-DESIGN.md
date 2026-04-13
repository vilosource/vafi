# ChatWidget — Design

**Status:** Design
**Date:** 2026-04-13
**Scope:** Phase C of the agent bridge service — web chat interface in vtf
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

## What This Does NOT Cover

- **Slack adapter** — separate Phase C item, different design
- **Mobile app** — direct HTTP client, no vtf web component needed
- **Conversation history API** — v1 uses localStorage; server-side history is v2
- **Multiple simultaneous chats** — v1 is one chat per project; multi-chat is v2
- **File uploads / image attachments** — v2
- **Voice input** — v2

## Implementation Sequence

| Phase | What | Depends on |
|-------|------|-----------|
| 1 | `bridge.ts` API client + `useBridgeStream` hook | Nothing |
| 2 | `ChatWidgetContext` + `ChatWidget` shell (3 layout modes) | Phase 1 |
| 3 | `ChatWindow` + `ChatMessage` + `ChatInput` | Phase 2 |
| 4 | Lock lifecycle (acquire/reconnect/release) | Phase 3 |
| 5 | Streaming integration (NDJSON → messages) | Phase 4 |
| 6 | Polish: tool indicators, markdown, auto-scroll, beforeunload | Phase 5 |
| 7 | Integration: buttons in project pages, App.tsx mount | Phase 6 |

### Definition of Done

A user on a vtf project page can:
1. Click "Chat with Architect" → widget opens, lock acquired
2. Type a message → streamed response with markdown rendering
3. See tool use indicators when agent runs bash/edit/read
4. Send follow-up messages with full conversation context
5. Close widget → prompted to release or keep alive
6. Reopen widget → reconnects to existing session
7. Refresh page → messages restored from localStorage, session still alive
