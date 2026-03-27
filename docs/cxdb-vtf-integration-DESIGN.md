# CXDB-vtf Integration Design

Status: Proposal (2026-03-27)

## Problem Statement

vtf tracks task lifecycle (who claimed what, when, what status) but has no
visibility into what an agent actually did during execution. When a task fails
or a judge rejects work, the supervisor can only see the outcome — not the
reasoning, tool calls, errors, or recovery attempts that led to it.

CXDB is deployed (dev: `cxdb.dev.viloforge.com`, prod: `cxdb.viloforge.com`)
and the vafi controller captures execution traces via cxtx. Traces are tagged
with `task:<vtf-task-id>` labels and can be looked up via the CXDB API (see
`vtaskforge/docs/guides/cxdb-trace-lookup-GUIDE.md` for the lookup procedure).

### What exists today

- The vafi controller invokes `cxtx claude -p "<prompt>"` for each task
- cxtx tags contexts with `task:<vtf-task-id>` labels automatically
- CXDB API supports lookup: `GET /v1/contexts` filtered by label
- Rework creates separate contexts, all sharing the same `task:` label
- CXDB web UI at `https://cxdb.dev.viloforge.com/c/{context_id}` shows
  full conversation replay

### What's missing

The link is one-directional: you can go from task ID → CXDB (via API query).
But vtf doesn't know about CXDB — the task detail page has no trace link,
and the supervisor has no way to inspect execution without manually querying
the CXDB API.

## Proposed Integration

### 1. Store the CXDB context reference on the vtf task

After execution, the controller writes the CXDB context back to vtf.
Options in order of preference:

- **Task link** — `POST /v1/links/` with `link_type: "trace"`,
  `source_type: "task"`, `source_id: "<task_id>"`,
  `target_type: "url"`, `target_id: "<cxdb_url>"`.
  Structured, queryable, fits the existing link model.

- **Task note** — `POST /v1/tasks/{id}/notes/` with the CXDB URL.
  Simpler, no model changes, but not structured — harder to extract
  programmatically.

### 2. vtf task detail page: "View Trace" link

When a task has a `trace` link, the task detail page shows a "View Trace"
button linking to the CXDB web UI. If multiple traces exist (rework),
show each attempt with its context.

### 3. Execution summary (future)

Pull key stats from CXDB and display inline on the vtf task detail:
turn count, tool calls, errors, model, duration. Avoids leaving vtf
for the common case.

### 4. Supervisor signals (future)

Surface CXDB data in the agents page: last execution turn count, error
rate, average task duration per agent. Helps the supervisor spot patterns.

## CXDB API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/contexts` | List contexts with metadata, labels, head depth |
| GET | `/v1/contexts/{id}/turns?limit=N` | Paginated turns with full data |
| GET | `/v1/events` | SSE stream for live updates |
| POST | `/v1/contexts/create` | Create a new context |
| POST | `/v1/contexts/{id}/append` | Append a turn |

In-cluster: `http://cxdb-server.vafi-agents.svc.cluster.local`

See `vtaskforge/docs/guides/cxdb-trace-lookup-GUIDE.md` for full usage.

## Open Questions

1. For rework with CXDB forking — does `POST /v1/contexts/create` with
   `base_turn_id` from a previous context work across contexts, or only
   within the same context?
2. Should the CXDB base URL be configurable per-environment in vtf
   (dev vs prod instances)?
3. Which link type to use — does vtf's link system already support
   `link_type: "trace"` or does it need to be added?

## Implementation Order

1. **vafi controller**: write CXDB context URL to vtf task after execution
   (as link or note)
2. **vtf frontend**: render "View Trace" link on task detail page
3. **vtf API (optional)**: proxy CXDB stats for inline execution summary
