# Agent Context Passing — Work Artifacts Design

Status: Draft (2026-03-28)

## Problem

Agents working on the same task cannot see each other's output. When a judge rejects a task, the executor that picks up the rework receives the same bare prompt as the first attempt — it doesn't know what was rejected or why. This breaks the rework flow and blocks any multi-agent pipeline.

Discovered in Spike 3: the executor completed rework without addressing judge feedback because the feedback never reached it.

## Principle: The Workdir is the Artifact Store

Every task gets a workdir at `/sessions/task-<id>/`. This workdir is the shared artifact store for all agents working on that task. It persists across agent invocations on the shared volume.

The workdir contains two kinds of artifacts:

| Artifact type | Produced by | Examples |
|---|---|---|
| **Code artifacts** | Agents (via harness) | Source files, commits, test results |
| **Context artifact** | Controller (from vtf) | `.vafi/context.md` — task spec, reviews, notes, history |

Agents read both. They read the code to understand what exists. They read the context to understand what's expected and what happened before them.

## The Context File

Before each harness invocation, the controller writes `.vafi/context.md` into the workdir. This file is a materialization of the task's vtf state — everything the agent needs to know.

**Path:** `<workdir>/.vafi/context.md`

**Contents:**

```markdown
# Task: <title> (<id>)

## Specification
<full YAML spec>

## Test Commands
<test_command from task>

## History

### Note 1 — executor-default (2026-03-28T15:22:43Z)
Completion report:
> Implemented divide function with 4 tests. All acceptance criteria met.

### Review 1 — human-tester (2026-03-28T15:23:15Z)
Decision: **changes_requested**
> Missing division by zero handling. The divide function must raise a
> ValueError when b is 0. Add a test for divide(1, 0) that expects ValueError.

### Current Attempt
You are working on attempt 2. Address the feedback from the previous review.
```

**Key properties:**
- Regenerated before every invocation (always reflects latest vtf state)
- Includes all reviews and notes from vtf (the full conversation history)
- Ends with a clear statement of what the current agent should do
- Human-readable (useful for debugging)
- The harness (Claude Code) reads it naturally — it reads files in the workdir

## How It Works

### Executor flow (new task)

1. Controller claims task, creates workdir, clones repo
2. Controller fetches task data from vtf (spec, notes, reviews)
3. Controller writes `.vafi/context.md` — contains spec, no history
4. Controller invokes harness with minimal prompt: "Work on this task. Read .vafi/context.md for details."
5. Harness reads context file, implements task, commits
6. Controller reports result to vtf (notes, completion)

### Judge flow

1. Controller finds task in `pending_completion_review`
2. Workdir already exists with executor's code
3. Controller fetches task data from vtf (spec, notes including executor's completion report, reviews)
4. Controller writes `.vafi/context.md` — contains spec + executor's completion report
5. Controller invokes harness with: "Verify this task. Read .vafi/context.md for details."
6. Harness reads context, runs tests, reviews code, produces verdict
7. Controller submits review to vtf

### Executor flow (rework)

1. Controller claims `changes_requested` task
2. Workdir already exists with previous code
3. Controller fetches task data from vtf (spec, notes, reviews including judge rejection)
4. Controller writes `.vafi/context.md` — contains spec + full history (completion report + rejection)
5. Controller invokes harness with: "Work on this task. Read .vafi/context.md for details."
6. Harness reads context, sees the rejection feedback, fixes the issues
7. Controller reports result to vtf

### Arbitrary agent chain

The same mechanism works for any sequence of agents:

```
Agent A works → output stored as vtf notes → context.md updated
Agent B works → reads context.md (includes A's output) → output stored → context.md updated
Agent C works → reads context.md (includes A's and B's output) → ...
```

The controller materializes vtf state into the workdir. Agents communicate through vtf. The context file is the bridge.

## What the Controller Does

For each invocation, the controller:

1. Fetches the task from vtf with `expand=reviews`
2. Fetches task notes from vtf
3. Constructs the context markdown from this data
4. Writes it to `<workdir>/.vafi/context.md`
5. Invokes the harness

This is a pure function: vtf state in → markdown file out. No intelligence, no decisions.

## What the Methodology Says

The agent methodology (CLAUDE.md) tells the agent:

```
## Step 0: Orient

1. Read `.vafi/context.md` in the working directory — this contains the task
   specification, history, and any feedback from previous agents
2. Read `CLAUDE.md` for project conventions
...
```

The agent treats the context file as its primary briefing.

## Prompt Change

The prompt becomes simpler:

**Before:**
```
Implement the following task.

## Task: Add a divide function (LXW4...)

## Specification
[full spec YAML]

## Test Commands
[test commands]
```

**After:**
```
Work on this task. Read .vafi/context.md for the full specification and history.
```

The spec, test commands, history, and feedback are all in the context file. The prompt is just a pointer.

## Multi-Repo Tasks

A task that requires changes to multiple repos is decomposed into multiple tasks with dependencies. Each task has its own workdir and repo. Context passes between tasks through vtf notes — completion reports from upstream tasks are included in downstream tasks' context files.

```
Task 1 (repo-a) → completion report stored in vtf
Task 2 (repo-b, depends_on: Task 1) → context.md includes Task 1's notes
```

One task = one repo = one workdir. The task system handles coordination.

## Implementation

### Implementation (done)

1. **Module: `src/controller/context.py`**
   - `build_context(task_data, notes, reviews, role="executor", prior_summaries=None, workplan_context="") -> str` — pure function, vtf data → markdown
   - `write_context(workdir, content)` — writes to `.vafi/context.md`

2. **Controller: `execute()` method**
   - Before invoking harness, fetch full task data (notes + reviews)
   - Call `build_context()` and `write_context()`

3. **Prompt templates**
   - `templates/task.txt` → simplified to point at context file
   - `templates/judge.txt` → simplified to point at context file

4. **Methodology update**
   - Both executor.md and judge.md: Step 0 reads `.vafi/context.md`

5. **No vtf API changes needed** — all data already available via existing endpoints
