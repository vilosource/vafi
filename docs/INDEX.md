# vafi Documentation Index

## Design

| Document | Description | Status |
|----------|-------------|--------|
| [vafi-DESIGN.md](vafi-DESIGN.md) | Main architecture document — problem statement, four-layer architecture, GitLab Runner prior art, agent config, instruction delivery, prompt construction, output parsing, image strategy, K8s topology, gate execution | Draft |
| [controller-DESIGN.md](controller-DESIGN.md) | Controller design decisions D1-D8 — Python asyncio, session resumption, state machine changes, poll targets, rework limits, dynamic workdirs, cleanup, controller/orchestrator separation. Also documents the current simulation architecture and what works/doesn't. | Draft |

## Contracts

| Document | Description | Status |
|----------|-------------|--------|
| [vtf-vafi-interface-CONTRACT.md](vtf-vafi-interface-CONTRACT.md) | API contract between vtf and vafi — 14 interaction points with request/response examples, 5 vtf gaps (GAP-1 through GAP-5), vafi-side interface design (WorkSource protocol, VtfClient, VtfWorkSource), shared data types | Draft |

## How to read these docs

1. Start with **controller-DESIGN.md** for the problem statement and what the simulation proved
2. Read **vafi-DESIGN.md** for the full architecture (four layers, K8s, agent config, gates, output parsing)
3. Reference **vtf-vafi-interface-CONTRACT.md** when implementing either side of the vtf/vafi boundary

## Key decisions captured

- K8s is the deployment target (not Docker Compose)
- vafi is a fresh project, independent of vf-agents
- Controller is Python asyncio, inside the pod
- One image, role selected by `VF_AGENT_ROLE` env var
- Gates (test commands) are source of truth, never parse LLM output
- WorkSource protocol decouples controller from vtf
- Spikes 1 and 2 resolved — session files don't survive pod restarts (fallback is normal path), auth resolves from `$HOME` independent of cwd
