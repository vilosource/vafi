> **Archived**: This document is historical. For current architecture, see [ARCHITECTURE-SUMMARY.md](../ARCHITECTURE-SUMMARY.md) and [harness-images-ARCHITECTURE.md](../harness-images-ARCHITECTURE.md).

# K8s Harness Spikes — Analysis

Reference document for anyone working on the vafi controller or deploying agents to Kubernetes. Covers all spike findings from the k8s harness validation session.

---

## Spike 1: Claude Code Auth in Pods

**Goal**: Confirm agents can authenticate to Claude Code inside a pod without per-session OAuth tokens.

**Findings**:
- z.ai API key works via env vars: `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL`
- No Anthropic API key or OAuth token copying required
- Config-dir auth (copying `~/.claude/`) is fragile — tokens expire, not viable for overnight runs
- `vf-agents` already validates this pattern via `settings-json` auth type

**Secrets**:
- k8s Secret `vafi-secrets` in namespace `vafi-agents`
  - `anthropic-auth-token` — z.ai API key
  - `anthropic-base-url` — z.ai base URL
  - `vtf-token` — vtaskforge auth token

---

## Spike 2: Git Clone from Pods

**Goal**: Confirm pods can clone private repos over SSH.

**Findings**:
- SSH keys mounted from k8s Secrets are symlinks owned by root — SSH refuses them (`bad permissions`)
- Solution: init container copies keys from secret volume to `emptyDir`, sets `chmod 600`
- No `chown` needed — init container runs as agent user (UID 1000), files are already owned correctly
- `StrictHostKeyChecking=no` written to SSH config in the `emptyDir`

**Secrets**:
- k8s Secret `github-ssh` in namespace `vafi-agents`
  - `ssh-privatekey`
  - `ssh-publickey`

**Pattern** (init container):
```yaml
initContainers:
  - name: ssh-setup
    image: busybox
    command: ["/bin/sh", "-c"]
    args:
      - cp /secrets/ssh/ssh-privatekey /ssh/id_ed25519;
        chmod 600 /ssh/id_ed25519;
        echo "Host *\n  StrictHostKeyChecking no" > /ssh/config
    volumeMounts:
      - name: ssh-secret
        mountPath: /secrets/ssh
      - name: ssh-dir
        mountPath: /ssh
volumes:
  - name: ssh-secret
    secret:
      secretName: github-ssh
  - name: ssh-dir
    emptyDir: {}
```

---

## Spike 3: Network Egress

**Goal**: Confirm pods can reach external services needed by agents.

**Findings**:
- Pods can reach: GitHub (SSH clone), PyPI (`pip install`), npm registry
- k3s has no restrictive egress policy by default — all outbound works
- PEP 668 restriction present in base image (Debian bookworm) — `pip install` to the system Python fails without `--break-system-packages` or a venv

---

## Spike 4: Image Build

**Goal**: Build a working vafi-agent image stack.

**Bugs Fixed**:
1. `COPY src/controller/` to `/opt/vf-agent/controller/` didn't match `pyproject.toml`'s `where = ["src"]` — fixed to `COPY src/` to `/opt/vf-agent/src/`
2. `pip install` without `--break-system-packages` fails on PEP 668

**Image Stack**:

| Image | Size | Role |
|-------|------|------|
| `vafi-base` | 364 MB | OS + system deps |
| `vafi-claude` | 470 MB | Claude Code installed |
| `vafi-agent` | 481 MB | vafi controller + agent entrypoint |

---

## Spike 5: Full Harness (Realistic Task)

**Goal**: Run a realistic coding task end-to-end inside a pod.

**Result**: Claude Code successfully read existing files, wrote a new test file, ran pytest, and committed — all inside a cloned repo in a pod.

**Metrics**: 19 turns, 108s, $0.19

**Gotchas found**:
- Claude sets up `PYTHONPATH` during its session but it does not persist for the gate command. The gate's `test_command` must include `PYTHONPATH` explicitly, or the task spec must account for it.
- `pytest` is not pre-installed in `vafi-claude`. Claude installed it during its work, but if the gate runs independently after the session ends, pytest may not be present. Consider pre-installing pytest in `vafi-base`.
- Git config (`user.name`, `user.email`) must be set before commits work. The controller or pod entrypoint should handle this automatically.

---

## Spike 6: Session Resume (`--resume`)

**Goal**: Test whether `--resume` works for rework tasks inside pods.

**Result**: Resume works when the same pod handles the rework. Claude had full context of previous work and added docstrings and tests without re-reading the codebase.

**Metrics**:
- Initial task: 3 turns, $0.026
- Rework with resume: 11 turns, $0.102
- Same `session_id` returned on resume

**Gotcha**:
- Session files live in `~/.claude/` inside the container — they persist only within the pod's lifetime
- If a different pod picks up the rework, `--resume` fails (no session files). Must fall back to fresh session + full spec + judge feedback
- **Rework tasks should be routed to the same agent/pod when possible**

---

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Auth method | z.ai API key via env vars | Permanent, no expiry, no token rotation |
| SSH key delivery | Init container + emptyDir + chmod | Secret symlinks are root-owned, SSH rejects them |
| Secret layout | `vafi-secrets` (auth + vtf token) + `github-ssh` | Separation of concerns |
| `--bare` mode | Deferred | No evidence of noise or performance issues |
| Test environment setup | Claude's responsibility (Option A) | No controller setup phase needed |
| Gate `test_command` | Must be fully self-contained | PYTHONPATH and other env vars don't persist across session boundary |

---

## Gotchas — Quick Reference

| # | Gotcha | Mitigation |
|---|--------|------------|
| 1 | SSH keys from k8s Secrets are symlinks owned by root | Copy to emptyDir via init container, chmod 600 |
| 2 | PEP 668 blocks system-wide pip install in Debian bookworm | Use `--break-system-packages` in Dockerfiles, or use venv |
| 3 | PYTHONPATH set by Claude doesn't persist for gate command | Gate `test_command` must set PYTHONPATH explicitly |
| 4 | pytest not pre-installed in `vafi-claude` image | Pre-install pytest (and common test deps) in `vafi-base` |
| 5 | Git `user.name`/`user.email` not configured in pods | Controller or entrypoint must set git config before launching agent |
| 6 | Session resume only works on same pod | Route rework tasks to the originating pod; fall back to fresh session if pod is gone |
| 7 | Claude Code writes to `~/.claude/` on startup | Config dir must be writable; `vf-agents` uses tmpfs for this |
