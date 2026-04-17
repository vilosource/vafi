# Agent Bridge Service — Implementation Plan

---
status: superseded
superseded_by: agent-bridge-REWORK-PLAN.md
last_verified: 2026-04-17
---

> **⚠️ SUPERSEDED** — This was the original plan. Implementation deviated, and the [Rework Plan](agent-bridge-REWORK-PLAN.md) corrected all deviations. All phases are now complete. Kept for historical reference.

**Date:** 2026-04-02
**Design:** vafi/docs/agent-bridge-service-DESIGN.md
**Repo:** vilosource/vafi (new package: `src/bridge/`)

## Definition of Done

The bridge service is done when a human can send a prompt from a web chat widget, have it routed to a Pi agent (ephemeral or locked), receive a streamed response, and the entire interaction is recorded in vtf with a cxdb trace link.

All acceptance criteria verified by E2E tests running against the deployed bridge in vafi-dev — real HTTP, real vtf-dev, real Pi pods, real cxdb.

### Acceptance Criteria (all must pass via E2E against vafi-dev)

**AC-1: Ephemeral prompt**
A user sends `POST /v1/prompt` with a valid vtf token and a message. The bridge spawns a Pi process, sends the prompt, collects the response, records a SessionRecord in vtf, and returns a BridgeResponse with the agent's text, token counts, and session ID. The Pi process terminates after the response.

**AC-2: Streaming prompt**
A user sends `POST /v1/prompt/stream`. The bridge returns an NDJSON stream with `session_start`, `text_delta`, `tool_use`, and `result` events. The stream completes and the connection closes cleanly.

**AC-3: Lock acquire, prompt, release**
A user acquires a lock (`POST /v1/lock`) for a project+role. The bridge spawns a persistent Pi process in an agent pod. The user sends prompts routed to that locked session. The user releases the lock (`DELETE /v1/lock`). The Pi process terminates. The lock record is deleted in vtf. A SessionRecord exists.

**AC-4: Auth enforcement**
An invalid token returns 401. A valid token for a user without project membership returns 403. A valid token with membership succeeds.

**AC-5: Concurrency and rate limiting**
More than `MAX_CONCURRENT_EPHEMERAL` (default 5) simultaneous requests return 503. More than 10 requests/min from one user return 429 with `Retry-After`.

**AC-6: Lock contention**
User A holds a lock. User B tries to acquire the same lock. User B gets 409 with holder info. User A releases. User B retries and succeeds.

**AC-7: Health endpoint**
`GET /v1/health` returns active session counts, Pi process state, and is_alive status.

**AC-8: Role configuration**
Bridge loads `roles.yaml` and correctly routes locked vs ephemeral roles, applies model/thinking/methodology per role.

**AC-9: Idle timeout**
A locked session with no activity for `idle_timeout_hours` triggers graceful shutdown, lock release, and SessionRecord finalization.

**AC-10: No regression**
All existing vafi tests (193+) still pass. Bridge code does not break controller/cxdb.

## Testing Strategy

### Two layers

| Layer | Purpose | When it runs | What it hits |
|-------|---------|-------------|-------------|
| **Unit tests** | Fast feedback during TDD. Test individual functions, parsing, routing logic. All dependencies mocked. | Every commit, locally. `pytest tests/bridge/` | Nothing external |
| **E2E tests** | Acceptance gate. Prove the feature works against real infrastructure. | After deploy to vafi-dev. `pytest tests/bridge/e2e/` | Real bridge service + vtf-dev + Pi pods + cxdb |

No integration test layer. The gap between unit tests and E2E is intentional — unit tests catch logic bugs fast, E2E tests catch deployment/wiring bugs against real infrastructure. An in-between layer that calls the app in-process with real vtf is neither fast nor realistic.

### E2E test infrastructure

E2E tests run against the deployed bridge in `vafi-dev`:

```
Developer laptop                           vafi-dev (k8s)
┌─────────────────┐                 ┌──────────────────────────┐
│ pytest           │   HTTP          │ vafi-bridge (deployed)   │
│ tests/bridge/e2e │ ──────────────> │   ↓                     │
│                  │                 │ vtf-dev API              │
│                  │                 │ Pi agent pods            │
│                  │                 │ cxdb                     │
└─────────────────┘                 └──────────────────────────┘
```

E2E tests use a real vtf service account token (created via `create_service_account` management command, already available). The bridge URL is configurable via `BRIDGE_URL` env var (default: `https://bridge.dev.viloforge.com` or port-forward).

### Deploy cadence

Each phase ends with: unit tests pass → build image → deploy to vafi-dev → run applicable E2E tests. The E2E tests accumulate — Phase 4 runs the Phase 1 + Phase 4 E2E tests, etc.

## TDD Approach

Every step follows RED-GREEN-REFACTOR:

1. **RED**: Write the test first. Test must fail because the code doesn't exist.
2. **GREEN**: Write the minimum code to make the test pass.
3. **REFACTOR**: Clean up. Tests still pass.

## Phase 0: Deployable Skeleton

**Goal:** Empty FastAPI app, Dockerfile, k8s manifest, deployed to vafi-dev. Health endpoint returns 200.

This phase exists so that every subsequent phase can deploy and E2E test incrementally.

**Steps:**
1. Create `src/bridge/__init__.py`, `src/bridge/app.py` with FastAPI + health endpoint
2. Create `images/bridge/Dockerfile` (Python slim, installs bridge package)
3. Create k8s manifest or Helm values for `vafi-bridge` deployment in vafi-dev
4. Build, push, deploy
5. Verify: `curl https://bridge.dev.viloforge.com/v1/health` returns 200

**Unit tests:** `test_health_returns_ok`

**E2E tests after deploy:** `test_e2e_health` — health endpoint responds from deployed service

**Done when:** Bridge pod is Running in vafi-dev, health returns 200 via Traefik ingress.

---

### Phase 1: Auth Middleware

**Goal:** Token validation against vtf, project membership check.

**TDD sequence:**

1. RED: `test_auth_rejects_missing_token` — no Authorization header → 401
2. RED: `test_auth_rejects_invalid_token` — bad token → 401
3. RED: `test_auth_accepts_valid_token` — valid token → request proceeds, user info in context
4. RED: `test_auth_rejects_non_member` — valid token, user not in project → 403
5. GREEN: `src/bridge/auth.py` — middleware calling vtf `GET /v1/auth/validate/`

**Unit tests:** 4 (mocked vtf responses)

**Deploy + E2E:** `test_e2e_auth_enforcement` — real tokens against deployed bridge

**Done when:** AC-4 passes against vafi-dev.

---

### Phase 2: Role Configuration

**Goal:** Bridge loads roles.yaml, routes locked/ephemeral correctly.

**TDD sequence:**

1. RED: `test_load_roles_from_yaml` — loads config, returns typed RoleConfig objects
2. RED: `test_role_session_type` — architect=locked, assistant=ephemeral
3. RED: `test_role_model_config` — role has model, thinking_level, methodology
4. RED: `test_unknown_role_returns_400` — unknown role → 400
5. GREEN: `src/bridge/roles.py` — dataclass + YAML loader

**Unit tests:** 4

**Done when:** AC-8 unit tests pass.

---

### Phase 3: Ephemeral Process Manager

**Goal:** Spawn Pi, send prompt, collect response, terminate.

**TDD sequence:**

1. RED: `test_spawn_pi_process` — spawns Pi subprocess, is alive
2. RED: `test_send_prompt_returns_response` — sends JSONL prompt, gets agent_end
3. RED: `test_process_terminates_after_response` — Pi exits after shutdown
4. RED: `test_spawn_timeout` — Pi doesn't start → error
5. RED: `test_prompt_timeout` — Pi doesn't respond → error
6. RED: `test_parse_pi_events` — JSONL stream → typed event objects
7. GREEN: `src/bridge/pi_session.py`, `src/bridge/pi_events.py`

**Unit tests:** 6 (mocked subprocess)

**Done when:** PiSession passes all unit tests.

---

### Phase 4: Prompt Endpoint (Ephemeral)

**Goal:** `/v1/prompt` works for ephemeral roles.

**TDD sequence:**

1. RED: `test_prompt_returns_bridge_response` — valid request → BridgeResponse
2. RED: `test_prompt_spawns_and_terminates` — ephemeral role spawns then kills Pi
3. RED: `test_prompt_records_session` — SessionRecord created in vtf
4. RED: `test_prompt_concurrent_limit` — 6th request → 503
5. RED: `test_prompt_rate_limit` — 11th request/min → 429
6. GREEN: `src/bridge/endpoints.py` — prompt endpoint wiring

**Unit tests:** 5

**Deploy + E2E:** `test_e2e_ephemeral_prompt` — real prompt to deployed bridge, verify response and SessionRecord in vtf

**Done when:** AC-1 and AC-5 pass against vafi-dev.

---

### Phase 5: Streaming Endpoint

**Goal:** `/v1/prompt/stream` returns NDJSON.

**TDD sequence:**

1. RED: `test_stream_content_type` — response is application/x-ndjson
2. RED: `test_stream_event_order` — session_start → text_deltas → result
3. RED: `test_stream_tool_use_events` — tool_use events present
4. RED: `test_stream_error_event` — error → error event in stream
5. GREEN: Streaming response, NDJSON serializer, Pi event → bridge event translation

**Unit tests:** 4

**Deploy + E2E:** `test_e2e_streaming_prompt` — consume full NDJSON stream from deployed bridge

**Done when:** AC-2 passes against vafi-dev.

---

### Phase 6: Lock Manager + Locked Sessions

**Goal:** Lock acquire/release via vtf AgentLock. Persistent Pi in pods via kubectl exec.

**TDD sequence:**

1. RED: `test_acquire_lock_creates_agent_lock` — lock → AgentLock record in vtf
2. RED: `test_acquire_lock_spawns_pod_pi` — lock → kubectl exec Pi in agent pod
3. RED: `test_prompt_routes_to_locked_session` — prompt for locked role → persistent Pi
4. RED: `test_release_lock_stops_pi` — release → shutdown Pi, delete lock
5. RED: `test_lock_contention_409` — second user → 409
6. RED: `test_reconnect_existing_lock` — same user → existing session
7. RED: `test_lock_session_record` — release creates SessionRecord
8. GREEN: `src/bridge/lock_manager.py`, `src/bridge/pod_process.py`

**Unit tests:** 7

**Deploy + E2E:**
- `test_e2e_lock_lifecycle` — acquire → prompt → release, all real
- `test_e2e_lock_contention` — two users, 409 then success

**Done when:** AC-3 and AC-6 pass against vafi-dev.

---

### Phase 7: Idle Timeout

**Goal:** Locked sessions auto-terminate on inactivity.

**TDD sequence:**

1. RED: `test_idle_timeout_triggers_shutdown` — idle past timeout → Pi killed
2. RED: `test_idle_timeout_releases_lock` — lock deleted after timeout
3. RED: `test_activity_resets_timeout` — prompt resets timer
4. GREEN: Background timeout checker in lock manager

**Unit tests:** 3 (accelerated timer)

**Deploy + E2E:** `test_e2e_idle_timeout` — lock, wait, verify auto-released (may need short timeout config for test)

**Done when:** AC-9 passes.

---

### Phase 8: Channel Adapter Interface

**Goal:** Protocol for channel adapters. Slack adapter stubbed.

**TDD sequence:**

1. RED: `test_adapter_protocol` — ChannelAdapter has required methods
2. RED: `test_adapter_registration` — bridge accepts adapters
3. GREEN: `src/bridge/adapters/protocol.py`

**Unit tests:** 2

**Done when:** Adapter interface exists, Slack adapter is a documented TODO.

---

### Phase 9: Final E2E Suite + Regression

**Goal:** All ACs verified, all tests pass, clean deploy.

**Steps:**
1. Run full E2E suite against vafi-dev — all AC tests pass
2. Run `python -m pytest tests/` — all 240+ tests pass (193 existing + ~48 bridge)
3. Tag images with commit hash, push to harbor
4. Update bridge design doc with deployment details

**Verification checklist:**

- [ ] AC-1: `test_e2e_ephemeral_prompt` passes
- [ ] AC-2: `test_e2e_streaming_prompt` passes
- [ ] AC-3: `test_e2e_lock_lifecycle` passes
- [ ] AC-4: `test_e2e_auth_enforcement` passes
- [ ] AC-5: `test_prompt_concurrent_limit` + `test_prompt_rate_limit` pass
- [ ] AC-6: `test_e2e_lock_contention` passes
- [ ] AC-7: `test_e2e_health` passes
- [ ] AC-8: Role config unit tests pass
- [ ] AC-9: `test_e2e_idle_timeout` passes
- [ ] AC-10: 193 existing tests still pass
- [ ] Bridge image tagged and pushed
- [ ] Bridge running in vafi-dev
- [ ] Docs updated

## Test Count Expectations

| Phase | Unit | E2E | Cumulative |
|-------|------|-----|-----------|
| 0: Skeleton | 1 | 1 | 2 |
| 1: Auth | 4 | 1 | 7 |
| 2: Roles | 4 | 0 | 11 |
| 3: Pi Process | 6 | 0 | 17 |
| 4: Prompt | 5 | 1 | 23 |
| 5: Streaming | 4 | 1 | 28 |
| 6: Locks | 7 | 2 | 37 |
| 7: Timeout | 3 | 1 | 41 |
| 8: Adapters | 2 | 0 | 43 |
| 9: Final | 0 | 0 | 43 + 193 existing = **236+** |

## Deploy Pipeline Per Phase

```
Write failing test (RED)
    ↓
Write code to pass (GREEN)
    ↓
Refactor, unit tests pass
    ↓
Build image: docker build -f images/bridge/Dockerfile -t harbor.viloforge.com/vafi/vafi-bridge:$HASH .
    ↓
Push: docker push harbor.viloforge.com/vafi/vafi-bridge:$HASH
    ↓
Deploy: kubectl set image deployment/vafi-bridge -n vafi-dev vafi-bridge=harbor.viloforge.com/vafi/vafi-bridge:$HASH
    ↓
Run E2E tests: BRIDGE_URL=https://bridge.dev.viloforge.com pytest tests/bridge/e2e/ -v
    ↓
Phase done when: unit tests + E2E tests pass
```
