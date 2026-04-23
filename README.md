# vafi

Viloforge Agentic Fleet Infrastructure — an autonomous AI agent execution platform. Deploys executor and judge agents as Kubernetes pods that pull tasks from [vtaskforge](https://github.com/vilosource/vtaskforge), execute them via an AI harness (Claude Code, or any compatible CLI), and report results without a human in the loop.

## How it works

```
vtf board → executor claims task → clones repo → runs Claude Code → commits → reports
                                                                         ↓
                                          judge picks up review → runs tests → approves or rejects
                                                                         ↓
                                                              rejected → executor reworks with feedback
```

**Executor agents** poll vtf for claimable tasks. When a task is found, the controller clones the repo into a per-task workdir, writes a context file (`.vafi/context.md`) containing the spec and any prior feedback, and invokes Claude Code as a subprocess. The harness reads the context, implements the code, runs tests, and commits.

**Judge agents** poll vtf for tasks pending review. They enter the same shared workdir, run the test suite independently, review the code, and submit a structured verdict (approve or request changes).

**Context passing** — agents communicate through the task system. Each agent's output (completion reports, reviews) is stored in vtf. Before each invocation, the controller materializes the full task history into `.vafi/context.md` in the workdir. The next agent reads this file and has complete situational awareness.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Kubernetes cluster                              │
│                                                  │
│  ┌──────────────┐    ┌──────────────┐            │
│  │  Executor pod │    │  Judge pod   │            │
│  │  (controller) │    │  (controller) │           │
│  │       ↓       │    │       ↓       │           │
│  │  Claude Code  │    │  Claude Code  │           │
│  └──────┬────────┘    └──────┬────────┘           │
│         │ shared volume      │                    │
│         └────────┬───────────┘                    │
│                  ↓                                │
│         /sessions/task-<id>/    (workdirs)         │
│                                                   │
│  ┌──────────────┐                                 │
│  │  CXDB        │  ← execution trace store        │
│  └──────────────┘                                 │
└─────────────────────────────────────────────────┘
          │
          ↓
  ┌──────────────┐
  │  vtf API     │  ← task board (separate deployment)
  └──────────────┘
```

- **Same container image** for both executor and judge — the role is set via `VF_AGENT_ROLE` env var
- **Shared volume** at `/sessions/` — workdirs persist across agents. Judge reviews in the same workdir the executor used.
- **CXDB** captures full execution traces (every prompt, tool call, response) tagged by task ID

## Components

| Component | Purpose |
|-----------|---------|
| `src/controller/` | Python asyncio controller — poll/claim/execute/report loop |
| `methodologies/` | Generic agent instructions (executor.md, judge.md) |
| `charts/vafi/` | Helm chart for deploying executor + judge + CXDB |
| `images/` | 3-layer Docker image: base → claude → agent |

## Image hierarchy

```
vafi-base     Node 20 + git, python, pytest, jq, ssh
    ↓
vafi-claude   + Claude Code CLI + cxtx (trace capture)
    ↓
vafi-agent    + controller source + methodologies + entrypoint
```

Base and claude are pinned to versioned tags and rebuilt infrequently. Only the agent layer is rebuilt per deploy.

## Deployment

vafi is deployed via **Argo CD** (GitOps). The Helm chart in `charts/vafi/` is rendered by Argo CD using values from the separate `vafi-deploy` repo (`environments/dev.yaml`, `environments/prod.yaml`).

To roll out a new agent image:

```bash
# 1. Build + push (vafi-deploy/scripts/release.sh dev)
# 2. Edit vafi-deploy/environments/dev.yaml: image.agent.tag=<git-sha>
# 3. Commit + push to vafi-deploy main — Argo CD syncs within ~3 min
#    (force immediate: argocd app sync vafi-dev)
```

Direct `helm upgrade` and `kubectl set image` will be reverted by Argo CD's selfHeal.

The Helm chart supports:
- Executor and judge as separate deployments with independent replica counts
- CXDB as a toggleable component (`cxdb.enabled`)
- Ingress and cert-manager integration
- Pre-created secrets (`secrets.existingSecret`) or chart-generated secrets

## Running locally (without Kubernetes)

For development and testing, you can run the controller directly:

```bash
# Install
pip install -e .

# Configure
export VF_VTF_API_URL=http://localhost:8000
export VF_VTF_TOKEN=<your-vtf-token>
export VF_AGENT_ROLE=executor
export VF_SESSIONS_DIR=/tmp/sessions

# Run
python -m controller
```

The controller will poll the local vtf instance for tasks and execute them via Claude Code.

## Tests

```bash
python -m pytest tests/ -v    # 112 tests
```

## Key design documents

| Document | Purpose |
|----------|---------|
| [docs/vafi-DESIGN.md](docs/vafi-DESIGN.md) | Architecture and design decisions |
| [docs/controller-DESIGN.md](docs/controller-DESIGN.md) | Controller decisions D1-D8 |
| [docs/agent-context-passing-DESIGN.md](docs/agent-context-passing-DESIGN.md) | Context file mechanism for agent communication |
| [docs/generic-agents-spike-ANALYSIS.md](docs/generic-agents-spike-ANALYSIS.md) | Spike results and Rumsfeld matrix |

## Related projects

- [vtaskforge](https://github.com/vilosource/vtaskforge) — the task board that vafi agents work against
- [cxdb](https://github.com/vilosource/cxdb) — execution trace store

## License

MIT

<!-- webhook pipeline validated 2026-04-23 -->

<!-- multi-product pipeline test 2026-04-23 -->
