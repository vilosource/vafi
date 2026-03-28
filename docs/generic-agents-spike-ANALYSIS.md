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
- Harness (Claude Code) can run headless with `--output-format json`
- Task specs as YAML are sufficient for execution (proven in Phase 9 simulations)
- Session resume exists (`claude --resume <id>`)
- Workdir reuse works (invoker skips clone if `.git` exists)
- Shared volume means workdirs persist across executor restarts

### Known Unknowns (we need to figure out)

- What does a generic executor methodology look like? We've only tested project-specific ones.
- What does a generic judge methodology look like? The simulation used a hand-crafted judge persona.
- How does the executor discover it's doing rework? Does it read reviews from vtf, or does the controller need to inject feedback into the prompt?
- Does session resume actually help on rework, or does a fresh prompt with context work better?
- What branch strategy works? Task branch per task? Work on default branch? Who creates the branch?
- How does the executor handle repos it's never seen? Cold start with no CLAUDE.md, no conventions, no context.
- What's the minimum task spec that produces reliable results?
- How much of the methodology is actually needed vs what the model figures out on its own?

### Unknown Knowns (experience we haven't formalized)

- The simulation protocol guide documents what worked, but it's informal — human-driven, not machine-driven
- The vtf-executor (239 lines) and vtf-judge (248 lines) agent definitions encode real learnings but are tied to vtf/vafi
- We know from Phase 9 that judges catch real issues (stale comments, missing tests, N+1 queries) but we don't know which parts of the judge methodology actually drove that vs the model's inherent capability
- We've seen rework succeed in simulation but the human was the middleman — we don't know if the autonomous flow preserves enough context

### Unknown Unknowns (risks we haven't considered)

- How does the executor behave on unfamiliar codebases with no patterns to follow?
- What happens when the spec is ambiguous and there's no human to ask?
- How does the judge verify work in a repo it doesn't understand?
- What failure modes exist when executor and judge disagree repeatedly?
- Does the 3-attempt rework limit produce good outcomes or just exhaust retries?
- What happens with large repos where clone is slow?
- Does the executor make destructive changes outside the spec scope?

---

## Spike Plan

### Spike repo

A simple Python project (`vilosource/vafi-spike`) with:
- A utility library (calculator, string utils, or similar)
- Existing tests and patterns
- A CLAUDE.md with basic project conventions
- Enough code that the executor has patterns to follow

### What to test

**Spike 1: Cold start execution**
- Create a task spec for a new feature
- Executor has never seen the repo
- Observe: does it clone, read patterns, implement correctly, run tests, commit?

**Spike 2: Judge verification**
- After executor completes, run judge
- Observe: does it run tests independently, review code, produce useful verdict?

**Spike 3: Rework flow**
- Judge rejects with specific feedback
- Executor picks up rework
- Observe: does it read the feedback, build on previous work, fix the issues?

**Spike 4: Minimal methodology**
- Strip the methodology to bare minimum
- How little can we tell the executor and still get good results?
- What's essential vs nice-to-have?

### Success criteria

- [ ] Executor completes a task on unfamiliar repo without project-specific methodology
- [ ] Judge produces actionable feedback that identifies real issues
- [ ] Executor successfully reworks based on judge feedback without human intervention
- [ ] Full cycle (execute → judge → rework → judge approve) completes autonomously

---

## Findings

_Updated as spikes are executed._

### Spike 1: Cold start execution
- Date: TBD
- Result: TBD
- CXDB trace: TBD
- Learnings: TBD

### Spike 2: Judge verification
- Date: TBD
- Result: TBD
- CXDB trace: TBD
- Learnings: TBD

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
