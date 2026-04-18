# vafi Architecture Summary

Compact reference for the vafi agent fleet. Read this instead of the archived design docs.

Last updated: 2026-04-18

## What vafi is

A GitLab Runner-like system for AI agents. Agents run in k8s pods, poll vtf for tasks, execute them using AI harnesses (Claude Code or Pi), run verification gates, capture traces, and report results autonomously.

## System components

```
vtf API (task board)  <-->  vafi controller (in pod)  -->  harness (claude or pi)
       ^                         |                              |
       |                         v                         cxtx (trace proxy)
  Web UI / CLI            git clone + test suite                |
                                                           cxdb (traces + summaries)
```

- **vtf**: Task coordination API. Owns task state, specs, reviews, projects.
- **vafi controller**: Python asyncio loop inside a k8s pod. Polls vtf, claims tasks, invokes harness, runs gates, reports results. Harness-agnostic.
- **Harness**: The AI CLI that executes task specs. Runs as a subprocess. Currently Claude Code or Pi coding agent, selected by `VF_HARNESS` env var.
- **cxtx**: Trace capture proxy. Wraps harness invocation to intercept API calls and push to cxdb.
- **cxdb**: Execution trace store. Captures full conversation DAGs. Provides post-mortem analysis, session summaries, and MCP tools for the architect agent.
- **vafi-console**: Web-based terminal for interactive architect sessions (xterm.js + WebSocket proxy to k8s exec).

## Agent roles

| Role | Mode | Purpose |
|------|------|---------|
| **Executor** | Autonomous | Claims tasks, writes code, runs gates |
| **Judge** | Autonomous | Reviews executor work, approves or requests changes |
| **Architect** | Interactive | Planning sessions with a human, creates vtf tasks via MCP |

All three roles use the same image hierarchy and controller code. Role is selected by `VF_AGENT_ROLE` env var.

> **"Supervisor" is a design contract, not a running role.** The
> interface `CONTRACT.md §13` and `WorkSource.submit()` /
> `list_submittable()` describe a supervisor that polls for draft
> tasks with dependencies met and promotes them to `todo`. No such
> daemon runs in vafi — the controller has no `supervisor` branch.
> Draft→todo promotion is performed by humans (UI) or architect
> agents (MCP `vtf_submit_task`). The methods remain in the
> `WorkSource` protocol for a future supervisor implementation.

## Controller loop

```
register() -> loop { poll() -> claim() -> clone repo -> build context -> invoke harness -> run gates -> summarize -> complete/fail() }
```

1. Register agent with vtf (idempotent upsert)
2. Poll for work (rework first, then new tasks)
3. Claim task (heartbeat extends claim timeout)
4. Clone project repo (SSH via github-ssh secret)
5. Build context file (`.vafi/context.md` — task state, judge feedback, rework history)
6. Invoke harness with task prompt (wrapped in cxtx for trace capture)
7. Run verification gates (test suite exit code = source of truth)
8. Post-execution (best-effort, background): look up trace URL in cxdb and post to vtf notes; if summarizer configured, generate NL summary via Haiku
9. Report result: complete (gates passed) or fail (gates failed)
10. On changes_requested: controller picks up rework on next poll. After `VF_MAX_REWORK` rejections (default 3), the controller fails the task with a triage message instead of invoking the harness again — enforced in `_poll_and_execute` (fix 62f455d).

## Multi-harness support

Two harnesses are supported. See [harness-images-ARCHITECTURE.md](harness-images-ARCHITECTURE.md) for full details.

| Aspect | Claude Code | Pi |
|--------|------------|-----|
| Image | `vafi-agent` | `vafi-agent-pi` |
| CLI | `claude -p ... --output-format json` | `pi -p ... --mode json` |
| Permission handling | `--dangerously-skip-permissions` | Headless-safe by default |
| Methodology delivery | Auto-discovered from `~/.claude/CLAUDE.md` | `--append-system-prompt` flag |
| Output format | Single JSON object | Streaming JSONL |
| MCP config | `~/.claude.json` mcpServers | `~/.pi/agent/mcp.json` via pi-mcp-adapter |
| API key env var | `ANTHROPIC_AUTH_TOKEN` | `ANTHROPIC_API_KEY` |
| cxtx support | `cxtx claude` | `cxtx pi` |
| Helm chart template | `executor-deployment.yaml` | `executor-pi-deployment.yaml` |
| Values section | `executor.*` | `executorPi.*` (gated by `executorPi.enabled`) |

Both harnesses use the same controller, gates, WorkSource protocol, and reporting. Each runs as its own Deployment; work sources filter by agent-tag subset (`executor` for claude, `executor,pi` for pi). The controller's summarizer reads whichever API-key env var is present, so pi pods get the Haiku NL summary generator without Claude-specific env vars.

## Observability (cxdb)

Every task execution is traced:

1. **cxtx** wraps the harness subprocess, intercepting all LLM API calls
2. Traces are pushed to **cxdb** (immutable conversation DAG)
3. After execution, the **summarizer** extracts structured data (files changed, tools used, tests run, commits made)
4. **NL summary** generated via Haiku (one-liner, what happened, key decisions, failure analysis)
5. Trace URL and summary posted to vtf task notes and `execution_summary` field

The **cxdb-mcp** service exposes 4 tools for the architect agent: `cxdb_session_summary`, `cxdb_session_breadcrumbs`, `cxdb_get_turns`, `cxdb_list_sessions`.

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
| `poll_reviews(agent_id)` | Get tasks in changes_requested state |
| `claim(task_id, agent_id)` | Claim task for execution |
| `heartbeat(task_id)` | Extend claim timeout |
| `agent_heartbeat(agent_id)` | Update agent last_heartbeat |
| `set_agent_offline(agent_id)` | Mark agent offline on shutdown |
| `complete(task_id, result)` | Report success with results |
| `fail(task_id, reason)` | Report failure |
| `get_repo_info(project_id)` | Get clone URL + branch |
| `get_rework_context(task_id)` | Get judge feedback for rework |
| `count_rework_attempts(task_id)` | Check retry count (max 3) |
| `get_task_context(task_id)` | Get task with reviews for context file |
| `add_note(task_id, content)` | Post note to task (trace URLs, metadata) |
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
- **Images**: See [harness-images-ARCHITECTURE.md](harness-images-ARCHITECTURE.md)
  - `vafi-base` -> `vafi-claude` -> `vafi-agent` (Claude harness)
  - `vafi-base` -> `vafi-pi` -> `vafi-agent-pi` (Pi harness)
  - Agent Dockerfile is parameterized via `HARNESS_IMAGE` build arg
- **Namespaces**:
  - `vtf-prod` — vtf production (vtf.viloforge.com)
  - `vtf-dev` — vtf development (vtf.dev.viloforge.com)
  - `vafi-dev` — development executor/judge pools, connected to vtf-dev
  - `vafi-prod` — production executor/judge pools, connected to vtf-prod
- **Services** (Helm-managed, names are `<release>-<component>`):
  - `<release>-cxdb` — cxdb trace store (StatefulSet, port 80)
  - `cxdb-mcp` — MCP server for cxdb tools (port 8090, deployed separately from Helm chart)
  - `vafi-console` — web terminal for architect sessions (deployed separately from Helm chart)
- **vtf access from pods**: configured via `VF_VTF_API_URL` env var (code default: `vtf-api.vafi-system.svc.cluster.local:8000`; in practice set to `vtf-api.vtf-dev.svc.cluster.local:8000` or `vtf-api.vtf-prod.svc.cluster.local:8000` by Helm)
- **Auth**: Anthropic API key via k8s Secret (Helm-templated name, e.g. `vafi-secrets`), SSH via `github-ssh` secret

## Deployment model

Pools per environment, each connected to its vtf instance:

```
vafi-dev executor pool   --->  vtf-dev (development)
vafi-dev executor-pi pool
vafi-prod executor pool  --->  vtf-prod (production)
```

Managed via Helm chart (`charts/vafi/`). Dev pools used for testing controller changes. Prod pools run stable code.

## Test suite

193 tests covering controller, invoker (Claude + Pi), config, WorkSource, gates, judge, heartbeat, vtf client, cxdb (client, parser, extractor, summarizer, NL summary, dispatch, workplan context), and cxdb-mcp formatters.

```bash
cd ~/GitHub/vafi && python -m pytest tests/ -v
```

## Key decisions

1. **k8s, not Docker Compose** — pods provide isolation, resource limits, scheduling
2. **Controller inside pod** — self-managing, no host-side orchestration
3. **WorkSource protocol** — controller is vtf-agnostic, swappable work sources
4. **Multi-harness** — Claude Code and Pi supported via `VF_HARNESS` env var. Controller is harness-agnostic.
5. **Spec-driven execution** — task specs carry everything the agent needs
6. **Gates as source of truth** — test suite exit code determines pass/fail, never parse LLM output
7. **cxtx for traces** — every execution captured in cxdb, NL summaries generated automatically
8. **Supervisor is separate** — dispatches work to vtf board, doesn't run in pods
