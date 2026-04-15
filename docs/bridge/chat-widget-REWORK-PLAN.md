# Chat Widget — Rework Plan

**Date:** 2026-04-15
**Issues:** [chat-widget-ISSUES.md](chat-widget-ISSUES.md)
**Design:** [chat-widget-DESIGN.md](chat-widget-DESIGN.md)
**Rule:** Fix the bugs, close the parity gaps, ship the polish. No new features beyond what the design already specifies.

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

Each fix is deployed to dev and verified via Playwright before moving to the next.

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
- Extract `result` from the `message` event's content (same fields as `agent_end` extraction)
- Add explicit `break` after yielding `result` to exit the `async for` loop
- Fall through: if `agent_end` IS received, handle it as before (backward compatible)

**Verification:**
- Send a message via the chat widget
- Response streams in, Send button re-enables within seconds of response completing (not 120s)
- No "Locked prompt timed out" in bridge logs

### Phase R2: Bridge — Fix session ID mismatch (B1)

**Problem:** vtf lock created with `session_id=""`, never updated after Pi handshake. Heartbeat sees mismatch at 5 minutes.

**Changes:**

`vafi/src/bridge/vtf_locks.py` — add `vtf_update_lock`:
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

`vafi/src/bridge/app.py` — after line 436:
```python
# Update vtf lock with real session_id
if pod_session.session_id and lock_manager.use_vtf and lock.get("vtf_pk"):
    from .vtf_locks import vtf_update_lock
    await vtf_update_lock(lock["vtf_pk"], pod_session.session_id)
```

`vtaskforge/src/prefs/views.py` — ensure AgentLock viewset supports PATCH with `session_id` field writable. Check if the viewset already allows partial update. If not, add it.

**Verification:**
- Open chat widget, acquire lock
- `kubectl exec` into bridge pod, query vtf: `GET /v1/locks/?project_id=...`
- Confirm vtf lock has real session_id (not empty string)
- Wait 5+ minutes — heartbeat succeeds, Send button stays enabled

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

**Verification:**
- Send a message that triggers tool use (e.g., "list the files in this project")
- Chat widget shows "Running bash..." indicator while tool executes
- Indicator changes to completed state when done

### Phase R4: Bridge — Fix empty-line EOF bug (B3)

**Problem:** `read_stdout` returns `b""` for empty lines, reader loop treats as EOF.

**Changes:**

`vafi/src/bridge/pod_process.py` — `_reader_loop`, line 346:
```python
# Current:
if not data:
    break

# New: distinguish empty line from true EOF
if data == b"":
    # EOF from WebSocket close
    break
```

`vafi/src/bridge/pod_process.py` — `read_stdout`, around line 256:
```python
# Current:
if "\n" in self._buffer:
    line, self._buffer = self._buffer.split("\n", 1)
    return line.encode("utf-8")

# New: skip empty lines, don't return b""
if "\n" in self._buffer:
    line, self._buffer = self._buffer.split("\n", 1)
    if line.strip():
        return line.encode("utf-8")
    # Empty line — skip and continue reading
    continue
```

This ensures only actual JSONL content lines are returned; empty lines (which Pi may output between events) are silently skipped.

**Verification:**
- Long chat session with multiple tool uses doesn't randomly disconnect
- No "Reader loop EOF" in bridge logs during active conversations

### Phase R5: Frontend — Syntax highlighting (F1)

**Changes:**

```bash
cd vtaskforge/web && npm install react-syntax-highlighter @types/react-syntax-highlighter
```

`vtaskforge/web/src/components/ChatMessage.tsx` — add code block renderer to ReactMarkdown:
```tsx
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

// In the ReactMarkdown components prop:
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

**Verification:**
- Ask architect "show me a Python hello world"
- Response renders with Python syntax highlighting (keywords colored, strings colored)

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

**Verification:**
- Ask a question that generates a long response
- While response is streaming, scroll up manually
- Response continues streaming but view stays where user scrolled
- Scroll back to bottom — auto-scroll resumes

### Phase R7: Frontend — Shimmer animation on tool indicators (F3)

**Changes:**

`vtaskforge/web/src/components/ChatMessage.tsx` — add pulse animation to "started" tool badges:

```tsx
// For status === 'started':
<span className="... animate-pulse">
```

Or a custom shimmer keyframe if pulse is too subtle. The goal is visual feedback that the agent is actively running a tool.

**Verification:**
- Send a message that triggers tool use
- "Running bash..." badge pulses/shimmers while tool is executing
- Animation stops when status changes to "completed"

### Phase R8: Bridge — Correct lock ownership (B5)

**Problem:** vtf locks owned by `vafi-agent` (service token) instead of actual user.

**Changes:**

This is a design consideration — the bridge authenticates to vtf with a service token, but should attribute locks to the actual user. Options:

**Option A:** Bridge passes the actual user's vtf token (from the frontend Authorization header) to vtf when acquiring locks. This requires the bridge to proxy the user's token for lock operations only.

**Option B:** Bridge creates locks with an additional `on_behalf_of` field that stores the actual username. vtf lock API would need to support this.

**Option C:** vtf lock API accepts a `user_id` or `username` field in the POST body, allowing the service token to create locks attributed to another user.

Decision needed before implementation. This affects the `list_locks` response and heartbeat conflict messages.

**Verification:**
- Acquire lock, check vtf: `GET /v1/locks/` shows `user: "admin"` not `user: "vafi-agent"`
- Heartbeat conflict message shows correct username

## Execution Order

```
R1 (stream completion)  ← must fix first, chat unusable without it
  ↓
R2 (session ID sync)    ← must fix, breaks after 5 min
  ↓
R3 (event parity)       ← tool indicators don't work without it
  ↓
R4 (empty-line EOF)     ← defensive fix, prevents random disconnects
  ↓
R5 (syntax highlight)   ← install dep + wire up
  ↓
R6 (smart scroll)       ← UX improvement
  ↓
R7 (shimmer animation)  ← cosmetic polish
  ↓
R8 (lock ownership)     ← needs design decision
```

R1-R4 are bridge changes (vafi repo). R5-R7 are frontend changes (vtaskforge repo). R8 spans both.

Each phase: implement → deploy to dev → verify via Playwright or kubectl → move to next.
