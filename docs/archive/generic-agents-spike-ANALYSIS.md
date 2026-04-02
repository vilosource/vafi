> **Archived**: This document is historical. For current architecture, see [ARCHITECTURE-SUMMARY.md](../ARCHITECTURE-SUMMARY.md) and [harness-images-ARCHITECTURE.md](../harness-images-ARCHITECTURE.md).

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
- Prompt is a minimal pointer: "Work on task X. Read .vafi/context.md for details."
- Controller branches on `VF_AGENT_ROLE`: executor polls claimable/rework, judge polls pending_completion_review
- Repo cloned with `--depth 1 --single-branch` — workdir has one history commit plus executor's commits
- No task branch created — executor commits directly to the default branch in the workdir
- Each task gets its own workdir (`/sessions/task-<id>/`), only one agent can claim a task at a time
- Judge enters the same workdir as executor — can see commits via `git log`
- Judge does NOT claim tasks — submits review directly, review endpoint handles state transition
- SSH auth to GitHub works (authenticated as `vilosource`) — push is possible
- Git user.name/email configured in entrypoint (blocker fixed)
- Python 3.11.2, pytest 7.2.1, git, curl, jq available in container
- Claude Code 2.1.85 with `--resume`, `--fork-session`, `--json-schema`, `--no-session-persistence`
- `.vafi/context.md` is the agent communication channel — controller materializes vtf state (spec, reviews, notes) into workdir before each invocation
- Context file is regenerated before every invocation with latest vtf state
- Generic executor methodology: 60 lines, works on unfamiliar repos (Spike 1: 14 turns, $0.12)
- Generic judge methodology: 65 lines, produces structured JSON verdicts
- Full autonomous cycle verified: executor → judge → rework with feedback → judge approve (Spike 3b)
- Shallow clone sufficient for judge — judge reads files and executor commits, doesn't need full history (Spike 2)

### Known Unknowns (remaining — not answered by spikes)

- Does session resume help on rework, or is a fresh prompt with context file sufficient? (Not tested — context file approach worked without resume)
- What's the minimum task spec that produces reliable results? (Spikes used detailed specs — haven't tested minimal ones)
- What failure modes exist when executor and judge disagree repeatedly? (3-attempt limit exists but not tested)
- What happens with large repos where clone is slow? (Spike repo was tiny)
- How does the system perform on non-Python codebases? (Only tested Python)

### Unknown Knowns → Now Known (formalized by spikes)

- ~~The simulation protocol guide documents what worked, but it's informal~~ → Generic methodology extracts the essential steps. Project-specific content is unnecessary.
- ~~We don't know which parts of the judge methodology drove quality~~ → The judge methodology is 65 lines. The model's inherent capability handles most of the review; the methodology just structures the output.
- ~~We don't know if autonomous rework preserves enough context~~ → It does, via the context file. The executor reads the rejection, addresses it specifically, and the judge approves.
- ~~Branch strategy was never an issue~~ → No task branches needed. Each task has its own workdir. The executor commits on whatever branch was cloned.

### Unknown Unknowns (discovered during spikes)

- Context file write order matters — must clone repo before writing `.vafi/context.md` or clone fails (discovered and fixed in Spike 3b)
- Stale tasks in `pending_completion_review` get picked up by the judge indiscriminately — judge has no project filtering (discovered in Phase 4)
- Multi-repo tasks decompose into multiple vtf tasks with dependencies — context passes via vtf notes (discussed, not spike-tested)
- What happens when the executor produces code that passes its own tests but breaks in integration?

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
- Date: 2026-03-28
- Result: **PARTIAL — mechanics work, feedback not incorporated**
- CXDB traces: ctx=6 (executor), ctx=7 (executor rework), ctx=8 (judge)
- Task: LXW4kH2g2g-QS8ienjd1r (vtf-dev)
- Learnings:
  - The mechanical flow works: `changes_requested → doing → pending_completion_review → done`
  - Executor reclaimed the task and ran in the existing workdir
  - **PROBLEM**: Executor did NOT read the judge feedback. The controller sends the same prompt for rework as for new work — no feedback injected.
  - **PROBLEM**: Judge approved the rework despite the requested fix (division by zero handling) NOT being implemented. The judge didn't cross-reference the previous rejection.
  - The divide function has no division-by-zero guard despite the rejection specifically requesting it.
  - Root cause: the executor has no way to know it's doing rework. The prompt is identical. The workdir already has the code from attempt 1, so the executor sees "nothing to do" and completes.
  - Root cause for judge: the judge reviewed the code against the spec only, not against the previous rejection. The spec didn't require division-by-zero, so the judge approved.
  - **Decision needed**: Should the controller inject judge feedback into the rework prompt? Or should the executor/judge query vtf for reviews themselves?

### Spike 3b: Rework Flow (with context file mechanism)
- Date: 2026-03-28
- Result: **SUCCESS**
- CXDB traces: ctx=9 (executor), ctx=10 (executor rework), ctx=11 (judge)
- Task: up68Sq8sABNOabgl5bkOG (vtf-dev)
- Learnings:
  - Context file mechanism works. Controller writes `.vafi/context.md` to workdir with full vtf state (spec, notes, reviews).
  - Executor read the judge rejection from context file and addressed it specifically: added `if b == 0: raise ValueError` and a test.
  - Judge approved the rework — full cycle: `todo → doing → pending_completion_review → changes_requested → doing → pending_completion_review → done`
  - Context file serves as the message-passing mechanism between agents. No MCP tools or vtf CLI needed in the container.
  - **Bug found**: context file was written before git clone, causing clone to fail on non-existent workdir. Fixed by cloning first, then writing context.
  - This mechanism generalizes to any agent chain — each agent's output (stored in vtf) is materialized in the next agent's context file.

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
