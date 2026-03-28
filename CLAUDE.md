# CLAUDE.md — vafi

## What this repo is

vafi (Viloforge Agentic Fleet Infrastructure) is an autonomous AI agent
fleet execution platform. It deploys agents as Kubernetes pods that pull
tasks from vtaskforge (vtf), execute them via Claude Code CLI, run
verification gates, and report results — without a human in the loop.

## Repository structure

```
charts/vafi/      Helm chart for deploying vafi (executor + CXDB)
images/           Dockerfiles for vafi image hierarchy
  base/           Node + system tools
  claude/         Claude Code CLI + cxtx binary
  agent/          Controller source + methodologies + entrypoint
src/controller/   Python asyncio controller (the core of vafi)
  context.py      Task context file generation (.vafi/context.md)
  controller.py   Poll/claim/execute/report loop (executor + judge roles)
  invoker.py      Harness invocation (Claude Code subprocess)
  config.py       Agent configuration from environment variables
  gates.py        Verification gate runner
  heartbeat.py    Agent and task heartbeat loops
  vtf_client.py   HTTP client for vtf REST API
  worksources/    WorkSource protocol and vtf implementation
methodologies/    Role-specific agent instructions
  executor.md     Generic executor methodology (60 lines)
  judge.md        Generic judge methodology (65 lines)
templates/        Prompt templates (judge.txt)
scripts/          Build scripts (build-images.sh, push-images.sh)
docs/             Design documents, contracts, plans
tests/            Unit tests (112 tests)
```

## Key commands

```bash
make help           # Show all available targets
make build          # Build agent image (uses pinned base/claude)
make build-base     # Rebuild base image layer
make build-claude   # Rebuild claude image layer
make push           # Push images to registry
make test           # Run controller unit tests
make helm-template  # Render Helm chart with default values
make helm-lint      # Validate Helm chart
```

## Architecture

Agents (executor and judge) run as Kubernetes pods. Both use the same
container image — the entrypoint copies the role-specific methodology
based on `VF_AGENT_ROLE` environment variable.

**Context passing:** The controller writes `.vafi/context.md` into the
task workdir before each harness invocation. This file contains the task
spec, all reviews, all notes, and role-specific instructions. Agents
communicate through this file — each agent's output (stored in vtf) is
materialized in the next agent's context file.

**Deployment:** Helm chart at `charts/vafi/`. Environment-specific values
and release scripts are in a separate private deploy repo.

## Design docs

See `docs/` for navigation. Key documents:
- `docs/vafi-DESIGN.md` — architecture
- `docs/controller-DESIGN.md` — controller decisions D1-D8
- `docs/agent-context-passing-DESIGN.md` — context file mechanism
- `docs/generic-agents-spike-ANALYSIS.md` — spike results and Rumsfeld matrix
- `docs/helm-migration-PLAN.md` — Helm migration plan
