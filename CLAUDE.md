# CLAUDE.md — vafi

## What this repo is

vafi (Viloforge Agentic Fleet Infrastructure) is an autonomous AI agent
fleet execution platform. It deploys agents as Kubernetes pods that pull
tasks from vtaskforge (vtf), execute them via Claude Code CLI, run
verification gates, and report results — without a human in the loop.

## Repository structure

```
ansible/          Server provisioning (k3s, OS config)
images/           Dockerfiles for vafi image hierarchy
k8s/              Kubernetes manifests (Kustomize)
  vafi-system/    vtf dogfood stack (Postgres, Redis, API, Celery)
  vafi-agents/    Agent pools (executor, judge, supervisor)
  overlays/       Environment-specific patches
scripts/          Build and operational scripts
src/controller/   Python asyncio controller (the core of vafi)
methodologies/    Role-specific agent instructions (executor.md, judge.md)
templates/        Prompt templates (task.txt, rework.txt, review.txt)
docs/             Design documents, contracts, plans
```

## Key commands

```bash
make help         # Show all available targets
make provision    # Full server provisioning (OS + k3s)
make k3s          # k3s install/update only
make build        # Build container image layers
make push         # Import images to k3s host
make deploy       # Apply k8s manifests
make all          # Build, push, deploy, seed
```

## Infrastructure

- **Dev cluster:** k3s on `vafi-1.dev.viloforge.com` (dedicated server)
- **Kubeconfig:** `~/.kube/vafi-dev.yaml`
- **Namespaces:** `vafi-system` (vtf stack), `vafi-agents` (agent pools)
- **Images:** `vafi-base` -> `vafi-claude` -> `vafi-agent` (built locally, imported via SSH)

## Design docs

See `docs/INDEX.md` for navigation. Key documents:
- `docs/vafi-DESIGN.md` — architecture
- `docs/controller-DESIGN.md` — controller decisions D1-D8
- `docs/vtf-vafi-interface-CONTRACT.md` — vtf API contract
- `docs/vafi-project-PLAN.md` — milestone plan M0-M4
