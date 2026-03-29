# Architect Agent Design

> The third vafi agent role — translates human intent into formal requirements and vtf draft tasks.
> Companion to: [openspec-viloforge-integration-DESIGN.md](openspec-viloforge-integration-DESIGN.md)
> Created: 2026-03-29

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
6. Creates draft tasks in vtf (the draft-to-todo transition is the review gate)

### What It Does NOT Do

- Write code (that's the executor)
- Review code (that's the judge)
- Execute tasks or poll for work (it's not a controller loop)
- Make implementation decisions without human input (unless autonomous mode)

## 3. Interaction Model

The architect is **launched on demand**, not long-lived. It runs in a container with Claude Code (or another harness), the project repo cloned, and access to vtf and project knowledge.

### Two Modes

**Interactive** — human drives the conversation:
- Human describes what they want
- Architect asks clarifying questions, explores the codebase
- Back-and-forth until requirements are clear
- Architect produces specs and draft tasks
- Human reviews and approves (draft-to-todo in vtf)

**Autonomous** — another agent (or human via single prompt) delegates:
- Receives a planning prompt with enough context
- Reads the codebase and project knowledge
- Produces specs and draft tasks without further input
- Human reviews the output asynchronously

Both modes produce the same output: formal requirements + vtf draft tasks.

## 4. Three Interfaces

Same architect backend, multiple frontends:

### 4.1 vtf CLI

```bash
vtf plan <project-name>

# Example:
vtf plan vafi
# → Launches architect container
# → Clones vafi repo
# → Loads vtf project context (workplans, tasks, history)
# → Drops into interactive session

vtf plan vafi --prompt "Add webhook notifications for task state changes"
# → Launches architect in autonomous mode
# → Produces specs and draft tasks
# → Returns results
```

The CLI uses the vf-agents session model as prior art:
- `vtf plan <project>` — start interactive session (like `vfa session start` + `attach`)
- `vtf plan <project> --prompt "..."` — autonomous mode (like `vfa session start` with headless output)
- Session stays alive for follow-ups until explicitly closed

### 4.2 MCP Server

Exposes architect capabilities as MCP tools that any client can call:

```
architect_start(project, prompt?)     → session_id
architect_send(session_id, message)   → response
architect_close(session_id)           → summary
```

This enables:
- Claude Code (or any MCP client) to plan features autonomously
- IDE integrations to offer planning workflows
- Chaining: "plan this feature, then when I approve, submit the tasks"

Key use case: user tells Claude Code "plan the next feature for vafi" — Claude Code uses MCP tools to start an architect session, drives the conversation, creates draft tasks, and reports back. Human reviews drafts in vtf.

### 4.3 Web UI

Planning session accessible from the vtf web interface:
- Start a session from the project page or workplan
- Chat interface for interactive planning
- Live preview of generated specs and tasks
- Approve/reject directly in the UI (draft-to-todo)

This is the lowest priority interface — CLI and MCP cover the primary use cases.

## 5. Architecture

### Container Model

The architect runs in a k8s Pod, launched on demand:

```
vtf plan vafi
       │
       ▼
  vtf API creates architect pod
       │
       ▼
  ┌─────────────────────────────┐
  │  Architect Pod              │
  │                             │
  │  ┌───────────────────────┐  │
  │  │  Claude Code CLI      │  │
  │  │  (interactive or -p)  │  │
  │  └───────────┬───────────┘  │
  │              │              │
  │  ┌───────────▼───────────┐  │
  │  │  Project repo clone   │  │
  │  │  + methodology        │  │
  │  │  + vtf CLI/MCP access │  │
  │  └───────────────────────┘  │
  └─────────────────────────────┘
```

Uses the same image hierarchy as executor/judge:
- Base layer (git, python, node, tools)
- Claude layer (Claude Code CLI, cxtx)
- Agent layer (methodology, vtf CLI)

Role is `architect` — methodology file at `methodologies/architect.md` gets copied to `~/.claude/CLAUDE.md`.

### Lifecycle

1. **Launch**: `vtf plan <project>` → API creates Pod with project context
2. **Setup**: Pod clones repo, loads vtf project state (workplans, tasks, existing specs)
3. **Interact**: Human (or agent) sends prompts, architect responds
4. **Produce**: Architect creates draft tasks in vtf via CLI/API
5. **Close**: Pod is destroyed (or TTL-expires)

Unlike executor/judge, the architect Pod has no controller loop. The harness (Claude Code) IS the process — either interactive (TTY attached) or headless (prompt mode).

### What Gets Loaded (Project Context)

When the architect starts, it has:

| Context | Source | How |
|---------|--------|-----|
| Project codebase | vtf project `repo_url` + `default_branch` | `git clone` into workdir |
| Existing specs | `openspec/specs/` in the cloned repo | Available on disk |
| Project metadata | vtf API (workplans, milestones, task history) | Available via vtf CLI/MCP |
| Design docs | `docs/` in the cloned repo | Available on disk |
| CLAUDE.md | Project repo | Auto-loaded by Claude Code |
| Architect methodology | Container image | `~/.claude/CLAUDE.md` |

The architect has the full codebase so it can produce informed plans — it knows what patterns exist, what files to reference, and how things are structured. This makes the resulting task specs much more useful for executors.

## 6. Architect Methodology

The methodology file (`methodologies/architect.md`) defines how the architect behaves. Core principles:

### Planning Process

1. **Understand what exists** — read the codebase, existing specs, design docs, and vtf history
2. **Clarify intent** — ask questions until requirements are unambiguous (interactive mode)
3. **Write formal requirements** — use SHALL/WHEN/THEN format for every requirement
4. **Break down into tasks** — each task is a self-contained unit, informed by actual codebase structure
5. **Create draft tasks in vtf** — use vtf CLI to create tasks with requirements, acceptance criteria, file references, and dependency ordering

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

**vtf draft tasks** (created via API):
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

Because the architect has the codebase, the task specs include real file paths, references to existing patterns, and accurate test commands — giving executors a head start.

### Task Quality Checklist

The architect validates each task before creating it:

- [ ] Files section names real paths (verified by reading the codebase)
- [ ] References point to existing files an executor should read first
- [ ] Acceptance criteria are concrete and testable
- [ ] Test command works in the project's test structure
- [ ] Dependencies are explicit (task X depends on task Y)
- [ ] Requirements trace back to SHALL/WHEN/THEN specs
- [ ] Scope is right-sized — one task per logical unit of work

## 7. vtf Integration

### New vtf Concepts

**`vtf plan` command**: CLI entry point for architect sessions. Talks to vtf API to:
1. Look up project (repo_url, default_branch, existing workplans)
2. Request architect Pod launch (via vafi or directly via k8s)
3. Attach to the Pod (interactive) or send prompt (autonomous)

**Draft tasks as output**: The architect creates tasks in `draft` status. The existing draft-to-todo transition is the human review gate — no new approval workflow needed.

### API Additions

```
POST /v1/projects/{id}/architect/       → Launch architect session
GET  /v1/projects/{id}/architect/       → Get active session status
POST /v1/projects/{id}/architect/send/  → Send prompt to session
DELETE /v1/projects/{id}/architect/     → Close session
```

Or the session management could live entirely in vafi, with vtf just providing project context via its existing API.

## 8. cxdb Integration

Every architect session is traced in cxdb (same as executor/judge). The trace captures:

- The full conversation (human intent → architect reasoning → output)
- Design decisions made during planning
- The final requirements and task breakdown

This means: "why did we plan it this way?" has an answer — read the architect trace in cxdb.

The trace also serves as input for future architect sessions: "last time we planned webhooks, here's what we decided and why."

## 9. Rollout

### Phase 1: CLI only, manual container

- Write architect methodology
- Launch container manually (kubectl or docker)
- Clone repo, load vtf project context
- Interactive Claude Code session for planning
- Create draft tasks via vtf CLI from inside the container
- Validate the planning workflow works end-to-end

### Phase 2: `vtf plan` command

- Add `vtf plan <project>` to vtf CLI
- Automate container launch with project context
- Automate repo clone and context loading
- Interactive and autonomous modes

### Phase 3: MCP server

- Expose architect as MCP tools
- Enable Claude Code (and other MCP clients) to plan autonomously
- Test the full loop: plan → review → approve → execute → judge

### Phase 4: Web UI

- Planning chat interface in vtf web app
- Session management from the browser
- Live preview of specs and tasks

## 10. Open Questions

1. **Where does session management live?** vtf API (new endpoints) or vafi (extend the controller)? The architect Pod is vafi infrastructure, but the session is tied to a vtf project.

2. **How does the architect access vtf?** Same as executor — vtf API token in the container. But the architect also needs to CREATE tasks, not just read them. Does it use the vtf CLI directly, or go through the controller?

3. **Should the architect commit specs to the repo?** If it writes `openspec/specs/` files, those need to be committed and pushed. Same deliver mechanism as executor — but for planning artifacts, not code.

4. **How do we handle multi-session planning?** If the human starts a session, closes it, and comes back later — can we resume? The vf-agents session model supports this via persistent containers + session IDs.

5. **What's the minimum viable methodology?** The executor methodology is 60 lines. How much guidance does the architect need to produce good specs and task breakdowns?
