# Phase 2: Entrypoint Refactor

**Goal:** Entrypoint sources `/opt/vf-harness/init.sh` instead of having Claude/Pi branches. Zero harness names in the entrypoint.
**Design reference:** Layer 3: Services → Shared Entrypoint
**Protocol:** See WORK-PROTOCOL.md
**Depends on:** Phase 0 (images have init.sh)

## Files Modified

```
images/agent/entrypoint.sh   — rewrite per design, source init.sh, no harness branching
```

## Entrypoint Content

Copy exactly from design doc "Shared Entrypoint" section. Key points:

- `source /opt/vf-harness/init.sh` — not `bash init.sh` (source runs in same shell, shares env)
- Guard with `[ -f /opt/vf-harness/init.sh ]` — safe if script missing (shouldn't happen but defensive)
- Autonomous mode: `export VF_PROMPT="$VF_ARCHITECT_PROMPT" && exec /opt/vf-harness/run.sh`
- No `if HARNESS`, no `.claude.json`, no `models.json`, no `if pi`
- Role routing (architect vs executor) stays — that's role behavior, not harness behavior

## TDD Sequence

RED:
```python
# tests/test_entrypoint.py
class TestEntrypoint:
    def test_no_harness_names(self):
        """entrypoint.sh contains zero occurrences of 'claude' or 'pi'."""
        with open("images/agent/entrypoint.sh") as f:
            content = f.read()
        assert "claude" not in content.lower()
        assert content.count('"pi"') == 0
        # Allow 'pi' in comments or paths like /opt/vf-harness but not as harness name

    def test_sources_init_sh(self):
        """entrypoint.sh sources /opt/vf-harness/init.sh."""
        with open("images/agent/entrypoint.sh") as f:
            content = f.read()
        assert "/opt/vf-harness/init.sh" in content

    def test_autonomous_uses_run_sh(self):
        """entrypoint.sh calls /opt/vf-harness/run.sh for autonomous mode."""
        with open("images/agent/entrypoint.sh") as f:
            content = f.read()
        assert "/opt/vf-harness/run.sh" in content
```

GREEN: Rewrite entrypoint per design.

## E2E After Deploy

Build both agent images with new entrypoint:
```bash
docker build --build-arg HARNESS_IMAGE=vafi/vafi-claude:latest -t vafi/vafi-agent:latest ...
docker build --build-arg HARNESS_IMAGE=vafi/vafi-pi:latest -t vafi/vafi-agent-pi:latest ...
```

Push and deploy. Verify:

1. **Pi executor pod starts correctly:**
   - `kubectl logs <pi-executor>` shows "Pi config files written" (from Pi's init.sh)
   - Pod is Running, controller registers with vtf

2. **Claude executor pod starts correctly** (if deployed):
   - Logs show ".claude.json written" (from Claude's init.sh)

3. **Architect pod starts correctly:**
   - Launch via console → pod starts, `/tmp/ready` written
   - init.sh ran (check for config files in pod)

4. Existing E2E tests pass

## Gate Checklist

- [ ] entrypoint.sh has zero occurrences of "claude" or "pi"
- [ ] entrypoint.sh sources /opt/vf-harness/init.sh
- [ ] entrypoint.sh uses /opt/vf-harness/run.sh for autonomous mode
- [ ] Pi executor pod starts and registers
- [ ] Claude agent image builds and starts (if tested)
- [ ] Existing E2E tests pass
- [ ] Commit message describes the entrypoint rewrite

## Done When

Entrypoint is harness-agnostic. Pods start via init.sh. Zero harness names in the file.
