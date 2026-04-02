# Phase 1: Config Restructure

**Goal:** Create harnesses.yaml, roles.yaml, infra.yaml. Deploy as shared ConfigMap. Services load them.
**Design reference:** Layer 2: Configuration (all three yaml sections)
**Protocol:** See WORK-PROTOCOL.md
**Depends on:** Phase 0 (images have scripts)

## Files Created

```
config/harnesses.yaml     — harness definitions (image, secrets, output_format)
config/roles.yaml         — role definitions (allowed_harnesses, default, env, resources)
config/infra.yaml         — shared infra (paths, volumes, SSH, readiness, shared_env)
```

## Files Modified

```
vafi-console: src/vafi_console/pods/models.py       — HarnessConfig, InfraConfig dataclasses
vafi-console: src/vafi_console/pods/config_loader.py — new, loads all 3 yaml files
vafi-console: src/vafi_console/main.py               — load config on startup, validate
vafi: src/bridge/config_loader.py                    — same schema parser for bridge
```

## Config Content

Copy yaml content exactly from the design doc sections. Key details:

- `harnesses.yaml`: Claude maps `anthropic-auth-token` → `ANTHROPIC_AUTH_TOKEN`. Pi maps same key → `ANTHROPIC_API_KEY`. This is the reason the mapping must be per-harness.
- `roles.yaml`: `allowed_harnesses` is a list. `default_harness` must be in that list (validated).
- `infra.yaml`: `shared_env` are literal values. `template_env` use `{{ variable }}` syntax resolved at pod creation time from Settings.

## TDD Sequence

RED:
```python
# tests/test_config_loader.py (in vafi-console)
class TestConfigLoader:
    def test_load_harnesses(self, tmp_path):
        """Parses harnesses.yaml into HarnessConfig objects."""

    def test_harness_has_image(self, tmp_path):
        """Each harness has a non-empty image field."""

    def test_harness_secret_env_map(self, tmp_path):
        """Claude maps anthropic-auth-token to ANTHROPIC_AUTH_TOKEN."""
        """Pi maps anthropic-auth-token to ANTHROPIC_API_KEY."""

    def test_load_roles(self, tmp_path):
        """Parses roles.yaml into RoleConfig objects with allowed_harnesses."""

    def test_role_references_valid_harness(self, tmp_path):
        """Validation passes when all harness refs exist."""

    def test_role_references_invalid_harness(self, tmp_path):
        """Validation fails when role references nonexistent harness."""

    def test_load_infra(self, tmp_path):
        """Parses infra.yaml into InfraConfig."""

    def test_infra_has_paths(self, tmp_path):
        """InfraConfig has home_path, sessions_path, ssh_mount_path."""
```

GREEN: Implement config loader module, dataclasses. Create yaml files.

## E2E After Deploy

Create ConfigMap:
```bash
kubectl create configmap vafi-config -n vafi-dev \
  --from-file=harnesses.yaml=config/harnesses.yaml \
  --from-file=roles.yaml=config/roles.yaml \
  --from-file=infra.yaml=config/infra.yaml
```

Mount in console and bridge deployments at `/app/config/`.

Verify:
- Console starts and logs "Loaded N harnesses, M roles"
- Invalid config (manually break a harness ref) → console refuses to start
- Existing E2E tests pass (config is loaded but not yet used for pod creation)

## Gate Checklist

- [ ] 3 yaml files created, content matches design
- [ ] Config loader parses all 3 files
- [ ] Validation rejects invalid config (AC-9)
- [ ] ConfigMap deployed in vafi-dev
- [ ] Console and bridge mount the ConfigMap
- [ ] Services start successfully with new config
- [ ] Existing E2E tests pass
- [ ] No harness names in config_loader source code

## Done When

Config loads, validates, is available to both services. Old config (roles.yaml) still used for pod creation — Phase 4 switches to the new config.
