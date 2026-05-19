# WC-2 — Controller integration mechanics (vafi) — DESIGN

**Status:** DRAFT v0.1 — 2026-05-19. Design-first; not implemented.
**Architecture:** R-slice WC-2 of `agentic-pipeline-ARCHITECTURE.md`
§10 (Workgraph Composition substrate). Consumes WC-1 (vtaskforge#10,
merged dd462df). **Kind:** feature (north-star TDD; behaviour-defining
controller git change — light R2-style ratification gate).

## What WC-2 owns

The **git mechanics** half of the integration-branch model. WC-1 supplies
the facts and serialization (`Milestone.integration_branch`, server-derived
`base_ref`, the `integrating` status, `take_merge_slot` under a Milestone
`select_for_update`, the `expire_stale_integrations` reaper). WC-2 makes
the controller (a) clone the **per-task** `base_ref` and (b) perform the
deterministic post-approve merge into the milestone integration branch,
reporting the outcome back to the SoR. The deterministic layer owns
composition; conflict → fail-loud → bounded rework; no silent stall.

## Grounded current state (source-verified)

- `controller/worksources/vtf.py:132 get_repo_info(project_id)` →
  `RepoInfo(url=project.repo_url, branch=project.default_branch or "main")`
  — clone branch is resolved **per project**.
- `controller/controller.py:382` calls `get_repo_info(task.project_id)`,
  `:385 _invoker._ensure_repo_cloned(repo_info, workdir)` — every task
  clones the project default; a DAG produces N disjoint branches.
- `vtf.py:95 complete()` adds notes + `tasks.complete()`. There is no
  integration step today.
- WC-1 (built): an approved **workgraph** task is routed
  `pending_completion_review → integrating` by `reviews/services.py`
  via `take_merge_slot()` (Milestone `select_for_update`, one in-flight
  per milestone). So when WC-2 runs, the SoR already holds the slot and
  the task sits in `integrating` carrying `base_ref` (= the milestone
  integration branch) on the v2 task API.
- `RepoInfo` (`controller/types.py:20`) = `{url, branch}`.

## Contract (the three changes WC-2 adds)

### D1 — per-task `base_ref` clone (consume the SoR rule)
Add `get_task_repo_info(task) -> RepoInfo` using `task.base_ref`
(WC-1/C2, already on the v2 task payload). `controller.py:382` switches
from `get_repo_info(task.project_id)` to the per-task form. The
controller **consumes** `base_ref`; it never re-derives the rule
(R2/OAQ-2 / WC-1-F-A consistent). `get_repo_info` stays for the
single-task / no-`base_ref` path (falls back to project default —
V16 byte-identical). Requires the vafi SDK `Task` model to surface
`base_ref` (schema-generated client: regenerate; else add the field).

### D2 — deterministic post-approve integration merge
The controller services `integrating` as just another state in its
poll loop (symmetric with todo/review). For a task in `integrating`:

1. Ensure the integration branch exists: create/locate
   `task.base_ref` off `project.default_branch` (idempotent — the
   R0 split: SoR owns the *name*, controller owns the git ref).
2. `git merge --no-ff` the task's delivered work branch into the
   integration branch; push.
3. **Success** → report SoR `integrating → done` (clears the slot;
   next milestone task can take it).
   **Conflict / push failure** → `git merge --abort`, report SoR
   `integrating → needs_attention` (I2) with the conflicting paths in
   a note → bounded rework (WC-1/C3 contract).

Idempotent + re-entrant: if the controller dies mid-merge, the
`expire_stale_integrations` reaper (WC-1/C4) escalates the stuck
`integrating` task; on retry, an already-merged commit is a no-op
(detect via merge-base / branch ancestry before merging).

### D3 — reaper alignment + observability
The controller emits the existing phase markers around the merge and
records the integration outcome (sha, conflicting files) as task
notes, so the SoR `integration_expired` / `needs_attention` path
carries actionable context. No new SoR fields (WC-1 closed the
silent non-terminal).

## Forks (light ratification, R2-style)

- **F-C integration trigger:** controller **poll-driven** — a
  work-source `list_integrations()` returning `status=integrating`
  tasks, serviced like any other state (resilient: reaper backstop +
  idempotent retry) — *recommended* — vs folding the merge
  synchronously into the post-approve path (couples merge latency to
  the review call; no clean retry). *Rec: poll-driven.*
- **F-D conflict policy:** `git merge --abort` →
  `integrating → needs_attention` carrying the conflict (fail-loud,
  bounded rework) — *recommended; effectively pre-decided by WC-1/C3*
  — vs controller-side auto-resolution (violates the determinism /
  no-silent-fix axiom). *Rec: fail-loud.*
- **OAQ-7 (deferred):** whole-DAG-complete → PR-to-`main` automation +
  integration-branch GC. First cut: controller opens the PR, human
  merges (irreversible step stays human — merge-ack discipline).

## Files touched (scope fence)

`controller/worksources/vtf.py` (+`get_task_repo_info`,
+`list_integrations`, +`report_integration_result`);
`controller/worksources/protocol.py` (+the new methods);
`controller/controller.py` (per-task clone at :382; +the
`integrating` service branch in the poll loop); `controller/types.py`
(unchanged — `RepoInfo` reused); a small git helper module for the
merge/abort/ancestry ops; the vafi SDK `Task` model (`base_ref`).
**Not** touched: harness invoker internals; gate runner; the
single-task clone path (V16); WC-1 / the SoR.

## Test plan (north-star TDD, red first)

- Unit: `get_task_repo_info` returns `branch == task.base_ref`;
  missing `base_ref` ⇒ project default (V16).
- Unit: git helper — clean merge fast-forwards; conflicting merge
  leaves the branch unmodified after `--abort`; already-merged is a
  detected no-op (idempotent).
- Integration (fake work source): a task in `integrating` with a
  clean delta → `report_integration_result(success)` →
  `integrating → done`. A conflicting delta → `--abort` →
  `needs_attention` with the conflict note.
- Integration: two sibling tasks, slot serialized by WC-1 — the
  controller never sees two `integrating` for one milestone (assert
  it services them one at a time).
- Scenario: deferred to the WC-3 proving delivery
  (server+client+poetry workgraph) once WC-2 lands.

## Migration / compat

Pure controller behaviour; no SoR migration. Single-task / no-`base_ref`
tasks keep the project-default clone and the straight
`pending_completion_review → done` path (V16 byte-identical). New
behaviour only engages for workgraph tasks (milestone owns an
integration branch).
