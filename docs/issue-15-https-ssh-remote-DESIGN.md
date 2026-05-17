# Issue #15 — Deterministic HTTPS→SSH origin rewrite (DESIGN)

**Date:** 2026-05-17
**Tracking:** [#15](https://github.com/ViloForge/vafi/issues/15)
(surfaced by the F7/F10 dogfood — see
[f7-f10-delivery-gate-DESIGN.md](f7-f10-delivery-gate-DESIGN.md))
**Kind:** bugfix (executor methodology — TDD red/green, fail-loud,
no over-engineering, full pyramid).

## The defect (one paragraph)

Agent pods (`vafi-executor`, `vafi-executor-pi`, `vafi-judge`) mount an
SSH key at `~/.ssh/id_ed25519` (chart `setup-ssh` initContainer, secret
`github-ssh`; its public half is on the `vilosource` account with push
to the target repos). But vtf project `repo_url` is **HTTPS**
(`https://github.com/<owner>/<repo>`), so `invoker._ensure_repo_cloned`
sets `origin` to HTTPS. The mounted credential is **SSH-only**, so to
push, `origin` must be the `git@github.com:` form. Today that rewrite is
delegated to the *agent* (executor methodology R4). The F7/F10 dogfood
(task `mzAuVTCxhhAQ8CChfnyCA`) proved the agent does not reliably do it
— it attempted token auth over HTTPS and failed; the delivery gate then
correctly failed the task. Credentials are present and valid; the gap is
that a **durable, deterministic step is delegated to the LLM** — the
exact anti-pattern F7/F10 exists to remove.

## Goal / non-goal

- **Goal:** the controller deterministically makes `origin` pushable
  with the mounted SSH credential, so a well-behaved agent's `git push`
  (and therefore the delivery gate) can succeed without the agent having
  to know to rewrite the remote.
- **Non-goal (scope fence, executor R6):**
  - Git **commit identity** (`user.email`/`user.name`). The dogfood
    agent committed fine (`480214c`); identity is not the proven defect.
    Out of scope — do not touch.
  - Non-GitHub hosts. The SSH wiring + key are GitHub-specific; a
    GitLab/other `repo_url` is left as-is (documented, not silently
    "handled").
  - The controller does **not** push. The agent still does the work and
    the push; we only make `origin` correct.

## Design

A pure, heavily-unit-tested URL transform plus a conditional, idempotent
application step in the component that already owns the clone.

### Pure helper — `https_github_to_ssh(url) -> str | None`

`https://github.com/<owner>/<repo>` (optional `.git`, optional trailing
`/`) ⇒ `git@github.com:<owner>/<repo>.git`. Anything else (already SSH,
`ssh://`, non-github host, unparseable) ⇒ `None`. No I/O — table-driven
unit tests, including negatives.

### Application — in `_ensure_repo_cloned`

After a successful clone **and** in the already-cloned no-op branch
(rework reuses a persisted workdir), call a normaliser:

```
ssh_url = https_github_to_ssh(repo.url)
if ssh_url is not None and <ssh key present at ~/.ssh/id_ed25519>:
    git -C <workdir> remote set-url origin <ssh_url>
```

- **Conditional on key presence** so local/dev/CI without the mounted
  key is unaffected (V16 — existing callers/tests don't regress;
  `git clone` itself is unchanged).
- **Idempotent** (`remote set-url` + applied in both paths) so rework
  runs converge regardless of entry path.
- Key path is an injectable attribute (default `~/.ssh/id_ed25519`) so
  the integration test can point it at a tmp file.
- Failure to rewrite is logged loudly but **non-fatal** to the clone
  itself — the delivery gate is the ultimate backstop (a bad rewrite ⇒
  push fails ⇒ gate fails ⇒ honest task failure, never a silent ghost).

## Files touched (scope fence)

- `src/controller/invoker.py` — add `https_github_to_ssh` (module
  function) + `_normalize_origin_for_push`; call it from
  `_ensure_repo_cloned` (post-clone + already-cloned branch). Inject SSH
  key path as a defaulted attribute.
- `tests/test_invoker.py` — unit (helper table incl. negatives) +
  hermetic real-git integration (origin rewritten iff key present;
  non-github left alone).
- `docs/INDEX.md` — link this doc.

Nothing else.

## Test plan (TDD red first, pyramid)

- **Unit:** `https_github_to_ssh` — `.git`/no-`.git`/trailing slash,
  already-ssh ⇒ None, `ssh://` ⇒ None, gitlab/non-github ⇒ None,
  garbage ⇒ None.
- **Integration (hermetic, real git):** clone a local bare "origin"
  whose URL is the https form (simulated via a mapping is unnecessary —
  assert on the helper for URL logic; for the apply step, init a repo
  with an `https://github.com/...` origin, run `_normalize_origin_for_push`
  with the key-path attr pointing at (a) an existing tmp file ⇒ origin
  becomes `git@github.com:...`; (b) a missing path ⇒ origin unchanged).
  Non-github origin ⇒ unchanged regardless of key.
- **Scenario / dogfood:** after deploy, re-fire Exp#3 — expect a **green
  delivery**: agent pushes `vafi/task-<id>`, delivery gate passes, task
  `done`; verified against `vilosource/vtf-canary` ground truth (real
  branch present). The negative (no push) is already covered by the
  F7/F10 dogfood.

## Why this is the right layer

Same stance as F7/F10: the system guarantees the durable step instead of
trusting the LLM. It pairs with the delivery gate — the gate verifies
the deliverable reached origin; this ensures a correct agent *can* get
it there deterministically. Both sit at controller seams, are hermetic-
git testable with the harness already in the repo, and degrade safely
(the gate remains the backstop if the rewrite is ever wrong).
