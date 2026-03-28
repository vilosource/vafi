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
- **Namespace issue**: Single `vafi-agents` namespace serves both dev and prod. Should be `vafi-dev` and `vafi-prod` per viloforge-platform convention.
- **CXDB issue**: Single CXDB instance serves both dev and prod domains. Should be separate instances per environment.

## Target State

- **vafi repo (public)**: Helm chart at `charts/vafi/` with generic defaults. No viloforge URLs, no credentials, no domain names.
- **vafi-deploy repo (private)**: Viloforge-specific values, release scripts (vafi + CXDB), secret management. Same pattern as `vtf-deploy/`.
- **Namespaces**: `vafi-dev` and `vafi-prod`, each with their own executor and CXDB instance.

## What Goes Where

| Item | vafi repo (public) | vafi-deploy repo (private) |
|------|-------------------|---------------------------|
| Helm chart templates | `charts/vafi/templates/` | - |
| Default values (generic) | `charts/vafi/values.yaml` | - |
| Dockerfiles | `images/base/`, `images/claude/`, `images/agent/` | - |
| Controller source | `src/`, `methodologies/`, `templates/` | - |
| Build scripts | `scripts/build-images.sh` (parameterized) | - |
| Environment values | - | `environments/dev.yaml`, `environments/prod.yaml` |
| Release script (vafi) | - | `scripts/release.sh` |
| Release script (CXDB) | - | `scripts/release-cxdb.sh` |
| Secret creation | - | `scripts/create-secrets.sh` |
| Registry URLs | - | In environment values (`image.repository`) |
| Domain names | - | In environment values (`ingress.cxdbHost`) |
| API credentials | - | In environment values or out-of-band secrets |

## Related Infrastructure

| Repo | Responsibility |
|------|---------------|
| **viloforge-platform** | Cluster provisioning — k3s, Traefik, Harbor, cert-manager. Ansible playbooks. |
| **viloforge-cloudflare** | DNS records for viloforge.com. |
| **vtf-deploy** | vtf Helm values + release script. |
| **vafi-deploy** (this plan) | vafi Helm values + release scripts + CXDB build. |

Cluster infrastructure (Harbor, Traefik, cert-manager, namespaces) is managed by viloforge-platform, not by vafi or vafi-deploy.

## Design Decisions

### CXDB in the vafi chart

CXDB deploys alongside the executor per environment. Rather than a separate chart, CXDB is a toggleable component in the vafi chart (`cxdb.enabled: true`). This keeps the deployment atomic — one `helm upgrade` deploys everything for an environment.

### CXDB image build in vafi-deploy

CXDB is a fork from a third party maintained in our GitHub repo. We don't pollute the cxdb repo with build scripts. Instead, vafi-deploy owns the CXDB image build via a separate `scripts/release-cxdb.sh`. CXDB releases independently from the executor — a vafi deploy does not rebuild CXDB.

`release-cxdb.sh` also builds the `cxtx` binary (Rust, from the cxdb source) and publishes it as a small image (`vafi-cxtx:<tag>`). The vafi-claude Dockerfile copies the binary from this image instead of cloning the repo and compiling at build time.

### Image layer strategy — pinned versions

The 3-layer image hierarchy (base → claude → agent) has different change frequencies:

| Layer | Changes when | Rebuild frequency |
|-------|-------------|-------------------|
| **vafi-base** | Node version, system packages | Rarely (monthly) |
| **vafi-claude** | Claude CLI version, cxtx binary | Occasionally |
| **vafi-agent** | Controller source code | Every deploy |

Base and claude are pinned to versioned tags (e.g., `vafi-base:v1.0`, `vafi-claude:v1.0`). The agent Dockerfile references the pinned claude version:

```dockerfile
ARG CLAUDE_TAG=v1.0
FROM ${REGISTRY}/vafi-claude:${CLAUDE_TAG}
```

The release script only builds the agent image on every deploy. Base and claude are rebuilt manually when their inputs change, tagged with a new version, and pushed. The version pins are in vafi-deploy's environment values, so different environments can run different base versions.

Build commands in vafi repo:
- `make build-base` — rebuild base layer, tag and push
- `make build-claude` — rebuild claude layer (requires cxtx image), tag and push
- `make build` or release script — rebuild agent layer only (fast, seconds)

### Namespace per environment

Each environment gets its own namespace following viloforge-platform convention:
- `vafi-dev` — executor + CXDB pointing at vtf-dev
- `vafi-prod` — executor + CXDB pointing at vtf-prod

The current `vafi-agents` namespace is the existing dev deployment. During migration it is replaced by `vafi-dev`. The `vafi-system` namespace is empty and gets deleted.

### Secret management

The Helm chart generates `vafi-secrets` from values (like vtf's chart does). For production, operators can either:
- Put credentials in values files (simple, acceptable for private deploy repos)
- Create secrets out-of-band and set `existingSecret: vafi-secrets` to skip generation

The `github-ssh` secret is always created out-of-band (contains SSH private keys that should never be in values files). The chart references it but does not create it.

### Registry deployment

The `vafi-system/registry.yaml` (Docker registry:2) was never deployed — the namespace is empty. Harbor (managed by viloforge-platform) is the container registry. The local registry manifest is dead code and gets removed.

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
  cxtx:
    repository: vafi-cxtx
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
  existingSecret: ""       # if set, skip generating vafi-secrets
  anthropicAuthToken: ""
  anthropicBaseUrl: "https://api.anthropic.com"
  vtfToken: ""

sshSecret:
  name: github-ssh         # pre-created secret with SSH keys
```

### Task 1.2: Executor deployment template

**File:** `templates/executor-deployment.yaml`

Converts `k8s/vafi-agents/executor-pool.yaml` into a Helm template. Key parameterizations:
- Image: `{{ .Values.image.agent.repository }}:{{ .Values.image.agent.tag }}`
- Init container image: `{{ .Values.image.base.repository }}:{{ .Values.image.base.tag }}`
- All env vars from values (poll interval, timeout, max rework, etc.)
- vtf API URL from `{{ .Values.vtf.apiUrl }}`
- CXDB URLs conditional on `{{ .Values.cxdb.enabled }}`
- Secret references use `{{ include "vafi.secretName" . }}`
- SSH secret name from `{{ .Values.sshSecret.name }}`
- Resource limits and probe timings from values
- Labels from `_helpers.tpl` (no version in selectors — avoids the Kustomize bug)

### Task 1.3: CXDB StatefulSet template

**File:** `templates/cxdb-statefulset.yaml`

Wrapped in `{{- if .Values.cxdb.enabled }}`. Parameterizations:
- Image: `{{ .Values.image.cxdb.repository }}:{{ .Values.image.cxdb.tag }}`
- Storage size and class from values
- Resource limits from values
- Labels from helpers (no version in selectors)

### Task 1.4: CXDB service and ingress templates

**Files:**
- `templates/cxdb-service.yaml` — ClusterIP service, gated by `cxdb.enabled`
- `templates/cxdb-ingress.yaml` — ingress, gated by `cxdb.enabled` AND `ingress.enabled`
- `templates/cxdb-certificate.yaml` — cert-manager Certificate, gated by `certificate.enabled`

Each environment gets its own ingress with its own host — no multi-host ingress.

### Task 1.5: Sessions PVC template

**File:** `templates/sessions-pvc.yaml`

Storage size and class from values.

### Task 1.6: Secrets template

**File:** `templates/secret.yaml`

Gated by `{{ if not .Values.secrets.existingSecret }}`. Generates `vafi-secrets` with anthropic auth token, base URL, and vtf token. The `github-ssh` secret is NOT generated — always pre-created out-of-band.

### Task 1.7: Helpers template

**File:** `templates/_helpers.tpl`

Helpers:
- `vafi.fullname` — release-aware name
- `vafi.labels` — standard Helm labels (chart, managed-by, instance, version)
- `vafi.selectorLabels` — component-specific selector labels (stable, NO version)
- `vafi.secretName` — either `existingSecret` or generated name
- `vafi.commonEnv` — shared env vars (vtf URL, CXDB URL, timing, secrets)

Critical: selector labels must NOT include `app.kubernetes.io/version`.

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

```
vafi-deploy/
  README.md
  environments/
    dev.yaml
    prod.yaml
  scripts/
    release.sh
    release-cxdb.sh
    create-secrets.sh
```

### Task 2.2: Dev environment values

**File:** `environments/dev.yaml`

```yaml
image:
  agent:
    repository: harbor.viloforge.com/vafi/vafi-agent
  base:
    repository: harbor.viloforge.com/vafi/vafi-base
  cxtx:
    repository: harbor.viloforge.com/vafi/vafi-cxtx
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
  existingSecret: vafi-secrets
```

### Task 2.3: Prod environment values

Same structure as dev but with:
- `vtf.apiUrl` pointing at `vtf-prod`
- `cxdb.publicUrl: "https://cxdb.viloforge.com"`
- `ingress.cxdbHost: cxdb.viloforge.com`

### Task 2.4: Release script (vafi)

**File:** `scripts/release.sh`

Builds only the agent image (fast — base and claude are pinned). Pushes to Harbor. Deploys via Helm.

```bash
# Build agent only (base and claude are pinned)
docker build --build-arg REGISTRY="${REGISTRY}" \
  --build-arg CLAUDE_TAG="${CLAUDE_TAG}" \
  -t "${REGISTRY}/vafi-agent:${GIT_SHA}" \
  -f images/agent/Dockerfile "${VAFI_REPO}"

docker push "${REGISTRY}/vafi-agent:${GIT_SHA}"

helm upgrade --install vafi "${CHART_PATH}" \
  --namespace "${NAMESPACE}" --create-namespace \
  -f "${VALUES}" \
  --set "image.agent.tag=${GIT_SHA}"
```

Wait for rollouts, run health checks.

### Task 2.5: Release script (CXDB)

**File:** `scripts/release-cxdb.sh`

Independent from vafi releases. Builds two images from the cxdb source repo:
1. `vafi-cxtx:<tag>` — minimal image containing just the compiled cxtx binary
2. `cxdb:<tag>` — the full CXDB server image

```bash
CXDB_REPO="${CXDB_REPO:-$(dirname "$DEPLOY_ROOT")/cxdb}"
GIT_SHA=$(cd "$CXDB_REPO" && git rev-parse --short HEAD)

# Build cxtx binary image
docker build -t "${REGISTRY}/vafi-cxtx:${GIT_SHA}" \
  -f "${CXDB_REPO}/Dockerfile.cxtx" "${CXDB_REPO}"

# Build cxdb server image
docker build -t "${REGISTRY}/cxdb:${GIT_SHA}" "${CXDB_REPO}"

# Push both
docker push "${REGISTRY}/vafi-cxtx:${GIT_SHA}"
docker push "${REGISTRY}/cxdb:${GIT_SHA}"

# Deploy (updates cxdb image tag only, doesn't touch executor)
helm upgrade vafi "${CHART_PATH}" \
  --namespace "${NAMESPACE}" \
  -f "${VALUES}" \
  --set "image.cxdb.tag=${GIT_SHA}" \
  --reuse-values
```

### Task 2.6: Secret creation script

**File:** `scripts/create-secrets.sh`

Migrated from `vafi/scripts/create-secrets.sh`. Same logic:
- Creates `vafi-secrets` (z.ai key, anthropic base URL, vtf token)
- Creates `github-ssh` (SSH keys)
- Auto-creates vtf token via `kubectl exec` into vtf-api pod
- Idempotent (deletes and recreates)
- Takes `dev` or `prod` argument to target the right namespace and vtf instance

### Task 2.7: Update claude Dockerfile for cxtx image

**File:** `images/claude/Dockerfile` (in vafi repo)

Replace the git clone + Rust build with a `COPY --from` the pre-built cxtx image:

Before:
```dockerfile
FROM rust:1.85-bookworm AS cxtx-builder
RUN git clone --depth 1 https://github.com/vilosource/cxdb.git /build/cxdb
WORKDIR /build/cxdb
RUN cargo build -p cxtx --release

FROM ${REGISTRY}/vafi-base:latest
COPY --from=cxtx-builder /build/cxdb/target/release/cxtx /usr/local/bin/cxtx
```

After:
```dockerfile
ARG REGISTRY=vafi
ARG BASE_TAG=latest
ARG CXTX_TAG=latest
FROM ${REGISTRY}/vafi-cxtx:${CXTX_TAG} AS cxtx

FROM ${REGISTRY}/vafi-base:${BASE_TAG}
COPY --from=cxtx /usr/local/bin/cxtx /usr/local/bin/cxtx
```

No git clone, no Rust toolchain, builds in seconds.

---

## Phase 3: Migrate Live Deployment

### Task 3.1: Create vafi-dev namespace

The release script creates the namespace via `--create-namespace`. The current `vafi-agents` namespace stays untouched until migration is verified.

### Task 3.2: Deploy to vafi-dev

Run `release.sh dev`. This creates a fresh deployment in `vafi-dev` with:
- New executor-pool (pointing at vtf-dev)
- New CXDB instance (empty — dev traces start fresh)
- New sessions PVC
- Secrets pre-created via `create-secrets.sh --dev`

Verify:
- Executor pod polls vtf-dev successfully
- CXDB ingress responds at `cxdb.dev.viloforge.com` (requires DNS/ingress update to point to new namespace — or update existing ingress)
- Create a test task, watch executor claim and execute
- Verify CXDB trace captured

### Task 3.3: Cutover CXDB ingress

The existing CXDB ingress in `vafi-agents` serves `cxdb.dev.viloforge.com`. The new one in `vafi-dev` serves the same host. Two ingresses for the same host will conflict. Options:
- Delete the old ingress in `vafi-agents` before deploying to `vafi-dev`
- Or deploy `vafi-dev` without ingress first, verify everything works, then swap

### Task 3.4: Decommission vafi-agents namespace

After `vafi-dev` is verified:
1. Scale old executor-pool to 0 in `vafi-agents`
2. Verify new executor in `vafi-dev` is handling work
3. Delete all resources in `vafi-agents`
4. Delete the `vafi-agents` namespace
5. Delete the empty `vafi-system` namespace

### Task 3.5: Deploy to vafi-prod

Run `release.sh prod`. Creates fresh deployment in `vafi-prod` with:
- Executor pointing at vtf-prod
- CXDB at `cxdb.viloforge.com`
- Own sessions PVC

Verify same as dev.

---

## Phase 4: Clean Up vafi Repo

### Task 4.1: Remove Kustomize manifests

Delete the entire `k8s/` directory:
- `k8s/namespaces.yaml`
- `k8s/vafi-agents/` (all manifests, kustomization.yaml)
- `k8s/vafi-system/` (registry.yaml — never deployed)
- `k8s/overlays/`

### Task 4.2: Remove viloforge-specific scripts

Move to vafi-deploy:
- `scripts/deploy.sh` — replaced by vafi-deploy release script
- `scripts/create-secrets.sh` — moved to vafi-deploy
- `scripts/smoke-test.sh` — viloforge-specific vtf integration
- `scripts/seed-vtf.sh` — viloforge-specific
- `scripts/vtf-connect.sh` — viloforge-specific

Keep in vafi repo:
- `scripts/build-images.sh` — generic, parameterized by `VAFI_REGISTRY`

### Task 4.3: Update Makefile

Remove:
- `deploy`, `redeploy`, `secrets`, `seed`, `smoke-test`, `first-deploy`, `all`
- `provision`, `k3s`, `os` (ansible stubs — ansible lives in viloforge-platform)

Keep:
- `build`, `push`, `help`

Add:
- `build-base` — rebuild and tag base image
- `build-claude` — rebuild and tag claude image (requires cxtx image)
- `helm-template` — render chart with default values
- `helm-lint` — validate chart

### Task 4.4: Update documentation

Update `CLAUDE.md` and `README.md`:
- Remove references to `k8s/` directory and Kustomize
- Document Helm chart at `charts/vafi/`
- Reference vafi-deploy for viloforge-specific deployment
- Document `values.yaml` configuration options
- Document image build pipeline and pinned layer strategy

### Task 4.5: Audit for viloforge references

Grep the entire vafi repo for viloforge-specific strings:
- `harbor.viloforge.com` — only in Dockerfiles as `ARG REGISTRY` default (overridable)
- `viloforge.com` — should not appear anywhere else
- `vtf-dev`, `vtf-prod` — should not appear
- `z.ai` — should not appear
- `cxdb.dev.viloforge.com`, `cxdb.viloforge.com` — should not appear

---

## Success Criteria

- [ ] `helm template vafi charts/vafi/` renders without errors using only default values
- [ ] No viloforge-specific values in default rendering
- [ ] `helm template vafi charts/vafi/ -f environments/dev.yaml` renders correct viloforge config
- [ ] `release.sh dev` builds agent image, pushes, deploys to `vafi-dev`
- [ ] `release-cxdb.sh dev` builds cxdb + cxtx images independently
- [ ] Executor pod in `vafi-dev` polls, claims, and executes a task
- [ ] CXDB in `vafi-dev` captures traces, ingress serves at `cxdb.dev.viloforge.com`
- [ ] `grep -r 'viloforge\|harbor\|z\.ai' charts/ src/` returns zero matches (excluding Dockerfile ARG defaults)
- [ ] Old `vafi-agents` and `vafi-system` namespaces deleted
- [ ] All existing unit tests pass
