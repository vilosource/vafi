# Context Hydration Implementation Audit

**Date:** 2026-04-14
**Scope:** All changes from the context hydration + PVC implementation session
**Status:** Deployed to dev, functional but flaky

## Files Changed

| File | Repo | Change |
|------|------|--------|
| `src/bridge/pod_process.py` | vafi | PVC volumes, inline Pi config, hydration in exec, initialize() revert |
| `src/bridge/pi_session.py` | vafi | Added `vtf_api_url` param to `build_pi_env()` |
| `src/bridge/app.py` | vafi | Pass `vtf_api_url`, `sessions_pvc` config |
| `images/agent/hydrate_context.py` | vafi | NEW: standalone hydration script |
| `images/agent/entrypoint.sh` | vafi | Hydration block for Claude harness path |
| `images/agent/Dockerfile` | vafi | Copy hydrate_context.py into image |
| `methodologies/architect.md` | vafi | Reference PROJECT_CONTEXT.md in Step 0 |
| `web/src/App.tsx` | vtaskforge | Token auto-provisioning in AuthProvider |
| `web/src/pages/ProjectDashboard.tsx` | vtaskforge | Fixed: pass project.id not project.name |
| `web/src/pages/Home.tsx` | vtaskforge | Fixed: pass project.id not project.name |

---

## Issue Registry

### CRITICAL

#### C1: Shell injection via repo_url

**Files:** `hydrate_context.py:189-192`, `entrypoint.sh:157-166`, `pod_process.py` exec command
**Description:** Hydration script writes `repo_url` from VTF API response to `/tmp/repo_url`. The exec command and entrypoint.sh read it with `$(cat /tmp/repo_url)` inside a bash string. If `repo_url` contains shell metacharacters (backticks, `$()`, semicolons), they execute as the agent user.
**Impact:** Remote code execution if a project's `repo_url` is malicious.
**Fix:** Validate repo_url format (must match `^(https?://|git@)[^\s;|&$]+$`) before writing. Use `--` in git clone to prevent flag injection.

#### C2: Inline Pi config as Python-in-bash string

**Files:** `pod_process.py:117-140`
**Description:** Pi configuration (models.json, mcp.json, settings.json) is written via a Python one-liner embedded in a bash `-c` string. This is ~500 chars of Python stuffed into a shell command. Any quoting issue breaks the entire exec command silently. Impossible to test in isolation.
**Impact:** Fragile — broke multiple times during implementation. Untestable. Hard to maintain.
**Fix:** Extract to a standalone script (e.g., `/opt/vf-agent/pi-config.py`) shipped in the agent image, invoked as `python3 /opt/vf-agent/pi-config.py`. Same pattern as `hydrate_context.py`.

#### C3: Duplicated Pi config logic

**Files:** `entrypoint.sh:22-54` AND `pod_process.py:117-140`
**Description:** Identical Pi config setup (models.json + mcp.json) exists in two places: the entrypoint (for Helm-deployed pods) and the exec command (for bridge-created pods). If Pi config format changes, both must be updated.
**Impact:** Config drift between the two paths.
**Fix:** Single shared script used by both paths.

---

### HIGH

#### H1: Stale lock on pod crash

**Files:** `app.py:418-425`, `lock_manager.py`
**Description:** When a pod dies unexpectedly (exit 137, deleted, OOM), the bridge's lock release code never runs. The VTF lock record persists. Next session attempt finds the stale lock and shows "Session held by vafi-agent."
**Impact:** User cannot open new sessions without manual lock cleanup.
**Fix:** Bridge should detect WebSocket close in the reader loop and release the VTF lock. Also add a lock TTL/expiry mechanism.

#### H2: No WebSocket liveness check

**Files:** `pod_process.py:PodSession`
**Description:** `PodSession` holds a `PodExecConnection` (WebSocket). If the connection dies (pod restart, network issue), the bridge doesn't detect it until the next prompt attempt fails with "Cannot write to closing transport."
**Impact:** User sends message, gets cryptic error. Must close/reopen chat.
**Fix:** Add health check in `send_prompt()`/`stream_prompt()` — verify WebSocket is alive before writing. Reader loop EOF should trigger lock release.

#### H3: VTF locks endpoint ignores project filter

**Files:** vtaskforge `prefs/views.py` (AgentLock viewset)
**Description:** `GET /v1/locks/?project=X` returns ALL locks regardless of the project query parameter. A lock for project "python-calc" blocks project "-VTDrP9URo0zuAxCAitOA".
**Impact:** Any stale lock blocks all projects.
**Fix:** Fix the VTF locks viewset to filter by project_id.

#### H4: VTF API 404 on NanoIDs with leading dash

**Files:** vtaskforge URL routing
**Description:** `GET /v1/projects/-VTDrP9URo0zuAxCAitOA/` returns 404. The leading `-` in the NanoID may be interpreted by Django's URL router as a flag or invalid path segment.
**Impact:** Direct project lookup always fails for IDs starting with `-`. Hydration falls back to search (which may return wrong project).
**Fix:** Investigate Django URL pattern — may need explicit regex or path converter that allows `-` prefix.

#### H5: Weak project resolution fallback

**Files:** `hydrate_context.py:149-169`
**Description:** When direct lookup fails (404), script searches by name and takes the first result. If the service token doesn't have access to the target project (membership issue), search returns a different project. No disambiguation or user confirmation.
**Impact:** Architect gets context from the WRONG project (we saw pi-e2e-test instead of python-calc).
**Fix:** Service token must have access to all projects. Or pass user's token for hydration. Fail loudly on ambiguous match.

#### H6: Service token missing project membership

**Files:** Bridge deployment config, VTF project membership
**Description:** The bridge's `VTF_API_TOKEN` belongs to `vafi-agent` user which doesn't have membership in all projects. API calls filtered by membership return wrong results.
**Impact:** Hydration resolves wrong project.
**Fix:** Add vafi-agent to all projects as a service member, or use a staff token that bypasses membership checks.

#### H7: Duplicated Pi init handshake (3 copies)

**Files:** `pi_session.py:162-190`, `pi_session.py:263-285`, `pod_process.py:341-362`
**Description:** Three copies of "send get_state, wait for response, extract session_id" logic.
**Impact:** DRY violation. Bug fix in one copy doesn't propagate to others.
**Fix:** Extract to shared async function `async def initialize_pi_session(ws) -> str`.

#### H8: God function create_app()

**Files:** `app.py:107-581`
**Description:** `create_app()` is 475 lines containing: config loading, manager creation, startup hooks, 10+ route handlers, and stream formatters.
**Impact:** Untestable, hard to navigate, violates SRP.
**Fix:** Split into route modules: `lock_routes.py`, `prompt_routes.py`, `health_routes.py`.

#### H9: Token provisioning race condition

**Files:** `App.tsx:92-111`
**Description:** Token fetch from `/v1/auth/token/` is async and non-blocking. Chat widget can open before token is stored in localStorage. `bridge.ts:getToken()` throws if token missing.
**Impact:** Intermittent "No auth token available" on fast page loads.
**Fix:** Either await the token fetch, or check token availability before allowing widget open.

---

### MEDIUM

#### M1: Silent error swallowing in hydrate_context.py

**Files:** `hydrate_context.py:34-42`
**Description:** `fetch()` returns `None` for ALL errors (404, 502, auth, timeout). Caller cannot distinguish failure modes.
**Fix:** Return structured result with error info. Log error type.

#### M2: entrypoint.sh `|| true` hides all failures

**Files:** `entrypoint.sh:155, 166`
**Description:** Both hydration and git clone use `|| true`, making all failures invisible.
**Fix:** Log errors before `|| true`. Check for critical failures (e.g., no workdir created).

#### M3: No retry logic in hydration

**Files:** `hydrate_context.py:34-42`
**Description:** Single 5s timeout, no retry. VTF API might be slow on startup.
**Fix:** Add 1 retry with short backoff for transient errors (502, timeout).

#### M4: Widget title shows NanoID

**Files:** `ChatWidgetContext.tsx:48`
**Description:** Chat widget stores `project: string | null` — only the ID. Title bar shows "Chat — -VTDrP9URo0zuAxCAitOA" instead of project name.
**Fix:** Pass `{id, name}` object through chat widget state.

#### M5: Home.tsx 'default' fallback

**Files:** `Home.tsx:419`
**Description:** When no projects exist, passes `'default'` as project to chat widget. API returns 403.
**Fix:** Disable button when no projects exist.

#### M6: No input validation on messages

**Files:** `app.py:288, 474`
**Description:** No message length limit. Attacker can send 1GB message causing OOM.
**Fix:** Add max message length validation (e.g., 100KB).

#### M7: Lock manager is in-memory only

**Files:** `app.py:137`
**Description:** Lock state lives in bridge process memory. Multiple bridge replicas = separate lock state = conflicts.
**Fix:** Already uses VTF as lock store, but in-memory cache is source of truth. Should always query VTF.

#### M8: Hardcoded magic numbers

**Files:** `pod_process.py:189` (60s wait), `pi_session.py:27` (120s timeout), `hydrate_context.py:22` (5s timeout)
**Description:** Timeouts hardcoded without named constants.
**Fix:** Define as constants at module level.

#### M9: k8s exec framing duplicated

**Files:** `pod_process.py:254-276`
**Description:** Binary vs TEXT frame handling has duplicated channel parsing logic.
**Fix:** Extract `_parse_frame()` method.

#### M10: PodExecConnection uses `Any` types

**Files:** `pod_process.py:230-233`
**Description:** `ws: Any, ws_ctx: Any, ws_client: Any` — no type safety.
**Fix:** Add proper type annotations.

---

### LOW

#### L1: Hardcoded CORS origins in app.py
#### L2: No layer optimization in Dockerfile
#### L3: `--break-system-packages` in Dockerfile
#### L4: Inconsistent error recovery patterns in frontend
#### L5: No jitter/backoff on frontend token fetch
#### L6: Hardcoded paths in entrypoint.sh (/tmp/repo_url, /tmp/ready, etc.)
