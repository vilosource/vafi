# vf-agent Controller Design

Status: Draft (2026-03-21)

## Problem Statement

vtaskforge has a working task execution process — supervisor orchestrates,
executors implement, judges verify — but the entire system runs as a
**manual simulation** inside a single Claude Code session. The human acts
as supervisor, spawns subagents as executors and judges, and manually
tracks retries and state transitions. This works for development and
dogfooding but cannot scale, run unattended, or be deployed as
infrastructure.

The simulation has proven the process works (Phase 9: zero test failures,
successful reject/rework cycle, parallel execution without conflicts), but
it has fundamental limitations:

### 1. Single session, single machine

Everything runs inside one Claude Code context window. The supervisor,
all executors, and all judges share one conversation. This means:
- No parallelism beyond subagent concurrency within one session
- If the session dies, all state is lost (no heartbeats, no recovery)
- The human must be present to initiate and monitor

### 2. The supervisor is a human pretending to be software

The human performs supervisor duties that should be automated:
- Reads the board (`vtf task list --status todo`)
- Decides which tasks to submit based on DAG dependencies
- Dispatches executors with hand-crafted prompts
- Dispatches judges after executor reports completion
- Tracks retry counts mentally
- Escalates after repeated failures

This is the exact control loop that a program should run.

### 3. Subagent dispatch is not process dispatch

When the supervisor spawns a subagent via Claude Code's Agent tool:
- The executor runs in-process (same OS process, shared filesystem)
- No isolation between executor instances
- No resource controls (token limits, timeouts, cost caps)
- No heartbeats to vtf (the supervisor is the heartbeat)
- Executor identity is the supervisor's identity
- No container boundary — executors can access anything

### 4. No unattended execution

The system cannot:
- Run overnight processing a backlog of tasks
- Scale horizontally (add more executors)
- Recover from crashes (restart and resume)
- Operate without a human session open

### What we need

A **controller** that runs inside a long-lived Docker container and
performs the vtf task loop — polling for work, invoking the harness,
monitoring execution, and reporting results. The controller:

- Polls vtf for claimable tasks (or receives them)
- Invokes a CLI harness (Claude Code, or any future AI CLI) as a subprocess
- Monitors the subprocess (heartbeats, timeouts)
- Parses the result and runs verification gates
- Reports back to vtf (complete, fail, submit for review)
- Loops

This is the GitLab Runner model: a thin wrapper that pulls jobs from a
coordinator and delegates real work to an execution environment.

---

## Current State: The Simulation

### Architecture

```
┌─────────────────────────────────────────────────────┐
│  Claude Code Session (single process)               │
│                                                     │
│  ┌──────────────┐                                   │
│  │   Human +    │  "vtf task list --status todo"    │
│  │   Opus AI    │──────────────────────────────────►│
│  │ (Supervisor) │                                   │
│  └──────┬───────┘          vtf API                  │
│         │                  (localhost:8001)          │
│         │ Agent tool                                │
│         ▼                                           │
│  ┌──────────────┐                                   │
│  │   Sonnet     │  reads spec, writes code,         │
│  │ (Executor    │  runs tests, commits              │
│  │  subagent)   │                                   │
│  └──────┬───────┘                                   │
│         │                                           │
│         │ returns completion report                 │
│         ▼                                           │
│  ┌──────────────┐                                   │
│  │   Human +    │  dispatches judge                 │
│  │   Opus AI    │──────────┐                        │
│  │ (Supervisor) │          │                        │
│  └──────────────┘          ▼                        │
│                     ┌──────────────┐                │
│                     │   Opus       │                │
│                     │  (Judge      │                │
│                     │  subagent)   │                │
│                     └──────────────┘                │
└─────────────────────────────────────────────────────┘
```

### How the simulation executes a task

1. **Human initiates**: "Run the next task" or "Execute milestone X"
2. **Supervisor reads board**: `vtf task list --status todo` via Bash tool
3. **Supervisor reads spec**: `vtf task show <id> --json` → extracts `.spec` YAML
4. **Supervisor constructs prompt**: Pastes executor system prompt + spec + test
   commands into an Agent tool invocation
5. **Executor subagent runs**: Sonnet receives the prompt, reads reference files,
   writes code, runs tests, commits changes, returns a completion report
6. **Supervisor runs Gate 1a**: Executes `test_command` from the task spec
7. **Supervisor runs Gate 1b**: Runs full test suite (`pytest tests/`)
8. **Supervisor dispatches judge** (if `judge: true`): Constructs judge prompt,
   spawns Opus subagent, receives verdict
9. **Supervisor updates board**: `vtf task complete <id>` or handles rejection
10. **Supervisor checks DAG**: Submits next tasks whose dependencies are met
11. **Loop**: Returns to step 2

### What the executor subagent receives

The supervisor constructs a prompt containing:

```
You are an executor agent for vtaskforge. Implement the task spec below.
Read reference files first, follow existing patterns, run tests, and commit.

## Project location: ~/GitHub/vtaskforge/

## Task spec
[full YAML spec content from vtf API]

## How to run tests
[test_command values from task metadata]

## Important
- Read reference files FIRST
- Follow existing patterns
- Run tests before committing
- Commit when done
- Report any spec deviations
```

The executor also inherits the vtf-executor agent definition (230 lines of
methodology: blast radius analysis, reference-driven development, completion
report format) as its system prompt.

The project's CLAUDE.md is loaded automatically by Claude Code from the
working directory.

### What the executor subagent returns

A text completion report:

```markdown
## Task [id] — [name]: Complete

**Files created:** [list]
**Files modified:** [list]
**Blast radius discoveries:** [list or "None"]
**Test results:** X/X passed
**Spec deviations:** None | [description]
**Notes:** [observations]
```

The supervisor parses this visually (not programmatically) and decides
next steps.

### What the judge subagent receives

```
You are a Judge Agent. Review the code changes for task [ID].
You verify:
- Does the implementation match the design doc's intent?
- Does the code follow established patterns?
- Are there dead code, N+1 queries, or architectural issues?

## Files to review
[list of modified files]

## Design references
[relevant design docs]

Produce a structured verdict: PASS/FAIL with reasoning.
```

### What the judge subagent returns

A text verdict (PASS or FAIL with reasoning), which the supervisor then
translates into a vtf review submission via the API.

---

## What Works (Validated by Phases 8-9)

| Aspect | Evidence |
|--------|----------|
| **YAML specs are sufficient for execution** | Phase 9: all tasks completed from specs alone, no hand-crafted glue needed |
| **Reject/rework cycle works** | Phase 9 task 9.2: judge rejected, executor reworked, judge approved on attempt 2 |
| **Parallel execution is safe** | Phase 9 wave 4: four executors ran simultaneously with zero merge conflicts |
| **Judge catches real issues** | Stale comments, missing tests, design doc divergences, N+1 query risks |
| **Executors report honestly** | Phase 9: no false completions (vs Phase 8 where executor declared success with 262 test failures) |
| **vtf state machine handles the full lifecycle** | draft → todo → doing → pending_completion_review → changes_requested → done all work |
| **vtf API has all needed endpoints** | claimable with tag matching, heartbeat, claim expiry, reviews with changes_requested/resubmit |

## What Doesn't Work (Gaps in the Simulation)

| Gap | Impact |
|-----|--------|
| **No heartbeats** | If session dies mid-task, vtf doesn't know. Claim never expires because no one calls heartbeat. |
| **No process isolation** | Executor subagents share the supervisor's filesystem, env vars, and permissions |
| **No resource controls** | No per-task token limits, timeouts, or cost caps. An executor can burn unlimited tokens. |
| **No crash recovery** | If the session ends, all in-flight work is lost. No way to resume. |
| **No horizontal scaling** | Can't add more executors. One session = one executor at a time (subagent concurrency is limited). |
| **Supervisor is manual** | Human must be present to drive the loop. Cannot run unattended. |
| **Review gate not enforced** | `judge: true` in specs doesn't set `needs_review_on_completion` on imported tasks. Executors bypass the judge gate. |
| **Output parsing is visual** | Supervisor reads completion reports as text, not structured data. Fragile and not automatable. |
| **Single agent identity** | All executors share one agent registration, blocking concurrent claims. |
| **No rework path for autonomous executors** | `changes_requested` → `resubmit` goes back to `pending_completion_review`, not back to a claimable state for executors to re-pick-up |

---

## Existing Infrastructure: vf-agents

The vf-agents system (`~/GitHub/vf-agents/`) already provides significant
infrastructure that the controller builds on. It is a Go binary that runs
on the host, managing Docker containers for AI harness execution.

### What vf-agents provides today

| Capability | Implementation |
|---|---|
| **Workdir management** | `workdir.Manager` — ephemeral, provided, or persistent modes |
| **Container execution** | `executor.Run()` — runs container, captures output, respects timeout |
| **Runtime adapters** | `ClaudeAdapter`, `GeminiAdapter`, `PiAdapter` — builds commands, parses output |
| **Volume mounting** | `BuildAccessMounts()` — SSH keys, git config, plugins, profile volumes |
| **Headless execution** | Adapter `BuildCommand()` generates `claude -p "prompt" --output-format json` |
| **Output parsing** | `ParseOutput()` on each adapter — parses JSON into `StandardResult` |
| **Session management** | `session start/send/close/list/prune` — detached containers with session tracking |
| **Auth management** | tmpfs + credential staging + pre-run hooks |
| **Resource limits** | `--memory`, `--cpus`, `--pids-limit` on container creation |
| **Multi-runtime** | Same orchestrator works with Claude, Gemini, Pi |
| **Image hierarchy** | Base → toolset → runtime → SecondBrain layered Dockerfiles |

### Current vf-agents lifecycle model

```
vfa run → start container → harness runs → container stops → output captured
```

One container = one harness execution. The container IS the task. The
harness starts with the container and ends when the container stops.

### What changes for the controller model

The controller introduces a **long-lived container** where the harness
is invoked multiple times as a subprocess:

```
container starts → controller loop begins
  → poll vtf → claim task → create workdir → invoke harness
  → harness exits → run gates → report to vtf
  → poll vtf → claim next task → create new workdir → invoke harness
  → ...
container stays alive between tasks
```

**Key deltas from current vf-agents:**

| Concern | Current vf-agents | Controller model |
|---|---|---|
| Container lifecycle | One container = one task | Long-lived, multiple tasks |
| Workdir | Set once at container start | Dynamic, created per task |
| Harness invocation | Container entrypoint | Subprocess invoked by controller |
| vtf integration | None | Poll, claim, heartbeat, report |
| Session resumption | Not tied to task lifecycle | Resume on rework |
| Output handling | Captured on container exit | Parsed per harness invocation |

**What we build on:** The existing image hierarchy (base, toolset, runtime,
SecondBrain layers), adapter system (command building, output parsing),
auth management (tmpfs + credential staging), and volume mount patterns
are all reusable. Modified images are needed to include the controller
as the entrypoint and support the long-lived container model.

---

## Terminology

| Term | Definition |
|------|-----------|
| **Harness** | The AI CLI tool (Claude Code, or any future equivalent) that executes prompts. It reads files, writes code, runs commands, and returns results. It knows nothing about vtf. |
| **Controller** | The program inside the Docker container that manages the harness. It polls vtf, constructs prompts, invokes the harness as a subprocess, parses results, runs gates, and reports back. It knows nothing about code — only about vtf task lifecycle. |
| **Orchestrator** | The system outside the containers that manages container lifecycle — starts executor containers, mounts volumes, assigns agent identities, handles cleanup. For v1 this may be `docker compose`; later it could be a dedicated pool manager or k8s. |
| **vf-agent image** | The Docker image containing the controller, the harness, and all tools needed for execution (git, python, node, etc). Built on top of existing vf-agents image layers. |
| **Executor** | A running instance of the vf-agent image configured to poll for and execute tasks. |
| **Judge** | A running instance of the vf-agent image configured to poll for tasks in `pending_completion_review` and verify them. Same image, different controller mode. |
| **Supervisor** | The service that manages board state — submits tasks when DAG dependencies are met. May be a separate container, a vtf background job, or a Celery task. Does NOT dispatch executors or judges. |
| **vtf** | The vtaskforge API server. Source of truth for all task state. |

---

## Architecture

Three layers with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│  Orchestrator (outside containers)                          │
│  docker compose / k8s / pool manager                        │
│                                                             │
│  Responsibilities:                                          │
│  - Start/stop executor and judge containers                 │
│  - Assign agent identities (VF_AGENT_ID env var)            │
│  - Mount shared session volume at /sessions/                │
│  - Set resource limits (memory, CPU)                        │
│  - Cleanup workdirs on milestone completion                 │
│                                                             │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │  Executor Container │  │  Executor Container │  ...      │
│  │                     │  │                     │           │
│  │  ┌───────────────┐  │  │  ┌───────────────┐  │          │
│  │  │  Controller   │  │  │  │  Controller   │  │          │
│  │  │  (Python      │  │  │  │  (Python      │  │          │
│  │  │   asyncio)    │  │  │  │   asyncio)    │  │          │
│  │  │               │  │  │  │               │  │          │
│  │  │  polls vtf    │  │  │  │  polls vtf    │  │          │
│  │  │  claims tasks │  │  │  │  claims tasks │  │          │
│  │  │  heartbeats   │  │  │  │  heartbeats   │  │          │
│  │  │  runs gates   │  │  │  │  runs gates   │  │          │
│  │  │  reports back │  │  │  │  reports back │  │          │
│  │  └───────┬───────┘  │  │  └───────┬───────┘  │          │
│  │          │ subprocess│  │          │ subprocess│          │
│  │  ┌───────▼───────┐  │  │  ┌───────▼───────┐  │          │
│  │  │   Harness     │  │  │  │   Harness     │  │          │
│  │  │  (Claude Code │  │  │  │  (Claude Code │  │          │
│  │  │   CLI)        │  │  │  │   CLI)        │  │          │
│  │  └───────────────┘  │  │  └───────────────┘  │          │
│  └─────────────────────┘  └─────────────────────┘          │
│          │                         │                        │
│          └────────┬────────────────┘                        │
│                   ▼                                         │
│         /sessions/ (shared volume)                          │
│         ├── milestone-abc/                                  │
│         │   ├── task-001/   ← workdir with repo + sessions  │
│         │   ├── task-002/                                   │
│         │   └── task-003/                                   │
│         └── milestone-def/                                  │
│             └── ...                                         │
└─────────────────────────────────────────────────────────────┘
                    │
                    ▼
          ┌─────────────────┐
          │   vtf API       │
          │   (vtaskforge)  │
          └─────────────────┘
```

---

## Design Scope

This document covers the **controller** — the program that bridges vtf
and the harness. Specifically:

**In scope:**
- Controller poll/claim/invoke/report loop
- Prompt construction (what gets sent to the harness)
- Output parsing (what comes back from the harness)
- Heartbeat management during execution
- Test gate execution after harness completes
- Error handling and retry logic
- Rework feedback loop (judge rejection → executor retry)
- Workdir management (per-task directories on shared volume)
- Configuration (env vars, per-task overrides)

**Out of scope (separate design docs):**
- Docker image composition (modified vf-agents images)
- Orchestrator design (container lifecycle, volume management)
- Supervisor service (DAG management, task submission)
- Multi-project support and repo management
- Scaling and orchestration (docker compose, k8s)
- Cost tracking and billing
- Event stream / SSE integration

---

## Design Decisions

Decisions made during design, with context and reasoning.

### D1: Python with asyncio for the controller

The controller is a Python async application, not a shell script or Go binary.

**Why:** The controller needs concurrent operations — heartbeats while the
harness runs, and likely more async concerns later (log streaming, event
publishing, parallel gate execution). asyncio provides this natively.
Python is also the natural fit given vtf's Django/Python ecosystem and
the availability of `httpx` for async HTTP.

**Rejected alternatives:**
- Shell script: cannot handle concurrent heartbeats cleanly
- Go: viable but no ecosystem advantage; vtf is Python, CLI is Python

### D2: Session resumption for rework

When a judge rejects a task (`changes_requested`), the controller resumes
the original harness session rather than starting fresh. This preserves
the full context — every file read, every decision made, every test run —
making rework faster, cheaper, and more accurate.

**How it works:**
1. Controller captures the harness session ID after initial execution
2. Stores session ID in vtf task metadata (so it survives controller restarts)
3. On rework, checks if session files exist in the task's workdir
4. If yes: `claude --resume <session-id> -p "<judge feedback>"`
5. If no (container changed, files lost): falls back to fresh session with
   full spec + judge feedback as context

**Session persistence via shared volume:** Session files live in each
task's workdir on the shared `/sessions/` volume. The workdir structure
is `/sessions/<milestone-id>/<task-id>/`. Because all executor containers
mount the same shared volume, **any executor** can pick up rework on any
task — the session files are right there in the task's workdir.

This means rework is not tied to a specific executor identity. If
executor-7 did the original work and dies, executor-8 can resume the
session from the same workdir on the shared volume.

**Fallback for unavailable sessions:** If session files are corrupted
or the harness can't resume (version mismatch, etc.), the controller
falls back to a fresh session with the full spec + judge feedback
prepended as context.

**SPIKE: Harness session and workdir behavior**
> Validation needed before implementation:
> 1. Where does the harness store session files? (`~/.claude/`? relative
>    to cwd? configurable?)
> 2. Are session files tied to `$HOME` or to the working directory?
> 3. Does `--resume` work when session files are on a mounted volume?
> 4. Can a harness instance resume a session created by a different
>    instance (same image, same paths, different container)?
> 5. Can the working directory change between invocations without
>    breaking session resumption?
> 6. How does the harness resolve auth tokens and config — from `$HOME`
>    or from the working directory?
>
> This is a quick test: run the harness in a container with a mounted
> volume, execute a task, stop the container, start a new container
> with the same volume, try `--resume`. Also test with different cwd
> between invocations.

### D3: State machine change — `changes_requested` → `doing`

The current vtf state machine has no work phase during rework. The
`resubmit` action goes directly from `changes_requested` to
`pending_completion_review`, skipping `doing`. This means no heartbeats,
no claim timeout, and no audit trail during rework execution.

**Change required:** Add `doing` to the valid transitions from
`changes_requested` in `state_machine.py`. This is a one-line change:

```python
"changes_requested": [
    "doing",                     # executor reclaims for rework (NEW)
    "pending_start_review",
    "pending_completion_review",
    "draft",                     # major rework
    "cancelled",
    "deferred",
],
```

**Rework flow with this change:**
```
changes_requested → doing     (controller reclaims, heartbeats start)
doing → pending_completion_review  (controller calls complete after rework)
```

The existing `resubmit` action is preserved for cases where rework
doesn't need a full `doing` phase (e.g., human making a quick fix).

### D4: Two poll targets for the controller

The controller polls two sources:

1. **`GET /v1/tasks/claimable?tags=<my-tags>`** — new work (`todo` tasks
   matching the executor's tags with all dependencies met)
2. **`GET /v1/tasks/?status=changes_requested&assigned_to=<my-agent-id>`**
   — rework assigned to this executor

Rework takes priority over new work. When the controller finds a
`changes_requested` task assigned to it, it handles that before polling
for new tasks.

**Rework prompt construction:**
```
The judge rejected your previous work on this task.

## Judge feedback
[review comments from vtf API]

## What to do
Read the feedback carefully. Fix the issues identified. Run tests
to verify your fixes. Commit when done.
```

This is sent either as a session resumption prompt or as part of a
fresh session (with the full spec prepended) depending on whether
session files are available.

### D5: Max rework attempts — 3, configurable

After 3 consecutive judge rejections on the same task, the controller
stops retrying and transitions the task to `needs_attention` (via the
`fail` action), signaling that a human needs to triage.

```
VF_MAX_REWORK_ATTEMPTS=3   # env var, default 3
```

The attempt count does not require local state — the controller queries
the vtf reviews API for the task and counts reviews with
`decision=changes_requested`. This survives container restarts and
works even if a different executor picks up the rework.

### D6: Dynamic workdirs per task on shared volume

All executor containers mount a shared volume at `/sessions/`. The
controller creates a workdir per task at
`/sessions/<milestone-id>/<task-id>/`.

```
/sessions/
  └── milestone-abc/
        ├── task-001/        ← repo checkout + harness session files
        ├── task-002/
        └── task-003/
```

**Per-task lifecycle:**
- **New task**: Controller creates the workdir, clones the repo into it,
  invokes the harness with that directory as cwd
- **Rework**: Controller reuses the existing workdir (repo + session files
  already present), invokes the harness in the same directory
- **Completed**: Workdir persists until milestone cleanup

**Why per-task workdirs:**
- Isolation: tasks cannot contaminate each other's repo state
- Rework: session files and repo state are preserved for resumption
- Debugging: workdirs for completed tasks can be inspected
- Any executor can work on any task — workdirs are on the shared volume

**Dynamic workdir vs current vf-agents:** Current vf-agents sets the
workdir once at container start (via `workdir.Manager` and mount at
`/workdir`). The new model requires the controller to create and
switch workdirs per task at runtime. Modified images must support the
harness being invoked with different working directories across its
lifetime.

### D7: Workdir cleanup on milestone completion

Workdirs accumulate during milestone execution and are cleaned up in
bulk when the milestone completes. For v1, cleanup is manual. Future
optimization: the orchestrator receives a milestone completion event
(webhook, SSE, or polling) and deletes `/sessions/<milestone-id>/`.

**Why milestone-level, not per-task:**
- Preserves all workdirs for cross-task debugging during milestone
  execution
- `needs_attention` tasks block milestone completion, so their workdirs
  are always preserved when needed
- One cleanup event per milestone instead of per task
- Disk is cheap — tolerating 200GB+ is acceptable

**v1:** Human runs `rm -rf /sessions/<milestone-id>/` after verifying
the milestone is complete.

**Future:** Orchestrator automates cleanup via vtf milestone completion
event.

### D8: Controller inside the container, orchestrator outside

The controller runs **inside** the executor container as a long-lived
process. It invokes the harness as a subprocess (`subprocess.run()`),
not as a separate container.

The **orchestrator** runs outside the containers and manages container
lifecycle — starting containers, assigning agent identities, mounting
volumes, setting resource limits, and handling cleanup.

**Why the controller is inside:**
- The harness is a subprocess, not a container — no Docker API needed
- `subprocess.kill()` handles hung harnesses
- `subprocess.run()` survives harness crashes (parent process is fine)
- asyncio heartbeats work alongside subprocess execution
- No Docker socket access needed (security benefit)
- No Docker-in-Docker complexity

**Why the orchestrator is outside:**
- Must control volume mounts (assigned at container creation)
- Must assign agent identities (env vars at container creation)
- Must set resource limits (container-level constraints)
- Must manage container lifecycle (start, restart, scale)
- For v1, this is `docker compose`. Future: dedicated pool manager or k8s.

**Separation of concerns:**

| Layer | Responsibility |
|-------|---------------|
| **Orchestrator** (outside) | Container lifecycle, volume mounts, agent identity, resource limits, workdir cleanup |
| **Controller** (inside) | vtf poll/claim loop, prompt construction, harness invocation, heartbeats, gate execution, vtf reporting |
| **Harness** (inside, subprocess) | Execute prompts, read/write code, run commands, store sessions |
