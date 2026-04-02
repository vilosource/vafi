# vtf ↔ vafi Interface Contract

Status: Updated 2026-04-02
Originally extracted from: vafi-DESIGN.md (now archived)

This is the API contract between vtf and vafi. vafi can be developed
in isolation against this contract. Changes needed in vtf are identified
as gaps at the end.

---

## API Interaction Points

### 1. Agent Registration (controller startup)

```
POST /v1/agents/
{
  "name": "executor-1",
  "tags": ["executor", "claude"]
}
→ 201 Created
{
  "id": "agent_xyz",
  "name": "executor-1",
  "tags": ["executor", "claude"],
  "status": "online",
  "token": "auth_token_here"
}
```

The controller stores the token and uses it for all subsequent calls:
```
Authorization: Token {token}
```

**GAP-1:** Registration is not idempotent. If the controller restarts
and POSTs the same agent name, it creates a duplicate. Needs upsert
behavior — create if new, update tags/status if exists.

### 2. Poll for Work (controller loop)

**Priority 1 — Rework tasks (any agent can pick up):**
```
GET /v1/tasks/?status=changes_requested&expand=reviews
→ 200 OK
{
  "results": [
    {
      "id": "task_abc",
      "title": "...",
      "spec": "...",
      "project": "project_xyz",
      "reviews": [
        {
          "decision": "changes_requested",
          "reason": "Missing test for edge case...",
          "reviewer_id": "judge-1"
        }
      ]
    }
  ]
}
```

The `expand=reviews` gives the judge feedback needed for the rework
prompt. The controller reads the latest `changes_requested` review
to build the rework prompt.

**Priority 2 — New claimable work:**
```
GET /v1/tasks/claimable/?tags=executor,claude&agent_id={agent_id}
→ 200 OK
{
  "results": [
    {
      "id": "task_def",
      "title": "...",
      "spec": "...",
      "project": "project_xyz",
      "needs_review_on_completion": true
    }
  ]
}
```

Returns `todo` tasks where: all dependencies met, task requires tags
are a subset of the agent's tags, and task is unassigned or assigned
to this agent.

### 3. Get Project Metadata (for repo clone)

```
GET /v1/projects/{project_id}/
→ 200 OK
{
  "id": "project_xyz",
  "name": "vtaskforge",
  "repo_url": "git@gitlab:vilosource/vtaskforge.git",
  "default_branch": "develop",
  ...
}
```

The controller uses `repo_url` and `default_branch` to clone the repo
into the task workdir.

**Note:** `repo_url` and `default_branch` already exist on the vtf
project model. No schema change needed.

**GAP-2:** The task response includes `project` as just an ID string.
The controller must make a separate call to get the repo URL. This
should be optimized — either expand project inline on the task response
(`?expand=project`) or include `repo_url` and `default_branch` directly
in the claimable response.

### 4. Claim Task

```
POST /v1/tasks/{task_id}/claim/
{
  "agent_id": "executor-1",
  "tags": ["executor", "claude"]
}
→ 200 OK (task with claimed_by, claimed_at, claim_expires_at set)
```

Atomic with `select_for_update()` — race-safe for concurrent executors.

**Validation enforced by vtf:**
- Task must be in `todo` status (409 if already claimed)
- Agent must exist (404 if not registered)
- `task.requires` must be subset of agent tags (422 if not)
- All `depends_on` links must target `done` tasks (422 if not)
- If `task.assigned_to` is set, must match agent_id (403 if not)

### 5. Heartbeat (during execution)

```
POST /v1/tasks/{task_id}/heartbeat/
→ 200 OK
```

Extends `claim_expires_at` by `claim_timeout` (default 30 minutes).
Only valid for tasks in `doing` status.

The controller runs this as an async coroutine alongside harness
execution, firing every `claim_timeout / 2` to keep the claim alive.

### 6. Store Results (after harness completes)

**Completion report (executor):**
```
POST /v1/tasks/{task_id}/notes/
{
  "text": "## Task abc — Widget API: Complete\n\nFiles created: ...\nTest results: 8/8 passed\n...",
  "actor_id": "executor-1"
}
→ 201 Created
```

**Session ID for rework resumption:**
```
POST /v1/tasks/{task_id}/notes/
{
  "text": "vafi:session_id=session_abc123",
  "actor_id": "executor-1"
}
→ 201 Created
```

**GAP-3:** Using notes for structured data (session_id, cost, turn
count) is a workaround. A `metadata` JSON field on the task model
would be cleaner — the controller PATCHes it with execution data:
```
PATCH /v1/tasks/{task_id}/
{
  "metadata": {
    "session_id": "session_abc123",
    "cost_usd": 0.042,
    "num_turns": 12,
    "completion_report": "..."
  }
}
```

### 7. Complete Task

```
POST /v1/tasks/{task_id}/complete/
→ 200 OK
```

If `needs_review_on_completion=true`:
  task → `pending_completion_review` (judge picks it up)
If false:
  task → `done`

### 8. Fail Task

```
POST /v1/tasks/{task_id}/fail/
→ 200 OK
```

Task → `needs_attention`. Human triage required.

The failure reason should be stored as a note (or in metadata) before
calling fail, so the human triaging has context.

### 9. Judge Poll for Reviews

```
GET /v1/tasks/?status=pending_completion_review&expand=reviews,links
```

The judge controller filters for tasks matching its tags. The task
spec + links give the judge everything it needs: what was requested
(spec), what changed (executor's completion report in notes), and
what to compare against (design docs via links).

### 10. Judge Submit Review

```
POST /v1/tasks/{task_id}/reviews/
{
  "decision": "approved",
  "reason": "Implementation matches spec. Tests pass. No architectural issues.",
  "reviewer_id": "judge-1",
  "reviewer_type": "agent"
}
→ 201 Created
```

If `decision == "approved"`:
  `pending_completion_review` → `done`

If `decision == "changes_requested"`:
  `pending_completion_review` → `changes_requested`
  `review_return_to` set automatically to `pending_completion_review`

### 11. Executor Rework (changes_requested → doing)

When the executor picks up a `changes_requested` task (from poll
step 2, priority 1):

```
POST /v1/tasks/{task_id}/claim/
{
  "agent_id": "executor-1",
  "tags": ["executor", "claude"]
}
```

**GAP-4:** The state machine does not allow `changes_requested → doing`.
Current valid transitions from `changes_requested` are:
`pending_start_review`, `pending_completion_review`, `draft`,
`cancelled`, `deferred`.

Required change: add `doing` to valid transitions from
`changes_requested`. The claim endpoint should handle this transition
when the task is in `changes_requested` status.

After rework completes, the executor calls complete, which goes back
to `pending_completion_review` (via `review_return_to`).

### 12. Rework Attempt Counting

The controller counts rework attempts by querying reviews:
```
GET /v1/tasks/{task_id}/?expand=reviews
```

Count reviews where `decision == "changes_requested"`. If count >=
`VF_MAX_REWORK` (default 3), the controller calls fail instead of
attempting another rework.

No vtf change needed — the data is already there.

### 13. Supervisor: Submit Unblocked Tasks

The supervisor polls for draft tasks whose dependencies are all met:

```
GET /v1/tasks/?status=draft&expand=links
```

For each task, the supervisor checks if all `depends_on` link targets
are in `done` status. If so:

```
POST /v1/tasks/{task_id}/submit/
```

If `needs_review_before_start=true` → `pending_start_review`
If false → `todo` (claimable by executors)

**GAP-5:** This requires the supervisor to fetch all draft tasks and
check dependencies client-side. A server-side endpoint that returns
"draft tasks with all dependencies met" would be more efficient,
similar to the `claimable` endpoint for `todo` tasks.

### 14. Session ID Retrieval (for rework resumption)

When picking up rework, the controller needs the session ID from the
previous execution:

```
GET /v1/tasks/{task_id}/notes/
→ scan for note with "vafi:session_id=" prefix
```

Or with the metadata field (GAP-3):
```
GET /v1/tasks/{task_id}/
→ read metadata.session_id
```

---

## vtf Changes Required

Summary of all gaps identified in the interface contract.

| # | Change | Severity | Description |
|---|--------|----------|-------------|
| GAP-1 | Agent registration upsert | ~~Blocks restart~~ **RESOLVED** | POST /v1/agents/ now upserts by name. |
| GAP-2 | Task response project expansion | **Performance** | Add `?expand=project` support on task endpoints. Controller works around with extra GET call. |
| GAP-3 | Task metadata field | ~~Blocks session resume~~ **Workaround** | Structured data stored in vtf task notes (`vafi:session_id=`, `vafi:execution_metadata`). Not a dedicated field, but functional. |
| GAP-4 | State machine: changes_requested → doing | ~~Blocks rework~~ **RESOLVED** | Claim endpoint handles this transition. |
| GAP-5 | Submittable tasks endpoint | **Supervisor efficiency** | Supervisor checks deps client-side. Low priority. |

**Priority order for implementation:**
1. ~~GAP-4 (state machine)~~ — **RESOLVED**
2. ~~GAP-1 (agent upsert)~~ — **RESOLVED**
3. ~~GAP-3 (metadata field)~~ — **Workaround** (vtf notes)
4. GAP-2 (project expansion) — optimization, low priority
5. GAP-5 (submittable endpoint) — optimization, low priority

---

## vafi-side Interface

The controller consumes the vtf API through a layered interface:
`WorkSource` (abstract) → `VtfWorkSource` (vtf-specific) → `VtfClient`
(HTTP). This separation means the controller knows nothing about vtf
endpoints — it calls the `WorkSource` interface. A different work
source (queue, manual) can be swapped in without changing controller
logic.

### VtfClient — HTTP client for vtf REST API

Thin wrapper over vtf endpoints. Handles auth headers, JSON
serialization, error mapping, and pagination. One method per API call.

```python
class VtfClient:
    def __init__(self, base_url: str, token: str | None = None): ...

    # Agent registration
    async def register_agent(self, name: str, tags: list[str]) -> dict

    # Polling
    async def list_claimable(self, tags: list[str], agent_id: str) -> list[dict]
    async def list_tasks(self, status: str, assigned_to: str | None = None,
                         expand: list[str] | None = None) -> list[dict]

    # Task lifecycle
    async def claim_task(self, task_id: str, agent_id: str, tags: list[str]) -> dict
    async def heartbeat(self, task_id: str) -> None
    async def complete_task(self, task_id: str) -> None
    async def fail_task(self, task_id: str) -> None
    async def submit_task(self, task_id: str) -> None

    # Project
    async def get_project(self, project_id: str) -> dict

    # Notes
    async def add_note(self, task_id: str, text: str, actor_id: str) -> dict
    async def list_notes(self, task_id: str) -> list[dict]

    # Reviews
    async def submit_review(self, task_id: str, decision: str,
                            reason: str, reviewer_id: str) -> dict

    # Detail
    async def get_task(self, task_id: str, expand: list[str] | None = None) -> dict
```

### Data types — shared across the interface

```python
@dataclass
class AgentInfo:
    id: str
    token: str

@dataclass
class RepoInfo:
    url: str          # git clone URL
    branch: str       # default branch

@dataclass
class TaskInfo:
    id: str
    title: str
    spec: str         # YAML spec content
    project_id: str
    test_command: dict
    needs_review: bool
    assigned_to: str | None

@dataclass
class ReworkContext:
    session_id: str | None     # from previous execution, for --resume
    judge_feedback: str        # latest review with changes_requested
    attempt_number: int        # how many times rejected so far

@dataclass
class GateResult:
    name: str
    command: str
    exit_code: int
    stdout: str
    passed: bool

@dataclass
class ExecutionResult:
    success: bool              # all gates passed
    session_id: str | None     # harness session ID for future rework
    completion_report: str     # harness result text (opaque to controller)
    cost_usd: float
    num_turns: int
    gate_results: list[GateResult]
```

### WorkSource — abstract interface

The controller's only dependency. Defines what the controller can do
with the work system, without knowing how.

```python
class WorkSource(Protocol):
    """Abstract interface to a work system."""

    # Registration
    async def register(self, name: str, tags: list[str]) -> AgentInfo

    # Polling — returns highest priority available task, or None
    async def poll(self, agent_id: str, tags: list[str]) -> TaskInfo | None
    async def poll_reviews(self, agent_id: str) -> list[TaskInfo]

    # Task lifecycle
    async def claim(self, task_id: str, agent_id: str) -> TaskInfo
    async def heartbeat(self, task_id: str) -> None
    async def agent_heartbeat(self, agent_id: str) -> None
    async def set_agent_offline(self, agent_id: str) -> None
    async def complete(self, task_id: str, result: ExecutionResult) -> None
    async def fail(self, task_id: str, reason: str) -> None

    # Context for execution
    async def get_repo_info(self, project_id: str) -> RepoInfo
    async def get_rework_context(self, task_id: str) -> ReworkContext
    async def count_rework_attempts(self, task_id: str) -> int
    async def get_task_context(self, task_id: str) -> dict
    async def add_note(self, task_id: str, content: str) -> None

    # Supervisor
    async def submit(self, task_id: str) -> None
    async def list_submittable(self) -> list[TaskInfo]

    # Judge
    async def submit_review(self, task_id: str, decision: str,
                            reason: str, reviewer_id: str) -> None
```

### VtfWorkSource — vtf implementation

Implements `WorkSource` using `VtfClient`. This is where vtf-specific
logic lives: priority ordering (rework before new work), review
parsing, session ID extraction from notes, dependency checking for
the supervisor.

```python
class VtfWorkSource:
    """WorkSource backed by the vtf REST API."""

    def __init__(self, client: VtfClient, tags: list[str] | None = None, pod_name: str | None = None): ...

    async def register(self, name, tags) -> AgentInfo:
        # POST /v1/agents/ — store token for future calls
        ...

    async def poll(self, agent_id, tags) -> TaskInfo | None:
        # Priority 1: GET /v1/tasks/?status=changes_requested&assigned_to=me
        # Priority 2: GET /v1/tasks/claimable/?tags=...&agent_id=...
        # Return first match or None
        ...

    async def claim(self, task_id, agent_id) -> TaskInfo:
        # POST /v1/tasks/{id}/claim/
        ...

    async def heartbeat(self, task_id) -> None:
        # POST /v1/tasks/{id}/heartbeat/
        ...

    async def complete(self, task_id, result: ExecutionResult) -> None:
        # 1. POST /v1/tasks/{id}/notes/ — completion report
        # 2. POST /v1/tasks/{id}/notes/ — session_id (for rework)
        # 3. POST /v1/tasks/{id}/complete/
        ...

    async def fail(self, task_id, reason: str) -> None:
        # 1. POST /v1/tasks/{id}/notes/ — failure reason
        # 2. POST /v1/tasks/{id}/fail/
        ...

    async def submit(self, task_id) -> None:
        # POST /v1/tasks/{id}/submit/
        ...

    async def list_submittable(self) -> list[TaskInfo]:
        # GET /v1/tasks/?status=draft&expand=links
        # Filter client-side: only tasks with all depends_on targets done
        ...

    async def submit_review(self, task_id, decision, reason, reviewer_id):
        # POST /v1/tasks/{id}/reviews/
        ...

    async def get_repo_info(self, project_id) -> RepoInfo:
        # GET /v1/projects/{id}/ → extract repo_url, default_branch
        ...

    async def get_rework_context(self, task_id) -> ReworkContext:
        # GET /v1/tasks/{id}/?expand=reviews
        # GET /v1/tasks/{id}/notes/ → scan for session_id
        # Count changes_requested reviews for attempt_number
        ...

    async def count_rework_attempts(self, task_id) -> int:
        # GET /v1/tasks/{id}/?expand=reviews
        # Count reviews where decision == "changes_requested"
        ...
```

### How the controller uses the interface

The controller never imports `VtfClient` or `VtfWorkSource` directly.
It receives a `WorkSource` at init:

```python
class Controller:
    def __init__(self, work_source: WorkSource, config: AgentConfig): ...

    async def run(self):
        agent = await self.work_source.register(self.config.name, self.config.tags)
        while True:
            task = await self.work_source.poll(agent.id, self.config.tags)
            if task is None:
                await asyncio.sleep(self.config.poll_interval)
                continue
            await self.execute(task, agent)

    async def execute(self, task: TaskInfo, agent: AgentInfo):
        claimed = await self.work_source.claim(task.id, agent.id)
        repo = await self.work_source.get_repo_info(claimed.project_id)
        # ... clone, build prompt, invoke harness, run gates ...
        # ... complete or fail based on results ...
```

This is the complete interface that vafi develops against. The vtf
contract (above) defines what's on the other side of the wire. The
`WorkSource` interface is the seam between them.
