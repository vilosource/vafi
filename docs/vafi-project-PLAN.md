# vafi Project Plan

Status: Draft (2026-03-22)

## Overview

Build an autonomous agent fleet that pulls tasks from vtf, executes
them via Claude Code CLI, runs verification gates, and reports results
without a human in the loop.

vafi is built from scratch on Kubernetes. No dependency on vf-agents.

---

## Milestone 0: Spikes — DONE

Technical validation of Claude Code CLI behavior.

| Spike | Status | Finding |
|-------|--------|---------|
| Session resume across containers | Resolved | Session files live in `~/.claude/` inside the container, do not survive pod restarts. Fallback (fresh session + full spec + judge feedback) is the normal path for fleet ops. |
| Auth resolution vs cwd | Resolved | Credentials resolve from `$HOME/.claude/`, completely independent of cwd. Controller can invoke harness with different workdirs per task. |

No blockers from CLI behavior.

---

## Milestone 1: K8s Platform + Image

**Goal:** A running K8s cluster with vafi's container image built and
deployable. The foundation everything else runs on.

### K8s cluster — k3s on Hyper-V VM (decided)

**Setup:** Ubuntu Server 24.04 on Hyper-V, k3s installed via standard
script. `kubectl` on WSL2 points at the VM's IP. Production cluster
type (AKS or other) is a separate future decision — same manifests.

**VM provisioning:**
- [ ] Create Hyper-V VM (Ubuntu Server 24.04, minimal)
- [ ] Static IP or DHCP reservation for stable address
- [ ] Install k3s (`curl -sfL https://get.k3s.io | sh -`)
- [ ] Copy kubeconfig to WSL2 (`~/.kube/config`), update server IP
- [ ] Verify `kubectl get nodes` works from WSL2

**Cluster configuration:**
- [ ] Networking: vtf API reachable from agent pods, git server (GitLab) reachable
- [ ] Storage: PersistentVolume for `/sessions/` (k3s local-path-provisioner works out of the box)
- [ ] Secrets: Claude Code credentials (`~/.claude/`), SSH keys for git, vtf API token
- [ ] Namespaces: `vafi-system`, `vafi-agents`

### Container images

**Build on WSL2, import to k3s VM** (no registry needed for dev):
```
docker save vafi-agent:latest | ssh vafi-vm 'sudo k3s ctr images import -'
```

- [ ] `vafi-base` — Dockerfile: `node:20-bookworm-slim` + git, curl, ssh, jq, python
- [ ] `vafi-claude` — Dockerfile: `vafi-base` + Claude Code CLI
- [ ] `vafi-agent` — Dockerfile: `vafi-claude` + Python controller, methodologies, templates
- [ ] Build script that builds all layers and imports to the VM
- [ ] Container registry decision deferred — local import is sufficient for dev

### Value gate

A `vafi-agent` pod starts in the K8s cluster, the controller process
runs inside it, and it can reach the vtf API. No task execution yet —
just proof the platform works.

### Open decisions

| Decision | Options | Notes |
|----------|---------|-------|
| VM sizing | 2 CPU / 4 GB vs 4 CPU / 8 GB | Depends on how many concurrent agent pods we want |
| vtf deployment | In-cluster (vafi-system namespace) vs external | Dogfood instance currently runs on localhost:8001 |
| Container registry | Deferred — local import for dev, GHCR or ACR for prod | Not needed until CI/CD or multi-node |

---

## Milestone 2: Controller MVP

**Goal:** One executor picks up one task from vtf, clones the repo,
invokes Claude Code, runs gates, and reports the result back. Deployed
on K8s from day one.

### vtf changes needed (parallel stream, vtaskforge repo)

- [ ] GAP-4: State machine `changes_requested` -> `doing` transition
- [ ] GAP-1: Agent registration upsert (create or update by name)

### vafi work

- [ ] Python project scaffolding (`pyproject.toml`, package structure)
- [ ] `VtfClient` — async HTTP client for vtf API
  - `register_agent()`, `list_claimable()`, `claim_task()`,
    `heartbeat()`, `complete_task()`, `fail_task()`, `get_project()`,
    `add_note()`, `get_task()`
- [ ] `WorkSource` protocol (abstract interface)
- [ ] `VtfWorkSource` — vtf implementation of WorkSource
- [ ] Controller loop: poll -> claim -> clone -> build prompt -> invoke harness -> parse output -> run gates -> report
- [ ] Prompt template: `templates/task.txt`
- [ ] Methodology file: `methodologies/executor.md`
- [ ] Credential staging at pod start (copy to `$HOME/.claude/`)
- [ ] K8s manifests: executor Deployment (replicas=1), PVC for sessions
- [ ] Docker Compose for local dev/testing only

### Value gate

`kubectl apply` executor deployment -> pod starts -> registers with
vtf -> picks up a task -> clones repo -> Claude Code executes ->
gates pass -> vtf shows task as complete.

---

## Milestone 3: Rework & Judge

**Goal:** Full executor -> judge -> rework cycle works autonomously.

### vtf changes needed (parallel stream, vtaskforge repo)

- [ ] GAP-3: Task metadata JSON field (structured execution data)

### vafi work

- [ ] Judge role: same image, different methodology, polls `pending_completion_review`
- [ ] Methodology file: `methodologies/judge.md`
- [ ] Prompt template: `templates/review.txt`
- [ ] Prompt template: `templates/rework.txt`
- [ ] Rework detection: poll `changes_requested` tasks assigned to this agent
- [ ] Session resume: attempt `--resume` if same pod, fallback to fresh + context
- [ ] Max rework attempts (3, configurable via `VF_MAX_REWORK`)
- [ ] Rework attempt counting via vtf reviews API
- [ ] K8s manifests: judge Deployment (replicas=1)

### Value gate

Executor completes task -> judge reviews -> rejects with feedback ->
executor picks up rework -> fixes issues -> judge approves -> task done.

---

## Milestone 4: Multi-executor & Robustness

**Goal:** Multiple executors processing a backlog unattended, surviving
failures gracefully.

### vtf changes needed (parallel stream, vtaskforge repo)

- [ ] GAP-2: Project expansion on task response (`?expand=project`)
- [ ] GAP-5: Submittable tasks endpoint (draft tasks with deps met)

### vafi work

- [ ] Scale executor deployment (`replicas=3`)
- [ ] Heartbeat coroutine: async heartbeat during task execution
- [ ] Claim expiry recovery: tasks return to claimable when heartbeat stops
- [ ] Error classification: auth failure, rate limit, OOM, timeout, unknown
- [ ] Transient error retry with backoff
- [ ] Supervisor role: DAG-aware task submission (polls draft tasks, checks deps, submits)
- [ ] K8s manifests: supervisor Deployment (replicas=1)
- [ ] Logging and observability
- [ ] Cost tracking (aggregate `total_cost_usd` from harness output)

### Value gate

3 executors + 1 judge + 1 supervisor processing a 10+ task backlog
overnight. At least one simulated failure (kill a pod mid-task) with
successful recovery (task returns to claimable, another executor
picks it up).

---

## Dependencies

```
M0 (spikes) ──── DONE
     |
     v
M1 (K8s platform + image)
     |
     v
M2 (controller MVP) <── vtf GAP-4, GAP-1 (parallel stream)
     |
     v
M3 (rework & judge) <── vtf GAP-3 (parallel stream)
     |
     v
M4 (multi-executor)  <── vtf GAP-2, GAP-5 (parallel stream)
```

### vtf GAP work (parallel stream in vtaskforge repo)

These are code changes in `~/GitHub/vtaskforge/`, not in vafi. They
can be developed and merged independently, ahead of the vafi milestone
that needs them.

| GAP | Change | Blocks | Complexity |
|-----|--------|--------|------------|
| GAP-4 | State machine: `changes_requested` -> `doing` | M2 (rework) | One-line change |
| GAP-1 | Agent registration upsert | M2 (restart) | Small — add upsert logic to agent viewset |
| GAP-3 | Task metadata JSON field | M3 (session resume) | Medium — new model field, migration, serializer |
| GAP-2 | Project expansion on task response | M4 (performance) | Small — add expand support to serializer |
| GAP-5 | Submittable tasks endpoint | M4 (supervisor) | Medium — new endpoint with dependency checking |

**Recommended approach:** Implement GAP-4 and GAP-1 as soon as M1
is underway, so they're ready when M2 controller code needs them.

---

## First target project

The first project vafi executes tasks for. Candidates:

| Project | Pros | Cons |
|---------|------|------|
| vtaskforge | Dogfooding — vafi builds its own task tracker | Complex test suite, Docker Compose dependencies |
| A simple project | Fewer moving parts, faster validation | Less meaningful proof |

Decision needed before M2 — determines what the project environment
namespace looks like and what gates run.

---

## What is NOT in scope

- Multi-project execution (one project for MVP, expand later)
- Project environment namespaces (M2-M4 use a single hardcoded project)
- HPA autoscaling (manual `kubectl scale` is sufficient)
- Cost budgets and billing
- Event stream / SSE integration
- Multi-harness support (Claude Code only for now)
