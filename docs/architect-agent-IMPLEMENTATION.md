# Architect Agent — Implementation Reference

> Complete implementation guide for the architect agent. Serves as a pattern for building other interactive agents (as opposed to background worker agents like executor/judge).
> Updated: 2026-03-30

---

## What is the Architect Agent?

The architect is an interactive AI agent that sits between human intent and structured work. A user opens a terminal session with the architect, discusses what they want to build or change, and the architect creates formal requirements and draft tasks in vtf (the task tracker) via MCP tools.

Unlike executor and judge agents which are long-lived background workers polling for tasks, the architect runs on-demand in a k8s pod launched from the vtf web UI. The same container image (`vafi-agent`) serves all three roles — the role is selected by the `VF_AGENT_ROLE` environment variable.

---

## Architecture

Three systems collaborate to deliver an architect session:

```
vtf web UI                vafi-console              k8s pod (architect)
----------                ------------              -------------------
User clicks               POST /api/pods            entrypoint.sh:
"Plan with Architect"  -> (find or create pod)  ->   - patch .claude.json
                                                     - clone repo
Widget opens iframe    -> WS /ws/exec/{pod}     ->   - write CLAUDE.md
with embed=true           (k8s exec proxy)           - write /tmp/ready
                                                     - sleep infinity
Terminal renders       <- xterm.js <-> WebSocket <-  claude --dangerously-skip-permissions
in floating widget        (bidirectional relay)      (interactive CLI session)
```

**vtf web** provides the UI (floating widget with iframe). **vafi-console** manages pod lifecycle and proxies terminal connections. **The pod** runs Claude Code with MCP access to vtf.

---

## Pod Lifecycle

### Launch

1. User clicks a button in vtf web ("Plan with Architect" or "Consult Architect")
2. vtf widget opens an iframe pointing to `console.dev.viloforge.com/?role=architect&project={slug}&embed=true`
3. Console frontend calls `POST /api/pods {role: "architect", project: "{slug}"}`
4. PodManager does `find_or_create` — searches by labels `role+project+user`. If a matching pod exists and is healthy, reuses it. Otherwise creates a new one.
5. Console frontend polls `GET /api/pods/{name}` until status is `Running` (readiness probe passed)
6. Console frontend opens WebSocket to `WS /ws/exec/{pod_name}?command=claude`

### Inside the Pod

The entrypoint runs (for `VF_AGENT_ROLE=architect`):

1. Copy methodology to `~/.claude/CLAUDE.md`
2. Determine workdir: `/sessions/{project_slug}` or `/sessions/greenfield`
3. Patch `~/.claude.json`: skip onboarding, configure MCP server, set project trust
4. Clone repo to workdir (if `VF_REPO_URL` is set), or create empty directory
5. Write `CLAUDE.md` in workdir with project context
6. Write workdir path to `/tmp/ready` (readiness sentinel)
7. `exec sleep infinity` (wait for terminal attachment)

### Terminal Connection

The WebSocket proxy builds the exec command:

```bash
# First connection (no prior session):
cd /sessions/{project} && exec claude --dangerously-skip-permissions

# Subsequent connections (session exists):
cd /sessions/{project} && exec claude --continue --dangerously-skip-permissions
```

Session detection: Claude Code stores sessions under `~/.claude/projects/{dir-key}/` where `dir-key` is the absolute path with `/` replaced by `-`. The proxy checks if this directory exists to decide between `--continue` and fresh start.

### Cleanup

- Pod stays alive between connections (supports reconnect)
- Idle cleanup: after 30 minutes with 0 active WebSocket connections, the pod is deleted
- Active connection tracking via pod annotations (`vafi.viloforge.com/active-connections`)

---

## Environment Variables

The console PodManager injects these into every architect pod:

| Variable | Source | Purpose |
|----------|--------|---------|
| `VF_AGENT_ROLE` | Role config (`extra_env`) | Set to `architect` — controls entrypoint routing |
| `ANTHROPIC_AUTH_TOKEN` | Secret `vafi-secrets` | Claude API authentication |
| `ANTHROPIC_BASE_URL` | Secret `vafi-secrets` | Claude API endpoint |
| `VF_VTF_MCP_URL` | Console config (`vtf_mcp_url`) | vtf MCP server endpoint |
| `VF_VTF_TOKEN` | Secret `vafi-secrets` | vtf MCP authentication token |
| `VTF_API_URL` | Console config (`vtf_api_url`) | vtf REST API base URL |
| `VTF_PROJECT_SLUG` | Launch request | Project identifier (empty for greenfield) |
| `VTF_WORKPLAN_ID` | Launch request | Workplan context hint (optional) |
| `VF_REPO_URL` | Fetched from vtf project | Git clone URL (empty for greenfield) |
| `VF_DEFAULT_BRANCH` | Fetched from vtf project | Branch to clone (default: `main`) |
| `GIT_SSH_COMMAND` | Hardcoded | SSH config for git clone |

**Secrets required in the namespace:**
- `vafi-secrets`: keys `anthropic-auth-token`, `anthropic-base-url`, `vtf-token`
- `github-ssh`: key `ssh-privatekey` (mounted as volume at `/home/agent/.ssh/id_rsa`)

---

## Pod Specification

### Labels (for idempotent lookup)

```
vafi.viloforge.com/role: architect
vafi.viloforge.com/project: {slug}
vafi.viloforge.com/managed-by: console
vafi.viloforge.com/user: {username}
```

One pod per `role + project + user` combination. This ensures user isolation and project scoping.

### Readiness Probe

```yaml
readinessProbe:
  exec:
    command: ["test", "-f", "/tmp/ready"]
  initialDelaySeconds: 2
  periodSeconds: 2
```

The entrypoint writes `/tmp/ready` (containing the workdir path) after all setup is complete. Until this file exists, the pod reports as `Initializing` (Running but not Ready). The console frontend keeps polling and does not connect the WebSocket until the pod is `Running` (Ready=True).

### Volumes

| Name | Type | Mount | Purpose |
|------|------|-------|---------|
| `home` | emptyDir | `/home/agent` | Ephemeral home (`.claude/` config, Claude sessions) |
| `sessions` | PVC (`console-sessions`) | `/sessions` | Persistent workdir for project files and repo clones |
| `github-ssh` | secret | `/home/agent/.ssh` (readonly) | SSH key for git clone |

The `sessions` volume uses a PersistentVolumeClaim (`console-sessions`, 10Gi), not an emptyDir. This means repo clones and workdir files survive pod deletion. When a new pod is created for the same project, the repo is already there — no re-clone needed. Claude sessions (`~/.claude/`) are still in the ephemeral `home` volume, but `--continue` handles session resumption gracefully.

### Resources

```yaml
requests:
  cpu: "500m"
  memory: "1Gi"
limits:
  cpu: "1"
  memory: "2Gi"
```

### Security

```yaml
securityContext:
  runAsUser: 1001
  runAsNonRoot: true
automountServiceAccountToken: false
restartPolicy: Never
```

The pod has no k8s API access (no service account token mounted). It communicates only with vtf via HTTP (MCP) and the outside world via git (SSH).

---

## MCP Configuration

The entrypoint patches `~/.claude.json` with the MCP server config:

```json
{
  "mcpServers": {
    "vtf": {
      "type": "http",
      "url": "http://vtf-mcp.vtf-dev.svc.cluster.local:8002/mcp",
      "headers": {
        "Authorization": "Token {VF_VTF_TOKEN}"
      }
    }
  }
}
```

**Critical**: the `"type": "http"` field is mandatory. Without it, Claude Code silently fails to connect to the MCP server.

The MCP server runs as a separate k8s service (`vtf-mcp`) in the vtf namespace, not as a path on the API. Token authentication is required.

### Available MCP Tools

The architect has access to 14 vtf MCP tools. Key ones for planning:

| Tool | Purpose |
|------|---------|
| `vtf_board_overview` | See project state (tasks by status) |
| `vtf_workplan_tree` | Hierarchical view of workplan structure |
| `vtf_search_tasks` | Find tasks by query/status/label |
| `vtf_task_detail` | Full task specification |
| `vtf_manage_task` | Create/update tasks (primary architect tool) |
| `vtf_manage_workplan` | Create/update workplans |
| `vtf_manage_milestone` | Create/update milestones |

---

## Methodology

The architect's behavior is defined by a methodology file at `/opt/vf-agent/methodologies/architect.md`, copied to `~/.claude/CLAUDE.md` by the entrypoint.

### Planning Steps

0. **Orient** — Determine if existing or greenfield project
1. **Understand Intent** — Clarify goals, constraints, tech stack preferences
2. **Explore Codebase** — Read source files, understand patterns (existing projects)
3. **Write Requirements** — Formal SHALL/WHEN/THEN specifications
4. **Break Down into Tasks** — Decompose into executable units with specs
5. **Create Draft Tasks** — Use vtf MCP to persist tasks for review

### Task Specification Format

Each task created by the architect includes:
- **Title**: imperative form ("Add webhook model")
- **Description**: what to build and why
- **Files**: real paths to create or modify
- **References**: existing files the executor should read first
- **Acceptance criteria**: testable statements
- **Test command**: how to verify the work
- **Dependencies**: which tasks block this one

Tasks are created as **drafts** — a human reviews and submits them to `todo` status before executors can claim them.

### Project CLAUDE.md

In addition to the methodology at `~/.claude/CLAUDE.md`, the entrypoint writes a project-specific `CLAUDE.md` in the workdir:

```markdown
# Architect Session

You are an architect agent in the vafi fleet.

## Project
- **Project**: {VTF_PROJECT_SLUG}
- **Repository**: {VF_REPO_URL} (branch: {VF_DEFAULT_BRANCH})

## Available Tools
- vtf_board_overview, vtf_search_tasks, vtf_manage_task, etc.

## Workflow
1. Understand what the user wants
2. Explore existing project state via MCP
3. Break work into concrete tasks
4. Create tasks in vtf with clear specs
```

This gives the architect immediate context about which project it's working on without requiring the user to explain.

---

## Session Management

### First Connection

No prior Claude session exists. The proxy runs `claude --dangerously-skip-permissions` (no `--continue`). Claude starts fresh, reads the CLAUDE.md files, and begins the conversation.

### Reconnection (same pod)

A prior session exists at `~/.claude/projects/{dir-key}/`. The proxy detects this and runs `claude --continue --dangerously-skip-permissions`. Claude resumes the previous conversation with full context.

### Pod Reuse

The `find_or_create` logic matches pods by `role + project + user` labels. If a matching pod exists and is healthy (Running/Pending/Initializing), it's reused. The repo clone and workdir persist. Only the Claude session needs to resume.

### Pod Loss (cleanup or crash)

When the pod is deleted (idle TTL or crash), the `/sessions` volume persists on the PVC. Repo clones and workdir files survive. Only the Claude sessions (`~/.claude/`) in the ephemeral home volume are lost. On next connection, a new pod mounts the same PVC, the entrypoint sees the repo already cloned (no-op), and Claude starts fresh (no `--continue` since no session directory exists yet). The architect can rediscover prior work via vtf MCP and the existing codebase.

---

## Onboarding Bypass

Claude Code has a first-run experience (theme selection, trust dialog). In a pod, this blocks the terminal. The entrypoint patches `~/.claude.json`:

```json
{
  "hasCompletedOnboarding": true,
  "theme": "dark",
  "projects": {
    "/sessions/{project}": {
      "hasTrustDialogAccepted": true,
      "hasCompletedProjectOnboarding": true
    }
  }
}
```

Additionally, `--dangerously-skip-permissions` bypasses all tool permission prompts at runtime.

---

## Interactive vs Autonomous Mode

### Interactive (default)

The entrypoint runs `sleep infinity`. The user attaches via WebSocket. The conversation is human-driven — the architect asks questions, proposes plans, creates tasks with human approval.

### Autonomous

When `VF_ARCHITECT_PROMPT` is set, the entrypoint runs:

```bash
exec claude -p "$VF_ARCHITECT_PROMPT" --output-format json \
    --max-turns "${VF_MAX_TURNS:-50}" --dangerously-skip-permissions
```

The architect works independently with the prompt, creates tasks via MCP, and produces structured JSON output. No human interaction during execution.

---

## vtf Web Widget

The architect terminal is embedded in the vtf web UI as a floating widget:

### Entry Points

| Button | Location | Opens |
|--------|----------|-------|
| "Consult Architect" | Home page | `?role=architect` (greenfield) |
| "Plan with Architect" | Project dashboard | `?role=architect&project={slug}` |

### Widget Layouts

- **Floating**: draggable, resizable window overlaying vtf
- **Docked**: right-side panel with resizable divider
- **Minimized**: collapsed bar at bottom (iframe kept alive at 1x1px)
- **Pop-out**: opens full console in new browser tab

Layout switches are CSS-only (no iframe reload). The widget persists across vtf page navigation.

### Auth Flow (iframe)

1. vtf generates a single-use auth code via `POST /v1/auth/code/`
2. Code is appended to the console URL: `?code={code}&embed=true`
3. Console middleware exchanges code for session cookie
4. WebSocket connections authenticated via session cookie

---

## Comparison: Interactive Agent vs Background Worker

| Aspect | Architect (interactive) | Executor/Judge (background) |
|--------|------------------------|----------------------------|
| Launch | On-demand via console | Long-running Deployment |
| Lifecycle | Ephemeral, user-managed | Auto-restarting |
| Entry | `sleep infinity` + WebSocket exec | `python3 -m controller` |
| Session | Claude Code interactive CLI | Claude Code `-p` headless |
| Human interaction | Real-time conversation | None (autonomous) |
| Work output | Draft tasks via MCP | Code changes + commits |
| Readiness signal | `/tmp/ready` sentinel | Controller process check |
| Pod reuse | By role+project+user labels | Deployment replicas |

### Pattern for New Interactive Agents

To create a new interactive agent role (e.g., `reviewer`, `debugger`):

1. **Methodology**: write `methodologies/{role}.md` defining the agent's behavior
2. **Role config**: add entry to `config/roles.yaml` with image, resources, env vars
3. **Entrypoint**: the existing entrypoint already handles any role that uses `sleep infinity` — just set `VF_AGENT_ROLE` and the methodology is copied automatically
4. **vtf button**: add an entry point in the vtf web UI calling `useConsoleWidget().open({role: '{role}', ...})`

The infrastructure (pod launch, WebSocket proxy, session management, readiness probes, cleanup) is role-agnostic. Only the methodology and UI entry point are role-specific.

---

## Deployment Checklist

- [ ] `vafi-agent` image built and pushed to Harbor with current code
- [ ] `config/roles.yaml` includes the role with correct image tag
- [ ] `vafi-secrets` secret exists (anthropic-auth-token, anthropic-base-url, vtf-token)
- [ ] `github-ssh` secret exists (ssh-privatekey)
- [ ] vtf MCP service running (`vtf-mcp` in vtf namespace)
- [ ] vafi-console deployed with correct `VTF_MCP_URL` config
- [ ] vtf web built with `VITE_CONSOLE_URL` pointing to console
- [ ] Console RBAC allows pod create/exec/delete in the namespace

---

## Known Limitations

- **Claude session loss on pod deletion**: Claude conversation history doesn't survive pod cleanup (stored in ephemeral home volume). Workdir files and repo clones persist on PVC. Work product (vtf tasks) survives.
- **Single session per workdir**: `--continue` resumes the most recent session. No multi-session support.
- **No repo clone for greenfield**: Greenfield sessions start with an empty workdir. The architect proposes structure but has no codebase to reference.
- **First-run onboarding flash**: On the very first Claude launch in a new pod, the onboarding screen may briefly appear before `.claude.json` takes effect.
- **In-memory session store**: Console sessions (auth) don't survive console restarts. Users re-authenticate.
