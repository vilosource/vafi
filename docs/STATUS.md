# vafi — Status Dashboard

Last updated: 2026-04-17 (by: claude)

---

## Active Work

| Item | Area | Priority | Blocked by | Notes |
|------|------|----------|-----------|-------|
| Chat widget Phase 8: Session continuity | bridge + vtf | Medium | — | Load prior cxdb context on lock acquire so agent remembers previous conversations |
| Chat widget Phase 9: Display history | bridge + vtf | Medium | Phase 8 | Render prior cxdb conversation turns in widget |
| Console terminal session reuse | vafi-console | Low | — | connectToPod() clears terminal on every click. Proposed fix: tmux. No doc yet. |
| Slack adapter | bridge | Low | — | Channel adapter interface exists (`adapters/protocol.py`), Slack not implemented |

## Deferred

| Item | Area | Reason | Resume when |
|------|------|--------|-------------|
| Harness boundary refactor (9 phases) | vafi core | Design complete, zero implementation | Adding a 3rd harness (beyond Claude + Pi) |
| Context hydration hardening | bridge | C1 (shell injection) and C2 (inline config) identified in audit | Next bridge security pass |

## Recently Completed

| Item | Completed | Commits | Verified |
|------|-----------|---------|----------|
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
