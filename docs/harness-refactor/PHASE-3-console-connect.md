# Phase 3: Console — connect.sh

**Goal:** `build_exec_command` calls `/opt/vf-harness/connect.sh` for all harnesses. Remove all harness branching from the console terminal path.
**Design reference:** Layer 3: Services → vafi-console (terminal/proxy.py section)
**Protocol:** See WORK-PROTOCOL.md
**Depends on:** Phase 0 (images have connect.sh), Phase 2 (entrypoint calls init.sh)

## Files Modified (vafi-console repo)

```
src/vafi_console/terminal/proxy.py        — replace build_exec_command with generic connect.sh call
src/vafi_console/terminal/validation.py   — remove hardcoded ALLOWED_COMMANDS, accept injected set
src/vafi_console/api/terminal.py          — remove default="claude", use role default_harness
src/vafi_console/config.py                — remove allowed_commands tuple
```

## Proxy Changes

`build_exec_command` becomes (from design):
```python
def build_exec_command(command: str, workdir: str = "") -> list[str]:
    if command == "bash":
        if workdir:
            return ["/bin/bash", "-c", f"cd {workdir} && exec bash"]
        return ["/bin/bash"]
    return ["/opt/vf-harness/connect.sh"]
```

Three lines. No harness names. The connect.sh in the container handles everything.

## Validation Changes

```python
def validate_command(command: str, allowed_commands: frozenset[str]) -> str:
    if command not in allowed_commands:
        raise ValueError(f"Command '{command}' not allowed.")
    return command
```

`allowed_commands` is injected by the caller, derived from loaded harness config + "bash".

## Terminal API Changes

```python
command: str = Query(default=None)  # None = use role's default_harness
```

If `command` is None, look up the pod's role, get `default_harness` from role config.

## TDD Sequence

RED:
```python
# tests/test_proxy.py (in vafi-console)
class TestBuildExecCommand:
    def test_bash_returns_bash(self):
        cmd = build_exec_command("bash")
        assert cmd == ["/bin/bash"]

    def test_any_harness_returns_connect_sh(self):
        cmd = build_exec_command("pi")
        assert cmd == ["/opt/vf-harness/connect.sh"]

    def test_another_harness_returns_connect_sh(self):
        cmd = build_exec_command("claude")
        assert cmd == ["/opt/vf-harness/connect.sh"]

    def test_unknown_harness_returns_connect_sh(self):
        """Even unknown harness names go to connect.sh — validation is separate."""
        cmd = build_exec_command("aider")
        assert cmd == ["/opt/vf-harness/connect.sh"]

    def test_no_harness_names_in_proxy(self):
        """proxy.py contains zero harness-specific branching."""
        import inspect
        source = inspect.getsource(build_exec_command)
        assert "claude" not in source.lower()
        # 'pi' may appear in '/opt/vf-harness' path but not as a condition

class TestValidation:
    def test_validate_against_injected_set(self):
        allowed = frozenset({"claude", "pi", "bash"})
        assert validate_command("pi", allowed) == "pi"

    def test_rejects_unknown(self):
        allowed = frozenset({"claude", "bash"})
        with pytest.raises(ValueError):
            validate_command("aider", allowed)
```

GREEN: Update proxy.py, validation.py, terminal.py, config.py.

## E2E After Deploy

Build console, push, deploy.

Verify:
- AC-1: Launch Claude architect from web UI → Claude starts via connect.sh
- AC-2: Launch Pi architect from web UI → Pi starts via connect.sh
- AC-3: Launch without harness param → uses role's default

Test by connecting to vafi-console web UI at console.dev.viloforge.com and launching an architect session.

## Gate Checklist

- [ ] proxy.py has zero occurrences of "claude" or "pi" (except in path `/opt/vf-harness/`)
- [ ] validation.py has no hardcoded ALLOWED_COMMANDS frozenset
- [ ] terminal.py has no `default="claude"`
- [ ] config.py has no `allowed_commands`
- [ ] AC-1 passes (Claude architect via console)
- [ ] AC-2 passes (Pi architect via console)
- [ ] AC-3 passes (default harness selection)
- [ ] Existing E2E tests pass

## Done When

Console terminal path is harness-agnostic. All harnesses use connect.sh. Both Claude and Pi architects work.
