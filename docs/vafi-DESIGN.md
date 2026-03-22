# vafi — Viloforge Agentic Fleet Infrastructure

Status: Draft (2026-03-22)

## Problem Statement

vf-agents was built for a human standing at the controls. Every execution
begins with a human typing `vfa run` or `vfa session start`, and every
result ends with a human reading the output. The system is a cockpit —
powerful, flexible, and entirely manual.

This design made the right trade-offs for the first use case: a developer
running AI agents against codebases, iterating on prompts and harness
configurations, evaluating results interactively. The three-axis model
(runtime, provider config, profile) gives that developer precise control
over every dimension of an agent run.

But vtaskforge has proven a second use case that vf-agents cannot serve:
**autonomous agent fleets that pull work from a task system, execute it,
verify it, and report results — without a human in the loop**.

### What vtaskforge proved

Over Phases 0-9 of vtaskforge development (49 tasks, 870+ tests), we ran
an end-to-end simulation of autonomous agent execution inside a single
Claude Code session. A human acted as supervisor, dispatching Sonnet
executors and Opus judges as subagents, tracking state via the vtf API.

The simulation validated the process:

| Aspect | Evidence |
|--------|----------|
| YAML specs are sufficient for execution | Phase 9: all tasks completed from specs alone |
| Reject/rework cycle works | Phase 9 task 9.2: judge rejected, executor reworked, approved on attempt 2 |
| Parallel execution is safe | Phase 9 wave 4: four executors, zero merge conflicts |
| Judges catch real issues | Stale comments, missing tests, N+1 query risks |
| vtf state machine handles the full lifecycle | draft -> todo -> doing -> review -> done all work |

But the simulation hit a wall. With one human driving one session, it
cannot:

- **Run unattended** — someone must be present to drive the loop
- **Scale horizontally** — one session, one executor at a time
- **Survive failures** — if the session dies, all in-flight work is lost
- **Isolate executors** — subagents share the supervisor's filesystem
- **Control resources** — no per-task token limits, timeouts, or cost caps
- **Track execution** — no heartbeats, no audit trail during task work

These are not vtaskforge limitations. They are vf-agents limitations.
vtf has the API surface for all of this — claimable task queries, claim
expiry, heartbeats, review submissions. What is missing is a way to run
agents that use it.

### Why the current architecture cannot serve this

vf-agents has two execution modes, and neither fits:

**`vfa run` (single-shot):** One container, one prompt, one result. The
container starts, the harness runs, the container stops. There is no loop,
no polling, no state between invocations. You could wrap it in a shell
script that calls `vfa run` in a loop, but you would lose session
resumption (each run starts fresh), pay the container startup cost per
task, and have no heartbeats during execution.

**`vfa session` (multi-turn):** A long-lived container where a human sends
follow-up prompts via `vfa session send`. This is closer — the container
stays alive and the harness supports session resumption. But the loop is
still human-driven. There is no polling, no claiming, no automated
verification. And session state is tracked on the host
(`~/.vf-agents/active-session`), not inside the container, making it
impossible for the agent to manage its own work autonomously.

The gap is structural, not incremental. This is not a feature to add to
vf-agents — it is a **separate system** with different users, different
deployment model, and different lifecycle. vf-agents is a CLI for humans.
What we need is infrastructure for autonomous agents.

### Why a separate project: vafi

vf-agents and vafi serve different users and have different concerns:

| | vf-agents | vafi |
|--|-----------|------|
| **User** | Human developer | Automated system (vtf) |
| **Lifecycle** | CLI invocation → result | Long-running deployed service |
| **Deployment** | Installed on dev machine | Deployed as infrastructure |
| **Core concern** | "Run this prompt in a container" | "Poll for work, execute, verify, report" |
| **Analogy** | Docker CLI | GitLab Runner |

The pattern — poll for work, claim it, execute it, verify it, report
it — is universal. CI/CD runners, evaluation harnesses, batch processing
pipelines, and automated code review systems all follow the same loop.
vtf is the first work source, but vafi is designed to be work-source
agnostic.

vafi **consumes** vf-agents building blocks (image hierarchy, credential
staging patterns, adapter knowledge) but is independently developed,
deployed, and versioned.

---

## Current Architecture (Relevant Context)

### The three-axis model

vf-agents separates three concerns:

```
Provider Config  x  Run Profile  x  Prompt  =  Agent Run
(who to talk to)   (how to run)    (what)      (execution)
```

This model is correct and does not change. vafi adds a fourth axis:
**work source** — where tasks come from.

### Instruction assembly

Profiles point to an instruction directory containing `common.md` (shared)
and optional runtime-specific files (e.g., `claude-code.md`). The
assembler concatenates them and mounts the result as the runtime's
instruction file (e.g., `/workdir/CLAUDE.md`).

**vafi problem:** The instruction file is mounted at the workdir
path, which is set once at container creation. In vafi, the workdir
changes per task. The mounted instruction file does not follow.

### Container lifecycle

Both `vfa run` (ephemeral) and `vfa session` (persistent) manage container
lifecycle from the host. The host decides when to start, exec into, and
stop containers.

**vafi problem:** In vafi, the container must be self-managing.
It starts, runs a controller loop internally, and handles multiple tasks
autonomously. The host starts the container but does not drive it.

### Session management

Session state (container ID, session ID mapping) lives on the host at
`~/.vf-agents/active-session` and `~/.vf-agents/session-map.json`.

**vafi problem:** Session state must be accessible from inside the
container. The controller needs to resume sessions for rework, and session
files must be on a shared volume so any executor can pick up rework on
any task.

---

## Prior Art: GitLab Runner

vafi is not a novel architecture. It is the **GitLab Runner model**
applied to AI agent execution. GitLab Runner is battle-tested
infrastructure that solved the exact problems we face — Docker-based job
execution, project-agnostic runners, credential injection, workspace
setup, and multi-project scaling. Understanding how GitLab solved these
problems informs our design and prevents us from reinventing solutions
to already-solved problems.

### The analogy

| GitLab | Our system | Notes |
|--------|-----------|-------|
| GitLab Server | vtf API | Source of truth for all work state |
| GitLab Runner | vf-agents controller | Polls for work, executes it, reports back |
| Runner registration | Agent registration with vtf | Identity + tag-based routing |
| Pipeline | Milestone | Ordered collection of work |
| Job | Task | Single unit of work |
| `.gitlab-ci.yml` | Task spec YAML | Declarative work definition |
| Runner tags | Agent tags | Route work to capable agents |
| Job `image:` | Agent/task image | Container environment for execution |
| Runner executor | vafi orchestrator | Container lifecycle management |
| CI_JOB_TOKEN | Agent credentials | Scoped auth for repo access |
| Artifacts | Commits + completion reports | Work outputs |
| Services | Supporting containers (DB, etc.) | Infrastructure dependencies |
| Helper container | Controller (pre-task phase) | Clone repo, prepare workspace |
| Build container | Harness subprocess | Execute the actual work |

### Key lessons from GitLab Runner

**1. The job is self-describing, not the runner.**

GitLab Runner does not know which repo to clone or which image to use.
The job payload (from the server) contains everything: repo URL, commit
ref, container image, environment variables, scripts to run. The runner
is generic infrastructure.

**Implication for us:** vtf stores project execution metadata (repo URL,
default branch) on the project model. When vafi claims a task, the
response includes the project context — repo URL, branch, spec,
everything needed to execute. vafi is completely generic — no
project-specific config, no project mappings. A single executor
container can serve any project because every task carries its full
execution context.

This follows the GitLab model where the server is the single source of
truth for project knowledge. vtf is not a git server, but it stores
the repo URL as project metadata, just as any project management tool
links to a repo.

**2. Image selection happens at the job level.**

GitLab's `image:` keyword lets each job specify its container image. The
runner has a default image, but jobs override it. Admins can restrict
allowed images (`allowed_images` in runner config).

**Implication for us:** The agent config sets a default image. But a vtf
project or task spec can override it — a Python project specifies a
Python-tooled image, a Node project specifies a Node-tooled image. This
is how we handle heterogeneous workloads without building a new agent
type per project.

**3. Docker access via socket binding (pragmatic) or DinD (isolated).**

GitLab offers two approaches for jobs that need Docker:
- **Socket binding:** Mount `/var/run/docker.sock`. Simple, fast (host
  layer cache), but gives full Docker host access. Acceptable when you
  trust the workload.
- **Docker-in-Docker (DinD):** Run a separate Docker daemon as a service
  container. More isolated but slower (no layer cache) and still requires
  `privileged = true`.

**Implication for us:** Our executors need Docker access for gates that
run `docker compose exec api pytest`. For v1, socket binding is
appropriate — we control the images, the tasks, and the host. Future
isolation can use DinD if we run untrusted workloads.

**4. The helper container separates workspace prep from execution.**

GitLab uses a special helper image (Alpine + git + gitlab-runner-helper)
to clone repos, restore caches, and download artifacts. The user's job
image only runs the job script — it does not need git or artifact tools.

**Implication for us:** The controller serves the helper role. It clones
the repo, stages the workdir, copies methodology files. The harness
subprocess only executes the task prompt — it does not need to know about
vtf, task specs, or workspace setup.

**5. Per-job networking with DNS service discovery.**

GitLab creates a Docker bridge network per job. Service containers
(postgres, redis) are reachable by hostname. Jobs are network-isolated
from each other.

**Implication for us:** For v1, the executor container joins a Docker
network that can reach the vtf API and the git server. If gates run
`docker compose exec`, they talk to existing containers via the mounted
Docker socket (the test stack is already running on the host). Future:
per-task networks for full isolation.

**6. Tag-based routing for multi-project, multi-capability fleets.**

GitLab Runners register with tags (`docker`, `gpu`, `linux`). Jobs
require tags (`tags: [docker, linux]`). A runner only picks up jobs whose
tags it satisfies. Runners can be shared (all projects), group-scoped, or
project-specific.

**Implication for us:** vtf already has tag-based task matching on the
claimable endpoint. Projects can require specific tags, and only executors
with matching tags will claim their tasks. This is identical to GitLab's
model and needs no additional design work.

**7. Credentials are scoped and ephemeral.**

GitLab generates a CI_JOB_TOKEN per job with narrow scope (read access
to the project repo, write to its container registry). The token is
revoked when the job completes.

**Implication for us:** For v1, SSH keys or deploy tokens mounted into
the container provide git access. Future: vtf could issue scoped
per-task tokens for git operations, following GitLab's pattern.

---

## Design

### New concept: Agent Config

vafi introduces a single declarative file that fully describes an
autonomous agent — its identity, behavioral role, work source,
verification gates, and resource limits.

An agent config is not a replacement for provider configs and profiles.
It **composes** them, adding the fleet-specific concerns that neither
addresses:

```yaml
# agents/vtf-executor.yaml
id: vtf-executor
description: "Executes vtf tasks using Claude Code"

# Existing vf-agents concepts (composed, not replaced)
runtime: claude-code
provider: claude-anthropic               # which provider config to use
image: vtf-vff-agent:latest             # image override

# Behavioral identity (new)
role: executor
methodology: methodologies/executor.md   # agent role instructions
prompts:                                 # per-action prompt templates
  task: templates/task.txt
  rework: templates/rework.txt

# Work source (new)
work_source:
  type: vtf
  api_url: ${VF_VTF_API_URL}
  poll_interval: 30
  tags: [executor, claude]

# Verification gates (new)
gates:
  - name: task-tests
    command: "${test_command}"
  - name: full-suite
    command: "docker compose exec api pytest tests/"

# Limits (new, extends profile resource limits)
limits:
  task_timeout: 600
  max_rework: 3
  max_turns: 50

# Auth (references existing provider config)
auth:
  type: config-dir
  source: ~/.claude

# Resources (same as profile, applied at container level)
resources:
  memory: 4g
  cpus: 2
```

A judge agent uses the same structure with different behavioral config:

```yaml
# agents/vtf-judge.yaml
id: vtf-judge
description: "Reviews vtf task completions"

runtime: claude-code
provider: claude-anthropic
image: vtf-vff-agent:latest

role: judge
methodology: methodologies/judge.md
prompts:
  review: templates/review.txt

work_source:
  type: vtf
  api_url: ${VF_VTF_API_URL}
  poll_interval: 30
  query: pending_completion_review
  tags: [judge, claude]

gates: []                                # judges don't run gates

limits:
  task_timeout: 300
  max_turns: 30

auth:
  type: config-dir
  source: ~/.claude

resources:
  memory: 4g
  cpus: 2
```

**Key design choice:** The agent config is a composition layer, not a
replacement. Provider configs, profiles, and runtime definitions continue
to exist and serve human-driven mode unchanged. The agent config references
them and adds fleet-specific concerns.

### Instruction delivery: user-level methodology

The current instruction assembler mounts at `/workdir/CLAUDE.md`. This
breaks with dynamic workdirs. The fix uses the harness's native
instruction hierarchy.

Claude Code loads instructions from multiple levels:

```
~/.claude/CLAUDE.md              <- user-level (always loaded)
/repo-root/CLAUDE.md             <- project-level (loaded from cwd)
/repo-root/subdir/CLAUDE.md      <- directory-level (if cwd is deeper)
```

All levels stack. They do not collide.

**Key enabler: `$HOME != workdir` in vf-agents.** The existing vf-agents
container layout separates the user home (`/home/node`) from the working
directory (`/workdir`). This separation, originally designed for clean
credential isolation, gives us three independent namespaces that map
directly to our three instruction layers — each with a different
lifecycle and a different owner:

| Namespace | Path in container | Content | Lifecycle | Owner |
|-----------|-------------------|---------|-----------|-------|
| `$HOME` | `/home/node/.claude/CLAUDE.md` | Methodology — agent role instructions, blast radius rules, output format | Container lifetime (stable across all tasks) | Agent config |
| `cwd` | `/sessions/<ms>/<task>/CLAUDE.md` | Project context — build commands, test patterns, repo conventions | Task lifetime (fresh per clone) | Repository |
| `-p` arg | n/a (passed as CLI argument) | Task content — spec YAML, test commands, constraints | Invocation lifetime (ephemeral) | vtf API |

No collision. No merging. No path conflicts. The harness's native
instruction hierarchy and the container's existing namespace separation
solve the problem without any special handling.

Each layer has a different change frequency:

- **Methodology** changes when the agent process improves. Updated by
  editing files and restarting the container (or rebuilding the image).
- **Project context** changes when the repo changes. Always current
  because it comes from a fresh clone.
- **Task content** changes per task. Always current because it comes
  from the vtf API.

**Customization without image rebuild:** Mount a host directory over
`/opt/vf-agent/methodologies/` to override methodology files. The
controller reads from this path on init, so changes take effect on the
next task (or container restart, depending on implementation).

### Prompt construction

The controller builds prompts from templates with variable substitution.
Templates are shipped in the image at `/opt/vf-agent/templates/` and
are overridable via volume mount.

**Executor task prompt** (`templates/task.txt`):
```
Implement the following task.

## Task: {title} ({id})

## Specification
{spec}

## Test Commands
{test_command}
```

**Executor rework prompt** (`templates/rework.txt`):
```
The judge rejected your previous work on this task.

## Judge Feedback
{review_comments}

## What to fix
Read the feedback carefully. Fix the issues identified.
Run tests to verify your fixes. Commit when done.
```

**Judge review prompt** (`templates/review.txt`):
```
Review the implementation for task {id}: {title}.

## Files Changed
{changed_files}

## Task Specification
{spec}

Produce a structured verdict: PASS or FAIL with detailed reasoning.
```

Template variables are resolved from the vtf task API response. The
controller performs simple string substitution — no template engine
required.

### The four-layer architecture

```
+----------------------------------------------------------+
|  Layer 4: Kubernetes Orchestration                        |
|                                                           |
|  Manages all vafi resources as k8s objects:                |
|  - Agent pools as Deployments (executor, judge, super)    |
|  - Project environments as Namespaces + Deployments       |
|  - Session storage as PersistentVolumes                   |
|  - Secrets as k8s Secrets                                 |
|  - Scaling via replicas or HPA                            |
|                                                           |
|  kubectl scale deploy executor-pool -n vafi-agents --replicas=5
|  kubectl logs -f deploy/executor-pool -n vafi-agents      |
|  kubectl apply -f projects/vta/ -n vafi-project-vta       |
+----------------------------+-----------------------------+
                             | manages pods
+----------------------------v-----------------------------+
|  Layer 3: Controller (Python, inside pod)                 |
|                                                           |
|  The autonomous loop:                                     |
|  1. Init: register with work source, stage methodology    |
|  2. Poll for work (new tasks or rework assigned to me)    |
|  3. Claim task, start heartbeat coroutine                 |
|  4. Create workdir, clone repo                            |
|  5. Build prompt from template + task data                |
|  6. Invoke harness as subprocess                          |
|  7. Parse structured output (JSON)                        |
|  8. Run verification gates                                |
|  9. Report result to work source (complete/fail)          |
|  10. Loop -> step 2                                       |
+----------------------------+-----------------------------+
                             | subprocess per task
+----------------------------v-----------------------------+
|  Layer 2: Harness (Claude Code / Gemini / Pi)             |
|                                                           |
|  Loads methodology from ~/.claude/CLAUDE.md               |
|  Loads project context from cwd/CLAUDE.md                 |
|  Receives task via -p prompt                              |
|  Returns structured JSON output                           |
|  Supports --resume for rework                             |
+----------------------------------------------------------+

+----------------------------------------------------------+
|  Layer 1: Shared Infrastructure                           |
|                                                           |
|  Runtime adapters     (command building, output parsing)   |
|  Credential staging   (tmpfs + copy pattern)              |
|  Image hierarchy      (base -> toolset -> runtime)        |
|  Volume conventions   (workdir, config, sessions)         |
+----------------------------------------------------------+
```

**Layer 1 (Shared Infrastructure)** is the existing vf-agents
foundation. Runtime adapters, credential staging, image hierarchy, and
volume conventions are reused unchanged.

**Layer 2 (Harness)** is the AI CLI tool. It receives methodology via
user-level instructions, project context via repo-level instructions,
and task content via the `-p` prompt. It returns structured JSON output
that the controller parses.

**Layer 3 (Controller)** is new. A Python asyncio application running
inside the container. It implements the autonomous work loop: poll, claim,
execute, verify, report. It knows about work sources and gates but not
about specific AI tools — it invokes the harness as a subprocess using
the adapter's command format.

**Layer 4 (Kubernetes Orchestration)** manages all vafi resources as
native k8s objects. Agent pools are Deployments, project environments
are Namespaces with their own Deployments/StatefulSets, session storage
is PersistentVolumes, and secrets are k8s Secrets. Scaling, health
checks, rolling updates, and restart policies are all handled by k8s
natively.

### Work source abstraction

The controller polls a work source for tasks. The work source is an
interface, not a vtf-specific integration:

```
WorkSource
  Poll()       -> Task or None
  Claim(id)    -> success/failure
  Heartbeat(id)
  Complete(id, result)
  Fail(id, reason)
```

**VtfWorkSource** implements this against the vtf API:
- `Poll()` queries the claimable endpoint with tag matching, plus
  `changes_requested` tasks assigned to this agent (rework has priority)
- `Claim()` calls the vtf claim endpoint with agent ID
- `Heartbeat()` calls the vtf heartbeat endpoint on a timer
- `Complete()` calls the vtf complete/review-submit endpoint
- `Fail()` transitions the task to `needs_attention`

**ManualWorkSource** could implement this for human-driven testing:
- `Poll()` reads from a local queue file or stdin
- No claim/heartbeat (single consumer)
- `Complete()` writes result to stdout

The controller does not know which work source it uses. It calls the
interface. This makes the controller reusable beyond vtf.

### Kubernetes topology

```
Namespace: vafi-system
  vtf API (Deployment)               <- task tracker
  supervisor (Deployment, replicas=1) <- DAG management

Namespace: vafi-agents
  executor-pool (Deployment, replicas=3)  <- AI agent workers
  judge-pool (Deployment, replicas=1)     <- review agents
  sessions-pv (PersistentVolume)          <- shared workdirs

Namespace: vafi-project-vta              <- todo app environment
  postgres (StatefulSet)
  redis (Deployment)
  app (Deployment)

Namespace: vafi-project-vtf              <- vtaskforge environment
  postgres (StatefulSet)
  redis (Deployment)
  api (Deployment)
  web (Deployment)
```

**Agent pools** are Deployments in `vafi-agents`. Scaling is
`kubectl scale` or HPA based on vtf queue depth. Each pod runs the
controller loop — one pod = one agent.

**Project environments** are namespaces with their own infrastructure.
Each project gets a namespace (e.g., `vafi-project-vta`) containing
the services it needs. Executors access project services via k8s DNS
(e.g., `postgres.vafi-project-vta.svc.cluster.local`).

**Environment lifecycle:**
- **Milestone 1** of any project creates the environment (executor
  writes k8s manifests, applies them to the project namespace)
- **Subsequent milestones** evolve the environment (executor updates
  manifests — adds Redis, Celery workers, etc.)
- **Project completion** — namespace can be torn down

The environment is a **living artifact** that co-evolves with the
codebase. Tasks that add infrastructure dependencies update the k8s
manifests in the repo and apply them as part of task execution.

### Gate execution

Gates are verification steps that run after the harness completes but
before the controller reports success to the work source. They are
declared in the agent config and executed sequentially.

A gate is a shell command. It receives the task workdir as its working
directory and has access to template variables from the task spec
(e.g., `${test_command}`).

```yaml
gates:
  - name: task-tests
    command: "${test_command}"
    required: true            # failure = task failure
  - name: full-suite
    command: "pytest tests/"
    required: true
```

Gate results are included in the completion report to the work source.
If any required gate fails, the controller reports the task as failed
rather than complete.

Judges typically have no gates — they are the gate. An executor's
gates are typically test commands extracted from the task spec.

### Output parsing and success determination

The controller invokes the harness as a subprocess and receives structured
JSON output. A key design principle: **the controller never interprets
the LLM's natural language output**. It uses structured signals (exit
codes, JSON fields, gate results) to determine success or failure. The
result text is passed through opaquely — for humans and judges to read,
not for the controller to parse.

**What the harness returns** (`--output-format json`):

```json
{
  "result": "## Task abc - Widget API: Complete\n\nFiles created: ...",
  "is_error": false,
  "session_id": "session-abc123",
  "total_cost_usd": 0.042,
  "num_turns": 12,
  "stop_reason": "end_turn",
  "usage": { "input_tokens": 24000, "output_tokens": 3800 }
}
```

**Three levels of failure, three different responses:**

| Level | Signal | Meaning | Controller action |
|-------|--------|---------|-------------------|
| Infrastructure failure | Exit code != 0, stderr patterns | Harness crashed, auth failed, rate limited, OOM | Classify error; retry if transient, fail task if permanent |
| Harness error | `is_error: true` | Harness ran but could not complete the work | Report task as failed with result text as reason |
| Task failure | Gate exit code != 0 | Harness thinks it succeeded but tests fail | Report task as failed with gate output |

**The decision tree:**

```
Harness exit code != 0?
  |
  +-> Classify: auth, rate_limit, OOM, timeout, unknown
  +-> Transient? -> retry (up to N times with backoff)
  +-> Permanent? -> fail task, report error category
  |
is_error == true?
  |
  +-> Task failed. Report result text as failure reason.
  |
is_error == false?
  |
  +-> Extract session_id, store in vtf task metadata
  +-> Run gates sequentially
  |     |
  |     +-> All gates pass? -> Report task complete
  |     +-> Any gate fails? -> Report task failed with gate output
```

**Why gates are the source of truth, not the result text:**

The harness returns a free-text completion report ("Files created: ...",
"Test results: 8/8 passed"). Parsing this is fragile — it is LLM output
with no guaranteed format. During Phase 8 of vtaskforge development, an
executor declared success with "all tests passed" while 262 tests were
actually failing. The simulation caught this only because the human
supervisor ran the tests independently.

Gates solve this by running the actual verification commands. The
controller does not need to trust or parse the harness's self-assessment.
It runs the tests and uses the exit codes.

**What the controller extracts and stores:**

| Field | Stored where | Purpose |
|-------|-------------|---------|
| `session_id` | vtf task metadata (via API) | Session resumption on rework — survives container restarts |
| `total_cost_usd` | vtf task metadata or controller log | Cost tracking and budget enforcement |
| `num_turns` | Controller log | Diagnostics, tuning `max_turns` limits |
| `result` | vtf completion report (via API) | Human-readable output for judges and supervisors |
| `stop_reason` | Controller log | Detect `max_turns_reached` vs normal `end_turn` |

**The session_id lifecycle** (critical for the rework cycle):

```
1. Harness completes
   -> controller reads session_id from JSON output

2. Controller stores session_id in vtf task metadata
   -> survives container restarts, visible to any executor

3. Task goes to review -> judge rejects -> changes_requested

4. Controller picks up rework
   -> reads session_id from vtf task metadata
   -> checks if session files exist in task workdir

5. Session files exist?
   -> claude --resume <session_id> -p "<rework prompt>"
   Session files missing?
   -> fresh session with full spec + judge feedback as context
```

### Image strategy

One new image layer on top of the existing hierarchy:

```
node:20-bookworm-slim
  -> vf-agents-base           (git, curl, ssh, jq)
       -> vf-agents-claude    (+ Claude Code CLI)
            -> vtf-vff-agent  (+ Python controller, methodologies, templates)
```

The `vtf-vff-agent` image contains:

```
/opt/vf-agent/
  controller/                  # Python controller source
    __main__.py                # entrypoint
    poller.py                  # work source polling loop
    invoker.py                 # harness subprocess management
    gates.py                   # gate execution
    heartbeat.py               # async heartbeat coroutine
    worksources/
      vtf.py                   # VtfWorkSource implementation
      manual.py                # ManualWorkSource (testing)
  methodologies/               # role-specific instructions
    executor.md                # executor methodology (the 233 lines)
    judge.md                   # judge methodology
  templates/                   # prompt templates
    task.txt
    rework.txt
    review.txt
```

**One image, role selected by environment variable:**

```
VF_AGENT_ROLE=executor  ->  copies executor.md to ~/.claude/CLAUDE.md
VF_AGENT_ROLE=judge     ->  copies judge.md to ~/.claude/CLAUDE.md
```

The controller reads `VF_AGENT_ROLE` on startup, copies the appropriate
methodology file, and loads the matching prompt templates.

**Customization without rebuild:**

```yaml
# docker-compose.yml
executor-1:
  image: vtf-vff-agent:latest
  environment:
    VF_AGENT_ROLE: executor
  volumes:
    - ./custom-methodologies:/opt/vf-agent/methodologies:ro
    - ./custom-templates:/opt/vf-agent/templates:ro
```

Edit files on the host, restart the container.

### Container-internal architecture

```
+------------------------------------------------------+
|  vtf-vff-agent container                              |
|                                                       |
|  Entrypoint: python -m controller                     |
|                                                       |
|  +------------------------------------------------+  |
|  |  Controller (Python asyncio)                    |  |
|  |                                                 |  |
|  |  +-------------------------------------------+  |  |
|  |  |  Init                                     |  |  |
|  |  |  - Read VF_AGENT_ROLE, VF_AGENT_ID        |  |  |
|  |  |  - Copy methodology to ~/.claude/CLAUDE.md|  |  |
|  |  |  - Register with work source              |  |  |
|  |  +-------------------------------------------+  |  |
|  |                    |                            |  |
|  |                    v                            |  |
|  |  +-------------------------------------------+  |  |
|  |  |  Poll Loop (async)                        |  |  |
|  |  |  - Check rework (priority)                |  |  |
|  |  |  - Check claimable tasks                  |  |  |
|  |  |  - Sleep on empty                         |  |  |
|  |  +-------------------------------------------+  |  |
|  |           |                                     |  |
|  |           v  (task found)                       |  |
|  |  +-------------------------------------------+  |  |
|  |  |  Task Execution                           |  |  |
|  |  |  1. Claim task                            |  |  |
|  |  |  2. Create/reuse workdir                  |  |  |
|  |  |  3. Clone repo (or reuse for rework)      |  |  |
|  |  |  4. Build prompt from template            |  |  |
|  |  |  5. Start heartbeat coroutine             |  |  |
|  |  |  6. Invoke harness (subprocess)      --------+---> claude -p "..."
|  |  |  7. Stop heartbeat                        |  |  |
|  |  |  8. Parse harness output (JSON)           |  |  |
|  |  |  9. Run gates                             |  |  |
|  |  |  10. Report to work source                |  |  |
|  |  +-------------------------------------------+  |  |
|  |           |                                     |  |
|  |           v                                     |  |
|  |      (back to poll loop)                        |  |
|  +------------------------------------------------+  |
|                                                       |
|  /sessions/ (shared volume, RW)                       |
|    milestone-abc/                                     |
|      task-001/  <- repo checkout + harness sessions   |
|      task-002/                                        |
|                                                       |
|  /home/node/.claude/ (tmpfs)                          |
|    CLAUDE.md          <- methodology (copied on init) |
|    .credentials.json  <- auth (staged on start)       |
|                                                       |
|  /opt/vf-agent/ (image or volume, RO)                 |
|    methodologies/     <- role instruction files        |
|    templates/         <- prompt templates              |
|    controller/        <- controller source             |
+------------------------------------------------------+
```

### Workdir management

All executor containers mount a shared volume at `/sessions/`. The
controller creates per-task workdirs at
`/sessions/<milestone-id>/<task-id>/`.

**New task:** Controller creates the directory, clones the repo, sets
cwd for the harness invocation.

**Rework:** Controller reuses the existing workdir. The repo state and
harness session files from the previous attempt are preserved, enabling
session resumption.

**Cleanup:** Workdirs persist until milestone completion. For v1, manual
cleanup (`rm -rf /sessions/<milestone-id>/`). Future: automated via
orchestrator event.

### Session resumption for rework

**Spike 1 findings (2026-03-22):** Investigation of vf-agents session
handling confirms that Claude Code stores session files in `~/.claude/`
inside the container, NOT in the working directory. These files do not
survive container restarts. Workdir contents (code changes, commits) on
shared volumes DO survive. This means:

| Scenario | Session resume? | Code state? |
|----------|----------------|-------------|
| Rework on same pod (still alive) | Yes | Yes |
| Rework after pod restart/reschedule | No — fallback | Yes |
| Rework picked up by different pod | No — fallback | Yes |

**The fallback path is the normal path for fleet operations.** Pods
restart, get rescheduled, and scale down/up routinely. The design must
treat fresh-session-with-context as the primary rework mechanism, not
the exception.

**Rework flow:**

1. Controller captures `session_id` from harness JSON output
2. Stores `session_id` in vtf task metadata (survives pod restarts)
3. On rework, checks if session files exist in `~/.claude/`
4. If yes (same pod, still alive): `claude --resume <session-id> -p "<rework prompt>"`
5. If no (common case): fresh session with full spec + judge feedback as context

**Future optimization:** Mount a per-task Claude config directory on the
shared session volume (e.g., `/sessions/<ms>/<task>/.claude/`) and set
`CLAUDE_CONFIG_DIR` per harness invocation. This would make session
resume work across pods. Not required for MVP — the fallback path is
proven effective from vtaskforge Phase 9 rework cycles.

### The contract: orchestrator <-> controller

The vafi orchestrator (Layer 4) and controller (Layer 3) communicate through
environment variables and filesystem conventions only. No API, no socket,
no shared memory.

**Environment variables (set by vafi orchestrator, read by controller):**

```bash
# Identity
VF_AGENT_ID=executor-1           # unique agent identity
VF_AGENT_ROLE=executor           # executor | judge
VF_AGENT_TAGS=executor,claude    # comma-separated tags for task matching

# Work source
VF_WORK_SOURCE=vtf               # work source type
VF_VTF_API_URL=http://vtf:8001   # vtf API endpoint
VF_POLL_INTERVAL=30              # seconds between polls

# Limits
VF_TASK_TIMEOUT=600              # per-task timeout in seconds
VF_MAX_REWORK=3                  # max rework attempts before escalation
VF_MAX_TURNS=50                  # max harness turns per invocation

# Repo (resolved per task from vtf project metadata)
# When the controller claims a task, the vtf response includes the
# project's repo_url and default_branch. No project config in vafi —
# vtf is the source of truth. Enables multi-project execution.
```

**Filesystem conventions:**

| Path | Purpose | Mount type |
|------|---------|------------|
| `/opt/vf-agent/methodologies/` | Role instruction files | Image layer or RO volume |
| `/opt/vf-agent/templates/` | Prompt templates | Image layer or RO volume |
| `/opt/vf-agent/controller/` | Controller source | Image layer |
| `/sessions/` | Per-task workdirs (repo + sessions) | Shared RW volume |
| `/home/node/.claude/` | Harness config (credentials + methodology) | tmpfs |

### Kubernetes deployment

Agent configs translate to k8s manifests. The agent config YAML is the
source of truth; k8s manifests are generated or hand-written from it.

**Agent pool deployment example:**

```yaml
# k8s/agents/executor-pool.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: executor-pool
  namespace: vafi-agents
spec:
  replicas: 3
  selector:
    matchLabels:
      app: vafi-agent
      role: executor
  template:
    metadata:
      labels:
        app: vafi-agent
        role: executor
    spec:
      containers:
        - name: agent
          image: vtf-vff-agent:latest
          env:
            - name: VF_AGENT_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name    # pod name = agent ID
            - name: VF_AGENT_ROLE
              value: executor
            - name: VF_AGENT_TAGS
              value: executor,claude
            - name: VF_VTF_API_URL
              value: http://vtf-api.vafi-system.svc.cluster.local:8001
            - name: VF_POLL_INTERVAL
              value: "30"
            - name: VF_TASK_TIMEOUT
              value: "600"
            - name: VF_MAX_REWORK
              value: "3"
            - name: VF_MAX_TURNS
              value: "50"
          volumeMounts:
            - name: sessions
              mountPath: /sessions
          resources:
            limits:
              memory: 4Gi
              cpu: "2"
      volumes:
        - name: sessions
          persistentVolumeClaim:
            claimName: vafi-sessions
```

**Project environment example:**

```yaml
# k8s/projects/vta/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: vafi-project-vta

---
# k8s/projects/vta/postgres.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: vafi-project-vta
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    spec:
      containers:
        - name: postgres
          image: postgres:16
          env:
            - name: POSTGRES_DB
              value: vta
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: db-credentials
                  key: password
```

**Key k8s features used:**

| Feature | Purpose |
|---------|---------|
| Pod name as agent ID | `metadata.name` → stable identity per pod |
| DNS service discovery | Agents reach project services via `service.namespace.svc.cluster.local` |
| PersistentVolumeClaim | Shared session storage across agent pods |
| Namespaces | Isolation between projects and between agents/system |
| Resource limits | Per-pod memory/CPU caps |
| Secrets | Credentials per namespace (git SSH keys, API keys) |
| Restart policy | Auto-restart failed agents |
| Replicas | Scale agent pools |

### Relationship to vf-agents

vafi is a separate project, not a mode of vf-agents. They serve different
users but share infrastructure:

| System | User | Purpose |
|--------|------|---------|
| `vfa` (vf-agents) | Human developer | Run AI tools in containers interactively |
| `vafi` | Automated systems (vtf) | Autonomous agent fleet execution |

**What vafi reuses from vf-agents:**

| Building block | How vafi uses it |
|----------------|-----------------|
| Image hierarchy (base, toolset, runtime layers) | vafi images build on top of `vf-agents-claude` |
| Credential staging patterns (tmpfs + copy) | Same auth mechanism for harness inside containers |
| Adapter knowledge (CLI flags, output format, session resume) | Controller invokes harness using the same command patterns |
| Volume conventions | Consistent mount patterns across both systems |

**What vafi builds independently:**

| Component | Purpose |
|-----------|---------|
| Controller (Python) | Autonomous work loop inside containers |
| Agent configs | Declarative agent definitions (identity, role, work source, gates) |
| vafi orchestrator | Container lifecycle, fleet management |
| Work source abstraction | Pluggable task sources (vtf first) |
| Gate system | Declarative verification after harness completion |
| Worker images | `vtf-vff-agent` and future specialized images |

---

## Remaining Design Gaps

The following gaps require decisions before implementation begins.

### Gap 6: Supervisor role — RESOLVED

The supervisor is just another agent role, not a separate system. Same
image, same controller loop, different behavior when work is found.

| Role | Polls for | Action | Harness? |
|------|-----------|--------|----------|
| Executor | Claimable tasks | Invoke harness, run gates | Yes |
| Judge | Tasks pending review | Invoke harness for review | Yes |
| Supervisor | Completed tasks | Check DAG, submit unblocked tasks | No |

`VF_AGENT_ROLE=supervisor` — the controller skips harness invocation
and instead runs pure logic: query which tasks have all dependencies
met, transition them from `draft` to `todo` (making them claimable by
executors).

The supervisor is a vafi agent, not a vtf feature. It runs in the same
fleet, managed the same way, with the same container lifecycle.

### Gap 7: Registration and identity — RESOLVED

Following the GitLab Runner model: stable IDs, idempotent registration.

**Identity:** The orchestrator assigns a stable `VF_AGENT_ID` via env
var (e.g., `executor-1`, `judge-1`, `supervisor-1`). The ID is stable
across container restarts — same container name, same identity.

**Registration:** On startup, the controller calls
`POST /v1/agents/register` with its ID, role, and tags. vtf upserts —
if the ID already exists, it updates the record (tags, status, last
seen). This makes registration idempotent. Restarts just work.

**No token exchange for v1.** vtf is internal infrastructure. The agent
ID in the env var is sufficient identity. The controller uses it for
all vtf communication (claim, heartbeat, report).

**Future (multi-tenant):** Add a registration token flow — admin
generates a token in vtf, agent uses it to register, gets back a
scoped API token for future communication. Same pattern as GitLab
Runner's registration token exchange.

### Gap 8: Resource controls — RESOLVED

Following the GitLab Runner model: admin sets ceilings, tasks operate
within them. Tasks can request lower limits but never exceed the agent
config.

**Limit hierarchy:**

| Limit | Set by | Overridable by task? | Enforcement |
|-------|--------|---------------------|-------------|
| `task_timeout` | Agent config | Yes, lower only | `subprocess.run(timeout=N)` — controller kills harness |
| `max_turns` | Agent config | Yes, lower only | `claude --max-turns N` flag passed to harness |
| `memory`, `cpus` | Orchestrator | No — Docker container limit | Docker resource constraints at container creation |
| `cost` | Tracked, not enforced (v1) | N/A | Read `total_cost_usd` from harness JSON output, log it |

**Precedence:** `min(agent_config, task_spec)` — the more restrictive
value wins. The agent config is the ceiling, the task spec can only
tighten.

**Example:** Agent config has `task_timeout: 600`, `max_turns: 50`.
A simple task spec sets `timeout: 120`, `max_turns: 20`. The controller
uses `timeout=120`, `max_turns=20`. A complex task spec sets
`timeout: 900` — the controller caps it at `600` (agent ceiling).

**Cost tracking (v1):** Read `total_cost_usd` from harness JSON output,
store in vtf task metadata and controller logs. No enforcement — just
visibility. Future: cost cap that terminates the harness mid-task when
a budget is exceeded.

### Gap 9: Repo and workspace provisioning — RESOLVED

Following the GitLab Runner model: **vtf owns project knowledge, vafi
owns execution knowledge.** vtf stores repo URL and default branch on
the project model. When vafi claims a task, the task response includes
the project context — everything needed to clone and execute.

**Boundary between vtf and vafi:**

| Concern | Owner | Rationale |
|---------|-------|-----------|
| Repo URL | vtf (project model) | Project metadata — same as any PM tool linking to a repo |
| Default branch | vtf (project model) | Project-level setting |
| Branch override | vtf (milestone, future) | Feature branch per milestone |
| Task spec | vtf (task model) | Already exists |
| Clone strategy | vafi (agent config) | Execution detail — how to clone, not what to clone |
| Git credentials | vafi orchestrator (v1: mounted SSH keys) | Execution infrastructure |
| Git credentials | vtf (future: scoped tokens per task) | Following GitLab CI_JOB_TOKEN pattern |

**vtf project model changes required:**
- Add `repo_url` field (e.g., `git@gitlab:group/vtaskforge.git`)
- Add `default_branch` field (e.g., `develop`)
- Task claim response should include project metadata so vafi
  gets everything in one call

vafi is completely generic — no project mappings, no project config
files. Any executor can work on any project because the task carries
its full execution context.

**Clone strategy (v1): Fresh clone per task.**
- `git clone --branch <branch> <url> /sessions/<milestone>/<task>/`
- Guarantees clean state, no cross-task contamination
- For rework: workdir already exists, skip clone, reuse
- Future optimization: `fetch` strategy (reuse cached clone, `git clean`
  + `git fetch`) for speed

**Git credentials: SSH keys mounted into container.**
- Orchestrator mounts keys at `/home/node/.ssh/` (same pattern as
  current vf-agents)
- Future: vtf-issued deploy tokens per task (GitLab CI_JOB_TOKEN pattern)

**Branch selection:** From vafi project config `default_branch`. Future:
milestone-level branch override for feature branches.

**Full clone (v1).** The harness benefits from git history (`git blame`,
`git log`). Shallow clone saves time but limits context. Optimize later
if clone time becomes a bottleneck.

### Gap 10: Docker access for gates — RESOLVED

With k8s as the deployment target, the Docker socket problem goes away.

Agents don't run `docker compose exec` — they interact with the project
environment via k8s:
- **Test commands** connect to project services via DNS
  (e.g., `postgres.vafi-project-vta.svc.cluster.local`)
- **Environment updates** use `kubectl apply` to evolve the project stack
- **Ephemeral test infra** uses k8s Jobs with sidecar containers
  (fresh postgres per task, auto-cleanup)

No Docker socket binding. No DinD. The cluster provides the execution
environment natively.

### Gap 11: Image selection per task — RESOLVED

With k8s, image selection is native. Agent pods use a default image
from the Deployment spec, but tasks or projects can override it via
pod template patches or separate Deployments per project type.

k8s handles image pulling, caching, and version management. Different
agent pools can use different images:

```yaml
# Python project agents
executor-python:
  image: vtf-vff-agent-python:latest

# Node project agents
executor-node:
  image: vtf-vff-agent-node:latest
```

Tag-based routing (already in vtf) directs tasks to the right pool.
A Python project's tasks require tag `python`, routed to the
`executor-python` pool.

---

## vtf ↔ vafi Interface Contract

**Extracted to:** [vtf-vafi-interface-CONTRACT.md](vtf-vafi-interface-CONTRACT.md)

The full API contract (14 interaction points, 5 vtf gaps, vafi-side
interface design with WorkSource protocol, VtfClient, and data types)
lives in its own document for independent reference from both vafi
and vtaskforge repos.

### Summary

- **14 API interaction points** covering agent registration, polling,
  claiming, heartbeat, result storage, completion, failure, judge
  review, rework, and supervisor submission
- **5 vtf gaps** (GAP-1 through GAP-5) that require vtf code changes
- **3-layer vafi interface**: VtfClient (HTTP) → VtfWorkSource
  (vtf-specific) → WorkSource (abstract protocol)
- **6 shared data types**: AgentInfo, TaskInfo, RepoInfo, ReworkContext,
  GateResult, ExecutionResult

See the contract document for full details.

---


---

## Next Steps

### Dependencies

**Kubernetes cluster setup** — vafi requires a running k8s cluster.
This is a separate design and implementation effort covering:
- Cluster provisioning (k3s on a single machine? Managed k8s? Multi-node?)
- Networking (ingress, service mesh, DNS)
- Storage (PersistentVolumes for session storage)
- Secrets management (k8s Secrets, external secrets operator)
- Image registry (Harbor, GHCR, or local registry)
- Monitoring and observability
- RBAC for agent pods (what can agents access?)

This should be designed in the vafi workspace as its own effort before
controller implementation begins.

**vtf interface changes** — the 5 gaps identified in the interface
contract above. These are vtf code changes that should be implemented
in the vtaskforge project. Priority: GAP-4 → GAP-1 → GAP-3 → GAP-2
→ GAP-5.

### Spikes

Technical validation needed before controller implementation.

**Spike 1: Harness session and workdir behavior — RESOLVED (2026-03-22)**

Claude Code stores session files in `~/.claude/` inside the container.
These files do NOT survive container/pod restarts. Workdir contents
(code changes, commits) on shared volumes DO survive.

Implications:
- Session resume (`--resume`) works within the same pod's lifetime
- After pod restart/reschedule, the fallback path applies: fresh
  session with full spec + judge feedback as context
- The fallback is the **normal path** for fleet operations — pods
  restart routinely
- Future optimization: mount per-task Claude config on shared volume
  via `CLAUDE_CONFIG_DIR` to enable cross-pod session resume

**Spike 2: Dynamic workdir auth resolution — RESOLVED (2026-03-22)**

Investigation of vf-agents credential handling confirms:

1. Claude Code CLI resolves credentials from `$HOME/.claude/`
   (hardcoded, no env var override like `CLAUDE_CONFIG_DIR`)
2. Changing cwd between invocations has zero effect on auth
3. No cwd-relative config lookups exist — all credential paths
   are anchored to `$HOME`

The vf-agents container layout (`$HOME=/home/node`, workdir at
`/workdir`) already proves this separation. Credentials are staged
from the host into `$HOME/.claude/` at container start via pre-run
hooks. The workdir is a completely independent mount.

**Implication for vafi:** The controller can invoke the harness with
different cwds per task (`/sessions/<ms>/<task>/`) and auth works
without any special handling. Credentials are staged once at pod
start and remain valid for all task executions in that pod's lifetime.

### Implementation roadmap

Once dependencies and spikes are resolved:

1. **K8s cluster** — provision and configure
2. **vtf interface changes** — GAP-1 through GAP-5
3. **Controller** — Python asyncio controller (the core of vafi)
4. **Agent image** — `vtf-vff-agent` with controller, methodologies, templates
5. **Agent manifests** — k8s Deployments for executor, judge, supervisor pools
6. **First project environment** — vtf dogfood as a k8s namespace
7. **End-to-end test** — executor picks up a task, clones, executes, gates, reports
