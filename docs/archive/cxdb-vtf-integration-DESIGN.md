> **Archived**: This document is historical. For current architecture, see [ARCHITECTURE-SUMMARY.md](../ARCHITECTURE-SUMMARY.md) and [harness-images-ARCHITECTURE.md](../harness-images-ARCHITECTURE.md).

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

## Architecture Decision

The vafi controller does NOT write trace references back to vtf. Instead,
vtf queries CXDB directly using the task ID as the lookup key. This means:

- **vafi's only responsibility**: cxtx tags contexts with `task:<id>` (already done)
- **vtf queries CXDB**: task detail API enriches responses with trace data
- **No middleman**: if the controller crashes, the trace still exists in CXDB

CXDB is an accepted dependency for vtf. It will also be used for the
judge/review system in the future (judge reads execution traces to inform
reviews).

## vtf-side Implementation

### 1. CXDB client in vtf backend

New service that queries CXDB for traces by task ID:
`GET /v1/contexts` filtered by `task:<id>` label. Returns context ID,
turn count, error count, is_live, and the web UI URL.

### 2. Task detail API enrichment

The task serializer includes a `traces` field with CXDB data when
available. Graceful degradation — if CXDB is unreachable, the field
is null.

### 3. Task detail page: "View Trace" link

Renders trace link(s) to the CXDB web UI. If multiple traces exist
(rework), shows each attempt.

### 4. Execution summary (future)

Pull key stats from CXDB inline: turn count, tool calls, errors, model,
duration. Avoids leaving vtf for the common case.

### 5. Judge integration (future)

Judge reads execution traces from CXDB to inform reviews — sees the
agent's reasoning, not just the git diff.

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
2. CXDB base URL needs to be configurable per-environment in vtf settings
   (dev: `cxdb.dev.viloforge.com`, prod: `cxdb.viloforge.com`)
3. How should the judge consume traces — full turn replay or summary?

## Implementation Order

All work is on the vtf side:

1. **vtf backend**: CXDB client service + task serializer enrichment
2. **vtf frontend**: "View Trace" link on task detail page
3. **vtf frontend**: trace stats on agents page
4. **vtf backend (future)**: judge reads traces from CXDB for reviews
