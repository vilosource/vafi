# vafi Architecture Summary

Compact reference for executor and judge agents. Read this instead of the full design docs.

## What vafi is

A GitLab Runner-like system for AI agents. Agents run in k8s pods, poll vtf for tasks, execute them, run verification gates, and report results autonomously.

## System components

```
vtf API (task board)  <-->  vafi controller (in pod)  -->  claude code (harness)
       ^                         |
       |                         v
  Web UI / CLI            git clone + test suite
```

- **vtf**: Task coordination API. Owns task state, specs, reviews, projects.
- **vafi controller**: Python asyncio loop inside a k8s pod. Polls vtf, claims tasks, invokes claude code, runs gates, reports results.
- **Claude Code**: The harness that executes task specs. Runs as a subprocess inside the agent pod.

## Controller loop

```
register() -> loop { poll() -> claim() -> clone repo -> invoke harness -> run gates -> complete/fail() }
```

1. Register agent with vtf (idempotent upsert)
2. Poll for work (rework first, then new tasks)
3. Claim task (30min timeout, heartbeat extends)
4. Clone project repo
5. Build prompt from task spec
6. Invoke Claude Code with prompt
7. Run verification gates (test suite)
8. Report result: complete (gates passed) or fail (gates failed)
9. If task needs review: vtf moves to pending_completion_review
10. Judge reviews, approves or requests changes
11. On changes_requested: controller picks up rework on next poll

## Key types

```python
AgentInfo(id, token)
TaskInfo(id, title, spec, project_id, test_command, needs_review, assigned_to)
RepoInfo(url, branch)
ReworkContext(session_id, judge_feedback, attempt_number)
ExecutionResult(success, session_id, completion_report, cost_usd, num_turns, gate_results)
GateResult(name, command, exit_code, stdout, passed)
```

## WorkSource protocol

The controller depends on `WorkSource`, not vtf directly. Methods:

| Method | Purpose |
|--------|---------|
| `register(name, tags)` | Register agent, get ID + token |
| `poll(agent_id, tags)` | Get next task (rework priority) |
| `claim(task_id, agent_id)` | Claim task for execution |
| `heartbeat(task_id)` | Extend claim timeout |
| `complete(task_id, result)` | Report success with results |
| `fail(task_id, reason)` | Report failure |
| `get_repo_info(project_id)` | Get clone URL + branch |
| `get_rework_context(task_id)` | Get judge feedback for rework |
| `count_rework_attempts(task_id)` | Check retry count (max 3) |
| `submit(task_id)` | draft -> todo (supervisor) |
| `list_submittable()` | Tasks with all deps done |
| `submit_review(task_id, decision, reason, reviewer_id)` | Judge verdict |

## vtf task lifecycle

```
draft -> todo -> doing -> [pending_completion_review -> done | changes_requested -> doing]
                      \-> needs_attention (unrecoverable failure)
```

## Infrastructure

- **k8s cluster**: k3s on fuji (192.168.2.91)
- **Registry**: harbor.viloforge.com (Harbor, in-cluster)
- **Images**: vafi-base → vafi-claude → vafi-agent (three-layer chain)
- **Namespaces**:
  - `vtf-prod` — vtf production (vtf.viloforge.com), the orchestrator
  - `vtf-dev` — vtf development (vtf.dev.viloforge.com), target for vtf changes
  - `vafi-agents` — executor/judge pods, one pool connected to vtf-prod
  - `vafi-prod` — vafi control plane (future)
- **vtf access from pods**: vtf-api.vtf-prod.svc.cluster.local:8000
- **vtf access from dev laptop**: https://vtf.viloforge.com

## Executor deployment model

One pool, one orchestrator. Like GitLab runners — there's one set of runners connected to one server.

```
executor-pool (vafi-agents)  --->  vtf-prod (orchestrator)
                                       |
                                  tasks reference
                                       |
                                  project repos (GitHub)
```

### Steady state

The `executor-pool` deployment in `vafi-agents` connects to **vtf-prod**. It polls for tasks, claims them, executes, reports back. This is the only permanent pool.

### Developing the executor

When changing controller code, images, or configuration:

1. `make build && make push` — build and push new images to harbor
2. `make smoke-test` — spins up an **ephemeral pod** connected to **vtf-dev**, submits a test task, watches execution, cleans up
3. If smoke test passes, promote: `make deploy --restart` to roll the new image into the stable pool

The smoke test never touches vtf-prod. The stable pool is never disrupted during development.

### Why not two pools?

vtf-dev is a **target application** (where agents deploy vtf changes), not a dev orchestrator. The dev/prod split is in the vtf instance, not the executor pool. Having two permanent pools would conflate "which vtf instance to talk to" with "which executor code to run."

## Key decisions

1. **k8s, not Docker Compose** — pods provide isolation, resource limits, scheduling
2. **Controller inside pod** — self-managing, no host-side orchestration
3. **WorkSource protocol** — controller is vtf-agnostic, swappable work sources
4. **Spec-driven execution** — task YAML carries everything the agent needs
5. **Gates as source of truth** — test suite exit code determines pass/fail, not agent self-report
6. **Supervisor is separate** — dispatches work to vtf board, doesn't run in pods
