# Viloforge Platform — Status Audit

**Date:** 2026-04-17
**Audited by:** AI agent (claude), verified against git history + deployed state
**Purpose:** Single source of truth for all phase-tracked work across the platform

---

## 1. Agent Bridge — Implementation Plan

**Doc:** `docs/bridge/agent-bridge-IMPLEMENTATION-PLAN.md`
**Date written:** 2026-04-02

This was the original 10-phase plan. It was superseded by the Rework Plan after implementation deviated significantly. Keeping for historical reference.

| Phase | What | Status | Evidence |
|-------|------|--------|----------|
| 0 | Deployable skeleton | ✅ DONE | `src/bridge/app.py`, deployed to vafi-dev |
| 1 | Auth middleware | ✅ DONE | `src/bridge/auth.py`, 5 unit tests |
| 2 | Role configuration | ✅ DONE | `src/bridge/roles.py`, `config/bridge-roles.yaml`, 4 unit tests |
| 3 | Ephemeral process manager | ✅ DONE | `src/bridge/pi_session.py`, 20 unit tests |
| 4 | Prompt endpoint | ✅ DONE | `/v1/prompt` in `app.py`, 14 unit tests |
| 5 | Streaming endpoint | ✅ DONE | `/v1/prompt/stream` in `app.py` |
| 6 | Lock manager + locked sessions | ✅ DONE | `lock_manager.py`, `vtf_locks.py`, `pod_process.py`, 12+18 unit tests |
| 7 | Idle timeout | ✅ DONE | `lock_manager.py:154`, 3 unit tests |
| 8 | Channel adapter interface | ✅ DONE | `src/bridge/adapters/protocol.py`, 2 unit tests |
| 9 | Final E2E suite | ⚠️ PARTIAL | 12 E2E tests exist (plan expected ~18), verification checklist never checked off |

**Recommendation:** Archive. Superseded by rework plan. Mark as historical in INDEX.md.

---

## 2. Agent Bridge — Rework Plan

**Doc:** `docs/bridge/agent-bridge-REWORK-PLAN.md`
**Date written:** 2026-04-02

Fixed 18 deviations from the original design. Two phases (A + B) plus Architect REPL.

### Phase A: Ephemeral Path

| Item | What | Status | Evidence |
|------|------|--------|----------|
| A1 | Skeleton fixes (health, CORS) | ✅ DONE | `app.py` health returns real counts |
| A2 | Auth middleware | ✅ DONE (no changes needed) | Already correct |
| A3 | Ephemeral process manager rework | ✅ DONE | `pi_session.py` uses `--mode rpc` |
| A4 | Prompt endpoints rework | ✅ DONE | Both `/v1/prompt` and `/v1/prompt/stream` work |
| A5 | Session recording | ✅ DONE | Commit `aa940a5` |
| A6 | Adapter interface rework | ✅ DONE | `adapters/protocol.py` |

### Phase B: Locked Path

| Item | What | Status | Evidence |
|------|------|--------|----------|
| B7 | Pod process manager | ✅ DONE | `pod_process.py`, 18 unit tests |
| B8 | Lock manager with vtf persistence | ✅ DONE | Commit `c030d31` |
| B9 | Locked session routing | ✅ DONE | `/v1/prompt/stream` locked path in `app.py` |
| B10 | Timeout + health monitoring | ✅ DONE | `lock_manager.py` idle timeout |
| B11 | Recovery on restart | ✅ DONE | Commit `c030d31` |

### Architect REPL

| Item | What | Status | Evidence |
|------|------|--------|----------|
| REPL | Acquire, multi-turn, release | ✅ DONE | `test_e2e_repl.py` (2 E2E tests) |

### Phase C: Channels + UI

| Item | What | Status | Evidence |
|------|------|--------|----------|
| Chat widget | Full chat UI in vtf | ✅ DONE | See §4 below |
| Slack adapter | Slack channel integration | ❌ NOT STARTED | Documented TODO in design |

### Verification Checklist

The checklist at line 313 has all boxes unchecked `- [ ]`. The work IS done but the doc was never updated.

**Recommendation:** Update checklist to `[x]`, mark Phase A+B as COMPLETE, note Slack adapter as future work.

---

## 3. Chat Widget — Issues & Gap Analysis

**Doc:** `docs/bridge/chat-widget-ISSUES.md`
**Date written:** 2026-04-15

| Issue | Severity | Status | Fixed in |
|-------|----------|--------|----------|
| B1: Session ID mismatch | Critical | ✅ FIXED | `03cafb6` (R2) |
| B2: No `agent_end` in locked mode | Critical | ✅ FIXED | `53ef419` (R1) — detects `stopReason=stop` instead |
| B3: Empty-line EOF bug | Medium | ✅ FIXED | `9e50ff7` (R4) |
| B4: Missing event forwarding | Medium | ✅ FIXED | `53ef419` (R3) |
| B5: Lock user is service token | Low | ✅ FIXED | `85a2bda` (R8) |
| F1: No syntax highlighting | Medium | ✅ FIXED | `783a708` (R5) |
| F2: No smart auto-scroll | Medium | ✅ FIXED | `783a708` (R6) |
| F3: No shimmer animation | Low | ✅ FIXED | `783a708` (R7) |
| A1: "Welcome back, token-user" | — | ✅ FIXED | `89de243d` (already marked in doc) |
| A2: No logout button | — | ✅ FIXED | `89de243d` (already marked in doc) |

**Recommendation:** Update all B1–B5 and F1–F3 with FIXED status and commit hashes, matching the A1/A2 format already in the doc.

---

## 4. Chat Widget — Rework Plan (R1–R8)

**Doc:** `docs/bridge/chat-widget-REWORK-PLAN.md`
**Date written:** 2026-04-15

| Phase | What | Repo | Status | Commit |
|-------|------|------|--------|--------|
| R1 | Stream completion (detect `stopReason`) | vafi | ✅ DONE | `53ef419` |
| R2 | Session ID sync to vtf | vafi | ✅ DONE | `03cafb6` |
| R3 | Event forwarding parity | vafi | ✅ DONE | `53ef419` (combined with R1) |
| R4 | Empty-line EOF fix | vafi | ✅ DONE | `9e50ff7` |
| R5 | Syntax highlighting | vtaskforge | ✅ DONE | `783a708` |
| R6 | Smart auto-scroll | vtaskforge | ✅ DONE | `783a708` (combined with R5) |
| R7 | Shimmer animation | vtaskforge | ✅ DONE | `783a708` (combined with R5) |
| R8 | Lock ownership | both | ✅ DONE | vafi:`85a2bda`, vtf:`5f95591`+`334f11f` |

**E2E:** 13/13 Playwright tests passing (verified 2026-04-17)

**Per-phase checklist** (line 505) has all boxes unchecked — work is done but doc never updated.

**Recommendation:** Mark all phases DONE with commits. Update per-phase checklist.

---

## 5. Chat Widget — Design (Phases 1–9)

**Doc:** `docs/bridge/chat-widget-DESIGN.md`
**Date written:** ~2026-04-08

| Phase | What | Status | Evidence |
|-------|------|--------|----------|
| 1 | `bridge.ts` API client + `useBridgeStream` | ✅ DONE | `vtaskforge/web/src/api/bridge.ts`, `hooks/useBridgeStream.ts` |
| 2 | `ChatWidgetContext` + `ChatWidget` shell | ✅ DONE | `contexts/ChatWidgetContext.tsx`, `components/ChatWidget.tsx` |
| 3 | `ChatWindow` + `ChatMessage` + `ChatInput` | ✅ DONE | All three components exist |
| 4 | Lock lifecycle | ✅ DONE | `useLockHeartbeat`, acquire/release in context |
| 5 | Streaming integration | ✅ DONE | NDJSON parsing, `useBridgeStream` |
| 6 | Polish | ✅ DONE | Tool indicators, markdown, auto-scroll, beforeunload |
| 7 | Integration | ✅ DONE | Buttons in Home.tsx, ProjectDashboard.tsx, App.tsx mount |
| 8 | Session continuity (cxdb → agent) | ❌ NOT STARTED | No code loading prior cxdb context on lock acquire |
| 9 | Display history (cxdb → widget) | ❌ NOT STARTED | No code rendering prior cxdb turns in widget |

### Definition of Done check:
- ✅ 1–7: All verified
- ❌ 8: "Start a new session after release → agent has context from the previous session via cxdb"
- ❌ 9: "See previous conversation messages rendered in the widget from cxdb history"

**Recommendation:** Add status column to implementation sequence table. Phases 8–9 are genuine remaining work.

---

## 6. Harness Boundary Refactor (Phases 0–8)

**Doc:** `docs/harness-refactor/` (9 phase docs + INDEX + WORK-PROTOCOL)
**Date written:** ~2026-04-13

| Phase | What | Status | Evidence |
|-------|------|--------|----------|
| 0 | Create init.sh, connect.sh, run.sh in images | ❌ NOT STARTED | No scripts found in `images/` |
| 1 | Config restructure (harnesses.yaml, roles.yaml, infra.yaml) | ❌ NOT STARTED | No harnesses.yaml or infra.yaml exist |
| 2 | Entrypoint sources init.sh | ❌ NOT STARTED | entrypoint.sh still uses `VF_HARNESS` switch |
| 3 | Console uses connect.sh | ❌ NOT STARTED | No connect.sh |
| 4 | PodSpecBuilder from config | ❌ NOT STARTED | No PodSpecBuilder class |
| 5 | Controller calls run.sh | ❌ NOT STARTED | No run.sh |
| 6 | Bridge uses config-driven pods | ❌ NOT STARTED | Bridge still has hardcoded patterns |
| 7 | bash-agent acid test | ❌ NOT STARTED | No bash-agent image |
| 8 | Final gate + grep check | ❌ NOT STARTED | Depends on all above |

**Current state:** Only the design docs exist (commit `db36103`). Zero implementation.

**Recommendation:** These docs are still valid as a plan. Either prioritize execution or explicitly defer with a note in INDEX.md.

---

## 7. Context Hydration Audit

**Doc:** `docs/bridge/context-hydration-AUDIT.md`
**Date written:** 2026-04-14

Documents the `hydrate_context.py` implementation and its issues. Lists critical items (shell injection via repo_url, inline Pi config fragility). Status of fixes unclear from the doc itself.

**Recommendation:** Check if C1/C2 were fixed, update doc accordingly.

---

## 8. Console Terminal Bug

**Tracked in:** MemPalace only (no doc)
**Date found:** 2026-04-13

Every click on a pod in console.dev.viloforge starts a new terminal session — `connectToPod()` in `web/src/main.js` disconnects old WebSocket, clears xterm, spawns fresh kubectl exec. Proposed fix: tmux inside pod.

**Status:** ❌ NOT STARTED — diagnosis recorded, implementation never done.

**Recommendation:** Create a doc or VTF task.

---

## Summary

| Area | Total Phases | Done | Remaining | Doc Accuracy |
|------|-------------|------|-----------|-------------|
| Bridge impl plan | 10 | 10 | 0 | ⚠️ Checklist unchecked, superseded |
| Bridge rework plan | 13 items | 12 | 1 (Slack) | ⚠️ Checklist unchecked |
| Chat widget issues | 10 bugs | 10 | 0 | ⚠️ B1–B5, F1–F3 not marked fixed |
| Chat widget rework | 8 phases | 8 | 0 | ⚠️ Checklist unchecked |
| Chat widget design | 9 phases | 7 | 2 (§8, §9) | ⚠️ No status column |
| Harness refactor | 9 phases | 0 | 9 | ✅ Accurate (nothing started) |
| Context hydration | audit | ? | ? | ⚠️ Fix status unknown |
| Console terminal | 1 bug | 0 | 1 | ❌ No doc exists |

### Test Inventory

| Area | Unit | E2E/Integration | Frontend |
|------|------|----------------|----------|
| vafi (all) | 317 | — | — |
| vafi bridge | 110 | 12 | — |
| vtf backend | 1,982 | — | — |
| vtf frontend | — | — | 336 unit + 86 E2E |
| Chat widget Playwright | — | 13 | — |
