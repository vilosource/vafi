# Agent Bridge Service — Rework Plan

**Date:** 2026-04-02
**Reason:** Implementation deviated from design. This plan corrects every deviation and completes all missing features per the original design.
**Design:** vafi/docs/agent-bridge-service-DESIGN.md
**Rule:** Follow the design. No stubs. No shortcuts. Improvements require explicit approval before implementation.

## What went wrong

1. Locked prompt path returns 501 instead of routing to Pi in a pod
2. Lock acquire/release is in-memory dict, not vtf AgentLock API
3. Session recording missing entirely
4. Rate limiting missing entirely
5. Ephemeral Pi uses `--mode json` (one-shot) instead of `--mode rpc` (design spec)
6. No MCP env vars injected into Pi processes
7. Health endpoint returns hardcoded values
8. No idle timeout background task
9. No process recovery on restart
10. Lock release returns 404 instead of 403 for non-owner
11. Agent timeout returns 200 with error instead of 504
12. CORS allows all origins instead of vtf-specific
13. No `/v1/sessions` endpoint
14. No adapter registration mechanism
15. `cxdb_context_id` and `input_tokens` always return stub values
16. `harness` field missing from RoleConfig
17. `SESSIONS_DIR` env var not wired
18. `PI_OTEL_ENDPOINT` missing from Pi env injection

## Design decisions (from design doc, not my interpretation)

These are answers to the questions I asked. The design doc already specifies them:

1. **Ephemeral Pi mode**: Design says `--mode rpc` for both ephemeral and locked. Ephemeral uses `--mode rpc --no-session`. This is the spec — implement it.

2. **Pod cleanup on lock release**: Design says "Pod stays alive (sleep infinity) — available for reconnection." Pods are kept alive after release. Cleanup is separate (idle timeout or manual).

3. **Phase C timing**: Design's dependency graph says Phase C starts after Phase A step 6 (adapter interface). Not blocked on Phase B. But Phase C is out of scope for this rework — it starts after Phase B E2E passes.

4. **Pi session resume**: Design flags `--session-dir` resume as an unverified assumption (spike S3 not done). Rework implements it in B11 with the design's stated fallback: "spawn fresh Pi process, load cxdb summary as context."

---

## Phase A: Complete the Ephemeral Path

Design steps 1-6. Every item either works against real infrastructure or is explicitly excluded.

### A1: Bridge skeleton fixes

| Item | Current | Fix |
|------|---------|-----|
| CORS | `allow_origins=["*"]` | `["https://vtf.dev.viloforge.com", "https://vtf.viloforge.com"]` |
| `/v1/sessions` | Missing | `GET /v1/sessions` proxies to vtf `GET /v1/profile/sessions/`, pass-through auth token, forward query params `project`, `role`, `since` |
| Health endpoint | `active_locked_sessions: 0` hardcoded | Read from `lock_manager`, `ephemeral_semaphore` |
| `SESSIONS_DIR` env var | Not read | Add to bridge config, used by pod process manager for PVC mount path |

**TDD:**
- RED: `test_cors_rejects_unauthorized_origin` — request from `http://evil.com` has no CORS headers
- RED: `test_sessions_endpoint_returns_records` — GET /v1/sessions returns list
- RED: `test_health_reflects_real_counts` — health shows actual ephemeral count during concurrent requests
- GREEN: implement fixes
- E2E: `test_e2e_sessions_endpoint` — send prompt, then GET /v1/sessions, verify record exists

### A2: Auth middleware (DONE — no changes)

### A3: Ephemeral process manager rework

| Item | Current | Fix |
|------|---------|-----|
| Pi mode | `--mode json` (one-shot) | `--mode rpc --no-session` per design. Spawn process, send `{"type": "prompt", "message": "..."}` via stdin, read events from stdout, send `{"type": "shutdown"}` |
| `ManagedProcess` | Not implemented | Implement dataclass per design: `session_id`, `project`, `role`, `user`, `process`, `lock` (asyncio.Lock), `response_queue`, `reader_task`, `started_at`, `last_activity`, `prompt_count` |
| Pi env vars | Not injected | Implement `build_pi_env()` per design: `VF_VTF_MCP_URL`, `VF_VTF_TOKEN`, `VTF_PROJECT_SLUG`, `VF_CXDB_MCP_URL`, `PI_OTEL_ENDPOINT` |
| `input_tokens` | Always 0 | Parse `usage.input` from Pi JSONL `message_end` / `agent_end` events |
| `harness` field | Missing from RoleConfig | Add `harness: str` field (values: `pi-rpc`, `claude-cli`), load from roles.yaml |

**TDD:**
- RED: `test_ephemeral_uses_rpc_mode` — verify Pi command includes `--mode rpc --no-session`
- RED: `test_pi_env_vars_injected` — verify subprocess gets VF_VTF_MCP_URL etc.
- RED: `test_managed_process_dataclass` — ManagedProcess has all required fields
- RED: `test_input_tokens_parsed` — JSONL with `usage.input: 54` → `input_tokens: 54`
- RED: `test_role_has_harness_field` — RoleConfig has `harness` attribute
- GREEN: rewrite PiSession to use RPC protocol, implement ManagedProcess, build_pi_env()
- E2E: `test_e2e_ephemeral_prompt` — real prompt via --mode rpc, real response

### A4: Prompt endpoints rework

| Item | Current | Fix |
|------|---------|-----|
| Rate limiting | Missing | Per-user sliding window: 10 prompts/min. 429 with `Retry-After` header. Track by `user_id` from auth. |
| Timeout | Returns 200 with `is_error=True` | Return HTTP 504 on agent timeout |
| `cxdb_context_id` | Always None | After execution, query cxdb `GET /v1/contexts?label=session:{session_id}` to find context ID |
| Stream `error` events | Missing | Emit `{"type": "error", "message": "..."}` on exception during stream |
| Stream `agent_event` type | Missing | Emit `{"type": "agent_event", "data": {...}}` for every Pi event (rich clients) alongside the simplified text_delta/tool_use events |
| Concurrency race | Check then acquire | Acquire semaphore first (use `try_acquire` pattern or handle inside `async with`) |
| Project required | Skipped if None | Require `project` for all prompts (design always resolves project) |

**TDD:**
- RED: `test_rate_limit_429` — 11th request in 1 min returns 429 with Retry-After
- RED: `test_timeout_returns_504` — mock Pi that never responds → 504
- RED: `test_cxdb_context_id_populated` — mock cxdb lookup returns ID
- RED: `test_stream_error_event` — error during stream → `{"type": "error"}` in output
- RED: `test_stream_agent_event` — raw Pi events emitted as agent_event
- RED: `test_project_required` — prompt without project returns 422
- GREEN: implement rate limiter, fix timeout handling, add cxdb lookup, fix stream events

### A5: Session recording (DEFERRED)

**Gap:** vtf only has `GET /v1/profile/sessions/` (read-only). No POST endpoint exists for creating SessionRecords. The bridge cannot record sessions until vtf adds a write endpoint.

**Dependency:** vtf needs a `POST /v1/profile/sessions/` endpoint (or equivalent) that accepts: project, role, channel, session_id, cxdb_context_id, started_at, ended_at.

**Impact:** No audit trail for bridge interactions until this is resolved. All other Phase A features work without it.

### A6: Adapter interface rework

Design step 6. Protocol + registration mechanism.

| Item | Current | Fix |
|------|---------|-----|
| Protocol | Defined but unused | Keep as-is |
| Registration | Missing | `app.state.adapters: dict[str, ChannelAdapter]`, `register_adapter()` method |
| Wiring | Bridge never calls adapters | After prompt response, call `adapter.send_response()` if `channel` matches a registered adapter |

**TDD:**
- RED: `test_register_adapter` — register adapter, verify stored
- RED: `test_adapter_called_on_response` — mock adapter, verify `send_response` called after prompt
- GREEN: add adapter registry, wire into prompt flow

### Phase A Definition of Done

Deploy to vafi-dev. ALL of these E2E tests must pass against the deployed service:

| E2E Test | Verifies |
|----------|----------|
| `test_e2e_health` | Real counts for ephemeral and locked sessions |
| `test_e2e_auth_enforcement` | 401 bad token, 403 non-member, 200 valid |
| `test_e2e_ephemeral_prompt` | Real Pi --mode rpc prompt + response |
| `test_e2e_streaming_prompt` | NDJSON with session_start, text_delta, agent_event, result |
| `test_e2e_rate_limit` | 429 after 10 requests in 1 minute |
| `test_e2e_sessions_endpoint` | SessionRecord appears after sending a prompt |
| `test_e2e_project_required` | Prompt without project returns 422 |

**Gate:** Phase B does not start until all Phase A E2E tests pass.

---

## Phase B: Locked Path

Design steps 7-10 + recovery (not in original numbering but specified in design's "Process Recovery on Bridge Restart" section).

### B7: Pod process manager

Per design: locked agents run Pi inside agent pods via kubectl exec.

| Item | Implementation |
|------|---------------|
| Pod creation | `kubernetes_asyncio` API: create Pod with `vafi-agent-pi` image, `sleep infinity` command, PVC for `/sessions`, env vars from `build_pi_env()` |
| Pod naming | `architect-{project_slug}-{user}` (sanitized for k8s label rules) |
| Pod ready wait | Poll for `condition=Ready`, timeout 60s |
| kubectl exec | `kubernetes_asyncio` WsApiClient, exec: `pi --mode rpc --session-dir /sessions/{project}/`, attach stdin/stdout |
| JSONL relay | Read stdout line-by-line (async), write stdin for prompt/shutdown commands |
| `ManagedProcess` | Same dataclass as ephemeral but `process` field holds the exec WebSocket connection instead of subprocess |
| Pod kept alive | On lock release: Pi shutdown, exec disconnects, pod stays (`sleep infinity`) |
| Pod reuse | On reconnect: existing pod found by name, new exec opened, Pi resumed with `--session-dir` |

**TDD:**
- RED: `test_pod_created_on_lock_acquire` — mock k8s API, verify pod spec
- RED: `test_exec_opened_after_pod_ready` — mock exec, verify Pi --mode rpc command
- RED: `test_jsonl_relay_sends_prompt` — mock exec stdin, verify JSONL prompt sent
- RED: `test_jsonl_relay_reads_response` — mock exec stdout, verify events parsed
- RED: `test_pod_stays_alive_on_release` — verify pod NOT deleted on release
- RED: `test_pod_reused_on_reconnect` — same pod name found, new exec opened
- GREEN: implement pod_process.py with kubernetes_asyncio
- E2E: `test_e2e_lock_acquire_spawns_pod` — acquire lock, verify pod exists in k8s

### B8: Lock manager with vtf persistence

Replace in-memory dict with vtf AgentLock API.

| Item | Implementation |
|------|---------------|
| Acquire | `POST /v1/locks/` → creates AgentLock, returns lock with pk |
| Release | `DELETE /v1/locks/<pk>/` → deletes AgentLock |
| Reconnect | `POST /v1/locks/` same user → returns existing (vtf handles this) |
| Contention | `POST /v1/locks/` different user → 409 from vtf |
| List | `GET /v1/locks/?project=&role=` with query params |
| Release 403 | Check lock owner before DELETE, return 403 if mismatch |
| SessionRecord on release | `POST /v1/profile/sessions/` with session summary |
| In-memory process table | Keep `ManagedProcess` dict keyed by lock pk, but lock state is in vtf |

**TDD:**
- RED: `test_acquire_calls_vtf_locks_api` — verify POST /v1/locks/
- RED: `test_release_calls_vtf_delete` — verify DELETE /v1/locks/<pk>/
- RED: `test_release_non_owner_returns_403` — different user → 403
- RED: `test_list_locks_with_filters` — project/role query params forwarded
- RED: `test_session_record_on_release` — verify POST to sessions endpoint
- GREEN: rewrite lock_manager.py with httpx calls to vtf
- E2E: `test_e2e_lock_persisted_in_vtf` — acquire, verify in vtf, release, verify gone

### B9: Locked session routing

Wire prompt endpoints to use locked Pi processes.

| Item | Implementation |
|------|---------------|
| `POST /v1/prompt` locked role | Check lock exists (vtf), get ManagedProcess, send prompt via exec stdin, collect response, touch last_activity |
| `POST /v1/prompt/stream` locked role | Same but yield NDJSON events as they arrive from exec stdout |
| No lock → 409 | Locked role without an active lock returns 409 "Acquire a lock first" |
| Conversation continuity | Pi in --mode rpc maintains state — each prompt builds on previous |

**TDD:**
- RED: `test_locked_prompt_routes_to_process` — mock ManagedProcess, verify prompt sent via exec
- RED: `test_locked_prompt_without_lock_returns_409` — no lock → 409
- RED: `test_locked_prompt_touches_last_activity` — verify timestamp updated
- RED: `test_locked_stream_yields_events` — NDJSON events from exec stdout
- GREEN: add locked routing to prompt endpoints
- E2E: `test_e2e_locked_prompt` — acquire, prompt, verify response has continuity
- E2E: `test_e2e_locked_prompt_stream` — acquire, stream, verify NDJSON events

### B10: Timeout + health monitoring

Background tasks on app startup.

| Item | Implementation |
|------|---------------|
| Health check task | Every 60s: for each ManagedProcess, send `{"type": "get_state"}`, verify response. Dead process → cleanup lock in vtf, remove from table, log error. |
| Idle timeout task | Every 60s: check `last_activity` for all locked processes. `> timeout/2` → log warning (future: notify via adapter). `> timeout` → send shutdown, release lock in vtf, cleanup. |
| Health endpoint | `pi_processes` array with: `session_id`, `project`, `role`, `user`, `uptime_seconds`, `prompt_count`, `message_count`, `is_alive` |
| Startup registration | `asyncio.create_task()` in FastAPI `startup` event |

**TDD:**
- RED: `test_health_check_detects_dead_process` — mock dead process, verify cleanup
- RED: `test_idle_timeout_triggers_shutdown` — accelerated timeout, verify release
- RED: `test_idle_timeout_warns_at_half` — accelerated timeout, verify warning logged
- RED: `test_health_returns_pi_processes` — verify array format
- GREEN: implement background tasks
- E2E: `test_e2e_idle_timeout` — acquire with short timeout, wait, verify released

### B11: Recovery on restart

Startup hook in FastAPI `startup` event.

| Item | Implementation |
|------|---------------|
| Query active locks | `GET /v1/locks/` from vtf on startup |
| Check pod exists | `kubernetes_asyncio` get pod by name |
| Resume | Pod exists + session files → open exec, Pi with `--session-dir` |
| Stale cleanup | Pod missing or session corrupt → release lock in vtf, log warning |
| Fallback | Per design: "spawn fresh Pi process, load cxdb summary as context" |

**TDD:**
- RED: `test_recovery_resumes_existing_locks` — mock vtf locks + existing pod → ManagedProcess created
- RED: `test_recovery_cleans_stale_locks` — mock vtf locks + missing pod → lock released
- GREEN: implement startup recovery
- E2E: `test_e2e_recovery` — acquire lock, restart bridge deployment, verify lock still works

### Phase B Definition of Done

Deploy to vafi-dev. ALL of these E2E tests must pass:

| E2E Test | Verifies |
|----------|----------|
| `test_e2e_lock_acquire_spawns_pod` | Pod created in k8s with correct image and env |
| `test_e2e_locked_prompt` | Multi-turn conversation via locked session |
| `test_e2e_locked_prompt_stream` | NDJSON streaming from locked session |
| `test_e2e_lock_contention` | User A locks, user B gets 409, A releases, B succeeds |
| `test_e2e_lock_release_pod_stays` | Pod alive after release (design spec) |
| `test_e2e_lock_reconnect` | Re-acquire same lock, resume conversation |
| `test_e2e_lock_persisted_in_vtf` | AgentLock exists in vtf during lock, gone after release |
| `test_e2e_idle_timeout` | Auto-release after inactivity |
| `test_e2e_health_with_locked` | Health returns real pi_processes array |
| `test_e2e_recovery` | Bridge restart preserves active locks |

**Plus all Phase A E2E tests still pass (no regression).**

**Gate:** Architect REPL does not start until all Phase B E2E tests pass.

---

## Architect REPL

After Phase B gate passes.

CLI that:
1. Acquires lock via `POST /v1/lock` (project + role=architect)
2. Enters prompt loop: read input → `POST /v1/prompt/stream` → render NDJSON events
3. On Ctrl+D/exit: releases lock via `DELETE /v1/lock`
4. On Ctrl+C during prompt: cancel current (future: `POST /v1/prompt` with `abort`)

E2E test: `test_e2e_architect_repl` — acquire, send 2 prompts (verify continuity), release

---

## Phase C: Channels + UI (deferred)

Per design dependency graph, Phase C can start after Phase A step 6. Not in scope for this rework. Includes:
- Web ChatWidget (React component in vtf)
- Slack adapter (Events webhook, ExternalIdentity, slash commands)
- End-to-end: Slack → bridge → Pi → vtf → response

---

## Test Count Expectations

| Phase | Unit Tests | E2E Tests | Cumulative |
|-------|-----------|-----------|-----------|
| A (rework) | ~25 | 7 | 32 |
| B (new) | ~25 | 10 | 67 |
| REPL | 2 | 1 | 70 |
| Existing vafi | 193 | — | 263 |

---

## Verification Checklist (Definition of Done)

Run at the end of Phase B:

**Phase A (all green):**
- [ ] `test_e2e_health` — real counts
- [ ] `test_e2e_auth_enforcement` — 401/403/200
- [ ] `test_e2e_ephemeral_prompt` — real Pi --mode rpc
- [ ] `test_e2e_streaming_prompt` — NDJSON with agent_event type
- [ ] `test_e2e_rate_limit` — 429 after 10/min
- [ ] `test_e2e_sessions_endpoint` — SessionRecord exists
- [ ] `test_e2e_project_required` — 422 without project

**Phase B (all green):**
- [ ] `test_e2e_lock_acquire_spawns_pod` — pod in k8s
- [ ] `test_e2e_locked_prompt` — multi-turn continuity
- [ ] `test_e2e_locked_prompt_stream` — NDJSON from locked session
- [ ] `test_e2e_lock_contention` — 409 then success
- [ ] `test_e2e_lock_release_pod_stays` — pod alive after release
- [ ] `test_e2e_lock_reconnect` — resume conversation
- [ ] `test_e2e_lock_persisted_in_vtf` — vtf AgentLock lifecycle
- [ ] `test_e2e_idle_timeout` — auto-release
- [ ] `test_e2e_health_with_locked` — pi_processes array
- [ ] `test_e2e_recovery` — bridge restart preserves locks

**REPL:**
- [ ] `test_e2e_architect_repl` — acquire, 2 prompts with continuity, release

**Regression:**
- [ ] 193 existing vafi tests pass
- [ ] All bridge unit tests pass (~50)
- [ ] All bridge E2E tests pass (~18)
