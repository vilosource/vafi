# vafi Documentation

Last updated: 2026-04-18

## Status

**[STATUS-AUDIT.md](STATUS-AUDIT.md)** — Current status of all phase-tracked work across the platform.

## How to read these docs

**Start here:** [ARCHITECTURE-SUMMARY.md](ARCHITECTURE-SUMMARY.md) — everything you need to understand vafi in one page.

**Then, based on what you're doing:**

- Building or modifying harness images? Read [harness-images-ARCHITECTURE.md](harness-images-ARCHITECTURE.md)
- Working on the vtf/vafi boundary? Read [vtf-vafi-interface-CONTRACT.md](vtf-vafi-interface-CONTRACT.md)
- Adding context passing to the controller? Read [agent-context-passing-DESIGN.md](agent-context-passing-DESIGN.md)
- Working on the architect agent or vafi-console? Read [architect-agent-IMPLEMENTATION.md](architect-agent-IMPLEMENTATION.md)
- Working on the agent bridge service? Read [bridge/agent-bridge-service-DESIGN.md](bridge/agent-bridge-service-DESIGN.md) (start with the "Start Here" section)
- Landing fixes from the 2026-04-18 vtf/vafi discovery pass? Read [vtf-vafi-fixes-PLAN.md](vtf-vafi-fixes-PLAN.md)

## Active Documents

These are authoritative and kept up-to-date.

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE-SUMMARY.md](ARCHITECTURE-SUMMARY.md) | System overview — components, controller loop, multi-harness, cxdb, infrastructure, key decisions |
| [harness-images-ARCHITECTURE.md](harness-images-ARCHITECTURE.md) | Multi-harness image architecture — Claude vs Pi, Dockerfiles, config files, CLI invocation, output parsing, how to add a new harness |
| [vtf-vafi-interface-CONTRACT.md](vtf-vafi-interface-CONTRACT.md) | API contract between vtf and vafi — 14 interaction points, WorkSource protocol, gap analysis (GAP-1/GAP-4 resolved) |
| [agent-context-passing-DESIGN.md](agent-context-passing-DESIGN.md) | Context file design — `.vafi/context.md` materialized before each harness invocation |
| [architect-agent-IMPLEMENTATION.md](architect-agent-IMPLEMENTATION.md) | Architect agent — pod lifecycle, vafi-console integration, WebSocket proxy, MCP tools |
| [bridge/agent-bridge-service-DESIGN.md](bridge/agent-bridge-service-DESIGN.md) | Agent bridge service — HTTP API for agent prompts, Pi RPC process manager, locked/ephemeral sessions. Phase A+B implemented, Phase C (channels) remaining. |
| [bridge/agent-bridge-IMPLEMENTATION-PLAN.md](bridge/agent-bridge-IMPLEMENTATION-PLAN.md) | Original 10-phase TDD implementation plan with acceptance criteria (historical). |
| [vtf-vafi-fixes-PLAN.md](vtf-vafi-fixes-PLAN.md) | 2026-04-18 discovery fixes — MCP `requires` overload, `parse_bool("")` bug, hand-rolled pi executor + wrong liveness probe, `VF_MAX_REWORK` not enforced, supervisor gap. 5 fixes ranked, ~9 hr critical path. |
| [bridge/agent-bridge-REWORK-PLAN.md](bridge/agent-bridge-REWORK-PLAN.md) | 18-item rework plan correcting implementation deviations (historical). |

## Archived Documents

Historical docs preserved for context. These were accurate when written but have been superseded by the active docs above. Each has an archive banner linking to the current authoritative source.

| Document | What it was | Why archived |
|----------|------------|-------------|
| [vafi-DESIGN.md](archive/vafi-DESIGN.md) | Original architecture (1,345 lines) | Superseded by ARCHITECTURE-SUMMARY + harness doc. Missing Pi, cxdb, Helm. |
| [controller-DESIGN.md](archive/controller-DESIGN.md) | Controller decisions D1-D8 | Absorbed into summary. Spikes and GAPs shown as open but resolved. |
| [vafi-project-PLAN.md](archive/vafi-project-PLAN.md) | Milestone plan M0-M4 | M0-M2 complete. Pi listed as out-of-scope (now done). Old server IPs. |
| [architect-agent-DESIGN.md](archive/architect-agent-DESIGN.md) | Architect design proposal | Superseded by implementation doc. No Pi support, cxdb tagged future. |
| [cxdb-vtf-integration-DESIGN.md](archive/cxdb-vtf-integration-DESIGN.md) | cxdb integration proposal | vafi-side fully implemented. Stale namespace references. |
| [helm-migration-PLAN.md](archive/helm-migration-PLAN.md) | Kustomize to Helm migration | Migration completed. |
| [m2-simulation-ANALYSIS.md](archive/m2-simulation-ANALYSIS.md) | M2 post-mortem (8 tasks, 94 tests) | Historical snapshot. Current state: 193 tests. |
| [k8s-harness-spikes-ANALYSIS.md](archive/k8s-harness-spikes-ANALYSIS.md) | K8s spike results (auth, clone, exec) | Findings absorbed into decisions. Stale namespace refs. |
| [generic-agents-spike-ANALYSIS.md](archive/generic-agents-spike-ANALYSIS.md) | Generic agent spike (Rumsfeld matrix) | Spike complete, findings applied. |
| [dev-server-setup-ANALYSIS.md](archive/dev-server-setup-ANALYSIS.md) | Fuji server provisioning analysis | Setup completed. |

## External

| Document | Where it belongs |
|----------|-----------------|
| [viloforge-cloudflare-repo-SPECIFICATION.md](viloforge-cloudflare-repo-SPECIFICATION.md) | Should be in the `viloforge-cloudflare` repo. Kept here until migrated. |
