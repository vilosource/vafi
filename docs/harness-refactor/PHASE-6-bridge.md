# Phase 6: Bridge — Config-Driven Pods

**Goal:** Bridge creates pods from config, not hardcoded specs. Ephemeral path uses run.sh.
**Design reference:** Layer 3: Services → vafi bridge
**Protocol:** See WORK-PROTOCOL.md
**Depends on:** Phase 1 (config loaded), Phase 5 (run.sh works)

## Files Modified (vafi repo)

```
src/bridge/pod_process.py    — use config for pod specs, not hardcoded values
src/bridge/pi_session.py     — ephemeral calls /opt/vf-harness/run.sh
src/bridge/app.py            — load harness config, pass to pod/session managers
```

## Pod Process Changes

`PodProcessManager.build_pod_spec()` reads from config:
- Image from harness config
- Env vars from harness secret mapping + role env + infra shared_env
- Volumes from infra config
- No hardcoded `ANTHROPIC_API_KEY`, `models.json` heredoc, or mount paths

`build_exec_command()` in pod_process.py: for locked sessions, exec `/opt/vf-harness/connect.sh` (not `pi --mode rpc` with heredoc).

Note: locked sessions currently use Pi's `--mode rpc` for persistent conversation. The connect.sh approach works differently — it starts an interactive session, not an RPC session. For locked sessions, the bridge may need to use `run.sh` per prompt (one-shot per request) or a future `serve.sh` for RPC. This is a design limitation acknowledged in the design doc (`supports_rpc` field). For now, locked Pi sessions can use connect.sh with k8s exec stdin/stdout relay (same as console terminal).

## Ephemeral Changes

`PiSession.run_ephemeral()` calls `/opt/vf-harness/run.sh` with `VF_PROMPT` env var instead of constructing Pi-specific command.

## TDD Sequence

RED:
```python
# tests/bridge/test_pod_process.py
class TestPodProcessManager:
    def test_pod_spec_image_from_config(self):
        """Pod image comes from harness config, not hardcoded."""

    def test_pod_spec_no_hardcoded_env(self):
        """No 'ANTHROPIC' or 'vafi-secrets' strings in pod_process.py."""

    def test_exec_command_uses_connect_sh(self):
        """Exec command is /opt/vf-harness/connect.sh."""

# tests/bridge/test_pi_session.py
class TestPiSession:
    def test_ephemeral_uses_run_sh(self):
        """Ephemeral command is /opt/vf-harness/run.sh."""

    def test_prompt_passed_via_env(self):
        """VF_PROMPT env var contains the prompt."""
```

GREEN: Update pod_process.py, pi_session.py, app.py.

## E2E After Deploy

Build bridge, push, deploy.

Verify:
- AC-5: Send ephemeral prompt → bridge calls run.sh → response returned
- AC-6: Acquire lock → pod created from config → prompt works → release
- Existing bridge E2E tests pass

## Gate Checklist

- [ ] pod_process.py has zero hardcoded env vars or secret names
- [ ] pi_session.py calls run.sh, not `pi -p ...`
- [ ] Pod specs use image from harness config
- [ ] AC-5 passes (ephemeral via run.sh)
- [ ] AC-6 passes (locked with config-driven pod)
- [ ] Existing bridge E2E tests pass

## Done When

Bridge is harness-agnostic. Pod specs from config. Ephemeral uses run.sh. Locked uses connect.sh.
