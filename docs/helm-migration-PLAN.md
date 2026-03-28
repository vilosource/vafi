# vafi Helm Migration Plan

## Goal

Migrate vafi from Kustomize to Helm and separate viloforge-specific deployment config into a private repo. This makes the vafi repo public-ready — no credentials, no vendor-specific URLs, no deployment secrets.

## Current State

- **Deployment method**: Kustomize (`k8s/vafi-agents/kustomization.yaml`)
- **Components deployed**: executor-pool (Deployment), cxdb-server (StatefulSet), cxdb service + ingress, sessions PVC
- **Images**: 3-layer build (base → claude → agent), pushed to `harbor.viloforge.com/vafi/`
- **Secrets**: Created out-of-band via `scripts/create-secrets.sh` (z.ai API key, GitHub SSH, vtf token)
- **Viloforge-specific hardcoded values**: Harbor registry, `cxdb.viloforge.com` domains, `vtf-dev` API URL, Traefik annotations, cert-manager issuer
- **Known issue**: Kustomize `commonLabels` injects `app.kubernetes.io/version` into selectors, causing immutable selector errors on updates

## Target State

- **vafi repo (public)**: Helm chart at `charts/vafi/` with generic defaults. No viloforge URLs, no credentials, no domain names.
- **vafi-deploy repo (private)**: Viloforge-specific values, release script, secret management. Same pattern as `vtf-deploy/`.

## What Goes Where

| Item | vafi repo (public) | vafi-deploy repo (private) |
|------|-------------------|---------------------------|
| Helm chart templates | `charts/vafi/templates/` | - |
| Default values (generic) | `charts/vafi/values.yaml` | - |
| Dockerfiles | `images/base/`, `images/claude/`, `images/agent/` | - |
| Controller source | `src/`, `methodologies/`, `templates/` | - |
| Build scripts | `scripts/build-images.sh` (parameterized) | - |
| Environment values | - | `environments/dev.yaml`, `environments/prod.yaml` |
| Release script | - | `scripts/release.sh` |
| Secret creation | - | `scripts/create-secrets.sh` |
| Registry URLs | - | In environment values (`image.repository`) |
| Domain names | - | In environment values (`ingress.cxdbHost`) |
| API credentials | - | In environment values or out-of-band secrets |

## Design Decisions

### CXDB in the vafi chart

CXDB deploys alongside the executor and they share the namespace. Rather than a separate chart, CXDB is a toggleable component in the vafi chart (`cxdb.enabled: true`). This keeps the deployment atomic — one `helm upgrade` deploys everything.

If CXDB is later extracted to its own chart, the toggle makes that migration clean.

### Registry deployment

The `vafi-system/registry.yaml` (Docker registry:2) is cluster infrastructure, not part of the vafi application. It is NOT included in the Helm chart. It remains a one-time manual deployment or moves to a separate infrastructure repo.

### Secret management

The Helm chart generates `vafi-secrets` from values (like vtf's chart does). For production, operators can either:
- Put credentials in values files (simple, acceptable for private deploy repos)
- Create secrets out-of-band and set `existingSecret: vafi-secrets` to skip generation

The `github-ssh` secret is always created out-of-band (contains SSH private keys that should never be in values files). The chart references it but does not create it.

### Namespace

The chart deploys to whatever namespace Helm targets (`--namespace`). No namespace creation — the release script handles that.

---

## Phase 1: Create Helm Chart in vafi Repo

### Task 1.1: Chart scaffold

Create the base chart structure at `charts/vafi/`.

**Files:**
- `Chart.yaml` — chart name, version, description, appVersion
- `values.yaml` — all configurable values with generic defaults
- `templates/_helpers.tpl` — naming helpers, labels, selector labels, common env, secret name
- `templates/NOTES.txt` — post-install instructions

**values.yaml structure:**
```yaml
image:
  agent:
    repository: vafi-agent
    tag: latest
    pullPolicy: Always
  base:
    repository: vafi-base
    tag: latest
  cxdb:
    repository: cxdb
    tag: latest
    pullPolicy: Always

imagePullSecrets: []

executor:
  replicas: 1
  role: executor
  tags: "executor"
  agentId: ""              # empty = auto-generated
  pollInterval: 30
  taskTimeout: 600
  maxRework: 3
  maxTurns: 50
  heartbeatInterval: 300
  resources:
    requests: { memory: 256Mi, cpu: 100m }
    limits: { memory: 1Gi, cpu: 500m }
  readinessProbe:
    initialDelaySeconds: 30
    periodSeconds: 10
  livenessProbe:
    initialDelaySeconds: 60
    periodSeconds: 30

vtf:
  apiUrl: ""               # required — in-cluster vtf API URL
  # token comes from secret

cxdb:
  enabled: true
  publicUrl: ""            # external URL for trace links
  storage: 10Gi
  storageClassName: ""
  resources:
    requests: { memory: 256Mi, cpu: 100m }
    limits: { memory: 1Gi, cpu: 500m }

sessions:
  storage: 10Gi
  storageClassName: ""

ingress:
  enabled: false
  className: ""
  annotations: {}
  cxdbHost: ""
  tls:
    enabled: false
    secretName: cxdb-tls

certificate:
  enabled: false
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer

secrets:
  # If existingSecret is set, skip generating vafi-secrets
  existingSecret: ""
  anthropicAuthToken: ""
  anthropicBaseUrl: "https://api.anthropic.com"
  vtfToken: ""

sshSecret:
  # Name of pre-created secret containing ssh-privatekey and ssh-publickey
  name: github-ssh
```

### Task 1.2: Executor deployment template

Templatize the executor-pool deployment.

**File:** `templates/executor-deployment.yaml`

Converts `k8s/vafi-agents/executor-pool.yaml` into a Helm template. Key parameterizations:
- Image: `{{ .Values.image.agent.repository }}:{{ .Values.image.agent.tag }}`
- Init container image: `{{ .Values.image.base.repository }}:{{ .Values.image.base.tag }}`
- All env vars from values (poll interval, timeout, max rework, etc.)
- vtf API URL from `{{ .Values.vtf.apiUrl }}`
- CXDB URLs conditional on `{{ .Values.cxdb.enabled }}`
- Secret references use `{{ include "vafi.secretName" . }}`
- SSH secret name from `{{ .Values.sshSecret.name }}`
- Resource limits from values
- Probe timings from values
- Labels from `_helpers.tpl` (avoids the Kustomize commonLabels selector issue)

### Task 1.3: CXDB StatefulSet template

Templatize the cxdb-server StatefulSet, gated by `cxdb.enabled`.

**File:** `templates/cxdb-statefulset.yaml`

Wrapped in `{{- if .Values.cxdb.enabled }}`. Parameterizations:
- Image: `{{ .Values.image.cxdb.repository }}:{{ .Values.image.cxdb.tag }}`
- Storage size from `{{ .Values.cxdb.storage }}`
- Storage class from `{{ .Values.cxdb.storageClassName }}`
- Resource limits from values
- Labels from helpers (NOT from Kustomize commonLabels)

### Task 1.4: CXDB service and ingress templates

**Files:**
- `templates/cxdb-service.yaml` — ClusterIP service, gated by `cxdb.enabled`
- `templates/cxdb-ingress.yaml` — ingress, gated by `cxdb.enabled` AND `ingress.enabled`
- `templates/cxdb-certificate.yaml` — cert-manager Certificate, gated by `certificate.enabled`

Ingress parameterizations:
- Host from `{{ .Values.ingress.cxdbHost }}`
- IngressClassName from `{{ .Values.ingress.className }}`
- Annotations from `{{ .Values.ingress.annotations }}`
- TLS secret name from `{{ .Values.ingress.tls.secretName }}`

No viloforge domain names in defaults — empty strings that must be set in environment values.

### Task 1.5: Sessions PVC template

**File:** `templates/sessions-pvc.yaml`

Parameterizations:
- Storage size from `{{ .Values.sessions.storage }}`
- Storage class from `{{ .Values.sessions.storageClassName }}`

### Task 1.6: Secrets template

**File:** `templates/secret.yaml`

Gated by `{{ if not .Values.secrets.existingSecret }}` — if an existing secret is referenced, skip generation.

Generates `vafi-secrets` with:
- `anthropic-auth-token` from `{{ .Values.secrets.anthropicAuthToken }}`
- `anthropic-base-url` from `{{ .Values.secrets.anthropicBaseUrl }}`
- `vtf-token` from `{{ .Values.secrets.vtfToken }}`

The `github-ssh` secret is NOT generated — it's always pre-created out-of-band because it contains SSH private keys.

### Task 1.7: Helpers template

**File:** `templates/_helpers.tpl`

Helpers needed:
- `vafi.fullname` — release-aware name
- `vafi.labels` — standard Helm labels (chart, managed-by, instance, version)
- `vafi.selectorLabels` — component-specific selector labels (stable, no version)
- `vafi.secretName` — either `existingSecret` or generated name
- `vafi.commonEnv` — shared env vars referenced by executor (vtf URL, CXDB URL, timing, secrets)

Critical: selector labels must NOT include `app.kubernetes.io/version` — this was the Kustomize bug that caused immutable selector errors.

### Task 1.8: Verify chart renders correctly

Run `helm template` with default values and with viloforge-like overrides. Verify:
- All resources render without errors
- Labels are correct and stable (no version in selectors)
- Conditional resources (cxdb, ingress, certificate) toggle correctly
- Secret generation skips when `existingSecret` is set
- No viloforge-specific values in default rendering

---

## Phase 2: Create vafi-deploy Private Repo

### Task 2.1: Create repo structure

Create `~/GitHub/vafi-deploy/` with:
```
vafi-deploy/
  README.md
  environments/
    dev.yaml
    prod.yaml
  scripts/
    release.sh
    create-secrets.sh
```

### Task 2.2: Dev environment values

**File:** `environments/dev.yaml`

Viloforge dev-specific overrides:
```yaml
image:
  agent:
    repository: harbor.viloforge.com/vafi/vafi-agent
  base:
    repository: harbor.viloforge.com/vafi/vafi-base
  cxdb:
    repository: harbor.viloforge.com/vafi/cxdb

vtf:
  apiUrl: "http://vtf-api.vtf-dev.svc.cluster.local:8000"

cxdb:
  enabled: true
  publicUrl: "https://cxdb.dev.viloforge.com"

ingress:
  enabled: true
  className: traefik
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
  cxdbHost: cxdb.dev.viloforge.com
  tls:
    enabled: true
    secretName: cxdb-tls

certificate:
  enabled: true
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer

secrets:
  existingSecret: vafi-secrets   # pre-created via create-secrets.sh
```

Note: `secrets.existingSecret` is set because dev uses out-of-band secrets (z.ai key, SSH keys). The chart skips generating the secret.

### Task 2.3: Prod environment values

**File:** `environments/prod.yaml`

Same structure as dev but with:
- `vtf.apiUrl: "http://vtf-api.vtf-prod.svc.cluster.local:8000"`
- `cxdb.publicUrl: "https://cxdb.viloforge.com"`
- `ingress.cxdbHost: cxdb.viloforge.com`

### Task 2.4: Release script

**File:** `scripts/release.sh`

Same pattern as vtf-deploy's release script:
1. Build all 3 images (base, claude, agent) with git SHA tag
2. Push to Harbor
3. `helm upgrade --install vafi <chart-path> -n <namespace> -f <values> --set image.agent.tag=<sha>`
4. Wait for rollouts (executor-pool deployment, cxdb-server statefulset)
5. Health checks (executor pod running, cxdb responding)

Key difference from vtf: vafi builds 3 images (layered), not 1. The release script must build them in order and tag all with the same SHA.

```bash
#!/usr/bin/env bash
set -euo pipefail

ENV="${1:-}"
# ... env-specific config ...

GIT_SHA=$(cd "$VAFI_REPO" && git rev-parse --short HEAD)

# Build image layers in order
docker build -t "${REGISTRY}/vafi-base:${GIT_SHA}" images/base/
docker build --build-arg REGISTRY="${REGISTRY}" \
  -t "${REGISTRY}/vafi-claude:${GIT_SHA}" images/claude/
docker build --build-arg REGISTRY="${REGISTRY}" \
  -t "${REGISTRY}/vafi-agent:${GIT_SHA}" -f images/agent/Dockerfile .

# Push all
docker push "${REGISTRY}/vafi-base:${GIT_SHA}"
docker push "${REGISTRY}/vafi-claude:${GIT_SHA}"
docker push "${REGISTRY}/vafi-agent:${GIT_SHA}"

# Deploy
helm upgrade --install vafi "${CHART_PATH}" \
  --namespace "${NAMESPACE}" \
  -f "${VALUES}" \
  --set "image.agent.tag=${GIT_SHA}" \
  --set "image.base.tag=${GIT_SHA}" \
  --set "image.cxdb.tag=latest"  # cxdb has its own release cycle
```

### Task 2.5: Secret creation script

**File:** `scripts/create-secrets.sh`

Migrate from `vafi/scripts/create-secrets.sh`. Same logic:
- Creates `vafi-secrets` (z.ai key, anthropic base URL, vtf token)
- Creates `github-ssh` (SSH keys)
- Auto-creates vtf token via `kubectl exec` into vtf-api pod
- Idempotent (deletes and recreates)

---

## Phase 3: Migrate Live Deployment

### Task 3.1: Adopt existing k8s resources for Helm

Before Helm can manage existing resources, they need Helm ownership labels. For each resource in `vafi-agents` namespace:

```bash
kubectl label <resource> app.kubernetes.io/managed-by=Helm --overwrite
kubectl annotate <resource> meta.helm.sh/release-name=vafi meta.helm.sh/release-namespace=vafi-agents --overwrite
```

Resources to adopt:
- `deployment/executor-pool`
- `statefulset/cxdb-server`
- `service/cxdb-server`
- `ingress/cxdb-ingress`
- `pvc/sessions-pvc`

Do NOT adopt secrets (they're pre-created out-of-band with `existingSecret`).

### Task 3.2: Handle selector mismatch

The Kustomize `commonLabels` injected `app.kubernetes.io/version: v0.1.0` into deployment selectors. The Helm chart will NOT include version in selectors. This means:
- `deployment/executor-pool` — selector mismatch, must delete and recreate
- `statefulset/cxdb-server` — selector mismatch, must delete with `--cascade=orphan` (keeps PVC and pod) then let Helm recreate

**Procedure:**
1. Delete executor-pool deployment (brief executor downtime)
2. Delete cxdb-server statefulset with `--cascade=orphan` (cxdb pod keeps running)
3. Run `helm upgrade --install` — creates fresh resources with correct selectors
4. Delete orphaned cxdb pod — new statefulset creates replacement attached to existing PVC

### Task 3.3: Deploy and verify

Run the release script for dev:
```bash
cd vafi-deploy && ./scripts/release.sh dev
```

Verify:
- All pods Running (executor-pool, cxdb-server)
- Executor polls vtf successfully (check logs)
- CXDB ingress responds (`curl https://cxdb.dev.viloforge.com/v1/contexts?limit=1`)
- Create a test task, watch executor claim and execute it
- Verify CXDB trace captured for the task

### Task 3.4: Deploy prod (if applicable)

Same procedure for prod, if vafi has a prod deployment. Currently executor-pool only targets vtf-dev, so this may be deferred.

---

## Phase 4: Clean Up vafi Repo

### Task 4.1: Remove Kustomize manifests

Delete the entire `k8s/` directory from the vafi repo:
- `k8s/namespaces.yaml`
- `k8s/vafi-agents/` (all manifests, kustomization.yaml)
- `k8s/vafi-system/` (registry.yaml)
- `k8s/overlays/`

### Task 4.2: Remove viloforge-specific scripts

Remove or update scripts that reference viloforge infrastructure:
- `scripts/deploy.sh` — remove (replaced by vafi-deploy release script)
- `scripts/push-images.sh` — keep but ensure registry is parameterized (already uses `VAFI_REGISTRY`)
- `scripts/create-secrets.sh` — move to vafi-deploy
- `scripts/smoke-test.sh` — move to vafi-deploy (viloforge-specific vtf integration)
- `scripts/seed-vtf.sh` — move to vafi-deploy
- `scripts/vtf-connect.sh` — move to vafi-deploy

Scripts to keep in vafi repo:
- `scripts/build-images.sh` — generic, parameterized by `VAFI_REGISTRY`

### Task 4.3: Update Makefile

Remove Kustomize targets:
- Remove: `deploy`, `redeploy`, `secrets`, `seed`, `smoke-test`, `first-deploy`, `all`
- Keep: `build`, `push`, `help`
- Add: `helm-template` (render chart with default values for review)
- Add: `helm-lint` (validate chart)

### Task 4.4: Update documentation

Update `CLAUDE.md` and `README.md`:
- Remove references to `k8s/` directory and Kustomize
- Document Helm chart at `charts/vafi/`
- Reference vafi-deploy for viloforge-specific deployment
- Document `values.yaml` configuration options
- Document image build pipeline (base → claude → agent)

### Task 4.5: Audit for viloforge references

Grep the entire vafi repo for viloforge-specific strings and remove or parameterize them:
- `harbor.viloforge.com` — should only appear in Dockerfiles as `ARG REGISTRY` default (overridable)
- `viloforge.com` — should not appear anywhere
- `vtf-dev`, `vtf-prod` — should not appear
- `z.ai` — should not appear (move to values)
- `cxdb.dev.viloforge.com`, `cxdb.viloforge.com` — should not appear

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Selector mismatch during migration | Brief executor downtime | Delete and recreate during low-activity window |
| CXDB PVC data loss | Trace history lost | Use `--cascade=orphan` on StatefulSet delete, verify PVC survives |
| Wrong credentials after migration | Executor can't authenticate | Use `existingSecret` to reference pre-created secrets, don't regenerate |
| Build script breaks | Can't deploy new versions | Test release script on dev before touching prod |
| Public repo exposes credentials | Security breach | Audit task 4.5 catches any leaked values before making repo public |

## Success Criteria

- [ ] `helm template vafi charts/vafi/` renders without errors using only default values (no viloforge references)
- [ ] `helm template vafi charts/vafi/ -f environments/dev.yaml` renders correct viloforge config
- [ ] `release.sh dev` builds, pushes, deploys successfully
- [ ] Executor pod polls, claims, and executes a task after migration
- [ ] CXDB ingress serves traces after migration
- [ ] `grep -r 'viloforge\|harbor\|z\.ai' charts/ src/` returns zero matches in vafi repo (excluding build ARG defaults)
- [ ] All existing unit tests pass
