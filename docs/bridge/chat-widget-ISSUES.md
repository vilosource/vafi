# Chat Widget — Issues & Gap Analysis

---
status: completed
last_verified: 2026-04-17
---

**Date:** 2026-04-15
**Scope:** Phase C audit — bugs, parity gaps, and missing polish discovered during first real user test
**Design:** [chat-widget-DESIGN.md](chat-widget-DESIGN.md)
**Tested on:** vtf.dev.viloforge.com, python-calc project, Chat with Architect

> **All issues in this document have been fixed.** See commit references below. Rework plan: [chat-widget-REWORK-PLAN.md](chat-widget-REWORK-PLAN.md)

## How these were found

User opened the chat widget on dev, sent "what is this project about?", received a full streamed response from the architect agent, and then could not send a follow-up message. Investigation uncovered a chain of issues spanning bridge auth, lock management, Pi event protocol, and frontend polish.

## Bridge Issues

### B1: Session ID mismatch — heartbeat false-conflict after 5 minutes — FIXED in `03cafb6` (R2)

**Severity:** Critical — breaks chat after 5 minutes of use

**What happens:**
1. `POST /v1/lock` — bridge calls `vtf_acquire_lock(project, role)` with `session_id=""` (empty default)
2. Pi handshake returns real session_id `"22c41474-3a82-47b8-972d-2fe338167802"`
3. Bridge updates **in-memory** lock dict (`app.py:436`) and returns it to frontend
4. Bridge **never updates the vtf database** lock with the real session_id
5. Frontend stores `sessionId="22c41474-..."`
6. 5 minutes later: heartbeat calls `GET /v1/locks` → bridge queries **vtf database** → returns `session_id=""`
7. Frontend heartbeat (`useLockHeartbeat.ts:40`): `lock.session_id ("") !== sessionId ("22c41474-...")` → conflict
8. `onConflict` fires → `lockStatus='error'` → textarea and Send button disabled

**Evidence from bridge logs (2026-04-15):**
```
07:09:03 — Lock acquired (vtf pk=57), Pi session 22c41474-...
07:09:12 — Prompt streamed successfully
07:14:06 — First heartbeat → vtf returns session_id="" → MISMATCH
07:15:24 — User clicks Retry (irregular interval confirms manual, not heartbeat)
07:17:37 — User clicks Retry again
```

**Verified via kubectl:**
```json
{"id": 57, "session_id": "", "user": "vafi-agent", "role": "architect"}
```

**Root code:**
- `vafi/src/bridge/app.py:436` — updates in-memory only
- `vafi/src/bridge/vtf_locks.py:15` — `vtf_acquire_lock` accepts session_id param but bridge never calls it with one, nor does it update after handshake

### B2: Pi does not send `agent_end` per prompt in locked RPC mode — FIXED in `53ef419` (R1)

**Severity:** Critical — 120-second stream hang after every response

**What happens:**
1. Pi processes the prompt and streams events (text_delta, tool_use, etc.)
2. Pi finishes the response (last message has `stopReason: "stop"`)
3. Pi does **not** send an `agent_end` event — it stays alive waiting for the next prompt
4. `PodSession.stream_prompt` waits for `agent_end` with 120s timeout (`pod_process.py:435`)
5. After 120s: yields error, breaks, generator exits, HTTP stream closes
6. Frontend shows "Stop" button for ~2 minutes after the response is visually complete

**Evidence from Pi session JSONL** (read from pod via kubectl exec):
```
2026-04-15T07:09:47.595Z message  role=assistant stopReason=stop text="Based on the PROJECT..."
```
No `agent_end` event in the session file. Session JSONL across 5 sessions only contains event types: `session`, `model_change`, `thinking_level_change`, `message`. No `agent_end` or `turn_end` in any persisted session.

**Note:** The JSONL captures persisted events. Pi likely sends streaming events (`message_update`, `tool_execution_start/end`) to stdout that are not persisted. Whether `agent_end` is sent to stdout but not persisted, or not sent at all in locked mode, requires verification. The 120s gap in bridge logs between last response event and heartbeat is consistent with the timeout.

**Root code:**
- `vafi/src/bridge/pod_process.py:443` — breaks only on `agent_end`
- `vafi/src/bridge/app.py:518` — `generate_locked` also looks for `agent_end` only

### B3: Empty-line EOF bug in ExecWebSocket reader — FIXED in `9e50ff7` (R4)

**Severity:** Medium — could kill session mid-prompt

**What happens:**
1. If Pi outputs an empty line to stdout (`\n\n`), `read_stdout` returns `b""`
2. Reader loop (`pod_process.py:346`) treats `b""` as EOF: `if not data: break`
3. Session dies: `_alive = False`, `None` enqueued as EOF signal
4. Next prompt hits `if not self._alive` → immediate error

**Root code:**
- `vafi/src/bridge/pod_process.py:254-258` — `read_stdout` returns `line.encode("utf-8")` which is `b""` for empty lines
- `vafi/src/bridge/pod_process.py:346` — `if not data: break` doesn't distinguish empty line from true EOF

### B4: Locked path missing event forwarding (parity gap with ephemeral) — FIXED in `53ef419` (R3)

**Severity:** Medium — tool indicators don't work in locked chat

The locked streaming generator (`generate_locked`, `app.py:504-527`) only handles 3 event types. The ephemeral generator (`generate`, `app.py:537-597`) handles 7. Missing from locked path:

| Event | Ephemeral (line) | Locked | Frontend impact |
|-------|-------------------|--------|-----------------|
| `tool_execution_start` | 564 → `tool_use` started | Missing | No "Running bash..." indicator |
| `tool_execution_end` | 568 → `tool_use` completed | Missing | No tool completion indicator |
| `error` | 575 → forwarded | Missing | Bridge errors silently swallowed |
| `turn_end` | 572 → turn count | Missing | `num_turns` always 0 in result |

All events ARE passed through as raw `agent_event`, but the frontend ignores `agent_event` in `handleStreamEvent` (`ChatWidgetContext.tsx:206`). Without the user-friendly `tool_use` and `error` event types, the frontend has no way to render tool indicators or show errors.

### B5: VTF lock `user` is service token, not actual user — FIXED in `85a2bda` (R8)

**Severity:** Low — confusing UX

The bridge acquires vtf locks using `VTF_API_TOKEN` (a service token owned by user `vafi-agent`). The vtf lock serializer returns `user: "vafi-agent"` instead of `"admin"` (the actual user). This means:
- Heartbeat conflict messages say "Session taken by vafi-agent" instead of "Session taken by admin"
- VTF lock management UI shows wrong owner

**Root code:**
- `vafi/src/bridge/vtf_locks.py:17-22` — uses `VTF_API_TOKEN` for all lock operations

## Frontend Issues

### F1: No syntax highlighting in code blocks — FIXED in `783a708` (R5)

**Severity:** Medium — architect responses often contain code

`react-syntax-highlighter` is specified in the design doc as a dependency but is not in `package.json`. Code blocks in assistant messages render as plain monospace text with no language-specific highlighting.

**Design spec:** "react-markdown + react-syntax-highlighter for code blocks"
**Actual:** Only `react-markdown@^10.1.0` and `remark-gfm@^4.0.1` installed.
**File:** `vtaskforge/web/src/components/ChatMessage.tsx:45-55`

### F2: No smart auto-scroll — FIXED in `783a708` (R6)

**Severity:** Medium — frustrating in long conversations

The design calls for IntersectionObserver-based smart scroll that avoids yanking the user back to the bottom when they've scrolled up to read history. Current implementation uses basic `scrollTop = scrollHeight` on every message change.

**Design spec:** "Don't auto-scroll if user scrolled up (track with IntersectionObserver on a sentinel div at the bottom)"
**Actual:** `ChatWindow.tsx:42-46` — always scrolls to bottom unconditionally
```typescript
useEffect(() => {
  if (scrollRef.current) {
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }
}, [messages]);
```

### F3: No shimmer animation on tool use indicators — FIXED in `783a708` (R7)

**Severity:** Low — cosmetic

Tool use badges show static colored pills with "..." or "✓" text. The design specifies a shimmer animation for in-progress tool use to give visual feedback that the agent is working.

**Design spec:** "'Running {tool}...' with shimmer animation"
**Actual:** Static `bg-surface-container-high` badge, no animation. `ChatMessage.tsx:25-42`

## Auth Issues (FIXED)

### A1: "Welcome back, token-user" — FIXED in 89de243d

Auto-provisioned `vtf_token` in localStorage caused the auth check to short-circuit on page reload, setting `username='token-user'` and skipping Django session auth.

**Fix:** Removed early-return in `App.tsx:52-58`. Session auth always runs.

### A2: No logout button — FIXED in 89de243d

No way to log out or clear stale auth state.

**Fix:** Added `UserFooter` component to `Sidebar.tsx` with logout button that clears Django session + localStorage token + redirects to login.

## Not Yet Started (Phases 8-9 per design)

| Phase | Feature | Description |
|-------|---------|-------------|
| 8 | Session continuity | On new lock acquire, load prior session context from cxdb so architect knows what was discussed before |
| 9 | Display history | Render prior conversation messages from cxdb turns in widget so user can scroll back |

These are explicitly scoped as later phases in the design doc and not part of the current bug fix.
