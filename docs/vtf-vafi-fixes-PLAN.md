# vtf & vafi — Discovery Fixes Implementation Plan

Last updated: 2026-04-18

All claims below cite file:line verified during the 2026-04-18 discovery pass.
Where a claim is not directly verified, it is marked **[unverified]** with
what additional reading is needed.

---

## Sequencing overview

```
Fix 1 (parse_bool)  ──►  Fix 2 (MCP requires+link)  ──►  Fix 3 (pi exec helm)
                                                              ▲
Fix 4 (max_rework) ─────────────────────────────────────────┼──── independent
Fix 5 (supervisor) ─────────────────────────────────────────┘     independent
```

Critical path: 1 → 2 → 3. Fixes 4 and 5 can be parallelized.

**Why this order.** Fix 1 is a 1-line parser fix that underlies several MCP
tools; doing it first makes all subsequent tests (which touch MCP
`update_task`) reliable. Fix 2 enables multi-task workflows via MCP, which is
how Fix 3 will be smoke-tested. Fix 3 fixes infrastructure drift on the pi
executor.

---

## Fix 1 — `parse_bool("")` returns `False`, not `None`

### Goal

Make `vtf_update_task` (and every other MCP tool using `parse_bool`) preserve
unspecified boolean fields instead of silently resetting them to `False`.

### Current state (verified)

- **Parser** (`vtaskforge/src/mcp_server/parsers.py:17-27`):
  ```python
  def parse_bool(value: str | bool | None) -> bool | None:
      """Returns None for None input (distinguishes "not provided" from "false")."""
      if value is None: return None
      if isinstance(value, bool): return value
      return str(value).lower() in ("true", "1", "yes")
  ```
- **Caller signatures** default to `""`, not `None`
  (`vtaskforge/src/mcp_server/tools/task_update.py:13-26`): `judge: str = ""`,
  `needs_review_before_start: str = ""`, `needs_review_on_completion: str = ""`.
- **Experimental reproducer** (2026-04-18): created a task with
  `judge=true, needs_review_on_completion=true`, called `update_task(labels=…)`,
  read back. Both booleans were silently set to `false`. Response `message`
  confirmed: `"Changed: labels, judge, needs_review_before_start,
  needs_review_on_completion"`.

### Proposed change

**One line**, `parsers.py:22`:

```python
 def parse_bool(value: str | bool | None) -> bool | None:
-    if value is None:
+    if value is None or value == "":
         return None
     if isinstance(value, bool):
         return value
     return str(value).lower() in ("true", "1", "yes")
```

Docstring already promises this semantics — implementation now matches intent.

### Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| One-line parser fix | Global fix, matches existing docstring intent | Callers passing `""` to mean "false" (if any) change behavior | **Chosen** |
| Change every caller default to `None` with `Optional[str] = None` | More explicit at signature layer | Touches ~20 MCP tool files; MCP signature compatibility unknown | Rejected — invasive |
| Add `parse_optional_bool` | Preserves existing `parse_bool("") == False` for any accidental callers | Duplicates API surface; existing docstring already promises not-None only for None | Rejected |

### Caller audit required

Grep `parse_bool(` across `vtaskforge/src/` for every call site; verify none
intentionally pass `""` to mean `False`. Expected result: every caller is the
MCP tool pattern (string default, parse, check `is not None` guard). If an
exception is found, guard that one call site.

### Tests

1. **Unit test in `tests/mcp_server/test_parsers.py`** (create if missing):
   ```python
   def test_parse_bool_empty_string_returns_none():
       assert parse_bool("") is None

   def test_parse_bool_preserves_existing_cases():
       assert parse_bool(None) is None
       assert parse_bool("true") is True
       assert parse_bool("false") is False
       assert parse_bool(True) is True
   ```
2. **Integration test in `tests/mcp_server/test_task_update.py`**: create task
   with `judge=true`, call `vtf_update_task` with only `labels=…`, assert
   `task.judge` remains `True`.

### Acceptance criteria

- Unit tests above pass.
- Re-run the reproducer via MCP: create `judge=true,
  needs_review_on_completion=true`, update labels only, read back → both
  booleans still `true`.

### Migration / rollout

Deploy the backend once; no migrations, no client-side changes needed.

### Risk

Very low. The docstring always promised this semantics; this aligns behavior
with the documented contract.

### Effort estimate

5 min code + 15 min test + 5 min grep audit = **25 min end-to-end**.

---

## Fix 2 — MCP `requires` overload + missing Link creation tool

### Goal

Make task dependencies creatable and observable through MCP. Stop the MCP
response from lying about dependencies via tag-string hydration.

### Current state (verified)

- **`Task.requires` is tag-requirements** — `JSONField(default=list)` at
  `vtaskforge/src/tasks/models.py:58`; claimable filter uses it at
  `src/tasks/services.py:144`: `set(task.requires).issubset(set(tags))`.
- **Task dependencies live in the `Link` table**: `src/links/models.py:25`;
  claimable filter at `services.py:137-140` excludes tasks with unresolved
  `depends_on` Links.
- **MCP `vtf_create_task.requires` docstring lies** —
  `src/mcp_server/tools/task_create.py:43` says "Comma-separated task IDs this
  task depends on". The code at `:84` populates `Task.requires` (tags field),
  not Link rows.
- **No MCP tool for Link creation** — verified by enumeration of
  `src/mcp_server/tools/`; 20 tools, none for links.
- **Serializer hydration** (`src/tasks/serializers_v2.py:73-79`): takes the
  `requires` list (strings) and does
  `TaskModel.objects.filter(pk__in=instance.requires)` → hydrates as
  `{id, title, status}` objects. Any string that happens to match a task PK
  becomes a fake dependency-looking ref in API responses.
- **Link REST API is public**: `POST /v1/links/` on `LinkViewSet` at
  `vtaskforge/src/links/views.py:18-25`, requires
  `source_type, source_id, target_type, target_id, link_type` per
  `LinkSerializer.Meta.fields` (`src/links/serializers.py:15-28`). Verified
  working 2026-04-18: returned `201 Created` with link id.

### Proposed change — three parts, one PR

**Part A — stop hydrating `requires` as task refs**

`vtaskforge/src/tasks/serializers_v2.py:73-79`: remove the hydration; return
the raw list.

```python
-        if instance.requires:
-            from tasks.models import Task as TaskModel
-            required_tasks = TaskModel.objects.filter(pk__in=instance.requires)
-            data["requires"] = [TaskRefSerializer(t).data for t in required_tasks]
+        # `requires` is a list of agent-tag strings. Return as-is.
+        data["requires"] = list(instance.requires or [])
```

Any frontend/consumer that previously treated `requires` as dependency objects
must be updated. The `dependencies` computed field (already present on
`TaskDetailV2Serializer`, returns `{resolved, dependencies, unresolved}`) is
the correct source of dep info.

**Part B — split MCP `vtf_create_task` params**

`vtaskforge/src/mcp_server/tools/task_create.py`:

```python
 def vtf_create_task(
     ...
-    requires: str = "",            # docstring: "Comma-separated task IDs this task depends on"
+    required_tags: str = "",       # docstring: "Comma-separated agent tags the claiming executor must have"
+    depends_on: str = "",          # docstring: "Comma-separated task IDs this task depends on (creates Link rows)"
     ...
 ):
```

- Keep backward-compat alias `requires` that maps to `required_tags` with a
  deprecation warning (optional, per project policy).
- After `task.save()`, if `depends_on` is non-empty, iterate the CSV and
  create Link rows using
  `Link.objects.create(source_type="task", source_id=task.id,
  target_type="task", target_id=tid, link_type="depends_on",
  project=task.project)`.

**Part C — new MCP tool `vtf_create_link`**

New file `vtaskforge/src/mcp_server/tools/link_create.py`:

```python
@mcp.tool()
@handle_errors
@serialize_response
def vtf_create_link(
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    link_type: str,
    metadata: str = "",
) -> dict:
    """Create a link between two entities (e.g., task depends_on another task).

    link_type values: depends_on, blocks, area, doc, relates_to.
    """
    from links.models import Link
    kwargs = dict(source_type=source_type, source_id=source_id,
                  target_type=target_type, target_id=target_id,
                  link_type=link_type)
    if metadata:
        import json
        kwargs["metadata"] = json.loads(metadata)
    link = Link.objects.create(**kwargs)
    return {"data": {"link": serialize_link(link)},
            "message": f"Created link {link.id}."}
```

Must wire up auth/project-scoping to match REST path — cross-check with
`LinkViewSet.perform_create` (`src/links/views.py:39-52`) for the
`_resolve_project` pattern.

### Tests

1. **`tests/mcp_server/test_task_create.py`** — new case: pass
   `depends_on="task_a,task_b"`, assert two `Link` rows exist after create
   with correct fields.
2. **`tests/mcp_server/test_link_create.py`** — new file: create a task pair,
   call `vtf_create_link` with `link_type=depends_on`, assert claimable filter
   excludes the dependent until upstream is done.
3. **`tests/tasks/test_v2_serializers.py`** — update existing `requires`
   assertions: expect list of strings, not hydrated objects.
4. **Manual smoke test**: repeat end-to-end dependency workflow via MCP-only
   (no REST shortcut).

### Acceptance criteria

- `vtf_create_task(depends_on=<id>)` creates a `Link` row and response shows
  `dependencies.unresolved=[<id>]`.
- `vtf_create_link(...)` works for all link types (at minimum `depends_on`,
  `blocks`).
- API response `requires` field is raw string list, not hydrated objects.
- The original stuck-task pattern (`requires="<task_id>"` as a dependency
  proxy) no longer silently traps — callers either use `depends_on` correctly
  or get the expected tag-requirement behavior.

### Compatibility breaks

- Response shape of `task.requires` changes from hydrated object list to
  string list. **Affected consumers [unverified]**: frontend at `web/`, CLI
  at `cli/vtf/`, any third-party API clients. Audit these before merge.
- MCP callers passing `requires=<task_id>` expecting dependency behavior will
  get different (correct) behavior. Given MCP is mostly agent-driven, this is
  low-impact in practice; a migration note in the PR is warranted.

### Effort estimate

- Part A: 15 min code + 30 min test update
- Part B: 45 min code + 30 min test
- Part C: 60 min code + 30 min test
- Consumer audit: 30 min
- **Total: ~4 hours for first-cut PR**

---

## Fix 3 — Pi executor deployment → Helm-managed

### Goal

Replace the hand-rolled `vafi-executor-pi` deployment with a Helm-chart
variant that uses the correct (PID-1) liveness probe, stops restarting every
90 seconds, and is reproducible from git.

### Current state (verified)

- **Hand-rolled deployment** (`kubectl get deployment vafi-executor-pi -n vafi-dev -o yaml`):
  `last-applied-configuration` annotation contains inline raw JSON manifest.
  Missing Helm labels (no `app.kubernetes.io/managed-by=Helm`, no
  `app.kubernetes.io/instance=vafi`). Claude executor (chart-managed) has
  these.
- **Chart templates enumerated** (`ls vafi/charts/vafi/templates/`): only
  `executor-deployment.yaml`, `judge-deployment.yaml`,
  `bridge-deployment.yaml`, `cxdb-*`, `secret`, `certificate`,
  `sessions-pvc`. **No `executor-pi` template.**
- **Override files in vafi-deploy** (`find vafi-deploy -name 'values*.yaml'`):
  `environments/dev.yaml`, `environments/prod.yaml`. Grep across vafi-deploy
  for `executor-pi` → 0 matches.
- **Wrong probe**: `livenessProbe.exec.command=["cat","/tmp/ready"]`.
  `/tmp/ready` is an **architect-pod sentinel** documented at
  `vafi/docs/architect-agent-IMPLEMENTATION.md:27,57,124,376`. Executor pods
  do not write `/tmp/ready`; they run `python3 -m controller` as PID 1.
- **Correct executor probe** (chart-managed claude pod, `kubectl describe`):
  `exec [/bin/bash -c cat /proc/1/cmdline | tr '\0' ' ' | grep -q 'python3 -m controller']`.
- **Running image drift**: last-applied manifest image is
  `vafi-agent-pi:33c11dc`; actually running image is `vafi-agent-pi:2c64c34`.
  Someone did a post-apply `kubectl set image` or direct edit.
- **Restart count** (`kubectl get pod`): 5370 restarts over ~15 days.
- **Extra env vars in hand-rolled manifest not in chart**:
  `VF_PI_PROVIDER=anthropic`, `VF_PI_MODEL=claude-sonnet-4-20250514`,
  `ANTHROPIC_API_KEY` (from `vafi-secrets.anthropic-auth-token`),
  `ANTHROPIC_BASE_URL` (from `vafi-secrets.anthropic-base-url`),
  `VF_OUTPUT_FORMAT=pi_jsonl` (on init container).
- **Missing pull secret warning**:
  `FailedToRetrieveImagePullSecret (x80136 over 15d): Unable to retrieve some image pull secrets (harbor-registry)`.
  Helm chart references `harbor-registry` pull secret which isn't in
  `vafi-dev`.

### Proposed change

**Step 1 — Parameterize the executor for multi-harness.** Two options:

- **Option 3a (recommended): New template per harness.** Copy
  `executor-deployment.yaml` to `executor-pi-deployment.yaml`, hardcode
  `VF_HARNESS=pi`, tags `executor,pi`, and the pi image value. Pros:
  simple, matches existing "one template per component" style. Cons: some
  duplication.
- Option 3b: List-driven template. Define `.Values.executors` as a list
  (`[{name, harness, tags, image}, ...]`), use a `range` in a single
  template. Pros: clean for adding more harnesses later. Cons: larger
  refactor; more Helm template complexity; affects existing claude executor.

Option 3a has lower risk and aligns with the existing chart style
(`bridge-deployment.yaml` is its own file).

Concrete new file `charts/vafi/templates/executor-pi-deployment.yaml`
(abbreviated — mirror `executor-deployment.yaml` structure):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "vafi.fullname" . }}-executor-pi
  labels:
    {{- include "vafi.labels" . | nindent 4 }}
    app.kubernetes.io/component: executor-pi
spec:
  replicas: {{ .Values.executorPi.replicas | default 1 }}
  selector:
    matchLabels:
      {{- include "vafi.selectorLabels" . | nindent 6 }}
      app.kubernetes.io/component: executor-pi
  template:
    metadata:
      labels:
        {{- include "vafi.selectorLabels" . | nindent 8 }}
        app.kubernetes.io/component: executor-pi
    spec:
      containers:
        - name: vafi-agent-pi
          image: {{ .Values.executorPi.image }}
          env:
            - name: VF_HARNESS
              value: pi
            - name: VF_AGENT_ROLE
              value: executor
            - name: VF_AGENT_TAGS
              value: "executor,pi"
            - name: VF_PI_PROVIDER
              value: {{ .Values.executorPi.provider | default "anthropic" }}
            - name: VF_PI_MODEL
              value: {{ .Values.executorPi.model }}
            # …rest of VF_* vars same shape as executor-deployment.yaml…
            - name: ANTHROPIC_API_KEY
              valueFrom:
                secretKeyRef: { name: vafi-secrets, key: anthropic-auth-token }
            - name: ANTHROPIC_BASE_URL
              valueFrom:
                secretKeyRef: { name: vafi-secrets, key: anthropic-base-url }
          livenessProbe:
            exec:
              command:
                - /bin/bash
                - -c
                - "cat /proc/1/cmdline | tr '\\0' ' ' | grep -q 'python3 -m controller'"
            initialDelaySeconds: {{ .Values.executorPi.livenessProbe.initialDelaySeconds | default 60 }}
            periodSeconds: {{ .Values.executorPi.livenessProbe.periodSeconds | default 30 }}
            timeoutSeconds: {{ .Values.executorPi.livenessProbe.timeoutSeconds | default 5 }}
            failureThreshold: {{ .Values.executorPi.livenessProbe.failureThreshold | default 3 }}
          readinessProbe:
            exec:
              command:
                - /bin/bash
                - -c
                - "cat /proc/1/cmdline | tr '\\0' ' ' | grep -q 'python3 -m controller'"
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 2
          # …volumes + ssh init container same as executor-deployment…
```

Add `executorPi:` section to `values.yaml` with defaults mirroring the
`executor:` section plus `image`, `provider`, `model`. Override in
`vafi-deploy/environments/dev.yaml` if needed.

**Step 2 — Fix the pull-secret drift.** Either:

- Create the `harbor-registry` secret in both `vafi-dev` and `vafi-prod`
  namespaces, OR
- Update the chart to use the existing registry secret name (`kubectl get
  secrets -n vafi-dev` to inventory).

### Rollout procedure

```bash
# 1. Delete the hand-rolled deployment explicitly so Helm doesn't try to adopt
kubectl delete deployment vafi-executor-pi -n vafi-dev

# 2. Helm upgrade with the new template
cd /workspace/vafi
helm upgrade vafi charts/vafi -n vafi-dev \
    -f /workspace/vafi-deploy/environments/dev.yaml \
    --atomic --timeout 5m

# 3. Verify
kubectl -n vafi-dev get pods -l app.kubernetes.io/component=executor-pi
kubectl -n vafi-dev describe pod -l app.kubernetes.io/component=executor-pi \
    | grep -E 'Liveness|Readiness|Image'
kubectl -n vafi-dev logs -l app.kubernetes.io/component=executor-pi --tail=30

# 4. Wait 5 min, verify 0 restarts
kubectl -n vafi-dev get pods -l app.kubernetes.io/component=executor-pi
```

### Acceptance criteria

- After rollout: pod has 0 restarts after 10 minutes.
- Pod's liveness probe is the PID-1 check, visible in describe output.
- Pod has Helm labels (`app.kubernetes.io/managed-by=Helm`).
- Submit a pi-tagged task via MCP, verify it's claimed and completes without
  pod restart.
- No `FailedToRetrieveImagePullSecret` warnings in new pod events.

### Risk

- Medium — live infrastructure change in vafi-dev. No prod impact unless
  applied to vafi-prod.
- If the pi harness has any behavior that depends on the hand-rolled manifest
  (like an unusual volumeMount), we miss it. Mitigation: the 5370 restart
  history shows the pod barely runs anyway; whatever's there isn't keeping
  it healthy.

### Open questions requiring human input

- Should vafi-prod get the same treatment? (`kubectl get deployment -n
  vafi-prod vafi-executor-pi` didn't appear in our earlier `get pods` survey,
  but worth explicit check.)
- What replica count for pi executor? Currently 1; keep or scale?
- Both claude and pi harnesses always deployed in both environments, or
  conditional?

### Effort estimate

- Chart template: 1.5 hours (copy + parameterize + test-render)
- Values + deploy-repo updates: 30 min
- Rollout & verification: 30 min
- Delete/adopt/validate: 30 min
- **Total: ~3 hours**

---

## Fix 4 — Enforce `VF_MAX_REWORK`

### Goal

Stop infinite rework loops. When `attempt_number >= max_rework`, transition
the task to `needs_attention` instead of re-invoking the harness.

### Current state (verified)

- **Config read**: `vafi/src/controller/config.py:51`:
  `max_rework=int(os.environ.get("VF_MAX_REWORK","3"))`.
- **Count available**: `vafi/src/controller/worksources/vtf.py:297-314`:
  `count_rework_attempts()` returns count of `changes_requested` reviews via
  `get_task(task_id, expand=["reviews"])`.
- **Populated into rework context**: `ReworkContext.attempt_number` (dataclass
  in `types.py` per ARCHITECTURE-SUMMARY.md key types).
- **Not enforced**: `controller.py` never compares `attempt_number` to
  `max_rework`. The count is stuffed into the rework prompt and forgotten.
  **[Caveat: controller.py has not been read end-to-end in this session.**
  Before writing the PR, read `controller.py` fully and confirm the rework
  branch has no count check.]
- **Contract expectation** (`vafi/docs/vtf-vafi-interface-CONTRACT.md:264-278`):
  "If count >= VF_MAX_REWORK (default 3), the controller calls fail instead
  of attempting another rework." Contract documents intended behavior that
  code doesn't implement.

### Proposed change

Insert a guard in the controller's rework handling branch (exact location
TBD after reading `controller.py`). Pseudocode:

```python
async def handle_rework(self, task: TaskInfo, agent: AgentInfo):
    ctx = await self.work_source.get_rework_context(task.id)
    if ctx.attempt_number >= self.config.max_rework:
        reason = (f"Rework limit exceeded: {ctx.attempt_number} prior rejections "
                  f"(max {self.config.max_rework}). Human triage required.")
        logger.warning(f"Task {task.id}: {reason}")
        await self.work_source.add_note(task.id, reason)
        await self.work_source.fail(task.id, reason)
        return
    # existing rework flow continues from here
    ...
```

Edge cases to handle:

- If `count_rework_attempts` raises: log warning, proceed with harness to
  avoid total stall.
- Two executor pods race on the same task: claim is atomic per contract;
  only one wins. Cap is checked by the winner.

### Tests

1. **Unit test in `vafi/tests/controller/test_controller.py`**: construct a
   `Controller` with mocked `WorkSource` returning
   `ReworkContext(attempt_number=3)`, call rework flow, assert
   `work_source.fail` is called and harness is **not** invoked.
2. **Boundary cases**: `attempt_number = 2` should still invoke harness;
   `attempt_number = 3` should fail; `attempt_number = 4` (unexpected) should
   also fail.

### Acceptance criteria

- Tests above pass.
- Manual/integration: create a task with `needs_review_on_completion=true`,
  have judge reject 3 times, confirm 4th attempt fails with
  `needs_attention` instead of re-running.

### Risk

Low — pure addition, no behavior change for tasks under the limit. Only
residual risk is that `count_rework_attempts` returns inaccurate values
(e.g. if reviews are deleted), causing a task to fail early.

### Effort estimate

- Read `controller.py` thoroughly and locate the rework branch: 30 min
- Implement guard: 15 min
- Tests: 30 min
- **Total: ~1 hr 15 min**

---

## Fix 5 — Supervisor: doc or build

### Goal

Reconcile the contract doc (which describes a supervisor) with the code
(which doesn't have one).

### Current state (verified)

- **Contract describes it**
  (`vafi/docs/vtf-vafi-interface-CONTRACT.md:280-301`): supervisor polls
  `GET /v1/tasks/?status=draft&expand=links`, checks `depends_on` targets
  are done, calls `POST /v1/tasks/{id}/submit/`.
- **`WorkSource` has the methods**
  (`vafi/src/controller/worksources/protocol.py:187-190`):
  `list_submittable()` and `submit()`.
- **`VtfWorkSource` implements them**
  (`vafi/src/controller/worksources/vtf.py:324-345`) with client-side dep
  check.
- **No caller**: `controller.py:131-134` shows role branches for `executor`
  and `judge` only; no `elif role == "supervisor"`.
- **Workaround in practice**: draft tasks are submitted manually via MCP
  `vtf_submit_task` or UI. Observed 2026-04-18: every task was submitted
  manually.

### Two paths

**Path A — Document (recommended unless active need).**

Update `vafi/docs/vtf-vafi-interface-CONTRACT.md` section 13 to mark the
supervisor as "Not implemented in code; submit via MCP `vtf_submit_task`
or UI." Update `vafi/docs/ARCHITECTURE-SUMMARY.md` "Agent roles" table
footnote to clarify that "supervisor" in the contract is a workflow pattern
currently served by humans/architect-agents. Leave the `WorkSource` interface
methods in place for future use.

**Path B — Build.**

Add a supervisor role to vafi:

1. Config: `agent_role: "supervisor"` branch in `controller.py`.
2. Loop: periodically call `list_submittable()` and `submit()` for each
   returned task.
3. Helm: new `supervisor-deployment.yaml` template, new `.Values.supervisor`
   section.
4. Rollout: deploy supervisor pod in each env.

Design decisions needed:

- Per-project or globally scoped?
- Poll interval?
- Submit failure retry/skip policy?
- Locking: multiple supervisors in one cluster — race on submit?

### Acceptance criteria

- **Path A**: doc clearly states supervisor is unbuilt; no code ambiguity
  remains. New contributors won't look for supervisor code that doesn't
  exist.
- **Path B**: draft tasks with all deps resolved transition to `todo`
  automatically within the configured poll interval. No manual submit needed
  for chained workflows.

### Risk

- Path A: zero.
- Path B: medium — new daemon, concurrency concerns, chart complexity.

### Effort estimate

- Path A: **30 min**
- Path B: **~2 days** (design + code + chart + tests + rollout)

### Recommendation

Path A for this PR cycle. Revisit Path B when there's a concrete use case
for autonomous draft→todo promotion (e.g. architect agent creating bulk
tasks that should run sequentially).

---

## Non-goals / explicitly out of scope

- **vafi → vtf-sdk-python migration** — the SDK is built and unused;
  migration is a multi-file refactor across `src/controller/`. Separate
  initiative, not bundled with these fixes.
- **Heartbeat race idempotency** — hypothetical issue (executor `complete()`
  after claim expired → `needs_attention`). No reproducer observed. Would
  need a fault-injection test to validate.
- **Historical gate misconfig patterns** — `gates.py` is fine; the issue was
  task specs that hardcoded `/usr/bin/python3`. Document in a task-spec style
  guide if one exists.
- **Cleaning stuck demo tasks from the discovery workplan** — trivial
  (cancel via MCP); not worth a planning entry.

---

## Verification / remaining unknowns before PRs land

Before PRs land, confirm these with direct reads (items flagged
**[unverified]** above):

1. **`parse_bool` callers audit** (Fix 1): grep every call site; ensure none
   intentionally pass empty-string-as-false.
2. **Read `controller.py` top-to-bottom** (Fix 4): confirm the rework branch
   has no count check; identify exact insertion point for the guard.
3. **vafi-prod state of `vafi-executor-pi`** (Fix 3): `kubectl get deployment
   -n vafi-prod vafi-executor-pi` to decide if prod also needs the fix.
4. **Frontend/CLI audit** (Fix 2 Part A): grep `vtaskforge/web/` and
   `vtaskforge/cli/vtf/` for consumers of the `requires` response field that
   assume hydrated-object shape.

---

## Summary table

| # | Fix | Lines changed (est.) | New files | Tests | Rollout risk | Effort |
|---|---|---|---|---|---|---|
| 1 | `parse_bool("")` → None | 1 | 0 | 1 unit + 1 integration | Very low | ~25 min |
| 2 | MCP `requires` split + link tool + serializer | ~80 | 1 (`link_create.py`) | 4+ tests | Medium (shape break) | ~4 hr |
| 3 | Pi executor to Helm | ~100 chart + values | 1 (`executor-pi-deployment.yaml`) | Manual smoke | Medium (live infra) | ~3 hr |
| 4 | `VF_MAX_REWORK` guard | ~10 | 0 | 3 unit tests | Low | ~1 hr 15 |
| 5A | Supervisor doc | ~30 docs | 0 | N/A | Zero | ~30 min |
| 5B | Supervisor build | ~200 + chart | 2+ (role + template) | 5+ tests | Medium | ~2 days |

**Full Path-A cycle (1+2+3+4+5A): ~9 hours of hands-on engineering** plus a
round of review. Could be 1–2 PRs per person, landed over 2 working days.

---

## Discovery provenance

This plan was produced from a 2026-04-18 discovery pass that included:

- Reading `vafi/docs/{ARCHITECTURE-SUMMARY,vtf-vafi-interface-CONTRACT,
  harness-images-ARCHITECTURE,agent-context-passing-DESIGN,
  architect-agent-IMPLEMENTATION}.md` and the `methodologies/{executor,
  judge,architect}.md` files.
- Reading `vafi/src/controller/{gates.py,vtf_client.py}` in full; partial
  reads of other controller modules.
- Reading `vtaskforge/src/{tasks/models.py,tasks/services.py,tasks/views.py,
  tasks/serializers_v2.py,links/models.py,links/views.py,links/serializers.py,
  mcp_server/parsers.py,mcp_server/tools/task_create.py,
  mcp_server/tools/task_update.py}` at the relevant sections.
- `kubectl describe` on executor and pi executor pods; log tails on judge,
  executor, cxdb, and bridge pods.
- Live spikes on vtf-dev:
  - Spike C: `update_task` boolean reset reproducer (confirmed bug).
  - Spike B: `needs_review_on_completion=true` → full judge review pipeline
    end-to-end (confirmed working, 1m 52s round-trip).
  - Spike A: Link-based `depends_on` via REST `POST /v1/links/` from inside
    a cluster pod, chained execution of dependent tasks
    (confirmed working; dependent claimed exactly 30s after upstream
    transitioned to `done`).
- Findings filed to mempalace under `vtf/{bugs,api,architecture}` and
  `vafi/{bugs,architecture}` drawers.
