# Phase 5: Controller — run.sh

**Goal:** Controller invoker calls `/opt/vf-harness/run.sh` instead of building harness-specific commands. Output format selection from config.
**Design reference:** Layer 3: Services → vafi controller
**Protocol:** See WORK-PROTOCOL.md
**Depends on:** Phase 0 (images have run.sh), Phase 2 (entrypoint calls init.sh)

## Files Modified (vafi repo)

```
src/controller/invoker.py   — replace _build_claude_command/_build_pi_command with run.sh
src/controller/config.py    — add output_format field
tests/test_invoker.py       — update tests for run.sh
```

## Invoker Changes

From design doc:
```python
async def _run_harness(self, prompt, workdir, task_id):
    env = dict(os.environ)
    env["VF_PROMPT"] = prompt
    env["VF_TASK_ID"] = task_id
    if self.config.max_turns > 0:
        env["VF_MAX_TURNS"] = str(self.config.max_turns)
    if self.config.cxdb_url:
        env["VF_CXDB_URL"] = self.config.cxdb_url

    cmd = ["/opt/vf-harness/run.sh"]
    process = await asyncio.create_subprocess_exec(*cmd, cwd=str(workdir), env=env, ...)
```

**Delete:** `_build_claude_command()`, `_build_pi_command()`
**Keep:** `_parse_claude_output()`, `_parse_pi_output()` — output parsing is per-format, selected by config

## Config Changes

```python
@dataclass
class AgentConfig:
    output_format: str = "claude_json"  # or "pi_jsonl"
```

Read from `VF_OUTPUT_FORMAT` env var. The harness's `output_format` from harnesses.yaml is set as a pod env var.

Parser selection:
```python
PARSERS = {
    "claude_json": self._parse_claude_output,
    "pi_jsonl": self._parse_pi_output,
}
parser = PARSERS.get(self.config.output_format, self._parse_claude_output)
```

## TDD Sequence

RED:
```python
# tests/test_invoker.py
class TestHarnessInvoker:
    def test_command_is_run_sh(self):
        """Harness command is /opt/vf-harness/run.sh, not claude or pi."""

    def test_prompt_in_env(self):
        """VF_PROMPT env var contains the prompt text."""

    def test_max_turns_in_env(self):
        """VF_MAX_TURNS env var set when max_turns > 0."""

    def test_cxdb_url_in_env(self):
        """VF_CXDB_URL env var set when cxdb configured."""

    def test_no_harness_names_in_command(self):
        """Command list does not contain 'claude' or 'pi'."""

    def test_output_format_selects_parser(self):
        """output_format='pi_jsonl' uses Pi parser."""

    def test_output_format_defaults_to_claude(self):
        """Default output_format uses Claude parser."""

    # Existing parse tests remain unchanged — they test the parsers themselves
```

GREEN: Rewrite _run_harness, delete _build_claude_command/_build_pi_command, add output_format to config.

## E2E After Deploy

Build both agent images (run.sh is now called by the invoker). Push and deploy Pi executor.

Verify:
- AC-4: Submit a task to vtf-dev. Pi executor claims it, invokes via run.sh, passes gates, completes.
- Check logs: command is `/opt/vf-harness/run.sh`, not `pi -p ...`
- cxdb trace exists (run.sh wraps with cxtx)

## Gate Checklist

- [ ] invoker.py has zero occurrences of "claude" or "pi" in command building (parser registry names are OK)
- [ ] `_build_claude_command` and `_build_pi_command` deleted
- [ ] `_run_harness` calls `/opt/vf-harness/run.sh`
- [ ] Prompt, max_turns, cxdb_url passed via env vars
- [ ] output_format selects correct parser
- [ ] AC-4 passes (task execution via run.sh)
- [ ] Existing invoker unit tests updated and pass
- [ ] Existing E2E tests pass

## Done When

Invoker is harness-agnostic. One `_run_harness` method. No harness-specific command building.
