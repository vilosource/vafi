# Phase 8 — Session Continuity Implementation Plan

Status: **approved by user 2026-04-19, ready to execute**
Spike: [phase-8-session-continuity-SPIKE.md](phase-8-session-continuity-SPIKE.md)
Definition of done (per project convention): **deployed + tested + confirmed**

---

## Decision summary

- **Storage:** Pi's JSONL files on PVC (`console-sessions`), at `/sessions/{lowercased-project-id}/*.jsonl`. cxdb-for-architect is deferred — `cxtx-pi` capture only records wrapper start/end events, not conversation content (verified in the spike).
- **Coupling:** Architect is hardcoded to Pi. Interactive fleet uses harness-specific loaders; autonomous fleet (executor/judge) is unchanged and keeps its own controller+cxtx path.
- **Capture:** Pi already writes the JSONL for free. No new capture mechanism needed.
- **Load + inject:** A new `build_prior_context.py` script runs inside the pod on lock-acquire. It scans `/sessions/{slug}/` for prior JSONL files, extracts the most recent user/assistant exchanges, writes a markdown summary to `/tmp/prior-context.md`, and the existing exec command adds a second `--append-system-prompt` flag pointing at that file.
- **Scope:** single-user, single-project, last-session(s) continuity, explicit-release session boundary. Multi-user (Q2), multi-session aggregation policy (Q1), failure modes (Q3), privacy opt-out (Q6) are out of scope for v1.

---

## Architecture

```
kubectl exec (locked lock acquire)
   │
   ▼
┌──────────────────────────────────────────────────────────────┐
│ pi-agent container                                           │
│                                                              │
│  bash -c '                                                   │
│    pi_config + hydrate_context (existing)                    │
│    python3 /opt/vf-agent/build_prior_context.py \            │
│      --session-dir /sessions/{slug}/ \                       │
│      --output /tmp/prior-context.md                          │
│      (writes file only if prior sessions found)              │
│                                                              │
│    PRIOR_FLAG="" ; [ -s /tmp/prior-context.md ] && \         │
│      PRIOR_FLAG="--append-system-prompt /tmp/prior-context.md"│
│                                                              │
│    exec pi --mode rpc --session-dir /sessions/{slug}/ \      │
│      --provider anthropic --model ... \                      │
│      --append-system-prompt /opt/vf-agent/methodologies/architect.md \
│      $PRIOR_FLAG \                                           │
│      --thinking medium                                       │
│  '                                                           │
└──────────────────────────────────────────────────────────────┘
```

Key point: the bridge's `build_exec_command` gains one preamble step + one conditional flag. Nothing else in the bridge changes.

---

## File layout

```
vafi/
├── images/agent/
│   └── build_prior_context.py                              [NEW]
├── images/agent/Dockerfile                                 [MODIFIED — COPY build_prior_context.py]
├── src/bridge/
│   └── pod_process.py                                      [MODIFIED — build_exec_command]
├── tests/
│   ├── agent/
│   │   └── test_build_prior_context.py                     [NEW — unit, fast]
│   ├── bridge/
│   │   └── test_pod_process.py                             [MODIFIED — exec command shape]
│   └── integration/
│       └── test_session_continuity.py                      [NEW — integration, deployed]
├── tests/fixtures/
│   └── pi_jsonl/                                           [NEW — fixture JSONL files]
│       ├── single-turn.jsonl                              
│       ├── multi-turn.jsonl                               
│       ├── empty.jsonl                                    
│       └── malformed.jsonl                                
└── docs/bridge/
    ├── phase-8-session-continuity-SPIKE.md                [UPDATE — append final-status entry]
    └── phase-8-session-continuity-PLAN.md                 [this doc]
```

---

## Phase 1 finding — Pi honors only the LAST `--append-system-prompt`

Verified 2026-04-19. When two `--append-system-prompt` flags are passed, the second overrides the first. Single-flag baseline works; double-flag loses the first file's content.

**Plan pivot:** the script now produces a **single merged system-prompt file** containing the methodology *and* (optionally) prior context. Bridge passes exactly one `--append-system-prompt` flag to Pi.

## `build_prior_context.py` spec (revised)

**Purpose:** Build the initial system-prompt file for Pi: always includes the role methodology; appends prior-session context when present.

**CLI:**
```
python3 build_prior_context.py \
  --session-dir <path> \
  --methodology <path> \
  --output <path> \
  [--max-bytes N] \
  [--max-prompts N] \
  [--max-sessions N]
```

**Defaults:**
- `--max-bytes`: 4096 — cap the *prior-context section* at 4KB (methodology is always included in full)
- `--max-prompts`: 20 — most recent user/assistant pairs across sessions
- `--max-sessions`: 5 — scan the N most recent JSONL files

**Behavior:**
1. Read `--methodology` file. If missing, exit 1 (error — methodology is required).
2. If `--session-dir` doesn't exist or has no `*.jsonl` files → write methodology verbatim to `--output` and exit 0.
3. Sort JSONL files by mtime descending; take first `--max-sessions`.
4. Parse each file line-by-line. Extract `message` events with role=`user` or role=`assistant`; pull `content[*].text`. Skip malformed lines silently.
5. Pair user→assistant in chronological order. Discard orphans.
6. Keep the last `--max-prompts` pairs across all scanned sessions, chronological order.
7. Build prior-context markdown section:
   ```
   ---

   # Continuation from previous sessions

   This is a continuation of a prior conversation on this project. Do not
   summarize this context back to the user unless asked. Treat it as
   established shared knowledge.

   ## User (2026-04-19T08:30:00Z)
   <user text>

   ## Assistant
   <assistant text>
   
   ... (repeat) ...
   ```
8. If prior-context section exceeds `--max-bytes`, trim oldest pairs until it fits. If a single pair exceeds cap, trim assistant text only.
9. Write `<methodology_content>\n\n<prior_context_section>` to `--output`.

**Exit codes:** 0 on success; 1 on missing methodology or unexpected error.

**Fallback behavior in bash:** if the script fails for any reason, the bridge's exec command falls back to copying the methodology file to `/tmp/initial-context.md` directly — ensures Pi always receives at least the methodology.

---

## `pod_process.build_exec_command` change

Current (simplified):
```python
cmd = (
    f"python3 /opt/vf-agent/pi_config.py 1>&2; "
    f"python3 /opt/vf-agent/hydrate_context.py --repo-url-only 1>&2 || true; "
    f"mkdir -p {session_dir} && if [...]; then git clone ...; fi; "
    f"mkdir -p {repo_dir} && python3 /opt/vf-agent/hydrate_context.py {repo_dir} 1>&2 || true; "
    f"cd {repo_dir} && exec pi --mode rpc --session-dir {session_dir} "
    f"--provider {provider} --model {model} "
    f"--append-system-prompt /opt/vf-agent/methodologies/{role}.md "
    f"--thinking {thinking_level}"
)
```

Modified (single merged file, fallback to methodology-only on script failure):
```python
methodology_file = f"/opt/vf-agent/methodologies/{role}.md"
initial_context_file = "/tmp/initial-context.md"

cmd = (
    f"python3 /opt/vf-agent/pi_config.py 1>&2; "
    f"python3 /opt/vf-agent/hydrate_context.py --repo-url-only 1>&2 || true; "
    f"mkdir -p {session_dir} && if [...]; then git clone ...; fi; "
    f"mkdir -p {repo_dir} && python3 /opt/vf-agent/hydrate_context.py {repo_dir} 1>&2 || true; "
    f"python3 /opt/vf-agent/build_prior_context.py "
    f"  --session-dir {session_dir} "
    f"  --methodology {methodology_file} "
    f"  --output {initial_context_file} 1>&2 || "
    f"  cp {methodology_file} {initial_context_file}; "
    f"cd {repo_dir} && exec pi --mode rpc --session-dir {session_dir} "
    f"--provider {provider} --model {model} "
    f"--append-system-prompt {initial_context_file} "
    f"--thinking {thinking_level}"
)
```

Single `--append-system-prompt` flag (required — Phase 1 showed Pi only honors the last flag). `/tmp/initial-context.md` always contains methodology at minimum. If prior sessions exist, appended below the methodology.

---

## Phased execution with gates

Each phase has a gate; do not proceed to the next until the gate passes.

### Phase 1 — Verify Pi accepts multiple `--append-system-prompt` flags
Small precondition check in the spike pod: run Pi with two `--append-system-prompt` files and confirm both appear in the system prompt (e.g., plant distinctive text in each, ask agent to repeat both).

**Gate:** Both appear in behavior, OR we discover Pi only respects one (→ plan pivots: script also merges methodology and prior-context into a single file).

### Phase 2 — `build_prior_context.py` with unit tests (TDD)
1. Create `tests/fixtures/pi_jsonl/` fixtures:
   - `single-turn.jsonl` (one user + one assistant) — copy a small excerpt of the real spike JSONL (`/workspace/vafi/tests/fixtures/cxdb/` has the baseline data we can adapt)
   - `multi-turn.jsonl` (3 user + 3 assistant)
   - `empty.jsonl` (0 bytes)
   - `malformed.jsonl` (some invalid lines mixed with valid)
2. Write `tests/agent/test_build_prior_context.py` with cases:
   - No session dir → exits 0, writes nothing
   - Empty dir → exits 0, writes nothing
   - Single session → output has user+assistant text, markdown shape correct
   - Multi-session (fixtures' mtimes set explicitly) → chronological order preserved
   - Over byte cap → truncates oldest pairs, stays under cap
   - Malformed JSONL → skips bad lines, still produces valid output from good lines
3. Write `images/agent/build_prior_context.py` until tests pass.

**Gate:** All unit tests pass. No dependency on deployed infra.

### Phase 3 — Bridge `pod_process.py` change + unit tests
1. Update `build_exec_command` to include the new preamble step + conditional `$PRIOR_FLAG`.
2. Update `tests/bridge/test_pod_process.py`:
   - Assert the constructed command string contains `build_prior_context.py` call
   - Assert it contains `[ -s /tmp/prior-context.md ] && PRIOR_FLAG=` conditional
   - Assert the pi invocation includes `$PRIOR_FLAG` between the methodology flag and `--thinking`
3. Run the existing bridge test suite to check for regressions.

**Gate:** All bridge tests pass. No existing test broken.

### Phase 4 — Image build
1. Add `COPY images/agent/build_prior_context.py /opt/vf-agent/build_prior_context.py` to `images/agent/Dockerfile` (both `vafi-agent` and `vafi-agent-pi` build from the same Dockerfile, so one edit covers both).
2. Run `scripts/build-images.sh` locally to confirm the Dockerfile change builds.
3. Verify the script lands at `/opt/vf-agent/build_prior_context.py` with executable perms.

**Gate:** Both `vafi-agent` and `vafi-agent-pi` images build clean. Script is in the correct path. Image builds push-ready.

### Phase 5 — Deploy to `vafi-dev`
1. Tag images with commit hash (`HARBOR/vafi/vafi-agent-pi:<sha>` and `HARBOR/vafi/vafi-bridge:<sha>`).
2. Push to harbor.
3. Update `vafi-deploy` (or use `kubectl set image`) for:
   - `vafi-bridge` deployment → pick up new bridge with modified `pod_process.py`
   - The pi-agent image is ref'd by env var `AGENT_PI_IMAGE` on the bridge — update that env too.
4. Wait for rollout (`kubectl rollout status`).
5. Verify bridge health: `GET /v1/health` returns 200.

**Gate:** Bridge + pi-agent images deployed and healthy. Existing chat widget E2E still passes.

### Phase 6 — Integration test: Test A (nonce plumbing)
Create `tests/integration/test_session_continuity.py` with:
1. Helper: creates UUID-suffixed vtf project, acquires architect lock, sends prompts, releases, cleans up.
2. **Test A (nonce):**
   - Session 1: send `test-a-plumbing-session1.txt` with `{NONCE}` = fresh UUID
   - Release lock, delete pod (hard release)
   - Session 2: send `test-a-plumbing-session2.txt`, assert response contains the nonce
3. Mark as `@pytest.mark.integration`; runs on demand, not in default `make test`.

**Gate:** Test A passes against `vafi-dev`. The bridge reads the JSONL, the summary script writes a file with the nonce, Pi ingests it via `--append-system-prompt`, and Pi recalls the nonce. Plumbing confirmed.

### Phase 7 — Integration test: Test B (task continuation)
Add **Test B** to the same file:
- Session 1: send `test-b-task-session1.txt` (design `BankAccount`)
- Release, delete pod
- Session 2: send `test-b-task-session2.txt` (add `transaction-history`)
- Assert response contains `BankAccount`, `deposit`, `withdraw` symbols from session 1

**Gate:** Test B passes. Quality of continuity confirmed, not just plumbing.

### Phase 8 — Commit, push, update status docs
1. Commit vafi changes on a branch (`phase-8-session-continuity`).
2. Push.
3. Update `vafi/docs/STATUS.md`:
   - Move Phase 8 to "Recently Completed"
   - Move Phase 9 to "Active Work" (unchanged)
4. Update `phase-8-session-continuity-SPIKE.md` status log with "implementation complete" entry.
5. Cleanup: delete spike project `spike-phase8-dbf69a25` / `spike-cxtx-stream-6e682cc5` from vtf, delete lingering pods.

**Gate:** Clean git state, all tests green, STATUS.md reflects reality, no spike artifacts left behind.

---

## Accepted risks / explicit non-goals

- **Token-window blow-up over time.** If a project accumulates many long sessions, the `--max-bytes 4096` cap will drop the oldest. We don't do smart summarization — just most-recent-wins. Good enough for v1.
- **PVC loss = continuity loss.** If `console-sessions` PVC is ever deleted, all prior histories vanish. Acceptable — it's dev-cluster storage.
- **Project-id casing collisions.** Two vtf projects whose IDs only differ by case collapse to the same `/sessions/{lowercased}/` dir (already an existing concern; not new).
- **No cross-cluster continuity.** Session history doesn't replicate. Acceptable for v1.
- **No user opt-out UI.** "Start fresh" would require Phase 9 UX work.
- **Multi-user same-project.** If user A and user B both use the architect role on the same project (unusual; each user has their own pod per `architect-{project}-{user}` naming), only A's sessions land in A's pod; B's sessions land in B's pod. Each user sees their own history only. This is a coincidentally correct boundary, but it's a consequence of the pod naming, not an intentional multi-user privacy guarantee.
- **Phase 9 (widget display of history)** is separate — this plan only gives Pi the context. Making the user see the prior conversation in the widget is follow-on.

---

## Rollback plan

If any gate after Phase 5 (deploy) fails in a way we can't fix in-session:
1. `kubectl set image` back to the previous tag for both bridge and agent-pi.
2. Revert the branch commits; do not merge.
3. Update SPIKE doc with the failure mode.

---

## Task breakdown (for TaskCreate)

One task per phase above. Dependencies: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8.
