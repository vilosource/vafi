# Phase 4: Console — PodSpecBuilder

**Goal:** Pod specs built from config (harnesses.yaml + roles.yaml + infra.yaml), not hardcoded values. Zero hardcoded env vars, secrets, or paths in manager.py.
**Design reference:** Layer 3: Services → Pod Spec Assembly
**Protocol:** See WORK-PROTOCOL.md
**Depends on:** Phase 1 (config loaded), Phase 3 (console uses connect.sh)

## Files Created (vafi-console repo)

```
src/vafi_console/pods/spec_builder.py   — config-driven pod spec assembly
```

## Files Modified (vafi-console repo)

```
src/vafi_console/pods/manager.py    — delegates spec building to PodSpecBuilder
src/vafi_console/api/pods.py        — accepts harness parameter in launch request
src/vafi_console/main.py            — wire PodSpecBuilder with loaded config
```

## PodSpecBuilder Design

From the design doc "Pod Spec Assembly" section:
```python
class PodSpecBuilder:
    def __init__(self, harness_registry, infra_config):
        ...

    def build(self, harness_name, role_config, project, user, **context):
        env = []
        env.extend(self._infra_env(context))
        env.extend(self._secret_env(harness))
        env.extend(self._role_env(role_config))
        env.extend(self._context_env(project, context))
        ...
```

Each method reads from config objects. No hardcoded values.

## API Changes

`POST /api/pods` accepts optional `harness` field:
```python
class LaunchRequest(BaseModel):
    role: str
    project: str
    harness: str | None = None  # defaults to role's default_harness
```

Validation: harness must be in role's `allowed_harnesses`.

## TDD Sequence

RED:
```python
# tests/test_spec_builder.py (in vafi-console)
class TestPodSpecBuilder:
    def test_uses_harness_image(self):
        """Pod spec uses image from harnesses.yaml, not hardcoded."""

    def test_claude_secret_mapping(self):
        """Claude gets ANTHROPIC_AUTH_TOKEN from vafi-secrets.anthropic-auth-token."""

    def test_pi_secret_mapping(self):
        """Pi gets ANTHROPIC_API_KEY from vafi-secrets.anthropic-auth-token (different env name)."""

    def test_role_env_injected(self):
        """VF_AGENT_ROLE from roles.yaml env dict."""

    def test_infra_volumes(self):
        """Mount paths from infra.yaml (home, sessions, ssh)."""

    def test_readiness_probe_from_config(self):
        """Readiness probe command from infra.yaml."""

    def test_no_hardcoded_env(self):
        """spec_builder.py contains zero 'ANTHROPIC' or 'vafi-secrets' strings."""

class TestLaunchAPI:
    def test_launch_with_harness(self):
        """POST /api/pods with harness=pi uses Pi image."""

    def test_launch_default_harness(self):
        """POST /api/pods without harness uses role's default."""

    def test_launch_invalid_harness(self):
        """POST /api/pods with harness not in allowed list returns 400."""
```

GREEN: Implement PodSpecBuilder, update manager, update pods API.

## E2E After Deploy

Build console, push, deploy.

Verify:
- Launch architect with Pi → pod uses vafi-agent-pi image, has ANTHROPIC_API_KEY (not ANTHROPIC_AUTH_TOKEN)
- Launch architect with Claude → pod uses vafi-agent image, has ANTHROPIC_AUTH_TOKEN
- Pod env vars match harnesses.yaml mapping
- Existing E2E tests pass

## Gate Checklist

- [ ] spec_builder.py has zero hardcoded env var names
- [ ] manager.py has zero hardcoded secret names or mount paths
- [ ] Pod specs use correct image per harness
- [ ] Secret-to-env mapping works (Claude vs Pi use different env var names)
- [ ] Launch API accepts harness parameter
- [ ] Invalid harness rejected with 400
- [ ] AC-1, AC-2, AC-3 pass
- [ ] Existing E2E tests pass

## Done When

manager.py has zero hardcoded env vars, secret names, or paths. Everything comes from config.
