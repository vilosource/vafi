# Phase 0: Create Harness Scripts

**Goal:** Write init.sh, connect.sh, run.sh for Claude and Pi images. Additive only — nothing calls them yet.
**Design reference:** Layer 1: Harness Image Contract (init.sh, connect.sh, run.sh sections)
**Protocol:** See WORK-PROTOCOL.md

## Files Created

```
images/claude/init.sh       — Claude config setup
images/claude/connect.sh    — Claude interactive start
images/claude/run.sh        — Claude headless invocation
images/pi/init.sh           — Pi config setup
images/pi/connect.sh        — Pi interactive start
images/pi/run.sh            — Pi headless invocation
```

## Files Modified

```
images/claude/Dockerfile    — COPY + chmod for 3 scripts to /opt/vf-harness/
images/pi/Dockerfile        — COPY + chmod for 3 scripts to /opt/vf-harness/
```

## Script Content

Copy exactly from the design doc "Example: Claude Image" and "Example: Pi Image" sections. Do not improvise. Do not add features.

Key points from the design:
- `init.sh` uses `set -e` — failure prevents pod readiness
- `connect.sh` reads WORKDIR from `/tmp/ready` sentinel
- `run.sh` reads prompt from `$1` or `$VF_PROMPT` env var
- `run.sh` wraps with cxtx if `$VF_CXDB_URL` is set
- Claude `init.sh` copies methodology to `~/.claude/CLAUDE.md` based on `$VF_AGENT_ROLE`
- Pi `run.sh` passes `--append-system-prompt` based on `$VF_AGENT_ROLE`
- All scripts must be executable (`chmod +x`)

## TDD Sequence

RED:
```python
# tests/test_harness_scripts.py
class TestHarnessScripts:
    def test_claude_init_exists(self):
        """init.sh exists at /opt/vf-harness/ in Claude image."""
        # Run: docker run --rm --entrypoint test vafi/vafi-agent:latest -x /opt/vf-harness/init.sh
        
    def test_claude_connect_exists(self):
        """connect.sh exists at /opt/vf-harness/ in Claude image."""

    def test_claude_run_exists(self):
        """run.sh exists at /opt/vf-harness/ in Claude image."""

    def test_pi_init_exists(self):
        """init.sh exists at /opt/vf-harness/ in Pi image."""

    def test_pi_connect_exists(self):
        """connect.sh exists at /opt/vf-harness/ in Pi image."""

    def test_pi_run_exists(self):
        """run.sh exists at /opt/vf-harness/ in Pi image."""

    def test_scripts_are_executable(self):
        """All scripts have execute permission."""
```

These tests can be implemented as subprocess calls to `docker run --rm --entrypoint test <image> -x /opt/vf-harness/<script>.sh`.

GREEN: Create the scripts per design, update Dockerfiles.

## E2E After Deploy

Build both images, push to harbor with commit hash tags. Do NOT deploy yet (entrypoint doesn't call them yet).

Verify:
- `docker run --rm --entrypoint cat <image> /opt/vf-harness/init.sh` — script content matches design
- Existing E2E tests still pass (scripts are additive, nothing uses them)

## Gate Checklist

- [ ] All 6 scripts exist in the correct images
- [ ] All scripts are executable
- [ ] Script content matches design document exactly
- [ ] Dockerfiles updated with COPY + chmod
- [ ] Images built and pushed with commit hash tags
- [ ] Existing E2E tests pass (no regression)
- [ ] No source code outside images/ was modified

## Done When

Both images have `/opt/vf-harness/{init,connect,run}.sh`. Nothing calls them yet. Existing behavior unchanged.
