# Generic Agent Spike — Rumsfeld Matrix

Status: Active (2026-03-28)

## Goal

Make vafi agents work as a general solution — generic executor and judge agents that can operate on any codebase, not just vafi. This spike validates the approach before building the production agents.

## Rumsfeld Matrix

### Known Knowns (we know this works)

- Controller poll/claim/execute/report loop works end-to-end
- vtf state machine handles full lifecycle including rework (`changes_requested → doing`)
- Any executor can pick up rework (no agent affinity required)
- CXDB captures execution traces tagged by task ID
- Harness (Claude Code 2.1.85) can run headless with `--output-format json`
- Task specs as YAML are sufficient for execution (proven in Phase 9 simulations)
- Session resume exists (`claude --resume <id>`)
- Workdir reuse works (invoker skips clone if `.git` exists)
- Shared volume at `/sessions/` means workdirs persist across executor and judge pods
- Same container image serves both executor and judge — entrypoint copies `methodologies/<role>.md` to CLAUDE.md based on `VF_AGENT_ROLE` env var
- Judge accesses executor's work via shared workdir — no push needed
- Executor clones default branch, shallow depth 1, commits locally
- No MCP tools in container — harness runs headless, controller handles all vtf API calls
- Controller prompt template is minimal (4 lines: title, id, spec, test_command)
- `VF_AGENT_ROLE` config flag exists and is read from env, but controller logic does not branch on it yet
- Repo cloned with `--depth 1 --single-branch` — workdir has one history commit plus executor's commits. No full repo history available.
- No task branch created — executor commits directly to the default branch in the workdir
- Each task gets its own workdir (`/sessions/task-<id>/`), only one agent can claim a task at a time — no concurrent access
- Judge enters the same workdir as executor — can see commits via `git log`, changed files via `git diff HEAD~N..HEAD`
- SSH auth to GitHub works (authenticated as `vilosource`) — push is possible
- **BLOCKER**: No git user.name/user.email configured — `git commit` will fail. Entrypoint must set this.
- No Claude Code plugins or settings beyond CLAUDE.md
- Python 3.11.2, pytest 7.2.1, git, curl, jq available in container
- Claude Code 2.1.85 supports `--resume <session-id>` for session resumption and `--fork-session` for branching from a resume point
- Claude Code supports `--json-schema` for structured output validation — controller can enforce verdict format from judge (solves verdict parsing)
- Claude Code supports `--no-session-persistence` to disable session file saving
- Session files not yet present in container — created on first execution, location TBD

### Known Unknowns (we need to figure out)

- What does a generic executor methodology look like? We've only tested project-specific ones (current one is 214 lines, vafi-specific: asyncio, WorkSource protocol).
- What does a generic judge methodology look like? The simulation used a hand-crafted 248-line persona tied to vtf.
- How does the executor discover it's doing rework? Does it read reviews from vtf, or does the controller need to inject feedback into the prompt? (`get_rework_context()` exists in vtf.py but controller doesn't call it)
- Does session resume actually help on rework, or does a fresh prompt with context work better?
- How does the executor handle repos it's never seen? Cold start with no CLAUDE.md, no conventions, no context.
- What's the minimum task spec that produces reliable results?
- How much of the methodology is actually needed vs what the model figures out on its own?
- ~~How does the judge extract a structured verdict (approved/changes_requested + reason) from harness output?~~ **Resolved**: `--json-schema` flag enforces structured output. Controller passes verdict schema, gets guaranteed JSON.
- Does `--depth 1` shallow clone give the judge enough context to review? It can read files but has no git history beyond the clone point + executor commits.

### Unknown Knowns (experience we haven't formalized)

- The simulation protocol guide documents what worked, but it's informal — human-driven, not machine-driven
- The vtf-executor (239 lines) and vtf-judge (248 lines) agent definitions at `~/.claude/agents/` encode real learnings but are tied to vtf/vafi
- We know from Phase 9 that judges catch real issues (stale comments, missing tests, N+1 queries) but we don't know which parts of the judge methodology actually drove that vs the model's inherent capability
- We've seen rework succeed in simulation but the human was the middleman — we don't know if the autonomous flow preserves enough context
- Branch strategy was never an issue in simulation because the human managed branches — autonomous agents need a strategy

### Unknown Unknowns (risks we haven't considered)

- How does the executor behave on unfamiliar codebases with no patterns to follow?
- What happens when the spec is ambiguous and there's no human to ask?
- How does the judge verify work in a repo it doesn't understand?
- What failure modes exist when executor and judge disagree repeatedly?
- Does the 3-attempt rework limit produce good outcomes or just exhaust retries?
- What happens with large repos where clone is slow?
- Does the executor make destructive changes outside the spec scope?

---

## Execution Plan

### Phase 1: Spike Infrastructure

Set up everything needed to run spikes.

**1.1 Create spike repo**
- Create `vilosource/vafi-spike` on GitHub
- Simple Python calculator library: `src/calc/operations.py`, `src/calc/validators.py`
- Existing tests: `tests/test_operations.py`, `tests/test_validators.py`
- `CLAUDE.md` with project conventions (test commands, code style, structure)
- Enough existing code that the executor has patterns to follow
- Must be cloneable via SSH by the executor container

**1.2 Create vtf project**
- Create a project in vtf-dev pointing at the spike repo (`repo_url`, `default_branch`)
- Create a workplan and active milestone for spike tasks

**1.3 Fix git config blocker**
- Add `git config --global user.name/email` to entrypoint.sh
- Build and push updated image
- Redeploy executor to vafi-dev

**1.4 Write generic executor methodology**
- New `methodologies/executor.md` replacing vafi-specific version
- Reference the vtf-executor agent (239 lines) for structure, strip project-specific content
- Focus on: read spec, read existing patterns, implement, run tests, commit
- First draft — will iterate based on Spike 1 results

**1.5 Build and deploy executor**
- Build image with updated entrypoint + generic methodology
- Push to Harbor
- Deploy to vafi-dev
- Verify executor pod starts and polls successfully

### Phase 2: Spike 1 — Cold Start Execution

Test the executor on an unfamiliar repo with a generic methodology.

**2.1 Create test task**
- Write a task spec: "Add a power function to operations.py"
- Include: description, files to create/modify, implementation approach, acceptance criteria, test command
- **Must set `needs_review_on_completion: true`** so task goes to `pending_completion_review` for the judge in Phase 4
- Submit task to vtf-dev

**2.2 Observe execution**
- Watch executor logs: does it claim, clone, execute?
- Monitor CXDB for trace capture
- Wait for task to reach `pending_completion_review`

**2.3 Evaluate results**
- Read CXDB trace: what did the executor do? Did it read patterns? Follow conventions?
- Check the workdir: are the files correct? Do tests pass? Is the commit clean?
- Document findings in Spike 1 section
- Update Rumsfeld matrix with learnings

**2.4 If execution fails**
- Read CXDB trace and executor logs to diagnose
- Fix methodology or infrastructure as needed
- Create a new task (new ID = fresh workdir) and retry
- Do not proceed to Phase 3 until at least one successful execution

### Phase 3: Judge Infrastructure

Build the judge capability into the controller.

**3.1 Write generic judge methodology**
- New `methodologies/judge.md`
- Reference the vtf-judge agent (248 lines) for structure, strip project-specific content
- Focus on: run tests, review code against spec, check acceptance criteria, produce verdict
- Verdict format: structured JSON (decision + reason)

**3.2 Controller changes for judge role**
- `_poll_and_process()`: branch on `config.agent_role`
  - executor: poll `changes_requested` + `claimable` (current behavior)
  - judge: poll `pending_completion_review`
- Judge report: parse harness output for verdict, call `submit_review()`
- Use `--json-schema` to enforce structured verdict output from harness
- Judge prompt template: `templates/judge.txt` (similar to task.txt but "verify" instead of "implement")

**3.3 Add judge section to Helm chart**
- The current chart has one `executor` section. Add a `judge` section to `values.yaml` with its own `replicas`, `role`, `tags`, and resource config.
- Add `templates/judge-deployment.yaml` — same structure as executor deployment but uses `judge` values and `VF_AGENT_ROLE=judge`.
- Alternative: reuse executor template with a loop over roles. Decide based on complexity.

**3.4 Build and deploy judge**
- Build image with judge methodology + controller changes
- Deploy to vafi-dev: Helm upgrade with `judge.replicas=1`
- Verify judge pod starts and polls `pending_completion_review`

### Phase 4: Spike 2 — Judge Verification

Test the judge on the executor's output from Spike 1.

**4.1 Trigger judge**
- The task from Spike 1 should be in `pending_completion_review`
- Judge pod picks it up, enters same workdir, runs harness

**4.2 Observe verification**
- Watch judge logs: does it claim, run tests, review code?
- Monitor CXDB for judge trace
- Read the structured verdict: is it approved or changes_requested?

**4.3 Evaluate results**
- Was the verdict correct? Did the judge catch real issues or false positives?
- Did the judge run tests independently?
- Did the structured output (`--json-schema`) work?
- Document findings, update matrix

### Phase 5: Spike 3 — Rework Flow

Test the full autonomous cycle: execute → judge reject → rework → judge approve.

**5.1 Create a task with an intentional trap**
- Write a task spec that a competent executor will implement but with a gap the judge should catch
- Example: "Add a divide function" — executor implements but may miss division by zero handling
- The executor may handle the edge case correctly (Claude is smart) — that's a valid outcome too. If the executor gets it right and the judge approves on first pass, that tells us the full cycle works even without rework.
- If we need to force rework: manually submit a `changes_requested` review before the judge picks it up, with specific feedback. This tests the rework path regardless of executor quality.
- **Must set `needs_review_on_completion: true`**
- Submit task

**5.2 Observe full cycle**
- Executor implements → judge reviews → judge rejects with feedback → executor picks up rework → judge re-reviews
- Watch both executor and judge logs through the full cycle
- Monitor CXDB for all traces (executor attempt 1, judge review 1, executor rework, judge review 2)

**5.3 Evaluate results**
- Did the judge catch the intentional gap?
- Did the executor read the judge feedback? (How — via vtf reviews? Via the workdir?)
- Did the executor fix the issue without reimplementing from scratch?
- Did the judge approve the rework?
- How many cycles did it take?
- Document findings, update matrix

### Phase 6: Spike 4 — Minimal Methodology

Test how little methodology the agents actually need.

**6.1 Strip executor methodology**
- Reduce to minimal instructions (10-20 lines)
- Remove step-by-step workflow, keep only goals and constraints

**6.2 Strip judge methodology**
- Same reduction

**6.3 Run a new task with the same pattern as Spike 1**
- Create a new task (different ID = fresh workdir) with a similar spec: "Add a modulo function"
- Same complexity as Spike 1 so results are comparable
- Compare: same quality? Worse? Better?

**6.4 Evaluate**
- What's essential in the methodology?
- What does the model figure out on its own?
- Document findings, update matrix

---

### Iteration Policy

Each phase ends with an evaluation. If the spike reveals issues:
- **Infrastructure issues** (crash, config error, blocker): fix before proceeding.
- **Methodology issues** (executor missed patterns, judge gave bad verdict): iterate on methodology and rerun the spike with a new task before proceeding.
- **Acceptable imperfections** (minor code style issues, verbose output): document and proceed. Don't chase perfection — the goal is to learn, not to ship.

Phases are sequential — don't skip ahead. Each phase builds on validated results from the previous one.

---

## Success Criteria

- [ ] Executor completes a task on unfamiliar repo without project-specific methodology
- [ ] Judge produces actionable feedback that identifies real issues
- [ ] Executor successfully reworks based on judge feedback without human intervention
- [ ] Full cycle (execute → judge → rework → judge approve) completes autonomously
- [ ] Rumsfeld matrix Known Unknowns resolved with evidence from spike traces

---

## Findings

_Updated as spikes are executed._

### Spike 1: Cold start execution
- Date: 2026-03-28
- Result: **SUCCESS**
- CXDB trace: https://cxdb.dev.viloforge.com/c/1
- Task: H9rRKon9kAcDGCaYc8ONn (vtf-dev)
- Execution: 14 turns, $0.12, ~50 seconds
- Learnings:
  - Generic 60-line methodology sufficient for cold start on unfamiliar repo
  - Executor read CLAUDE.md, discovered patterns from existing code, followed conventions exactly
  - Implementation matched existing pattern: ensure_numeric validation, docstring, return
  - Test class matched existing pattern: positive, negative, zero, float, invalid input cases
  - Added 7 tests (spec only required 5 acceptance criteria — executor added extras for floats and negative base)
  - Clean single commit, descriptive message, no scope creep
  - All 24 tests pass (18 existing + 6 new in operations + the original validator tests make 25 repo-wide)

### Spike 2: Judge verification
- Date: 2026-03-28
- Result: **SUCCESS**
- CXDB trace (executor): https://cxdb.dev.viloforge.com/c/4
- CXDB trace (judge): https://cxdb.dev.viloforge.com/c/5
- Task: wgQvEwdr2bcCW0JI8yghi (vtf-dev)
- Executor: 13 turns, $0.10
- Judge: approved with specific reasoning
- Learnings:
  - Full autonomous cycle works: executor → pending_completion_review → judge → done
  - Judge ran tests independently and verified all 22 pass
  - Judge correctly verified acceptance criteria
  - Judge produced structured verdict parsed by controller
  - Judge submitted review via POST /tasks/{id}/reviews/ without claiming
  - Shared workdir works — judge accessed executor's code and commits
  - The judge did NOT need to claim the task — review submission handles state transition
  - Stale test data in pending_completion_review was a nuisance — judge picks up whatever is in queue (no project filtering yet)

### Spike 3: Rework flow
- Date: TBD
- Result: TBD
- CXDB trace: TBD
- Learnings: TBD

### Spike 4: Minimal methodology
- Date: TBD
- Result: TBD
- CXDB trace: TBD
- Learnings: TBD

---

## Decisions Made

_Captured as spikes produce learnings._

## Open Questions

_Moved here from Known Unknowns as they're investigated but not yet resolved._
