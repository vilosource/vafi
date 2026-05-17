# F7 / F10 Fix — Delivery Gate (DESIGN)

**Date:** 2026-05-17
**Tracking:** [#8 (F7)](https://github.com/ViloForge/vafi/issues/8),
[#9 (F10)](https://github.com/ViloForge/vafi/issues/9)
**Source of truth for the defect:**
[executor-judge-observability-FINDINGS.md](executor-judge-observability-FINDINGS.md)
**Kind:** bugfix (executor methodology applies — TDD red/green, fail-loud,
no over-engineering, full pyramid).

## The defect (one paragraph)

After the harness exits 0, `controller.execute()`
(`src/controller/controller.py:423`) builds gates via
`GateRunner.from_task_command(task.test_command)`. With no `test_command`,
`gates.py:from_task_command` returns `GateRunner([])`; the success loop
(`controller.py:428`) initialises `all_required_gates_passed=True` and only a
*failing* gate falsifies it, so an empty gate list is a **vacuous pass** —
`success=True` purely because the agent process exited 0 (**F7**). Even with
a `test_command`, `GateRunner._run_single_gate` runs the gate subprocess with
`cwd=workdir` — the ephemeral, shallow, detached-HEAD pod clone
(`invoker.py:_ensure_repo_cloned`). An agent that creates and *locally*
commits the deliverable but never pushes still passes; the pod is discarded
and the origin repo is untouched (**F10**). Nothing in the codebase ever
inspects origin after the initial `--depth 1` clone, and `acceptance_criteria`
(present in vtf's Task) is never mapped into `TaskInfo`
(`worksources/vtf.py:_sdk_task_to_info`), so it is structurally unreachable on
the success path.

Root cause (shared): **completion is decided from the process exit code and
ephemeral local state; durable origin state is never consulted.**

## Goal / non-goal

- **Goal:** a task can only reach `done`/`approved` if a deliverable was
  durably pushed to origin. A no-op (empty workdir) or a discarded-workdir
  ghost must fail loud (`work_source.fail`), never silently complete.
- **Non-goal (this slice):** full semantic enforcement of free-text
  `acceptance_criteria`, forge PR-state verification, or a vtaskforge schema
  change. These are stronger *future* delivery gates behind the same seam
  (see "Forward compatibility"). Out of scope per executor `R6`.

## Design — synthesized, always-required delivery gate

We do **not** special-case the success logic (that would deepen the
exit-code-trust anti-pattern and break Open/Closed). Instead we treat
"deliverable shipped" as just another **required gate**, reusing the existing
`GateRunner`/`GateConfig`/exit-code machinery unchanged (OCP: extend the gate
set, don't modify the verdict computation).

### The deliverable contract (convention, Option 1)

The deterministic, machine-checkable definition of "shipped" for this slice:

> Origin has a branch **`vafi/task-<task.id>`** whose tip SHA differs from the
> project's base branch tip SHA (i.e. it carries ≥1 commit not on base).

This needs no forge credentials and no vtaskforge change. It is enforced two
ways that must agree:

1. **Producer side** — the branch-name contract is injected into the agent's
   prompt and `.vafi/context.md` so the executor knows exactly what to push.
   (The executor `bugfix` methodology already mandates push + PR + fail-loud;
   this makes the branch name *deterministic* so a gate can check it.)
2. **Verifier side** — a synthesized **delivery gate**, always present and
   `required=True`, that consults *origin* (not the workdir).

### Gate command

`GateRunner.from_task_command(test_command)` → `GateRunner.from_task(task,
repo_info)`. It always appends the delivery gate, then the optional
`test_command` gate (unchanged) when present. The delivery gate is an
ordinary shell `GateConfig` (so the entire run/subprocess path is reused),
run with `cwd=workdir` where `origin` is already configured by the clone:

```sh
# delivery gate (name="deliverable-pushed", required=True)
set -e
branch="vafi/task-<task.id>"
remote_sha=$(git ls-remote --heads origin "$branch" | cut -f1)
[ -n "$remote_sha" ]                                   # branch exists on origin
base_sha=$(git ls-remote --heads origin "<repo_info.branch>" | cut -f1)
[ "$remote_sha" != "$base_sha" ]                       # carries new commits
```

`git ls-remote` queries the remote directly (no fetch, no depth issue, works
on the shallow clone). Branch absent ⇒ non-empty test fails ⇒ exit≠0 ⇒
required gate fails ⇒ `success=False` ⇒ controller calls `work_source.fail`
with the gate stdout (fail-loud). This single gate closes **both** F7 (no
`test_command` is no longer a free pass — the delivery gate is always there)
and F10 (the check is against origin, so a discarded-workdir local commit
does not satisfy it).

### `acceptance_criteria` stance

We **stop advertising** `acceptance_criteria` as machine-enforced acceptance
and make that explicit: the machine floor is "deliverable durably pushed";
semantic AC grading remains the judge's job against the spec. (Mapping ACs
into `TaskInfo` for *semantic* gating is a separate, larger slice — flagged,
not silently done, per executor `R8`/`R6`.) This is the honest "or stop
advertising it" arm of the issue's recommended remediation.

## Files touched (scope fence — executor R6)

- `src/controller/gates.py` — add `from_task(task, repo_info)` building the
  delivery `GateConfig` + the optional `test_command` gate; keep
  `from_task_command` as a thin shim (V16: don't regress existing callers/
  tests) or delegate.
- `src/controller/controller.py:423` — call `from_task(task, repo_info)`
  (`repo_info` is already in scope at that point).
- `src/controller/controller.py` (prompt build ~391) + the context builder —
  inject the `vafi/task-<id>` branch-name contract so the producer side is
  deterministic.
- `tests/test_gates.py`, `tests/test_controller.py` (+ an integration test
  with a real local git "origin") — pyramid coverage.
- `docs/INDEX.md` — link this doc.

Nothing else. No refactor of adjacent code.

## Test plan (TDD red first, pyramid)

- **Unit (gates):** `from_task` always yields ≥1 required gate even with
  `test_command={}`/`None`; the delivery gate command embeds the task id and
  base branch; `test_command` gate still appended when present and ordered
  after delivery.
- **Unit (controller verdict):** with the delivery gate failing,
  `final_result.success is False` (the F7 vacuous pass is gone); prompt/
  context contains the `vafi/task-<id>` contract string.
- **Integration:** real on-disk bare git repo as `origin`; clone it as the
  pod workdir. (a) no branch pushed ⇒ delivery gate fails; (b) branch pushed
  but == base ⇒ fails; (c) branch pushed with a new commit ⇒ passes;
  (d) local commit, no push ⇒ fails (the F10 reproduction, now caught).
- **Scenario / dogfood:** re-run the F10 canary (`is_prime` spec, externally
  grounded `test_command`) on `vtf-e2e`; with this fix the discarded-workdir
  ghost must now terminate `failed`, not `done/approved`. Eat our own
  dogfood with a *delivery-grounded* canary (handoff directive).

## Forward compatibility

The seam is the gate, not the verdict logic. Stronger deliverable definitions
— forge open-PR verification (Option 2), or an explicit `expected_deliverable`
contract field in vtaskforge (Option 3) — later replace or augment the
delivery `GateConfig`'s command (or become a richer gate type) **without
touching `controller.py`'s success computation**. `acceptance_criteria`
semantic gating is the natural next slice on the same seam.
