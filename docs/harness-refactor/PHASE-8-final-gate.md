# Phase 8: Final E2E Gate

**Goal:** All acceptance criteria verified against vafi-dev. Final grep check for harness names in source code.
**Protocol:** See WORK-PROTOCOL.md
**Depends on:** All previous phases (0-7)

## E2E Test Suite

Run all tests against vafi-dev:

| Test | AC | What |
|------|-----|------|
| `test_e2e_claude_architect_console` | AC-1 | Launch Claude architect via console, type prompt, get response, session resume on reconnect |
| `test_e2e_pi_architect_console` | AC-2 | Launch Pi architect via console, type prompt, get response |
| `test_e2e_harness_selection` | AC-3 | Default harness from roles.yaml. Explicit harness override. Invalid harness → 400. |
| `test_e2e_controller_task` | AC-4 | Submit task, Pi executor claims, runs via run.sh, passes gate, completes |
| `test_e2e_bridge_ephemeral` | AC-5 | POST /v1/prompt → run.sh → response with session_id |
| `test_e2e_bridge_locked` | AC-6 | POST /v1/lock → pod from config → prompt → release |
| `test_e2e_bash_agent_console` | AC-7 | bash-agent launches from console, no code changes |
| `test_e2e_bash_agent_bridge` | AC-7 | bash-agent prompt via bridge, no code changes |
| `test_e2e_all_unit_tests` | AC-8 | `pytest tests/` — all 250+ pass |
| `test_e2e_config_validation` | AC-9 | Break config → service refuses to start |

## Source Code Grep

Final verification that no harness names remain in source code:

```bash
# Console source
grep -rn '"claude"\|"pi"' ~/GitHub/vafi-console/src/ --include="*.py" | grep -v __pycache__ | grep -v test

# Controller + bridge source
grep -rn '"claude"\|"pi"' ~/GitHub/vafi/src/ --include="*.py" | grep -v __pycache__ | grep -v test

# Entrypoint
grep -in 'claude\|"pi"' ~/GitHub/vafi/images/agent/entrypoint.sh
```

**Allowed exceptions (data, not logic):**
- Output parser registry: `"claude_json": _parse_claude_output` — these are format identifiers, not harness branching
- Test fixtures: test files may reference harness names in test data

**Not allowed:**
- Any `if ... == "claude"` or `elif ... == "pi"` in source code
- Any hardcoded CLI flag like `--dangerously-skip-permissions` outside harness scripts

## Full Verification Checklist

### Acceptance Criteria
- [ ] AC-1: Claude architect via console works (interactive, session resume)
- [ ] AC-2: Pi architect via console works (interactive)
- [ ] AC-3: Harness selection works (default + explicit + invalid → 400)
- [ ] AC-4: Controller task via run.sh works (claim, execute, gate, complete)
- [ ] AC-5: Bridge ephemeral via run.sh works (prompt → response)
- [ ] AC-6: Bridge locked with config-driven pod works (lock → prompt → release)
- [ ] AC-7: bash-agent works with zero code changes (console + bridge)
- [ ] AC-8: All unit tests pass (250+)
- [ ] AC-9: Config validation rejects invalid config

### Code Quality
- [ ] Zero harness names in console source (grep)
- [ ] Zero harness names in controller/bridge source (grep, except parser registry)
- [ ] Zero harness names in entrypoint (grep)
- [ ] Zero hardcoded env vars in manager.py/pod_process.py (grep ANTHROPIC, vafi-secrets)
- [ ] Zero hardcoded mount paths in manager.py/pod_process.py

### Deployment
- [ ] All images tagged with commit hash, pushed to harbor
- [ ] ConfigMap deployed with harnesses.yaml + roles.yaml + infra.yaml
- [ ] Console deployed with new code
- [ ] Bridge deployed with new code
- [ ] Controller/executor deployed with new code
- [ ] All services running in vafi-dev

### Documentation
- [ ] harness-images-ARCHITECTURE.md updated to reflect new boundary
- [ ] ARCHITECTURE-SUMMARY.md updated with three-layer harness model
- [ ] Phase docs archived (work is done)

## Done When

All checklist items are checked. The refactor is complete. The system follows SOLID principles with clear boundaries between harness images, configuration, and services.
