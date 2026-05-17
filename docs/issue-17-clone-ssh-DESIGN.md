# Issue #17 / R1 — Workspace-Access: clone via the managed SSH credential (DESIGN)

**Date:** 2026-05-17
**Tracking:** [#17](https://github.com/ViloForge/vafi/issues/17)
**Architecture:** R1 of
`viloforge-platform/docs/agentic-pipeline-ARCHITECTURE.md` (§5.2
Workspace-Access). **Kind:** bugfix (north-star TDD; no over-engineering).

## Defect

`_ensure_repo_cloned` runs `git clone <repo.url>` with `repo.url` =
HTTPS (vtf project `repo_url`). For a **private** repo, non-interactive
git has no credential → `fatal: could not read Username` → exit 128 →
task fast-fails before the harness runs (#17). #15 fixed *push* by
rewriting `origin` to SSH **after** clone; the clone itself never gets
the mounted SSH credential. Clone and push are the *same* capability and
must use the *same* credential path (architecture §5.2).

## Design

Reuse the #15 pure helper `https_github_to_ssh()` (already unit-tested).
Add one key-presence-gated resolver and apply it to the **clone URL**:

```
def _clone_url(self, url: str) -> str:
    ssh = https_github_to_ssh(url)
    return ssh if (ssh and self.ssh_key_path.exists()) else url
```

`git clone` uses `self._clone_url(repo.url)` instead of `repo.url`.
Consequences:

- Private GitHub repo now clones via `git@github.com:…` using the
  mounted key → #17 closed.
- `origin` is already SSH post-clone, so `_normalize_origin_for_push`
  (#15) becomes an idempotent no-op safety net — kept, unchanged.
- Same `https_github_to_ssh` contract: non-GitHub / already-SSH /
  no-key ⇒ URL unchanged (V16: public-repo + local/CI paths and the
  existing clone behavior unaffected when no key is present).

## Scope fence (executor R6)

- `src/controller/invoker.py` — add `_clone_url`; use it in the clone
  `cmd`. Nothing else; `_normalize_origin_for_push` untouched.
- `tests/test_invoker.py` — unit (resolver, incl. negatives) +
  subprocess-arg assertions that the clone command carries the SSH URL
  iff GitHub-HTTPS **and** key present.
- `docs/INDEX.md` — link.
- **Not** in scope: credential *identity* design (per-agent deploy key
  vs machine identity vs broker) — that is architecture OAQ-3, a later
  decision; this slice uses the already-mounted key as-is.

## Test plan (TDD red first)

- Unit: `_clone_url` — github-https+key⇒ssh; github-https+no-key⇒https;
  non-github+key⇒unchanged; already-ssh⇒unchanged.
- Behavioral: patch `subprocess.run`; assert the `git clone` argv
  contains the SSH URL when key present, the HTTPS URL when absent,
  unchanged for non-github. (Real private-auth clone is not hermetically
  testable; the fix's contract is "what URL we clone from", which is.)
- Regression: full in-scope suite green; #15 tests unaffected.
- Dogfood: re-fire the Flask experiment against a **private** repo →
  clone now succeeds, executor runs (the negative path #17 reproduced;
  this closes it). The experiment-runnable milestone.
