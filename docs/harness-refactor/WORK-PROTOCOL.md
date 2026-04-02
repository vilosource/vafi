# Harness Refactor — Work Protocol

**Design:** vafi-console-harness-boundary-DESIGN.md (in KB/viloforge/)
**Plan:** vafi-harness-boundary-IMPLEMENTATION-PLAN.md (in KB/viloforge/)

## Rules

1. **Follow the design exactly.** No shortcuts. No "simpler" alternatives. If the design says `init.sh` goes at `/opt/vf-harness/init.sh`, that's where it goes. If unsure, ask.

2. **TDD: RED → GREEN → REFACTOR.** Write failing test first. Write minimum code to pass. Clean up. Every phase starts with failing tests.

3. **E2E gate per phase.** After code passes unit tests: build → push → deploy to vafi-dev → run E2E tests. Phase is not done until E2E passes against real infrastructure.

4. **No improvisation.** If something isn't covered by the design, STOP and ask. Do not invent solutions. Do not add features. Do not "improve" things.

5. **No harness names in source code.** After each phase, grep the modified source files for `"claude"` and `"pi"`. Any match (outside test fixtures and parser registry) is a violation.

6. **Each phase maintains working state.** If a phase fails E2E, revert it. Do not proceed to the next phase with broken state.

7. **Commit per phase.** Each phase gets its own commit with a clear message describing what changed and what was verified.

## Gate Review Checklist

Run at the end of every phase before proceeding:

- [ ] All unit tests pass (`pytest tests/` — 250+ existing + new)
- [ ] Phase-specific E2E tests pass against vafi-dev
- [ ] No harness names in modified source files (grep check)
- [ ] Existing E2E tests still pass (no regression)
- [ ] Changes match the design document (not improvised)
- [ ] Commit message describes what changed and what E2E verified

## How to Read Phase Documents

Each phase document has:
- **Goal** — one sentence, what this phase achieves
- **Design reference** — which section of the design doc this implements
- **Files changed** — exact paths
- **TDD sequence** — RED tests listed, then GREEN implementation
- **E2E tests** — what to run against vafi-dev after deploy
- **Gate** — checklist items specific to this phase
- **Done when** — concrete exit criteria
