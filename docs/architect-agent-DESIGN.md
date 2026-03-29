# Architect Agent Design

> The third vafi agent role — translates human intent into formal requirements and vtf draft tasks.
> Created: 2026-03-29 | Updated: 2026-03-30 (spike findings incorporated)

---

## 1. Problem Statement

Today the path from idea to vtf task spec is manual. A human writes YAML specs by hand, informed by their understanding of the codebase, design docs, and conventions. This works but doesn't scale — writing good specs requires deep project context, and the quality depends on how much research the author does upfront.

The executor and judge agents are autonomous — they poll for work and execute without human involvement. But there is no agent for the planning phase. The gap is between "I want to add data export" and a set of vtf draft tasks with formal requirements, file paths, test commands, and dependency ordering.

## 2. What the Architect Does

The architect is a **planning agent** that:

1. Loads full project context (repo clone, vtf history, existing specs, design docs)
2. Consults with the human (or works autonomously) to understand intent
3. Reads the codebase to understand what exists, patterns, and structure
4. Produces formal requirements using SHALL/WHEN/THEN format
5. Breaks work into vtf draft tasks informed by the actual codebase
6. Creates draft tasks in vtf via MCP (the draft-to-todo transition is the review gate)

### What It Does NOT Do

- Write code (that's the executor)
- Review code (that's the judge)
- Execute tasks or poll for work (it's not a controller loop)
- Make implementation decisions without human input (unless autonomous mode)

## 3. Interaction Model

The architect is **launched on demand**, not long-lived. It runs in a container with Claude Code, the project repo cloned, and vtf MCP access for task management.

### Two Modes

**Interactive** — human drives the conversation:
- Human describes what they want
- Architect asks clarifying questions, explores the codebase
- Back-and-forth until requirements are clear
- Architect produces specs and creates draft tasks via MCP
- Human reviews and approves (draft-to-todo in vtf)

**Autonomous** — another agent (or human via single prompt) delegates:
- Receives a planning prompt with enough context
- Reads the codebase and project knowledge
- Produces specs and creates draft tasks via MCP without further input
- Human reviews the output asynchronously

Both modes produce the same output: formal requirements + vtf draft tasks.

## 4. Three Interfaces

Same architect backend, multiple frontends:

### 4.1 vtf CLI

```bash
vtf plan <project-name>

# Example:
vtf plan vafi
# → Launches architect Pod
# → Clones vafi repo
# → Drops into interactive Claude Code session

vtf plan vafi --prompt "Add webhook notifications for task state changes"
# → Launches architect in autonomous mode
# → Produces specs and draft tasks
# → Returns results
```

### 4.2 MCP Server

Exposes architect capabilities as MCP tools that any client can call:

```
architect_start(project, prompt?)     → session_id
architect_send(session_id, message)   → response
architect_close(session_id)           → summary
```

Key use case: user tells Claude Code "plan the next feature for vafi" — Claude Code uses MCP tools to start an architect session, drives the conversation, creates draft tasks, and reports back. Human reviews drafts in vtf.

### 4.3 Web UI

Planning session accessible from the vtf web interface. Lowest priority — CLI and MCP cover the primary use cases.

## 5. Architecture

### Container Model

The architect uses the **same image** as executor/judge (`vafi-agent`). The difference is the entrypoint — when `VF_AGENT_ROLE=architect`, the entrypoint skips the controller loop and either starts an interactive Claude Code session or runs headless with a prompt.

```
vtf plan vafi
       │
       ▼
  Create Pod (vafi-agent image, VF_AGENT_ROLE=architect)
       │
       ▼
  ┌─────────────────────────────────┐
  │  Architect Pod                  │
  │                                 │
  │  Entrypoint:                    │
  │  1. Copy methodology → CLAUDE.md│
  │  2. Patch ~/.claude.json        │
  │  3. Clone project repo          │
  │  4. sleep infinity (or claude)  │
  │                                 │
  │  ┌───────────────────────────┐  │
  │  │  Claude Code CLI          │  │
  │  │  + vtf MCP (14 tools)     │  │
  │  │  + project repo on disk   │  │
  │  │  + methodology            │  │
  │  └───────────────────────────┘  │
  └─────────────────────────────────┘
```

No new image required. No vtf CLI needed — MCP provides full task management.

### Entrypoint Changes

The existing `entrypoint.sh` ends with `exec python3 -m controller`. For architect role, it must:

1. Copy `methodologies/architect.md` → `~/.claude/CLAUDE.md` (same as executor/judge)
2. Patch `~/.claude.json` with onboarding and MCP config (see Section 6)
3. Configure git identity (same as executor/judge)
4. Clone the project repo into the workdir
5. **Skip the controller** — either `sleep infinity` (for `kubectl exec -it` attach) or `exec claude` (direct interactive) or `claude -p "$PROMPT"` (autonomous)

```bash
# In entrypoint.sh, replace the final line:
if [ "$AGENT_ROLE" = "architect" ]; then
    # Setup repo clone
    WORKDIR="/sessions/architect-$(date +%s)"
    git clone --branch "$VF_DEFAULT_BRANCH" --single-branch --depth 1 "$VF_REPO_URL" "$WORKDIR"
    cd "$WORKDIR"

    if [ -n "$VF_ARCHITECT_PROMPT" ]; then
        # Autonomous mode
        exec claude -p "$VF_ARCHITECT_PROMPT" --output-format json \
            --max-turns "${VF_MAX_TURNS:-50}" --dangerously-skip-permissions
    else
        # Interactive mode — wait for kubectl exec -it
        echo "Architect ready at $WORKDIR. Attach with: kubectl exec -it <pod> -- bash -c 'cd $WORKDIR && claude'"
        exec sleep infinity
    fi
else
    exec python3 -m controller
fi
```

### Lifecycle

1. **Launch**: `vtf plan <project>` → create Pod with project context
2. **Setup**: Entrypoint patches config, clones repo
3. **Interact**: Human attaches (`kubectl exec -it`) or autonomous prompt runs
4. **Produce**: Architect creates draft tasks in vtf via MCP tools
5. **Close**: Pod deleted (manual or TTL)

## 6. Configuration (Spike-Verified)

### ~/.claude.json

Must be patched by the entrypoint before Claude Code starts. Three concerns:

```json
{
  "hasCompletedOnboarding": true,
  "theme": "dark",
  "projects": {
    "<workdir-path>": {
      "hasTrustDialogAccepted": true,
      "hasCompletedProjectOnboarding": true
    }
  },
  "mcpServers": {
    "vtf": {
      "type": "http",
      "url": "http://vtf-mcp.vtf-dev.svc.cluster.local:8002/mcp",
      "headers": {
        "Authorization": "Token <VF_VTF_TOKEN>"
      }
    }
  }
}
```

**Critical details** (discovered during spike):
- `"type": "http"` is **required** — without it, MCP server silently fails to connect
- `hasCompletedOnboarding` skips the first-run welcome screen that blocks interactive input
- `hasTrustDialogAccepted` and `hasCompletedProjectOnboarding` are per-workdir and skip trust prompts
- Pattern from vf-agents `prepareClaudeHomeConfig()` in `internal/orchestrator/run.go`

### Environment Variables

Same secrets as executor/judge, plus architect-specific vars:

| Variable | Purpose |
|----------|---------|
| `VF_AGENT_ROLE=architect` | Selects architect entrypoint path |
| `VF_REPO_URL` | Git clone URL (from vtf project) |
| `VF_DEFAULT_BRANCH` | Branch to clone (from vtf project) |
| `VF_ARCHITECT_PROMPT` | If set, run autonomous mode with this prompt |
| `ANTHROPIC_AUTH_TOKEN` | Claude API auth (from secret) |
| `ANTHROPIC_BASE_URL` | Claude API endpoint (from secret) |
| `VF_VTF_TOKEN` | vtf API token for MCP auth (from secret) |

### Volumes and Secrets

Identical to executor/judge:
- `vafi-sessions` PVC mounted at `/sessions` (shared workdir storage)
- `github-ssh` secret → init container copies to `/home/agent/.ssh`
- `vafi-secrets` → `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `VF_VTF_TOKEN`

## 7. vtf MCP Access (Spike-Verified)

The architect uses vtf MCP tools directly — no vtf CLI needed. Spike confirmed 14 tools available:

| Tool | Purpose for Architect |
|------|----------------------|
| `vtf_board_overview` | See current project state |
| `vtf_search_tasks` | Find existing tasks, avoid duplicates |
| `vtf_task_detail` | Read existing task specs for context |
| `vtf_manage_task` | **Create draft tasks** (primary output) |
| `vtf_manage_workplan` | Create/update workplans |
| `vtf_manage_milestone` | Create/update milestones |
| `vtf_workplan_tree` | See workplan/milestone/task hierarchy |

The MCP server runs as a separate service in each vtf namespace:
- Dev: `http://vtf-mcp.vtf-dev.svc.cluster.local:8002/mcp`
- Prod: `http://vtf-mcp.vtf-prod.svc.cluster.local:8002/mcp`

## 8. Architect Methodology

The methodology file (`methodologies/architect.md`) defines how the architect behaves. Copied to `~/.claude/CLAUDE.md` by the entrypoint.

### Planning Process

1. **Understand what exists** — read the codebase, existing specs, design docs, and vtf board state (via MCP)
2. **Clarify intent** — ask questions until requirements are unambiguous (interactive mode)
3. **Write formal requirements** — use SHALL/WHEN/THEN format for every requirement
4. **Break down into tasks** — each task is a self-contained unit, informed by actual codebase structure
5. **Create draft tasks in vtf** — use vtf MCP tools to create tasks with requirements, acceptance criteria, file references, and dependency ordering

### Output Format

For each planned feature, the architect produces:

**Requirements** (in the repo as specs):
```markdown
### Requirement: Webhook notifications for task state changes
The system SHALL send webhook notifications when a task transitions to a new state.

#### Scenario: Task completed
- WHEN a task transitions to done
- THEN the system sends a POST request to all registered webhook URLs
- AND the payload includes task_id, old_status, new_status, and timestamp

#### Scenario: Webhook delivery failure
- WHEN the webhook endpoint returns non-2xx
- THEN the system retries up to 3 times with exponential backoff
```

**vtf draft tasks** (created via MCP `vtf_manage_task`):
```yaml
title: "Add webhook model and registration endpoint"
description: |
  Create Webhook model and CRUD endpoints for registering webhook URLs per project.
  Follow the existing ViewSet pattern in src/tasks/views.py.
files:
  create:
    - src/webhooks/models.py
    - src/webhooks/views.py
    - src/webhooks/serializers.py
  modify:
    - src/vtaskforge/urls.py
implementation:
  references:
    - src/tasks/models.py
    - src/tasks/views.py
acceptance_criteria:
  - "POST /v1/webhooks/ creates a webhook registration"
  - "GET /v1/webhooks/ lists webhooks for the project"
  - "DELETE /v1/webhooks/{id}/ removes registration"
test_command:
  unit: "pytest tests/webhooks/"
requirements:
  - requirement: "Webhook notifications for task state changes"
    scenarios: ["Webhook registration"]
depends_on: []
```

### Task Quality Checklist

The architect validates each task before creating it:

- [ ] Files section names real paths (verified by reading the codebase)
- [ ] References point to existing files an executor should read first
- [ ] Acceptance criteria are concrete and testable
- [ ] Test command works in the project's test structure
- [ ] Dependencies are explicit (task X depends on task Y)
- [ ] Requirements trace back to SHALL/WHEN/THEN specs
- [ ] Scope is right-sized — one task per logical unit of work

## 9. cxdb Integration

Every architect session is traced in cxdb (same as executor/judge) when `VF_CXDB_URL` is set. The trace captures:

- The full conversation (human intent → architect reasoning → output)
- Design decisions made during planning
- The final requirements and task breakdown

This means: "why did we plan it this way?" has an answer — read the architect trace in cxdb.

## 10. Rollout

### Phase 1: Manual container + methodology

- Write `methodologies/architect.md`
- Update `entrypoint.sh` to handle `VF_AGENT_ROLE=architect`
- Add `~/.claude.json` patching (onboarding + MCP config)
- Launch Pod manually, validate interactive and autonomous modes
- Test full workflow: plan → create draft tasks via MCP → review in vtf

### Phase 2: `vtf plan` command

- Add `vtf plan <project>` to vtf CLI
- Automate Pod launch with project context (repo_url, default_branch from vtf project)
- Support `--prompt` for autonomous mode
- Pod TTL and cleanup

### Phase 3: MCP server

- Expose architect as MCP tools (`architect_start/send/close`)
- Enable Claude Code (and other MCP clients) to plan autonomously
- Test the full loop: plan → review → approve → execute → judge

### Phase 4: Greenfield project support

The current design assumes an existing project with a repo to clone. For new projects:
- No repo exists — architect skips clone, proposes project structure instead of discovering it
- No vtf project exists — architect creates one via MCP
- First tasks are scaffolding (init repo, set up test framework, create structure) before feature work
- Methodology needs a greenfield path that asks about tech stack, conventions, and deployment target instead of exploring an existing codebase
- Task specs have no "files to modify" or "references" — only "files to create"

### Phase 5: Web UI

- Planning chat interface in vtf web app
- Session management from the browser
- Live preview of specs and tasks

## 11. Spike Results (2026-03-29)

All technical unknowns resolved:

| Test | Result |
|------|--------|
| Same image, entrypoint override | Works — no new image needed |
| Claude Code headless in k8s Pod | Works — `-p` with `--output-format json` |
| Claude Code interactive in k8s Pod | Works — `kubectl exec -it` with TTY |
| SSH auth / repo clone | Works — vilosource identity |
| Codebase-aware prompts | Works — reads files, produces informed output |
| Session resume (`--resume`) | Works — multi-turn preserves context |
| Git push from Pod | Works — push and revert verified |
| vtf MCP from Pod | Works — 14 tools, `type: http` required in config |
| Onboarding skip | Works — patch `~/.claude.json` with flags |

**Key finding**: MCP config in `~/.claude.json` **must** include `"type": "http"` — without it the server silently fails to connect. This was not obvious from documentation.

## 12. Open Questions

1. **Where does session management live?** vtf API (new endpoints) or a standalone service? The architect Pod is k8s infrastructure, but the session is tied to a vtf project.

2. **Should the architect commit specs to the repo?** If it writes `openspec/specs/` files, those need to be committed and pushed. Same deliver mechanism as executor — but for planning artifacts, not code.

3. **How do we handle multi-session planning?** If the human starts a session, closes it, and comes back later — can we resume? Session resume (`--resume`) works, but the Pod needs to stay alive.

4. **What's the minimum viable methodology?** The executor methodology is 60 lines. How much guidance does the architect need to produce good specs and task breakdowns?
