# Spike probe prompts (frozen)

Used by the Phase 8 session-continuity spike. See `vafi/docs/bridge/phase-8-session-continuity-SPIKE.md`.

These files are **frozen** for the duration of the spike. If you need to change one, log the change in the SPIKE doc status table with a justification — prior runs are invalidated by any prompt edit.

## Files

| File | Used by | Purpose |
|------|---------|---------|
| `baseline-session1.txt` | Step 1 (characterization) | Plant 3 distinctive facts in session 1 |
| `baseline-session2.txt` | Step 1 | Ask for the 3 facts in session 2 — observe only, no assert |
| `test-a-plumbing-session1.txt` | Step 3 Test A | Plant a unique nonce. `{NONCE}` is substituted at runtime with a UUID. |
| `test-a-plumbing-session2.txt` | Step 3 Test A | Ask for the nonce. Pass = exact string match. |
| `test-b-task-session1.txt` | Step 3 Test B | Ask agent to design a `BankAccount` class |
| `test-b-task-session2.txt` | Step 3 Test B | Ask agent to extend the class — pass = response references prior symbols |

## Substitutions

- `{NONCE}` — replaced by `uuid.uuid4().hex[:8].upper()` at test runtime so each run is unique. Prevents context-window leakage across runs giving false passes.
