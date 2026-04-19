# vafi — Status Dashboard

Last updated: 2026-04-18 (by: claude)

---

## Active Work

| Item | Area | Priority | Blocked by | Notes |
|------|------|----------|-----------|-------|
| Console terminal session reuse | vafi-console | Low | — | connectToPod() clears terminal on every click. Proposed fix: tmux. No doc yet. |
| Slack adapter | bridge | Low | — | Channel adapter interface exists (`adapters/protocol.py`), Slack not implemented |
| cxtx pi capture (upstream) | cxdb | Low | — | `cxtx pi` captures only wrapper start/end, not Anthropic API traffic. Affects all pi-based cxdb ingestion (executor + would-be architect). Upstream issue. |
| Phase 8 continuity header UX polish | bridge (build_prior_context.py) | Low | — | When the user asks "what's in your context?", the architect quotes the literal `# Continuation from previous sessions` header verbatim. Functionally correct but exposes implementation detail. Soften the header phrasing or restructure the instruction. |
| Phase 9 ended_at on lock release | bridge (session_recorder) | Low | — | SessionRecord rows currently have `ended_at: null` indefinitely. Add a release-side update (PATCH or new POST flow). Cosmetic — Phase 9 attribution works without it. |

## Deferred

| Item | Area | Reason | Resume when |
|------|------|--------|-------------|
| Harness boundary refactor (9 phases) | vafi core | Design complete, zero implementation | Adding a 3rd harness (beyond Claude + Pi) |
| Context hydration hardening | bridge | C1 (shell injection) and C2 (inline config) identified in audit | Next bridge security pass |

## Recently Completed

| Item | Completed | Commits | Verified |
|------|-----------|---------|----------|
| Chat widget Phase 9: Display history (project-scoped log w/ user attribution) | 2026-04-19 | vafi: branch `phase-9-display-history` (`7d808ac`); vtaskforge: branch `phase-9-display-history` (`0056b04`) | Playwright MCP manual ✅ on vtf.dev — widget shows "View prior conversation" expander, user message labeled `admin`, assistant labeled `Architect`. Streaming SessionRecord wiring closed as part of this. |
| Chat widget Phase 8: Session continuity (architect Pi JSONL → `--append-system-prompt`) | 2026-04-19 | branch `phase-8-session-continuity` | Test A (nonce plumbing) + Test B (task continuation) ✅ against vafi-dev |
| vtf/vafi discovery-pass fixes (5 fixes + 7 review follow-ups + pi image rebuild) | 2026-04-18 | vafi:`62f455d`+`88adabc`, vtf:`b2ea31c`+`5ad80d7`, deploy:`78d59bf`+`c092e43` | 4-task chain E2E ✅ (commit `46c27a1` on vafi-smoke-test) |
| Chat widget rework R1–R8 | 2026-04-16 | vafi:`85a2bda`, vtf:`334f11f` | 13/13 Playwright E2E ✅ |
| Bridge rework Phase A+B | 2026-04-14 | vafi:`dad9d0d` | 12 E2E tests ✅ |
| Chat widget Phases 1–7 | 2026-04-13 | vtf:`c5b3fe9` | Deployed to vtf.dev ✅ |
| Auth fix + logout | 2026-04-15 | vtf:`89de243d` | Playwright verified ✅ |
| Token endpoint | 2026-04-14 | vtf:`abf82d2` | 11 E2E pass ✅ |

## Test Inventory

| Area | Unit | E2E | Total |
|------|------|-----|-------|
| vafi (all) | 305 | 12 | 317 |
| vafi bridge | 110 | 12 | 122 |
| vtf backend | 1,982 | — | 1,982 |
| vtf frontend | 336 | 86 | 422 |
| Chat widget Playwright | — | 13 | 13 |
| **Platform total** | **2,623** | **111** | **2,734** |

## Doc Health

| Document | Status | Last verified |
|----------|--------|--------------|
| [bridge/chat-widget-DESIGN.md](bridge/chat-widget-DESIGN.md) | active (phases 8–9 remaining) | 2026-04-17 |
| [bridge/chat-widget-REWORK-PLAN.md](bridge/chat-widget-REWORK-PLAN.md) | completed | 2026-04-17 |
| [bridge/chat-widget-ISSUES.md](bridge/chat-widget-ISSUES.md) | completed (all fixed) | 2026-04-17 |
| [bridge/agent-bridge-REWORK-PLAN.md](bridge/agent-bridge-REWORK-PLAN.md) | completed | 2026-04-17 |
| [bridge/agent-bridge-IMPLEMENTATION-PLAN.md](bridge/agent-bridge-IMPLEMENTATION-PLAN.md) | superseded | 2026-04-17 |
| [bridge/agent-bridge-service-DESIGN.md](bridge/agent-bridge-service-DESIGN.md) | active | — |
| [bridge/context-hydration-AUDIT.md](bridge/context-hydration-AUDIT.md) | active (fixes pending) | — |
| [harness-refactor/INDEX.md](harness-refactor/INDEX.md) | deferred | 2026-04-17 |
