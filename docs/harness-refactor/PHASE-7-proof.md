# Phase 7: Proof — Zero-Code Harness Addition

**Goal:** Add a "bash-only" test harness with ZERO source code changes. This is the acid test of the design. If any source file needs modification, the design has failed.
**Design reference:** "Adding a New Harness" section
**Protocol:** See WORK-PROTOCOL.md
**Depends on:** All previous phases (0-6)

## Constraint

**Only these types of changes are allowed:**
- New files in `images/bash-agent/` (Dockerfile, init.sh, connect.sh, run.sh)
- Config changes in `config/harnesses.yaml` and `config/roles.yaml`
- k8s ConfigMap update

**NOT allowed:**
- Any modification to existing .py files
- Any modification to entrypoint.sh
- Any modification to proxy.py, manager.py, invoker.py, app.py
- Any modification to validation.py, config.py, terminal.py

## Files Created

```
images/bash-agent/Dockerfile    — FROM vafi-base, no AI CLI
images/bash-agent/init.sh       — no-op (echo "bash-agent harness ready")
images/bash-agent/connect.sh    — exec bash (interactive shell)
images/bash-agent/run.sh        — eval "$VF_PROMPT" (execute prompt as shell command)
```

## Config Changes

`config/harnesses.yaml` — add:
```yaml
  bash-agent:
    image: harbor.viloforge.com/vafi/vafi-bash-agent:<hash>
    description: Bash-only test harness (no AI CLI)
    output_format: raw_text
    secrets: []
```

`config/roles.yaml` — add bash-agent to architect's allowed list:
```yaml
  architect:
    allowed_harnesses: [pi, claude, bash-agent]
```

## Script Content

**init.sh:**
```bash
#!/bin/bash
set -e
echo "bash-agent harness ready"
```

**connect.sh:**
```bash
#!/bin/bash
WORKDIR=$(cat /tmp/ready 2>/dev/null || echo /home/agent)
cd "$WORKDIR"
exec bash
```

**run.sh:**
```bash
#!/bin/bash
set -e
PROMPT="${1:-$VF_PROMPT}"
eval "$PROMPT"
```

## Verification Procedure

1. Build the image:
```bash
docker build -f images/bash-agent/Dockerfile -t harbor.viloforge.com/vafi/vafi-bash-agent:<hash> .
docker push harbor.viloforge.com/vafi/vafi-bash-agent:<hash>
```

2. Update ConfigMap:
```bash
kubectl create configmap vafi-config -n vafi-dev --from-file=... --dry-run=client -o yaml | kubectl apply -f -
```

3. Restart console and bridge to pick up new config.

4. **Verify git diff shows zero .py file changes:**
```bash
git diff --name-only | grep '\.py$'
# Must output: (nothing)
```

5. Launch bash-agent architect from console → terminal opens bash shell
6. Send prompt via bridge ephemeral → `eval` runs the command, output returned

## TDD Sequence

RED:
```python
# tests/test_zero_code_proof.py
class TestZeroCodeProof:
    def test_no_python_files_modified(self):
        """After adding bash-agent, no .py files were modified."""
        import subprocess
        result = subprocess.run(["git", "diff", "--name-only"], capture_output=True, text=True)
        py_files = [f for f in result.stdout.strip().split("\n") if f.endswith(".py")]
        assert py_files == [], f"Python files modified: {py_files}"

    def test_bash_agent_in_harness_config(self):
        """bash-agent appears in loaded harness registry."""

    def test_bash_agent_in_role_allowed(self):
        """architect role allows bash-agent harness."""
```

GREEN: Already green — the point is that NO code changes are needed.

## E2E After Deploy

- AC-7: Launch architect with `harness=bash-agent` from console → bash shell opens
- AC-7: Send `POST /v1/prompt` with `role=assistant, harness=bash-agent` → command executed
- Verify: `git diff --name-only | grep '\.py$'` returns empty

## Gate Checklist

- [ ] Zero .py files modified (git diff)
- [ ] bash-agent image built and pushed
- [ ] ConfigMap updated with new harness
- [ ] Console launches bash-agent architect successfully
- [ ] Bridge ephemeral prompt works with bash-agent
- [ ] All existing E2E tests still pass (AC-1 through AC-6)
- [ ] AC-7 passes

## Done When

A third harness works end-to-end. The git diff shows only new files in `images/bash-agent/` and config changes. Zero source code modifications.

**If this phase requires ANY source code change, STOP. The design has a gap. Fix the design first.**
