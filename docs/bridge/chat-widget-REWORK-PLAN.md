# Chat Widget — Rework Plan

---
status: completed
last_verified: 2026-04-17
---

**Date:** 2026-04-15
**Completed:** 2026-04-16
**Issues:** [chat-widget-ISSUES.md](chat-widget-ISSUES.md)
**Design:** [chat-widget-DESIGN.md](chat-widget-DESIGN.md)
**Rule:** Fix the bugs, close the parity gaps, ship the polish. No new features beyond what the design already specifies.

> **All 8 phases (R1–R8) are complete.** Deployed and verified with 13/13 Playwright E2E tests passing.

## Definition of Done

A user on vtf.dev.viloforge.com can:
1. Click "Chat with Architect" → widget opens, lock acquired
2. Type a message → streamed response with **markdown + syntax-highlighted code blocks**
3. See **tool use indicators** when agent runs bash/edit/read (not just raw agent_event)
4. Send **follow-up messages** without the Send button becoming disabled
5. **Scroll up** during a long response without being yanked back to bottom
6. Close widget → prompted to release or keep alive
7. Reopen widget → reconnects to existing session
8. Refresh page → messages restored, session still alive
9. Leave widget open for **30+ minutes** without heartbeat breaking the session
10. **Log out** and back in — correct username shown, clean state

Each criterion is verified by automated tests AND manual Playwright confirmation on dev.

## Testing Strategy

Every phase includes:
- **Unit tests** that run in CI without infrastructure (mocked I/O)
- **E2E tests** where applicable (run against deployed dev environment)
- **Manual verification** via Playwright on vtf.dev.viloforge.com

Existing test infrastructure:
- **Bridge (vafi):** pytest + pytest-asyncio, 95 unit tests in `tests/bridge/`, ASGI test client via `httpx.ASGITransport`, mocks for auth/pods/Pi
- **Frontend (vtf):** Vitest + React Testing Library, 163 unit tests, Playwright E2E in `e2e/`
- **Backend (vtf):** pytest-django, 1679 tests

Test commands:
- Bridge: `cd /workspace/vafi && make test`
- Frontend: `cd /workspace/vtaskforge/web && npx vitest run`
- VTF backend: `cd /workspace/vtaskforge && docker compose exec api pytest`
- E2E: `cd /workspace/vtaskforge/web && VTF_BASE_URL=https://vtf.dev.viloforge.com npx playwright test e2e/chat-widget.spec.ts`

## Phases

### Phase R1: Bridge — Fix stream completion (B2)

**Problem:** Pi does not send `agent_end` per prompt in locked RPC mode. `stream_prompt` waits 120s for an event that never comes.

**Approach:** Detect response completion by the final `message` event with `stopReason: "stop"` or `stopReason: "end_turn"`, rather than waiting for `agent_end`. This matches Pi's actual protocol in locked mode where the agent loop finishes but the process stays alive.

**Changes:**

`vafi/src/bridge/pod_process.py` — `stream_prompt`:
```python
# Current (line 442-443):
event = parse_pi_event(line)
if event and event.type == "agent_end":
    break

# New: also break on final assistant message with stop
event = parse_pi_event(line)
if event and event.type == "agent_end":
    break
if event and event.type == "message":
    msg = event.data.get("message", {})
    if msg.get("role") == "assistant" and msg.get("stopReason") in ("stop", "end_turn"):
        break
```

`vafi/src/bridge/app.py` — `generate_locked`:
- Handle `message` events with `stopReason in ("stop", "end_turn")` as response completion
- Extract `result` from the message content and usage (same fields as `agent_end` extraction)
- Add explicit `break` after yielding `result` to exit the `async for` loop
- Fall through: if `agent_end` IS received, handle it as before (backward compatible)

**Unit tests** (`vafi/tests/bridge/test_pod_process.py`):
```
test_stream_prompt_breaks_on_message_stop
  — Mock queue with [session, message(stopReason=stop)] events
  — Assert stream yields both events and terminates without waiting for agent_end
  — Assert no timeout error

test_stream_prompt_breaks_on_agent_end
  — Existing behavior preserved: mock queue with [session, agent_end] events
  — Assert stream terminates on agent_end (backward compatible)

test_stream_prompt_timeout_when_no_stop
  — Mock queue that never sends stop or agent_end
  — Assert 120s timeout yields error event
```

**Unit tests** (`vafi/tests/bridge/test_prompt.py`):
```
test_locked_stream_yields_result_on_message_stop
  — Create app with locked role, mock PodSession.stream_prompt to yield
    [session, message_update(text_delta), message(stopReason=stop)] events
  — POST /v1/prompt/stream with locked role
  — Parse NDJSON response: assert text_delta and result events present
  — Assert result contains extracted text and token usage

test_locked_stream_yields_result_on_agent_end
  — Same as above but with agent_end event instead of message(stop)
  — Backward compatibility test
```

**Deploy + verify:**
- Deploy bridge to vafi-dev
- Open chat widget, send message
- Confirm: Send button re-enables within seconds (not 120s)
- Confirm: no "Locked prompt timed out" in bridge logs

---

### Phase R2: Bridge — Fix session ID mismatch (B1)

**Problem:** vtf lock created with `session_id=""`, never updated after Pi handshake. Heartbeat sees mismatch at 5 minutes.

**Changes:**

**vtf backend** — `vtaskforge/src/prefs/views.py` — add PATCH to `LockDetailView`:
```python
def patch(self, request, pk):
    try:
        lock = AgentLock.objects.get(pk=pk)
    except AgentLock.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    session_id = request.data.get("session_id")
    if session_id is not None:
        lock.session_id = session_id
        lock.save(update_fields=["session_id"])
    serializer = AgentLockSerializer(lock)
    return Response(serializer.data)
```

**Bridge** — `vafi/src/bridge/vtf_locks.py` — add `vtf_update_lock`:
```python
async def vtf_update_lock(lock_pk: int, session_id: str) -> bool:
    """PATCH /v1/locks/<pk>/ — update session_id after Pi handshake."""
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{VTF_API_URL}/v1/locks/{lock_pk}/",
            headers={"Authorization": f"Token {VTF_API_TOKEN}"},
            json={"session_id": session_id},
            timeout=10,
        )
        return resp.status_code == 200
```

**Bridge** — `vafi/src/bridge/app.py` — after line 436:
```python
if pod_session.session_id and lock_manager.use_vtf and lock.get("vtf_pk"):
    from .vtf_locks import vtf_update_lock
    await vtf_update_lock(lock["vtf_pk"], pod_session.session_id)
```

**Unit tests — vtf backend** (`vtaskforge/tests/prefs/`):
```
test_lock_detail_patch_updates_session_id
  — Create AgentLock with session_id=""
  — PATCH /v1/locks/<pk>/ with {"session_id": "real-sess-123"}
  — Assert 200, lock.session_id == "real-sess-123"

test_lock_detail_patch_returns_404_for_missing_lock
  — PATCH /v1/locks/999/ → 404
```

**Unit tests — bridge** (`vafi/tests/bridge/test_locks.py`):
```
test_acquire_lock_updates_vtf_session_id
  — Enable use_vtf on lock manager, mock vtf_acquire_lock and vtf_update_lock
  — POST /v1/lock → acquire lock
  — Assert vtf_update_lock called with (vtf_pk, pod_session.session_id)

test_acquire_lock_skips_vtf_update_when_no_session_id
  — Mock PodSession with session_id=None
  — Assert vtf_update_lock NOT called
```

**Deploy + verify (both vtf + bridge):**
- Deploy vtf with PATCH support
- Deploy bridge with vtf_update_lock call
- Open chat widget, acquire lock
- kubectl: `GET /v1/locks/?project_id=...` → confirm session_id is not empty
- Wait 5+ minutes → heartbeat succeeds, Send button stays enabled

---

### Phase R3: Bridge — Event forwarding parity (B4)

**Problem:** Locked path doesn't forward `tool_use`, `error`, or `turn_end` events. Tool indicators don't work.

**Changes:**

`vafi/src/bridge/app.py` — `generate_locked`, add handlers after `message_update` block:

```python
elif event.type == "tool_execution_start":
    tool_name = event.data.get("toolName", "unknown")
    yield json.dumps({"type": "tool_use", "tool": tool_name, "status": "started"}) + "\n"

elif event.type == "tool_execution_end":
    tool_name = event.data.get("toolName", "unknown")
    yield json.dumps({"type": "tool_use", "tool": tool_name, "status": "completed"}) + "\n"

elif event.type == "error":
    yield json.dumps({"type": "error", "message": event.data.get("message", "unknown error")}) + "\n"

elif event.type == "turn_end":
    num_turns += 1
```

Also initialize `num_turns = 0` at the start of `generate_locked` and include it in the `result` event.

**Unit tests** (`vafi/tests/bridge/test_prompt.py`):
```
test_locked_stream_forwards_tool_use_started
  — Mock PodSession.stream_prompt yielding [tool_execution_start(toolName="bash"), message(stop)]
  — Assert NDJSON output contains {"type": "tool_use", "tool": "bash", "status": "started"}

test_locked_stream_forwards_tool_use_completed
  — Same pattern with tool_execution_end
  — Assert {"type": "tool_use", "tool": "bash", "status": "completed"}

test_locked_stream_forwards_error_event
  — Mock stream yielding [error("Pi crashed")]
  — Assert NDJSON output contains {"type": "error", "message": "Pi crashed"}

test_locked_stream_counts_turns
  — Mock stream with multiple turn_end events
  — Assert result event has correct num_turns count

test_locked_stream_parity_with_ephemeral
  — Feed identical Pi events to both locked and ephemeral generators
  — Assert both produce the same set of user-facing event types
    (text_delta, tool_use, error, result — ignoring agent_event raw passthrough)
```

**E2E test** (`vtaskforge/web/e2e/chat-widget.spec.ts`):
```
test_tool_use_indicators_visible_during_chat
  — Login, open chat widget, send message that triggers tool use
  — Assert tool use badge visible in assistant message
```

**Deploy + verify:**
- Deploy bridge
- Send "list the files in this project" in chat
- Confirm: tool use indicators appear during response

---

### Phase R4: Bridge — Fix empty-line EOF bug (B3)

**Problem:** `read_stdout` returns `b""` for empty lines, reader loop treats as EOF.

**Changes:**

`vafi/src/bridge/pod_process.py` — `read_stdout`:
- Skip empty lines in the buffer instead of returning `b""` — continue the read loop

`vafi/src/bridge/pod_process.py` — `_reader_loop`:
- No changes needed if `read_stdout` never returns `b""` for non-EOF

**Unit tests** (`vafi/tests/bridge/test_pod_process.py`):
```
test_read_stdout_skips_empty_lines
  — Mock WebSocket that sends "line1\n\n\nline2\n" in one frame
  — Assert read_stdout returns "line1", then "line2" (skips empty lines)
  — Assert read_stdout does NOT return b""

test_read_stdout_eof_on_ws_close
  — Mock WebSocket that sends CLOSE message
  — Assert read_stdout returns b"" (true EOF)

test_reader_loop_survives_empty_lines
  — Feed a WebSocket stream with embedded empty lines between JSONL events
  — Assert reader loop enqueues all non-empty lines and does NOT exit prematurely
  — Assert _alive remains True throughout
```

**Deploy + verify:**
- Deploy bridge
- Long chat session with multiple tool uses
- Confirm: no "Reader loop EOF" in bridge logs during active conversations

---

### Phase R5: Frontend — Syntax highlighting (F1)

**Changes:**

```bash
cd vtaskforge/web && npm install react-syntax-highlighter @types/react-syntax-highlighter
```

`vtaskforge/web/src/components/ChatMessage.tsx` — add code block renderer to ReactMarkdown:
```tsx
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

components={{
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '');
    return match ? (
      <SyntaxHighlighter style={oneDark} language={match[1]} PreTag="div">
        {String(children).replace(/\n$/, '')}
      </SyntaxHighlighter>
    ) : (
      <code className={className} {...props}>{children}</code>
    );
  },
}}
```

**Unit tests** (`vtaskforge/web/src/components/__tests__/ChatMessage.test.tsx`):
```
test_renders_fenced_code_block_with_syntax_highlighter
  — Render assistant message with content: "```python\nprint('hello')\n```"
  — Assert SyntaxHighlighter component is rendered (or: assert <pre> with syntax class)
  — Assert language="python" attribute present

test_renders_inline_code_without_syntax_highlighter
  — Render assistant message with content: "Use `foo()` here"
  — Assert inline <code> element rendered, NOT SyntaxHighlighter

test_renders_code_block_without_language_as_plain
  — Render assistant message with content: "```\nsome text\n```"
  — Assert rendered as plain <code> block, not SyntaxHighlighter
```

**Deploy + verify:**
- Deploy vtf
- Ask architect "show me a Python hello world"
- Confirm: code block has syntax coloring (keywords, strings, etc.)

---

### Phase R6: Frontend — Smart auto-scroll (F2)

**Changes:**

`vtaskforge/web/src/components/ChatWindow.tsx`:
- Add a sentinel `<div>` at the bottom of the message list
- Use IntersectionObserver to track if sentinel is visible
- Only auto-scroll when sentinel is in viewport (user hasn't scrolled up)

```tsx
const sentinelRef = useRef<HTMLDivElement>(null);
const isAtBottom = useRef(true);

useEffect(() => {
  const sentinel = sentinelRef.current;
  if (!sentinel) return;
  const observer = new IntersectionObserver(
    ([entry]) => { isAtBottom.current = entry.isIntersecting; },
    { root: scrollRef.current, threshold: 0.1 },
  );
  observer.observe(sentinel);
  return () => observer.disconnect();
}, []);

useEffect(() => {
  if (isAtBottom.current && scrollRef.current) {
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }
}, [messages]);

// In JSX, after messages.map():
<div ref={sentinelRef} className="h-1" />
```

**Unit tests** (`vtaskforge/web/src/components/__tests__/ChatWindow.test.tsx`):
```
test_sentinel_div_exists_at_bottom_of_message_list
  — Render ChatWindow with messages
  — Assert sentinel div is present after messages

test_auto_scrolls_when_at_bottom
  — Render with messages, verify scrollTop === scrollHeight after new message added
  — (jsdom has limited IntersectionObserver support — may need to mock the observer
    and set isIntersecting=true, then verify scrollTop is updated)

test_does_not_auto_scroll_when_scrolled_up
  — Mock IntersectionObserver with isIntersecting=false (user scrolled up)
  — Add new message
  — Assert scrollTop did NOT change
```

Note: IntersectionObserver is not natively available in jsdom. Tests should mock it or use a polyfill. The key assertion is that the scroll behavior is conditional on the sentinel's visibility.

**Deploy + verify:**
- Deploy vtf
- Send a question that generates a long response
- Scroll up during streaming → view stays where scrolled
- Scroll back to bottom → auto-scroll resumes

---

### Phase R7: Frontend — Shimmer animation on tool indicators (F3)

**Changes:**

`vtaskforge/web/src/components/ChatMessage.tsx` — add `animate-pulse` class to "started" tool badges:

```tsx
// For status === 'started', add animate-pulse:
<span className={`inline-flex items-center gap-1 ... ${
  tu.status === 'started' ? 'animate-pulse' : ''
}`}>
```

**Unit tests** (`vtaskforge/web/src/components/__tests__/ChatMessage.test.tsx`):
```
test_tool_use_started_has_pulse_animation
  — Render assistant message with toolUses: [{tool: "bash", status: "started"}]
  — Assert badge element has class "animate-pulse"

test_tool_use_completed_no_pulse_animation
  — Render with toolUses: [{tool: "bash", status: "completed"}]
  — Assert badge element does NOT have class "animate-pulse"
```

**Deploy + verify:**
- Deploy vtf
- Send message that triggers tool use
- Confirm: badge pulses while tool running, stops when completed

---

### Phase R8: Bridge — Correct lock ownership (B5)

**Problem:** vtf locks owned by `vafi-agent` (service token) instead of actual user.

This is a design consideration. Options:

**Option A (recommended):** vtf lock API accepts `user_id` in the POST body, allowing the service token to create locks attributed to another user. Similar pattern to how `SessionCreateView` already supports `user_id` proxy (views.py:220).

**Changes if Option A:**

**vtf backend** — `vtaskforge/src/prefs/views.py` — `LockView.post`:
- Accept optional `user_id` field in POST body
- If present and requester is agent/staff: create lock for that user
- If absent: create lock for authenticated user (existing behavior)

**Bridge** — `vafi/src/bridge/vtf_locks.py` — `vtf_acquire_lock`:
- Pass `user_id` from the authenticated bridge user into the POST body

**Bridge** — `vafi/src/bridge/app.py` — `acquire_lock`:
- Extract `user["user_id"]` from the authenticated user and pass to `vtf_acquire_lock`

**Unit tests — vtf backend:**
```
test_lock_create_with_user_id_proxy
  — POST /v1/locks/ with user_id=42 as agent user
  — Assert lock.user_id == 42

test_lock_create_without_user_id_uses_request_user
  — POST /v1/locks/ without user_id
  — Assert lock.user == request.user (existing behavior)

test_lock_create_non_agent_cannot_proxy
  — POST /v1/locks/ with user_id=42 as regular human user
  — Assert 403 or user_id ignored
```

**Unit tests — bridge:**
```
test_acquire_lock_passes_user_id_to_vtf
  — Mock vtf_acquire_lock
  — Assert it's called with user_id from the authenticated user
```

**Deploy + verify:**
- Acquire lock via chat widget
- `GET /v1/locks/` → shows `user: "admin"` not `user: "vafi-agent"`
- Conflict messages show correct username

---

## Execution Order

```
R1 (stream completion)  ← vafi:53ef419 ✅
  ↓
R2 (session ID sync)    ← vafi:03cafb6 ✅
  ↓
R3 (event parity)       ← vafi:53ef419 (combined with R1) ✅
  ↓
R4 (empty-line EOF)     ← vafi:9e50ff7 ✅
  ↓
R5 (syntax highlight)   ← vtf:783a708 ✅
  ↓
R6 (smart scroll)       ← vtf:783a708 (combined with R5) ✅
  ↓
R7 (shimmer animation)  ← vtf:783a708 (combined with R5) ✅
  ↓
R8 (lock ownership)     ← vafi:85a2bda + vtf:5f95591 ✅
```

R1-R4 are bridge changes (vafi repo). R5-R7 are frontend changes (vtaskforge repo). R8 spans both.

## Per-Phase Checklist

All phases completed 2026-04-16:

- [x] Code changes implemented
- [x] Unit tests written and passing locally
- [x] All existing tests still pass (`make test` / `npx vitest run`)
- [x] Committed to repo
- [x] Deployed to dev environment
- [x] Manual verification via Playwright on vtf.dev.viloforge.com
- [x] Pushed to GitHub

**E2E results (2026-04-17):** 13/13 Playwright tests passing
