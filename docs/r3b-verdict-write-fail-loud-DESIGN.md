# R3b — Controller verdict-write fail-loud (vafi) — DESIGN

**Status:** IMPLEMENTED v0.1 — 2026-05-20. Code + unit tests green
locally; deploy + experiment-regression dogfood pending cluster
availability (vafi-dev path degraded this session).
**Architecture:** R-slice **R3b** of `agentic-pipeline-ARCHITECTURE.md`
§7 — split out of R3's faithful-reporting correction ("controller
verdict-write fail-loud" was *not* delivered by vtaskforge#9; it is a
small vafi-side slice). Realises the controller half of I2.
**Kind:** bugfix (executor methodology — TDD red/green, fail-loud, no
silent stall).

## The defect (source-verified)

`controller/controller.py` `_poll_and_review` wraps the **entire** judge
path — harness `execute`, verdict parse, and `submit_review` (the
verdict write) — in one `except Exception` whose only action was a
best-effort `add_note` followed by `return`. Consequences:

- A `submit_review` failure (the precise #18 "judge-write failure
  swallowed" case) is caught and discarded. The task stays in
  `pending_completion_review`; the judge polls the next task.
- The task is then recoverable **only** by R3's server-side
  `expire_stale_reviews` reaper, after the full `review_expires_at`
  timeout (default 30 min). The controller carries no fail-loud
  obligation of its own — exactly the I2 gap the architecture calls
  out (responsibility table: "Controller fail-loud obligation (I2) …
  judge-write failure swallowed", #18).

This is asymmetric with the rest of the controller, which already fails
loud: `_process_task` calls `work_source.fail(...)` on error;
`_poll_and_integrate` reports `report_integration_result(success=False)`
→ `needs_attention`.

## Grounded transition legality

- `tasks/state_machine.py` `VALID_TRANSITIONS["pending_completion_review"]`
  includes `needs_attention` (the same edge R3's reaper uses).
- vtaskforge `tasks/views.py:315 fail()` performs
  `perform_transition(task, "needs_attention", trigger_source="fail")`
  and clears stale claim fields. So `work_source.fail()` on a task in
  `pending_completion_review` is legal and lands it in `needs_attention`.
- `worksources/vtf.py:113 fail()` = `add_note("Task failed: <reason>")`
  then `tasks.fail()` — it both annotates and transitions, subsuming the
  old best-effort note.

## The fix

In `_poll_and_review`'s `except`, replace the swallowing `add_note` with
an explicit escalation: `await work_source.fail(task.id, reason)`,
driving `pending_completion_review → needs_attention` so the
human-escalation terminal (the needs-attention/reviews queue, the
architecture's defined fail-loud consumer) sees it immediately rather
than after the timeout. This covers both failure phases — a harness
failure (no verdict producible) and a verdict-write failure (verdict
produced, not recordable); both strand the task identically.

If `fail()` itself also fails (vtf unreachable — often the very reason
`submit_review` failed), log `CRITICAL` and fall through. R3's
`expire_stale_reviews` is the server-side backstop of last resort:
client-driven liveness is structurally the F4 mistake, so the durable
guarantee stays server-side; R3b only removes the *silent* swallow and
escalates promptly when vtf is reachable.

## Tests (TDD)

`tests/test_judge.py::TestJudgeVerdictWriteFailLoud` (red → green):
1. verdict-write failure → `work_source.fail(task_id, …)` awaited once.
2. judge-harness failure → `fail()` awaited; `submit_review` not called.
3. escalation also failing → logged, never raised (reaper backstop).
4. happy path → `submit_review` awaited; `fail()` never called.

## Acceptance / regression (pending cluster)

Dogfood against the lifecycle experiment once vafi-dev is reachable:
induce a verdict-write failure for a `pending_completion_review` task and
assert the controller drives it to `needs_attention` (not a 30-min stall).
Until deployed, R3b is IMPLEMENTED, not DELIVERED.
