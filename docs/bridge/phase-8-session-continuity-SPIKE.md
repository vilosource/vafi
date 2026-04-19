# Phase 8 — Session Continuity Spike Protocol

Status: **draft — protocol defined, no runs yet**
Owner: claude-opus (driver), user (decision-maker)
Created: 2026-04-19

---

## What this document is

A development protocol for Phase 8 (chat-widget session continuity). It is **not** a design or an implementation plan. It is the methodology we will use to discover what the design and plan should be.

The protocol assumes the design in `chat-widget-DESIGN.md §Session Continuity` may be wrong, partially right, or solving the wrong problem. We will not implement it until the spike confirms which.

This document accretes data over time. As we run the steps below, observations, the Rumsfeld matrix, and the design decisions land here in order. A future PLAN doc may be extracted once the design crystallizes.

---

## Core principle

**Characterize before assert. Failing baseline before design. Rumsfeld before implementation.**

Three commitments:

1. **Evidence over design-doc claims.** The design doc is a hypothesis. Run the system, observe, then decide.
2. **A failing test is the contract.** "Done" is defined as a specific test going green, written before any implementation.
3. **Rumsfeld delta is the artifact.** What we *thought* we knew vs. what the experiment showed — that delta is more valuable than either matrix in isolation.

---

## The 6-step protocol

### Step 1 — Characterize current state (no assertions)

Run a two-session probe with no pass/fail criteria. Just observe and record.

- Project: fresh, UUID-suffixed (`spike-phase8-{uuid8}`), so cxdb has no prior history.
- Session 1: acquire lock → send a structured prompt (see §"Probe prompts") → release lock.
- **Hard release**: lock deleted, pod deleted (`kubectl delete pod -l role=architect,project={uuid}`). This isolates the cxdb path from the Pi-session-file path (see "Open question P5").
- Session 2: acquire lock again on the same project → send continuation prompt → observe response.

Capture, do not assert:
- Was the same pod reused, or a fresh pod created?
- Did Pi's `/sessions/{slug}/` files survive pod deletion? (Likely no — `EmptyDir`. Confirm.)
- `cxdb_get_turns` output for session 1 dumped to `tests/fixtures/cxdb/spike-baseline-session1.json`. Inspect: is `assistant_turn.text` populated? What's *in* it (final answer only? chain-of-thought? structured output?)
- Did session-2 Pi spontaneously demonstrate any continuity at all (i.e., did it know about session 1 without us doing anything)?
- Bridge logs: did `session_recorder.py` write a `cxdb_context_id` to the SessionRecord at session-1 close?

Output: `phase-8-baseline-OBSERVATIONS.md` appended to this doc.

### Step 2 — Pre-baseline Rumsfeld

Before looking at step-1 results, fill out a Rumsfeld matrix from priors only (design doc + memory + intuition). This captures what we *thought* we knew going in. Do not edit after step 1 — its value is as a frozen prior.

Template in §"Rumsfeld matrix" below.

### Step 3 — Run assertion tests

Two tests, two purposes:

**Test A — plumbing (binary, deterministic, CI-eligible):**
- Session 1: "Remember this code: `ALPHA-7Z-{uuid}`."
- Session 2 (after hard release + pod delete): "What was the code I gave you?"
- Pass = exact string in response.
- Confirms the data path (cxdb → context summary → Pi prompt) works. Says nothing about quality.

**Test B — task-continuation (probabilistic, manual gate, milestone):**
- Session 1: "Design a Python class for a bank account with deposit and withdraw methods."
- Session 2: "Now add a transaction-history method to it." (no restatement)
- Pass = response references `BankAccount`, `deposit`, `withdraw` symbols from session 1 with consistent semantics.
- Confirms the loaded context is *useful*, not just present.

**Per cxdb tier**, run both tests against:
- Tier 1 only (~800 token structured summary)
- Tier 1 + Tier 2 (+ ~3K token breadcrumbs)
- Tier 1 + Tier 2 + Tier 3 (selective turns)

Expected matrix: Test A may fail for Tier 1 (summary doesn't preserve verbatim nonces — that's by design); Test B should pass at Tier 1. If Test B fails at all tiers, the design is wrong.

### Step 4 — Post-baseline Rumsfeld + delta

Fill the matrix again from data. Compare to the step-2 matrix. The **delta** is the deliverable:

- Which known unknowns became known knowns? (good — we learned)
- Which unknown knowns were invalidated? (better — we caught a hidden assumption)
- Which unknown unknowns surfaced? (best — the experiment did its job)

### Step 5 — Decision point

Three possible outcomes:

| Outcome | Trigger | Action |
|---------|---------|--------|
| Design holds | Test B passes at all relevant tiers | Proceed to implementation per `chat-widget-DESIGN.md §Session Continuity` |
| Design partial | Test B passes at some tiers, fails at others | Narrow scope; implement only the tiers that work |
| Design wrong | Test B fails at all tiers, OR step-1 reveals Pi session-file resume gives free continuity for the common case | Redesign. Write a new DESIGN doc; this SPIKE feeds it. |

The decision is made *with* the user, not autonomously.

### Step 6 — Implement minimum to make Test A + Test B green

TDD from the failing baseline. No scope creep beyond making the tests pass at the agreed tier(s).

---

## Test pyramid

| Layer | Where | Speed | Purpose |
|-------|-------|-------|---------|
| Unit | `vafi/tests/bridge/test_continuity_prompt_builder.py` | sub-second | Mock cxdb. Assert bridge builds the correct `--append-system-prompt` content from a fixture cxdb response. Many cases: empty, large, malformed. |
| Integration | `vafi/tests/integration/test_session_continuity.py` | minutes (Pi cold start ~35s × 2) | Real bridge, real Pi, real cxdb, deployed. One happy-path each for Test A and Test B. Run on demand, not on every commit. |
| E2E | `vtaskforge/web/e2e/chat-widget-continuity.spec.ts` | minutes | Playwright smoke. One test for Phase 9 (display history rendering) once Phase 8 is green. |

vafi may not have an integration test tier yet. If so, this work establishes it: pytest marker `@pytest.mark.integration`, separate Make target (`make test-integration`), excluded from default `make test`.

---

## Test isolation requirements (mandatory)

These prevent false positives. Skip any of them and the test lies.

1. **UUID-suffixed project per run.** No shared state across runs. Project name = `spike-phase8-{uuid8}`.
2. **Hard lock release between session 1 and session 2.** Without this, Pi's in-memory context gives a false pass.
3. **Pod deletion between sessions.** Without this, Pi's `/sessions/` files (if persistent) or warm in-memory state may give continuity that bypasses cxdb. `kubectl delete pod -l role=architect,project={uuid} --wait`.
4. **Cleanup at end.** Delete the project, delete any leftover pods, and mark the cxdb session as test-only if cxdb supports tagging. Otherwise accept some test-data accumulation in cxdb-dev (quantified, not unbounded).
5. **Nonce uniqueness.** The plumbing nonce includes a UUID so re-runs cannot accidentally pass via a leaked context window from a prior run.

---

## Probe prompts (frozen)

Stored as fixtures so they don't drift mid-spike.

- `tests/fixtures/prompts/baseline-session1.txt` — step-1 probe
- `tests/fixtures/prompts/baseline-session2.txt` — step-1 continuation
- `tests/fixtures/prompts/test-a-plumbing.txt` — nonce
- `tests/fixtures/prompts/test-b-task-session1.txt` — bank account design
- `tests/fixtures/prompts/test-b-task-session2.txt` — add method

If we change a prompt mid-spike, the prior runs are invalidated. Note any change in this doc with a justification.

---

## Open design questions (must resolve before "done")

These are deliberately not assumed. They block step 6 if unresolved.

| ID | Question | Why it matters | When to resolve |
|----|----------|---------------|-----------------|
| Q1 | Which prior session(s) get loaded — last only, all, time-windowed? | Design doc says "the last session's `cxdb_context_id`" (singular). Multi-session aggregation is undefined. Affects how shallow/deep continuity feels. | Before step 5 |
| Q2 | Multi-user: if user A had session 1 and user B starts session 2 on the same project, does B inherit A's context? | Privacy + UX. Locks are per `(project, role)` but continuity scope isn't defined. | Before step 5 |
| Q3 | Failure modes: cxdb down, invalid `cxdb_context_id`, summary build fails — fail loud, fail silent, or fall back to no-context? | Determines error UX in widget. Skipping this gives a brittle feature. | During step 6 |
| Q4 | Does Pi's `--append-system-prompt` treat appended content as authoritative context, or as a soft hint that may be deprioritized? | If soft, summaries may not actually shape behavior. Need a small isolated check. | During step 1 (cheap to test) |
| Q5 | Can Pi resume from its own JSONL session files via `--session-dir` after a fresh process on the same pod (spike S3, never run)? | If yes, the common case (release + reacquire while pod is warm) gets continuity for free without cxdb. **Could collapse Phase 8 to a much smaller change.** | During step 1 |
| Q6 | Does the user want an "ignore prior context / start fresh" option in the widget? | Privacy and clean-slate UX. May be Phase 9 scope, but the data path decisions in Phase 8 constrain it. | Before step 6 |
| Q7 | Is there an idempotency / replay risk — can the same prompt being added to context twice cause Pi to behave oddly? | If we load session 1 into session 2, then session 2 into session 3, content compounds. Bound on context size? | Before step 6 |

---

## Scope

**In scope for this spike:**
- Session-end mode: explicit release (cleanest, deterministic)
- Single-user, single-project, last-session continuity (the trivial case)
- Pi's `--append-system-prompt` behavior verification

**Explicitly out of scope (separate work):**
- Crash / pod eviction recovery (different failure surface — SessionRecord may not be finalized; deserves its own test, not a continuity test)
- Idle-timeout-triggered session end (post-conditions identical to release; redundant for continuity logic)
- Multi-user continuity (Q2 — needs design first)
- Multi-session aggregation (Q1 — needs design first)
- Phase 9 display-history rendering (separate phase, but informed by what we learn here)

---

## Rumsfeld matrix

Used twice: pre-baseline (step 2, frozen after step 1 starts) and post-baseline (step 4).

|  | We know we know | We know we don't know |
|---|---|---|
| **Articulated** | (Known knowns — verified facts and shipped behavior) | (Known unknowns — each must have a named experiment that would resolve it) |
| **Unarticulated** | (Unknown knowns — hidden assumptions, hard to surface; ask: "what am I taking for granted?") | (Unknown unknowns — can only populate post-hoc when the experiment surprises us) |

**Rules of use:**

1. Every "known unknown" must name the experiment that would move it to "known known."
2. "Unknown knowns" are the most valuable quadrant pre-experiment. Force yourself to articulate hidden assumptions (e.g., "we assume `assistant_turn.text` populates in interactive mode" — actually unverified).
3. "Unknown unknowns" only populate post-experiment. If the post-baseline matrix has none, the experiment was probably not informative enough.
4. The deliverable is the **delta** between pre- and post-matrices, not either matrix alone.

---

## Files this spike will produce

```
vafi/docs/bridge/phase-8-session-continuity-SPIKE.md   (this file, accretes)
vafi/tests/integration/test_session_continuity.py      (Test A + Test B)
vafi/tests/bridge/test_continuity_prompt_builder.py    (unit, mocked cxdb)
vafi/tests/fixtures/cxdb/spike-baseline-session1.json  (raw cxdb dump from step 1)
vafi/tests/fixtures/prompts/*.txt                      (frozen probes)
```

---

## Pre-baseline Rumsfeld (frozen 2026-04-19, before any step-1 data)

This matrix is filled from priors only — design doc, memory, code reading, intuition. **Do not edit after step 1 begins.** Its value is as a frozen snapshot of what we thought we knew going in.

### Known knowns (verified facts)

- Bridge is deployed at `bridge.dev.viloforge.com` in `vafi-dev` namespace.
- vtf `SessionRecord` model exists; bridge writes via `session_recorder.py` (per design doc §Session Continuity).
- cxdb is deployed; `src/cxdb/` package exists; `cxdb-mcp` MCP server runs in `vafi-dev`.
- `CxdbClient` (async HTTP), `parse_turns()`, `extract_tool_events()`, `extract_structured()` exist in `src/cxdb/`.
- Pi agents have cxdb MCP access — bridge injects `VF_CXDB_MCP_URL` into Pi's environment.
- Lock model: per `(project, role)`, 4-hour idle timeout (`LOCKED_IDLE_TIMEOUT_SECONDS`).
- Pods reused by `(role, project)` labels via `find_or_create` (per memory + bridge code).
- Pi cold start ~35s on a fresh pod (per memory, 2026-04-14).
- Bridge has CORS configured (verified per memory, 2026-04-14).
- Chat widget rework R1–R8 deployed and verified, 13/13 Playwright pass (2026-04-16).
- Pi `/sessions/{slug}/repo/` is now created by an init container (vafi commit 7a041fb, 2026-04-18).
- 4-task chain E2E ran successfully on `vafi-smoke-test` (commit 46c27a1, 2026-04-18) — agent execution path is healthy end-to-end.

### Known unknowns (each must name an experiment)

| Unknown | Experiment that would resolve it |
|---------|----------------------------------|
| Does `assistant_turn.text` populate in interactive bridge sessions? Spike0 data was executor-only and `text` was often empty there. | Step 1d — dump `cxdb_get_turns` after session 1, inspect `text` field across all `assistant_turn` entries. |
| Can Pi resume from `--session-dir` after a fresh process on the same pod (spike S3, never run)? | Step 1d — release lock without deleting pod; reacquire; observe whether session 2 has spontaneous continuity *before* any cxdb wiring exists. |
| Does Pi treat `--append-system-prompt` as authoritative context or as a soft hint that may be deprioritized? | Step 1d, side-experiment — inject a distinctive instruction via `--append-system-prompt` and observe whether Pi follows it. |
| Are Pi's `/sessions/` files persistent across pod restart? Memory says EmptyDir for session files (lost), PVC for workdir (survives). Recent init-container changes (4d179b6, 7a041fb) may have changed this. | Step 1d — check `kubectl describe pod` for volume mounts on `/sessions/` and `/sessions/{slug}/repo/`. |
| What does the cxdb tier-1 structured summary actually look like for an interactive session? Tier sizes (~800 tok / ~3K tok / variable) are design intent, not measured. | Step 1d — call `extract_structured()` on session 1's context; measure token count and content shape. |
| Does `session_recorder.py` write `cxdb_context_id` at session-1 close, or per-prompt? Design doc says "after each prompt" — needs confirmation. | Step 1d — query vtf SessionRecord rows mid-session and post-close; observe when the field appears. |
| What happens when cxdb is unreachable at session-2 acquire — fail loud, fail silent, or fall back to no-context? | Step 6 — failure-injection test (deliberate cxdb timeout). Out of scope for step 1. |
| Is there current bridge code that loads prior context at lock-acquire time, or is the entire load path TBD? | Step 1c (code read) — grep `lock_manager.py`, `app.py`, `pi_session.py` for any cxdb-load on acquire. |
| Does `CxdbClient` support querying by `cxdb_context_id` directly, or does it require `session_id` lookup first? | Step 1c — read `src/cxdb/__init__.py` and check method signatures. |

### Unknown knowns (hidden assumptions — articulate to surface)

These are things we are taking for granted but have not validated. Most valuable quadrant pre-experiment.

- We assume cxdb captures interactive bridge sessions the same way it captures executor sessions. Spike0 was executor-only.
- We assume Pi's `--append-system-prompt` is loaded once at startup and persists for the whole conversation, not re-read per prompt.
- We assume "the last session" is unambiguous. If two users had sessions on the same project at different times, "last" might cross user boundaries — and we have no policy for that yet.
- We assume cxdb's Python tools (`extract_structured`, etc.) are usable from inside the bridge process, not only via MCP. `CxdbClient` exists, but coverage of the summary-building path is unverified.
- We assume the user implicitly wants continuity. There may be cases (sensitive content, fresh-start UX) where they want a clean slate — no opt-out exists.
- We assume Pi's context window won't be a problem with prepended summaries. Tier 1 (~800 tok) is small, but cumulative across many prior sessions could grow unboundedly if we ever load more than the last.
- We assume the bridge has the `(project, role)` at lock-acquire time and can use it to query vtf for prior `SessionRecord`. (True for the API surface — but the *implementation* of that query path may not exist yet.)
- We assume `vafi-dev` behaves like prod for continuity. No reason to think otherwise, but worth flagging if results look weird.
- We assume the architect role pi-mcp-adapter changes (vafi commits bff420c, 88adabc) don't change cxdb write behavior. Recent pi migration touched a lot — could have side-effects we haven't traced.
- We assume our test isolation (UUID project + pod delete) is sufficient. There may be cluster-level state (e.g., orphaned PVCs, lingering bridge in-memory session entries) that bleeds across runs.
- We assume `--session-dir` if it works, would resume the *exact same* Pi conversation state, not a degraded version. Untested.

### Unknown unknowns

Empty by definition. Will populate post-baseline (step 4) from things the experiment surprised us with.

---

## Step 1 — Characterization observations (2026-04-19)

Probe ran via `scripts/spike/phase8_characterize.py`. Project `spike-phase8-dbf69a25` (id `8SRKxRyXm_Knz8dH6KlOK`), role `architect`. Two sessions on the same project, ~20s apart.

### Headline result

**No spontaneous continuity.** Session 2 returned `"UNKNOWN, UNKNOWN, UNKNOWN"` for the three facts planted in session 1. Failing baseline confirmed.

### What actually happened (corrected for script bugs)

1. **Same pod was reused for both sessions.** Pod `architect-8srkxryxm-knz8dh6klok-admin` was created at session-1 lock acquire and was still running at session 2. My script's pod-delete query used the wrong label key (`project=`) — actual key is `vafi.viloforge.com/project=` and **the value is lowercased** (`8srkxryxm-knz8dh6klok` from project id `8SRKxRyXm_Knz8dH6KlOK`). Pods were never deleted between sessions.
2. **Pi cold start was ~10s, not ~35s.** Memory was wrong (or warmer cluster). First lock-acquire-to-prompt-ready: 10s. Second (warm pod): <1s.
3. **`/sessions/` is a PVC (`console-sessions`), not EmptyDir.** Memory was wrong. Survives pod restart and is shared across all architect pods on this node.
4. **Both sessions' Pi JSONL files exist at `/sessions/{lowercased-project}/{timestamp}_{session_id}.jsonl`.** Format is `version:3` JSONL with `session`, `model_change`, `thinking_level_change`, `message` (user/assistant) entries. Assistant text is populated for short text-only responses.
5. **`assistant_turn.text` IS populated** in the Pi JSONL — at least for short text-only responses. Q1 partially answered (CoT/tool-using shape still TBD).
6. **The Pi exec command already passes `--session-dir`** (`pod_process.py:134`) — but **this flag is for write-output, not resume**. Pi creates a new JSONL per invocation with its own `session_id`. The flag does NOT cause Pi to read prior JSONL files in the same dir.
7. **No `--resume`, `--continue-session`, or similar flag is passed to Pi.** Whether Pi supports any such flag is unknown.
8. **`--append-system-prompt` takes a FILE PATH** (`/opt/vf-agent/methodologies/architect.md`), not a string. To inject prior context, we'd need to write a temp file before exec.
9. **The streaming endpoint does NOT call `session_recorder.record()`.** Only the non-streaming `/v1/prompt` (lines 315, 353) records SessionRecords in vtf. The streaming path (`/v1/prompt/stream` lines 497–632, used by the chat widget) has zero session-recording. **Therefore no `cxdb_context_id` is ever persisted for chat-widget sessions.** The Phase 8 design assumption "bridge records `cxdb_context_id` in vtf SessionRecords after each prompt" is false for the streaming path.
10. **No `cxdb_context_id` appears in the streaming `result` event.** Bridge has no awareness of any cxdb context that Pi may or may not have created via its MCP integration.
11. **Token counts confirm zero continuity context is being injected.** Session 1: 2790 input tokens for a 219-char prompt (methodology overhead). Session 2: 2673 input tokens for a 193-char prompt. If session 1's transcript were prepended in session 2, input would be much higher.
12. **Lock auto-release works as designed.** Lock stays alive across prompts; only an explicit `DELETE /v1/lock` (or pod_session.shutdown) tears it down. The widget's "keep alive" is implicit (just don't call DELETE).
13. **Cleanup works:** `kubectl delete pod` and `DELETE /v1/projects/{id}/` (HTTP 204) both succeeded.

### Files produced

- `vafi/tests/fixtures/cxdb/spike-baseline-observations.json` — full observation dump (with the corrected pod-label note)
- `vafi/scripts/spike/phase8_characterize.py` — runner script (label-query bug noted, kept as-is for traceability)

### Bridge logs of interest (verbatim, vafi-bridge-84bfd44988-p4mxq)

```
2026-04-19 09:00:21,903 - bridge.pod_process - INFO - Opening exec to pod ...
exec pi --mode rpc --session-dir /sessions/8srkxryxm-knz8dh6klok/ --provider anthropic --model claude-sonnet-4-20250514 --append-system-prompt /opt/vf-agent/methodologies/architect.md --thinking medium
```

---

## Post-baseline Rumsfeld (2026-04-19, after step 1)

### Known knowns (now verified — was unknown or wrong before)

- `--session-dir` is for OUTPUT only; Pi does NOT auto-resume from prior JSONL files in the same dir. (Previously: known unknown Q5. **Resolved: NO.**)
- `assistant_turn` content has `text` populated for short text-only responses in interactive bridge mode. (Q1 partial; tool-use shape still TBD.)
- `/sessions/` is a PVC (`console-sessions`), persistent across pod restart, shared across architect pods. (Pre-baseline assumed EmptyDir → persistent for some, lost for others. **Wrong; it's all persistent.**)
- Pi JSONL format is `version:3` with `session`/`model_change`/`thinking_level_change`/`message` entries. Each Pi invocation creates a new file named `{timestamp}_{session_id}.jsonl` in `/sessions/{lowercased-project}/`.
- The Pi exec command-line is now fully known (verbatim above).
- Lock release behavior: auto-released only on explicit DELETE, pod_session.shutdown, or session-close callback.
- Pod label key is `vafi.viloforge.com/project=<lowercased-id>` (with `_` → `-`), not `project=`.
- Project-create + project-delete via vtf REST works for admin (POST 201, DELETE 204).

### Known unknowns → still open

- **Does Pi support a resume/continue flag?** (No code reference found yet. Need to check pi-mcp-adapter or Pi binary docs.)
- **Does Pi auto-write to cxdb during interactive sessions, or only via explicit MCP tool calls?** (The streaming endpoint never sets `cxdb_context_id`, but Pi may still be writing context via its MCP integration. Need to query cxdb directly to check.)
- **What does `assistant_turn` look like for tool-use turns and CoT?** (Only saw short text-only responses in the baseline.)
- **What happens if we write to `--append-system-prompt` with a temp file containing prior context?** (Mechanism we'd likely use; never tested.)
- **Failure modes** — Q3 still unanswered.

### Unknown knowns (validated or invalidated)

- ❌ **INVALIDATED: "Bridge records cxdb_context_id in SessionRecord after each prompt."** The streaming endpoint does NOT call `session_recorder.record()` at all. This was a design-doc claim, not a code reality.
- ❌ **INVALIDATED: "EmptyDir loses session files on pod restart."** `/sessions/` is a PVC; nothing is lost on pod restart.
- ✓ **VALIDATED: `--append-system-prompt` is loaded once at startup, not per-prompt.** It's part of the exec command line.
- ⚠ **PARTIALLY VALIDATED: cxdb captures interactive sessions like executor.** Bridge doesn't *record* a context_id, but Pi MCP path may still write — unverified. Different concern than originally framed.
- ✓ **VALIDATED: Pi cold start is real** — but ~10s, not ~35s as memory claimed.

### Unknown unknowns surfaced (the experiment did its job here)

- 🆕 **The streaming endpoint and the non-streaming endpoint behave very differently for session recording.** The chat widget — the only consumer of the streaming endpoint in production — produces zero SessionRecord data. The Phase 8 design assumed parity that does not exist.
- 🆕 **Pod label scheme uses `vafi.viloforge.com/project=<lowercased-and-hyphenated-id>`.** The character-set mismatch between vtf project IDs (uppercase + underscore) and k8s label values (lowercase + hyphen) is a minefield for any future code that bridges the two namespaces.
- 🆕 **Same pod / same session-dir, two sessions, two different JSONL files. They are NOT linked from Pi's side.** No file in `/sessions/{project}/` indexes prior sessions; resume would have to scan and pick the most recent.
- 🆕 **`hydrate_context.py` runs every lock-acquire** and produces `PROJECT_CONTEXT.md`. There's an existing per-acquire hook we could extend with prior-session context loading without inventing a new mechanism.
- 🆕 **The reader-loop / lock-release race** — when a `DELETE /v1/lock` arrives, it triggers `pod_session.shutdown` → cancels reader → fires `on_close` → force_release. The user's explicit DELETE then sees 404. Cosmetic, but informative about lifecycle ordering.

### Rumsfeld delta summary

| Quadrant | Movement |
|----------|----------|
| Known unknowns → known knowns | Q5 (Pi --session-dir resume): NO. PVC durability for /sessions/: YES. |
| Unknown knowns → invalidated | Bridge records SessionRecord on streaming: FALSE. EmptyDir loses sessions: FALSE. |
| Unknown knowns → validated | --append-system-prompt loaded once at startup: TRUE. |
| Unknown unknowns surfaced | 5 new findings (streaming vs non-streaming endpoint divergence, label mismatch, JSONL non-linkage, hydrate_context hook, lifecycle race) |

The most consequential delta: **the design's central mechanism (record cxdb_context_id, query it later, build summary) is not just unimplemented — its first step is missing from the streaming codepath.** Phase 8 cannot just "wire up" cxdb loading; it must first add session recording to the streaming endpoint.

---

## Decision point (Step 5 — for user)

Three possible directions emerge from the data:

### Option A: Fix the design as written
1. Add `session_recorder.record()` calls to the streaming endpoint at result/end events.
2. Wait for cxdb to populate (via Pi's MCP path).
3. On lock-acquire, query SessionRecord for prior `cxdb_context_id`, build summary, inject via `--append-system-prompt`.
- **Cost:** Multi-component change across bridge + ensuring Pi reliably writes cxdb context.
- **Pro:** Matches the design doc; cxdb survives PVC loss; works cross-pod.
- **Con:** Requires Pi to consistently write to cxdb during interactive sessions (unverified). The cxdb summary tools and CxdbClient need API alignment (`find_context_by_task` exists but no `find_by_session_id`).

### Option B: Pivot to JSONL-based resume (cheaper, possibly sufficient)
1. On lock-acquire, scan `/sessions/{lowercased-project}/` for prior JSONL files.
2. Pick the most recent (or most recent N).
3. Build a summary from the JSONL `message` entries.
4. Write the summary to a temp file and pass via `--append-system-prompt` (alongside methodology).
- **Cost:** Single-file change, mostly in the bridge `build_exec_command` path.
- **Pro:** No dependency on cxdb wiring. Pi already writes JSONL reliably. PVC is durable.
- **Con:** Tied to PVC lifecycle (PVC loss = continuity loss). Same-pool sharing means cross-cluster restore is harder. Sanitized project name collision risk if two vtf projects collapse to the same k8s label.

### Option C: Hybrid — JSONL for warm path, cxdb for cold/cross-cluster
- Use JSONL when present (fast, no extra services).
- Fall back to cxdb when JSONL is missing (e.g., PVC reset).
- Requires both paths to work, but each path is independently implementable.

### My recommendation

Start with **Option B** as the minimum-viable Phase 8. It avoids the broken streaming-endpoint recording, uses already-existing JSONL data, and proves the user-facing continuity hypothesis cheaply. If it works and we later need cross-cluster durability, add Option A as a fallback (Option C).

This also lets us run Test A and Test B against a thin implementation immediately — fewer moving parts.

**User decision needed: A, B, or C?**

---

## Status log

| Date | Step | What happened |
|------|------|--------------|
| 2026-04-19 | 0 | Protocol drafted. |
| 2026-04-19 | 1a | Probe prompts written to `tests/fixtures/prompts/`. Frozen. |
| 2026-04-19 | 2 | Pre-baseline Rumsfeld matrix frozen. |
| 2026-04-19 | 1c | Infra access verified: bridge `/v1/health`, vtf `/v1/auth/login` (no trailing slash) → token, kubectl vafi-dev. |
| 2026-04-19 | 1b | Characterization runner written at `scripts/spike/phase8_characterize.py`. |
| 2026-04-19 | 1d | Probe ran. 13 findings logged above. Failing baseline confirmed (no continuity). Cleanup OK. |
| 2026-04-19 | 4 | Post-baseline Rumsfeld + delta written. 5 unknown unknowns surfaced. |
| 2026-04-19 | 5 | Decision point: Option A / B / C / cxtx-streaming-spike presented. |
| 2026-04-19 | 5b | cxtx-streaming spike run: cxtx preserves streaming for Pi RPC, but cxtx-pi only captures wrapper start/end events (not conversation content) — confirmed in cxdb context 104, head_depth=1. **Cxtx-for-architect is not viable; cxdb-backed continuity collapses for Pi.** |
| 2026-04-19 | 5c | User chose **Option A** (Pi JSONL on PVC). Implementation plan written at `phase-8-session-continuity-PLAN.md`. |
| 2026-04-19 | 6+ | Implementation complete and deployed (see PLAN status log). Test A (nonce plumbing) and Test B (task continuation) both PASS against vafi-dev. **Phase 8 DONE.** |
