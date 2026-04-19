# Phase 9 — Display History in Chat Widget Implementation Plan

Status: **draft, awaiting user approval**
Related: [phase-8-session-continuity-PLAN.md](phase-8-session-continuity-PLAN.md), [chat-widget-DESIGN.md](chat-widget-DESIGN.md)
Definition of done: deployed + tested + confirmed (per project convention)

---

## Decision summary

- **Goal:** When the user opens the chat widget on a project with prior architect sessions, render those prior user/assistant turns above the new conversation, with sender attribution on user messages. Visible scroll-back of the project's architectural log.
- **Source of truth:** Same as Phase 8 — Pi's JSONL files on the `console-sessions` PVC at `/sessions/{lowercased-project}/*.jsonl`. **No path change.** The architect chat is a **project-level resource**, not a per-user chatbot — its history naturally accumulates across all project members who've used it. The Phase 8 amendment proposed earlier (per-user dirs) is **withdrawn**.
- **Why project-scoped, not per-user:** the architect lock is per `(project, role)`, not per `(project, role, user)`. The lock serializes write access to the shared workspace `/sessions/{project}/repo/` and ensures one Pi process per architect role per project. Different users take turns. The conversation IS the project's design record; treating it as per-user would lose the team's accumulated architectural knowledge. The chat record belongs to the architect, not the user. Users can be attributed to individual messages they sent, but the overall conversation belongs to the project.
- **Architecture (Option B — SOLID-aligned):**
  1. **Wire `session_recorder.record()` on the streaming endpoint** (closes the deferred bug surfaced by the Phase 8 spike).
  2. **New vtf endpoint** — `GET /v1/sessions/project/{project_id}/?role=architect` returns all SessionRecord rows for the project across users.
  3. **Extract `pi_session_history` shared lib** — both `build_prior_context.py` (in-pod) and the bridge endpoint use one parser.
  4. **Bridge mounts PVC read-only**, exposes `GET /v1/sessions/history`, joins JSONL → vtf SessionRecord on `session_id` to attribute user messages.
  5. **Widget fetches on open**, shows a collapsed "View prior conversation (N messages)" expander; on expand, renders turns with `<username>` for user messages and "Architect" for assistant messages.
- **Coupling:** Architect = Pi forever (per Phase 8 simplification). Phase 9 inherits the same coupling with no new abstractions.
- **Multi-user policy (D1, revised):** Project-scoped history visible to all project members. User attribution at the message level via `session_id → user_id` lookup in vtf SessionRecord. Access control via `check_project_membership` (you see this history because you're a member of this project — same rule as everything else about the project).
- **Scope v1:**
  - Project-scoped (NOT per-user) history, last N turns across all sessions on this project
  - User text + assistant text only — tool calls and tool results are agent-internal, hidden
  - User messages labeled with username; assistant messages labeled "Architect"
  - **Collapsed by default** (D2) — banner: "View prior conversation (N messages)" or "Architect session log (N messages)"; click to expand
  - **Count + age cap (D3)** — `--max-prompts 20 --max-age-days 14` defaults
  - **No live refresh (D4)** — fetched on widget open; in-session new turns appear via the existing streaming response
- **Out of scope:**
  - Pagination / "load more older"
  - Editing or deleting prior turns
  - Migration of pre-Phase-9 sessions whose `session_id → user` is unrecorded (will display without attribution; see Q8)
  - Live updates from another tab/device while the widget is open
  - Phase-9 equivalent for ephemeral assistant role (locked roles only)
  - Filesystem path changes — Phase 8 paths unchanged

---

## Architecture

```
┌──────────────────┐  GET /v1/sessions/history?project=X&role=Y
│  Chat widget     │ ──────────────────────────────────────────▶  ┌──────────────────┐
│  (vtaskforge)    │                                              │  Bridge          │
│                  │  [{role, text, ts, session_id}, ...]         │                  │
│                  │ ◀──────────────────────────────────────────  │  reads PVC       │
└──────────────────┘                                              │  /sessions/...   │
                                                                  │  uses shared     │
                                                                  │  pi_session_     │
                                                                  │  history module  │
                                                                  └──────────────────┘
                                                                            │
                                                                            ▼
                                                          ┌────────────────────────────────┐
                                                          │ console-sessions PVC (mounted  │
                                                          │  read-only into bridge pod)    │
                                                          │  /sessions/{slug}/*.jsonl      │
                                                          └────────────────────────────────┘
```

**Shared module:** `src/lib/pi_session_history.py` exposes the parsing/extraction functions used today by `images/agent/build_prior_context.py`. Both the in-pod script (write-side, summarizes for `--append-system-prompt`) and the bridge endpoint (read-side, returns JSON for the widget) consume this single library. SOLID: one source of truth for "what does a Pi conversation look like."

**Why bridge-reads-PVC and not via-pod:**
- Bridge must answer the history query *before* a lock is acquired (UX: user opens widget → sees history immediately).
- PVC read-only mount on the bridge is a one-line helm chart change.
- No coordination with pod lifecycle; no kubectl exec round-trip.

---

## File layout

```
vafi/
├── src/
│   ├── lib/
│   │   └── pi_session_history.py             [NEW — extracted from build_prior_context.py]
│   └── bridge/
│       ├── app.py                             [MODIFIED — new GET /v1/sessions/history]
│       └── ... (no other bridge code change expected)
├── images/agent/
│   └── build_prior_context.py                 [MODIFIED — import from src/lib instead of inline]
├── tests/
│   ├── lib/
│   │   └── test_pi_session_history.py         [NEW — moved/expanded from tests/agent/]
│   ├── agent/
│   │   └── test_build_prior_context.py        [MODIFIED — slim, delegates to lib tests]
│   ├── bridge/
│   │   └── test_history_endpoint.py           [NEW — endpoint unit tests with mocked FS]
│   └── integration/
│       └── test_session_history_widget.py     [NEW — Playwright/HTTP end-to-end]
├── charts/vafi/templates/
│   └── bridge-deployment.yaml                 [MODIFIED — add console-sessions volume + mount]
└── docs/bridge/
    └── phase-9-display-history-PLAN.md        [this doc]

vtaskforge/
├── web/src/
│   ├── api/
│   │   └── bridge.ts                          [MODIFIED — add fetchSessionHistory()]
│   ├── context/
│   │   └── ChatWidgetContext.tsx              [MODIFIED — fetch on mount; expose priorTurns]
│   └── components/
│       ├── ChatWindow.tsx                      [MODIFIED — render priorTurns + divider]
│       ├── ChatMessage.tsx                     [MODIFIED — accept "isHistory" styling prop]
│       └── ... possibly a new <PriorHistoryDivider/> component
├── web/src/types/
│   └── chat.ts                                [MODIFIED — PriorTurn type]
└── e2e/
    └── chat-widget-history.spec.ts             [NEW — Playwright]
```

---

## Bridge endpoint spec

```
GET /v1/sessions/history?project={project_id}&role={role}&limit={N}
Authorization: Token <vtf-token>
```

- **Auth:** `require_auth` + `check_project_membership`. Caller's username is *not* used for filtering — history is project-scoped.
- **Path read:** `/sessions/{lowercased-project-id}/*.jsonl` (Phase 8 layout, unchanged).
- **Attribution flow:**
  1. Parse JSONL files in chronological order, extract `(session_id, role, text, timestamp)` for each user/assistant message.
  2. Call vtf `GET /v1/sessions/project/{project_id}/?role={role}` to fetch `session_id → {user_id, username}` map.
  3. Annotate each user message with `username`. Assistant messages keep `role=assistant` and render as "Architect" in the UI.
  4. Sessions whose `session_id` has no matching SessionRecord (e.g., from before Pre-Phase 0a wired the recorder) get `username=null` — UI renders these as "Unknown user" or omits the label.
- **Response:**
  ```json
  {
    "turns": [
      {
        "role": "user",
        "text": "...",
        "timestamp": "2026-04-19T12:01:07Z",
        "session_id": "abc-123",
        "username": "alice"
      },
      {
        "role": "assistant",
        "text": "...",
        "timestamp": "2026-04-19T12:01:09Z",
        "session_id": "abc-123",
        "username": null
      },
      ...
    ],
    "truncated": false
  }
  ```
  `username` is set on user messages when the SessionRecord exists; `null` otherwise. Assistant messages always have `username: null` (the UI renders them as "Architect").
- **Defaults:** `limit=20` (same as Phase 8's `--max-prompts`), `max=50` enforced server-side.
- **Empty case:** `200 {"turns": [], "truncated": false}` — never 404.
- **Filtering:** mirrors `build_prior_context.py` — only `message` events with role=user/assistant, only the `text` parts of `content` (tool calls and tool results stripped).
- **Sort order:** chronological (oldest → newest).

The endpoint does **not** acquire a lock or trigger a pod — pure read.

---

## Phased execution with gates

### Pre-Phase 0a — Wire `session_recorder.record()` on the streaming endpoint

**Scope:** the deferred bug from the Phase 8 spike (`/v1/prompt/stream` doesn't write SessionRecord). Phase 9 needs this for user attribution.

1. Modify `src/bridge/app.py`:
   - In `acquire_lock` handler, after Pi handshake completes (when `session_id` is known), call `session_recorder.record(user_id, project_id, role, channel="web", session_id, ended_at=None)`.
   - In `release_lock` handler (and `force_release` callback), call `session_recorder.record(...)` again with `ended_at=now()` to mark the session ended. (Or use a vtf PATCH if SessionRecord supports it; otherwise insert a new row — bridge already idempotent on session_id.)
2. Decide granularity: **per-lock**, not per-prompt. One SessionRecord per Pi process is what we need for `session_id → user` lookup.
3. Update `tests/bridge/test_locks.py` (or `test_app.py`) to assert `record()` is called with correct args on lock acquire/release.

**Gate:** unit tests pass; manual sanity-check that vtf gets a row when a chat-widget session starts.

### Pre-Phase 0b — vtf endpoint for project-scoped session listing

**Scope:** vtf needs a way to enumerate all SessionRecords for a project (across users), so the bridge can join JSONL → user.

1. Add `GET /v1/sessions/project/{project_id}/?role={role}` to `vtaskforge/src/prefs/views.py` (or wherever `SessionHistoryView` lives).
2. Auth: project membership check.
3. Returns: list of `{session_id, user_id, username, role, started_at, ended_at}` for the project.
4. Tests: returns empty list for unknown project; filters by role; only returns rows the caller has access to.

**Gate:** vtf tests pass; manual curl confirms the endpoint returns expected rows.

### Phase 1 — Extract `pi_session_history` library
1. Create `src/lib/pi_session_history.py` with `parse_session_jsonl`, `collect_prior_turns`, `_extract_text_content` lifted from `build_prior_context.py`.
2. Refactor `build_prior_context.py` to import from the lib.
3. Move the parser unit tests from `tests/agent/test_build_prior_context.py` to `tests/lib/test_pi_session_history.py`. Leave the *script-level* tests (CLI, file output, fallback) in `tests/agent/`.
4. Run `pytest tests/lib tests/agent` — no behavior change, all tests pass.

**Gate:** all unit tests green, no regression in `build_prior_context.py` behavior.

### Phase 2 — Bridge endpoint with mocked FS
1. Add `GET /v1/sessions/history` handler in `src/bridge/app.py`. Use `pi_session_history` lib.
2. Add `tests/bridge/test_history_endpoint.py`:
   - Returns 401 without auth
   - Returns 403 without project membership
   - Returns `{"turns": []}` for nonexistent session dir
   - Returns turns in chronological order for a populated dir (use a temp dir with fixture JSONL)
   - Respects `limit` param
   - `truncated: true` when limit hit
   - Mocks `os.path` / uses tmp_path to avoid needing PVC

**Gate:** all bridge tests green.

### Phase 3 — Bridge PVC mount in helm chart
1. Edit `charts/vafi/templates/bridge-deployment.yaml`:
   - Add volume entry referencing `{{ .Values.bridge.sessionsPVC | default "console-sessions" }}`
   - Mount at `/sessions` read-only on the bridge container
2. Add chart unit/template test if there's a pattern (`make helm-template`).
3. Document the new value in `charts/vafi/values.yaml` (or use the existing default).

**Gate:** `make helm-template` produces the expected mount; `make helm-lint` clean.

### Phase 4 — Widget API helper + state plumbing
1. `web/src/api/bridge.ts`: add `async fetchSessionHistory(project, role) -> PriorTurn[]`.
2. `web/src/types/chat.ts`: add `PriorTurn` type (role, text, timestamp, session_id).
3. `ChatWidgetContext.tsx`:
   - On widget open (or on context mount), call `fetchSessionHistory`.
   - Store result in `state.priorTurns` (default `[]`, no loading flicker if empty).
   - On any error, log + treat as empty (non-fatal).
4. Unit tests for the context + bridge.ts.

**Gate:** all frontend unit tests green; behavior verifiable via React Testing Library.

### Phase 5 — Widget rendering
1. `ChatWindow.tsx`:
   - When `priorTurns.length > 0` and no current-session messages yet, render the prior turns at top.
   - Insert a `<PriorHistoryDivider/>` between the last prior turn and the new conversation.
   - Auto-scroll to the bottom of the prior turns (so the user lands at the "now" line).
2. `ChatMessage.tsx`:
   - Accept an `isHistory` prop; apply a subtle dimmed style (e.g., `opacity-75` or a left border) when true.
3. Decide divider copy: e.g., "Previous conversation" / "—— New session ——". Confirm with user during implementation.
4. Playwright unit test: widget shows prior turns when API returns them; nothing if empty; divider visible only when both exist.

**Gate:** Playwright unit + RTL tests green; visual review acceptable.

### Phase 6 — Deploy
1. Build new bridge image (no new agent-pi image needed — Phase 9 is bridge-only on the backend).
2. Push to harbor.
3. `helm upgrade vafi` (or `kubectl set image` + manually patch volume if not using helm immediately).
4. Verify bridge `/v1/sessions/history?...` returns expected data via curl.

**Gate:** endpoint returns turns from a real PVC location; bridge stays healthy; no regression in Phase 8 continuity (re-run the integration tests).

### Phase 7 — Integration test (Playwright via deployed widget)
Add `e2e/chat-widget-history.spec.ts`:
1. Create test project, acquire lock, send a session-1 prompt with a unique nonce (similar to Phase 8 Test A).
2. Hard release.
3. Open the widget UI → assert that the user prompt and assistant reply from session 1 are visible above any new input area.
4. Send a session-2 prompt → assert it appears below the divider.
5. Cleanup.

**Gate:** Playwright passes against `vtf.dev.viloforge.com`.

### Phase 8 — Commit, docs, cleanup
1. Commit on branch `phase-9-display-history`.
2. Update `docs/STATUS.md`: Phase 9 → Recently Completed.
3. Append final entry to this PLAN doc's status log.
4. Cleanup test projects + lingering pods.
5. Stop before push (per existing convention).

**Gate:** clean state, green tests, docs aligned.

---

## Open design questions (resolve during implementation)

| ID | Question | Resolve when |
|----|----------|-------------|
| Q1 | Expander copy — "View prior conversation (4 messages)" vs "Earlier in this conversation…" vs other. | Phase 5 (with user) |
| Q2 | Should expanded history show timestamps (e.g., "2 hours ago") or just sequence? | Phase 5 |
| Q3 | What's the visual treatment for prior assistant messages — markdown rendered same as new, or simplified (no syntax highlight)? | Phase 5 |
| Q4 | Should the "tool use happened here" be hinted (e.g., "agent ran 3 tools") or completely hidden? | Phase 5 — recommend hidden for v1 |
| Q5 | If history fetch is slow (~500ms), do we render a skeleton or show empty until loaded? | Phase 4 |
| Q6 | Cap is 20 turns / 14 days by default — same as Phase 8 cap for context. Do we want different defaults for display vs context? | Phase 2 — start with same, revisit if too sparse |
| Q7 | ~~Per-user *repo/* checkout isolation~~ — **withdrawn**. Repo stays shared (it's the project workspace; per-user doesn't make sense for it). | n/a |
| Q8 | Pre-Phase-0a sessions have no SessionRecord (the wiring didn't exist yet). UI shows `username: null`. Display as "Unknown user," omit label, or filter them out entirely? | Phase 9.5 |
| Q9 | Bridge → vtf history call adds latency to the widget-open path. Cache in bridge memory? Or accept the network hop for v1? | Phase 9.2 — start without cache |

---

## Accepted risks / explicit non-goals

- **Live updates:** if the user has the widget open and another session writes to the JSONL elsewhere, the widget won't refresh until reopened. Acceptable for v1.
- **Multi-user privacy:** already addressed structurally — per-user pod naming means each user's `/sessions/{slug}/*.jsonl` is isolated. Phase 9 inherits this.
- **PVC unavailability:** if the PVC mount fails (cluster issue), the endpoint returns `{"turns": []}` and the widget shows nothing. Not a hard error — graceful degradation.
- **Read-only enforcement:** PVC mount on the bridge is `readOnly: true`. Bridge cannot accidentally corrupt the JSONL files Pi is writing.
- **Tool calls hidden:** users see what they typed and what the agent said. Tool execution stays implementation-detail. (Same filtering as Phase 8.)
- **No deduplication:** if the agent's reply contains text identical to its own prior reply, both show up — no semantic dedup.

---

## Rollback plan

Same as Phase 8: if any post-deploy gate fails:
1. `kubectl set image` back to previous bridge tag.
2. Revert PVC mount via helm rollback or manual deployment edit.
3. Revert branch commits; do not merge.

---

## Task breakdown (for TaskCreate)

One task per phase. Dependencies: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8.
