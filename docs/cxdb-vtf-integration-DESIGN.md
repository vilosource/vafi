# CXDB-vtf Integration Design

Status: Proposal (2026-03-27)

## Problem Statement

vtf tracks task lifecycle (who claimed what, when, what status) but has no
visibility into what an agent actually did during execution. When a task fails
or a judge rejects work, the supervisor can only see the outcome — not the
reasoning, tool calls, errors, or recovery attempts that led to it.

CXDB is already deployed at `cxdb.dev.viloforge.com` and the vafi controller
captures execution traces via cxtx. The traces contain full conversation
history: prompts, assistant responses, tool calls, tool results, errors, and
completion reports. However, there is no structured link between a vtf task
and its CXDB execution trace.

### Current state

- The vafi controller invokes `cxtx claude -p "<prompt>"` for each task
- cxtx captures the session and stores it in CXDB as a context
- The vtf task ID appears in the prompt text (e.g., "Add hello world script
  (F2sdEBpcHPVYjcsQZTU13)") but is not a structured field
- CXDB contexts have `labels` (currently `["cxtx", "claude", "interactive"]`)
  and a `custom` field in provenance, but neither contains the task ID
- Finding the trace for a given task requires searching prompt text — fragile

### What we want

Given a vtf task ID, find its CXDB execution trace(s) instantly. This enables:

1. **"View Trace" link** on the vtf task detail page — one click to see the
   full agent conversation in CXDB's UI
2. **Execution summary** on the vtf task — turn count, tool calls, errors,
   model, duration — pulled from CXDB without leaving vtf
3. **Rework comparison** — when a task has multiple attempts, link each to
   its CXDB context for side-by-side analysis
4. **Supervisor observability** — the supervisor can inspect agent behavior
   to decide whether to escalate, split, or re-spec a task

## Suggested Solution

### 1. Tag CXDB contexts with the vtf task ID

The controller should pass the vtf task ID as a label on the CXDB context.
The ideal flow:

```
controller claims task "FJNNkvIWmNopCpmCkHmVu"
  → invokes cxtx with label: task:FJNNkvIWmNopCpmCkHmVu
  → CXDB context created with labels: ["cxtx", "claude", "task:FJNNkvIWmNopCpmCkHmVu"]
```

**Current blocker:** cxtx does not support custom labels via CLI flags. Two
paths to resolve:

- **Option A: Contribute --label flag to cxtx** — upstream PR to add
  `cxtx --label "task:ID" claude -p "..."`. Clean, portable, benefits the
  ecosystem.

- **Option B: Environment variable convention** — cxtx already reads env
  vars for provenance. If cxtx reads a `CXTX_LABELS` env var and applies
  them, the controller sets `CXTX_LABELS=task:FJNNkvIWmNopCpmCkHmVu` before
  invocation.

- **Option C: Post-hoc labeling via CXDB API** — after cxtx finishes, the
  controller calls CXDB's API to add labels to the context. Requires knowing
  the context ID from cxtx output, and a CXDB endpoint for updating labels
  (may not exist yet).

### 2. Store the CXDB context URL on the vtf task

After execution, the controller writes the CXDB context URL back to vtf.
Two approaches:

- **Task note:** `POST /v1/tasks/{id}/notes/` with text containing the CXDB
  URL. Simple, no model changes, works today.

- **Task link:** `POST /v1/links/` with `link_type: "trace"`,
  `target_type: "cxdb"`, `target_id: "<context_id>"`. Structured, queryable,
  but requires adding a link type.

- **Task metadata field:** Add `cxdb_context_id` to the Task model. Most
  direct, but requires a migration.

Recommendation: start with a **task note** (no vtf changes needed), graduate
to a **link** when the pattern is validated.

### 3. vtf web UI: "View Trace" link

When a task has a CXDB trace note/link, the task detail page shows a
"View Trace" button linking to:

```
https://cxdb.dev.viloforge.com/c/{context_id}
```

This is a vtf frontend change, not a vafi concern.

## CXDB API Reference (observed)

Endpoints on the running instance at `cxdb.dev.viloforge.com`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/contexts` | List contexts with metadata, labels, head depth |
| GET | `/v1/contexts/{id}/turns?limit=N` | Paginated turns with full data |
| GET | `/v1/events` | SSE stream for live updates |
| POST | `/v1/contexts/create` | Create a new context |
| POST | `/v1/contexts/{id}/append` | Append a turn |

Context metadata includes: `context_id`, `client_tag`, `labels[]`,
`provenance.host_name`, `provenance.custom{}`, `head_depth`, `head_turn_id`,
`is_live`.

Each turn includes: `item_type` (system/user_input/assistant_turn/tool_result),
full content, `metrics` (model, tokens), timestamps, depth, parent_turn_id.

## Open Questions

1. Does the CXDB API support updating labels on an existing context?
   (Needed for Option C)
2. Can cxtx accept a `--label` flag or `CXTX_LABELS` env var?
   (Check cxtx source or open an issue upstream)
3. For rework with CXDB forking — does `POST /v1/contexts/create` with
   `base_turn_id` from a previous context work across contexts, or only
   within the same context?
4. Should the CXDB URL be configurable per-environment in vtf (dev vs prod
   CXDB instances)?

## Implementation Order

1. **Investigate** cxtx source for label support (or env var hooks)
2. **Implement** label passing in the vafi controller
3. **Write** CXDB context ID back to vtf task (as note, then link)
4. **Add** "View Trace" link to vtf task detail page (vtf frontend)
5. **Later:** Pull execution summary stats from CXDB into vtf API
