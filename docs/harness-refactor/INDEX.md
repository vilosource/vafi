# Harness Boundary Refactor

---
status: deferred
last_verified: 2026-04-17
---

> **Not started.** Design docs are complete. Zero implementation. Resume when adding a third harness (beyond Claude and Pi) makes this a priority.

Refactoring vafi to remove all harness-specific code from services. After this refactor, adding a new AI harness requires zero source code changes — only a new Docker image and yaml config entries.

## Documents

| Document | Purpose |
|----------|---------|
| [WORK-PROTOCOL.md](WORK-PROTOCOL.md) | Rules for every phase: TDD, E2E gates, no improvisation |
| [PHASE-0-harness-scripts.md](PHASE-0-harness-scripts.md) | Create init.sh, connect.sh, run.sh in images (additive) |
| [PHASE-1-config-restructure.md](PHASE-1-config-restructure.md) | Split config into harnesses.yaml, roles.yaml, infra.yaml |
| [PHASE-2-entrypoint.md](PHASE-2-entrypoint.md) | Entrypoint sources init.sh, zero harness names |
| [PHASE-3-console-connect.md](PHASE-3-console-connect.md) | Console uses connect.sh for all harnesses |
| [PHASE-4-console-podspec.md](PHASE-4-console-podspec.md) | PodSpecBuilder reads config, zero hardcoded values |
| [PHASE-5-controller-run.md](PHASE-5-controller-run.md) | Controller calls run.sh, output_format from config |
| [PHASE-6-bridge.md](PHASE-6-bridge.md) | Bridge uses config-driven pods and run.sh |
| [PHASE-7-proof.md](PHASE-7-proof.md) | bash-agent harness with zero code changes (acid test) |
| [PHASE-8-final-gate.md](PHASE-8-final-gate.md) | All 9 ACs verified, grep check, full checklist |

## Design

The design document is at: `KB/viloforge/vafi-console-harness-boundary-DESIGN.md`

## Execution Order

```
Phase 0 (additive, safe)
    ↓
Phase 1 (config, additive)
    ↓
Phase 2 (entrypoint, behavior change)
    ↓
Phase 3 (console terminal, behavior change)
    ↓
Phase 4 (console pods, behavior change)
    ↓
Phase 5 (controller, behavior change)
    ↓
Phase 6 (bridge, behavior change)
    ↓
Phase 7 (proof: zero-code harness addition)
    ↓
Phase 8 (final gate: all ACs, grep check)
```

Each phase has its own gate checklist. Do not proceed to the next phase until the current phase's gate passes.
