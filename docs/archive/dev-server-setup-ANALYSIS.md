> **Archived**: This document is historical. For current architecture, see [ARCHITECTURE-SUMMARY.md](../ARCHITECTURE-SUMMARY.md) and [harness-images-ARCHITECTURE.md](../harness-images-ARCHITECTURE.md).

# Dev Server Setup Analysis — fuji (192.168.2.91)

## Context

New dedicated dev server replacing the old k3s laptop (192.168.2.90). Clean Ubuntu 24.04 LTS, 6 cores, 16GB RAM, 98GB disk. Needs full provisioning via ansible playbooks in this repo.

Three new requirements beyond the previous k3s-only setup:

1. **WireGuard VPN** — spoke in a new viloforge mesh (separate from OptiscanGroup)
2. **Traefik ingress** — expose k8s services via HTTPS (previously disabled)
3. **Cloudflare DNS + Let's Encrypt** — `viloforge.com` zone already in Cloudflare, all services get DNS entries with TLS

## Requirement 1: WireGuard VPN

### Background

A new WireGuard mesh for viloforge infrastructure, separate from the existing OptiscanGroup S2S mesh (10.101.100.0/24). Fuji is the first node and will act as the hub for future spokes.

### Design decisions

**D1: Network allocation**

New mesh needs its own subnet. Proposal: `10.200.0.0/24` (avoids collision with OptiscanGroup mesh at `10.101.100.0/24` and Docker/k8s ranges).

| Node | WireGuard IP | Role | Public IP |
|------|-------------|------|-----------|
| fuji | 10.200.0.1 | hub | 192.168.2.91 (LAN only for now) |

Future spokes (cloud VMs, other dev machines) get `.2`, `.3`, etc.

**D2: Hub vs spoke**

Fuji starts as a hub — it has a static LAN IP and runs 24/7. The ansible role should configure it as a WireGuard server (listening on UDP 51820) with peer configs templated per-spoke. Even though it's LAN-only now, the config should be ready for when it gets a public IP or port forward.

**D3: Ansible role structure**

New `wireguard` ansible role:
- Install WireGuard packages
- Generate keypair (if not exists, store in `/etc/wireguard/`)
- Template `wg0.conf` from inventory variables
- Enable `wg-quick@wg0` systemd service
- UFW rule for UDP 51820

Key management: private key generated on first run, public key captured and stored. Peer public keys provided via inventory group_vars.

**D4: Key management approach**

Options:
- **A) Generate on host, exchange manually** — simple, secure, requires manual step per peer
- **B) Pre-generate all keys in inventory** — fully automated but keys in git (bad)
- **C) Generate on host, fetch pubkey via ansible fact** — automated, keys stay on hosts

Recommendation: **Option C**. Generate keypair on first run, register pubkey as an ansible fact, use it in peer templates. Private keys never leave the host or appear in git.

### Implementation

New ansible role: `roles/wireguard/`

```
roles/wireguard/
  defaults/main.yml    — wg_interface, wg_port, wg_address, wg_peers
  tasks/main.yml       — install, keygen, template, enable
  handlers/main.yml    — restart wg-quick@wg0
  templates/wg0.conf.j2
```

Inventory additions (`group_vars/k3s.yml`):
```yaml
wg_address: "10.200.0.1/24"
wg_port: 51820
wg_peers: []  # future spokes added here
```

## Requirement 2: Traefik Ingress

### Background

Previous k3s setup used `--disable=traefik`. Services were only accessible via kubectl port-forward or NodePort. This time, Traefik should handle ingress with proper HTTPS routing.

### Design decisions

**D5: k3s built-in Traefik vs Helm-managed Traefik**

| | k3s built-in | Helm chart |
|---|---|---|
| Install | Automatic (remove `--disable=traefik`) | `helm install traefik traefik/traefik` |
| Version control | Tied to k3s version | Independent, pin any version |
| Configuration | HelmChartConfig CRD | values.yaml, full control |
| CRD management | Automatic | Manual or Helm-managed |
| cert-manager integration | Manual config | Well-documented |
| Upgrades | k3s upgrades may change Traefik version | Explicit |

Recommendation: **Helm-managed Traefik**. We need cert-manager integration with Cloudflare DNS-01, custom middleware, and version control. k3s built-in Traefik is convenient but limited. Keep `--disable=traefik` in k3s config.

**D6: Ingress approach**

Use Kubernetes `Ingress` resources with Traefik as the IngressController. Each service gets an Ingress with:
- Host rule (`<service>.dev.viloforge.com`)
- TLS termination via cert-manager

**D7: Traefik exposure**

Traefik runs as a DaemonSet (or Deployment with hostPort) binding to ports 80 and 443 on the node. Since this is a single-node cluster, this is equivalent to the node IP serving all HTTP/HTTPS traffic.

### Implementation

New ansible role or k8s manifests:
- Helm chart values for Traefik
- cert-manager Helm chart
- ClusterIssuer for Let's Encrypt + Cloudflare DNS-01
- Cloudflare API token as k8s Secret

k8s manifests to add:
```
k8s/traefik/
  namespace.yaml
  helm-values.yaml
k8s/cert-manager/
  namespace.yaml
  helm-values.yaml
  clusterissuer.yaml
  cloudflare-secret.yaml  (template, actual token via sealed-secret or manual)
```

## Requirement 3: Cloudflare DNS + Let's Encrypt

### Background

`viloforge.com` is already managed in Cloudflare. We want:
- DNS A/CNAME records for all services (`*.dev.viloforge.com`)
- Let's Encrypt certificates via DNS-01 challenge (Cloudflare as solver)
- Automated cert issuance and renewal via cert-manager

### Design decisions

**D8: DNS record strategy**

Options:
- **A) Wildcard A record** — `*.dev.viloforge.com` → fuji's IP. Simple, one record covers all services. Works for LAN. For external access later, update to public IP or add Cloudflare tunnel.
- **B) Per-service A records** — `vtf.dev.viloforge.com`, `registry.dev.viloforge.com`, etc. More explicit, requires update per new service.
- **C) Wildcard + external-dns** — k8s `external-dns` controller auto-manages Cloudflare records from Ingress resources.

Recommendation: **Option A for now** (wildcard `*.dev.viloforge.com` → `192.168.2.91`), with Option C as a future enhancement. Wildcard is immediate, zero-maintenance, and works for all current and future services. Since this is a LAN dev server, the A record points to a private IP — only accessible from the local network (and via WireGuard once spokes connect).

Note: Cloudflare proxy (orange cloud) must be **disabled** for the wildcard record since it points to a private IP. DNS-only mode (grey cloud).

**D9: Certificate strategy**

Options:
- **A) Wildcard cert** — `*.dev.viloforge.com`, one cert covers everything
- **B) Per-service certs** — cert-manager issues individual certs per Ingress

Recommendation: **Option A — wildcard cert**. Single cert, single DNS-01 challenge, covers all services. cert-manager Certificate resource requesting `*.dev.viloforge.com` with Cloudflare DNS-01 solver. Stored as a k8s TLS Secret, referenced by Traefik's default TLS store.

**D10: Cloudflare API token scope**

Create a scoped API token with:
- Zone: `viloforge.com`
- Permissions: `Zone:DNS:Edit` (for DNS-01 challenge TXT record creation)

Token injected into k8s as a Secret, referenced by cert-manager's ClusterIssuer.

**D11: Let's Encrypt environment**

Use Let's Encrypt **staging** first to validate the flow, then switch to production. Staging has generous rate limits and avoids hitting production limits during testing.

### Implementation

Cloudflare setup (manual, one-time):
1. Add wildcard DNS record: `*.dev.viloforge.com` → `192.168.2.91` (DNS-only, no proxy)
2. Create scoped API token for cert-manager

k8s resources:
```yaml
# ClusterIssuer
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@viloforge.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token

# Wildcard Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-dev-viloforge
  namespace: traefik
spec:
  secretName: wildcard-dev-viloforge-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - "*.dev.viloforge.com"
  - "dev.viloforge.com"
```

## Service DNS mapping

All services get `<name>.dev.viloforge.com` entries, routed by Traefik Ingress:

| Service | DNS | Namespace | Notes |
|---------|-----|-----------|-------|
| vtf (API) | vtf.dev.viloforge.com | vafi-system | Django API |
| vtf (Web) | vtf.dev.viloforge.com | vafi-system | React SPA, same host, path-based routing or served by API |
| Harbor | harbor.dev.viloforge.com | harbor | Container registry (minimal: core + registry + db + redis) |
| Traefik dashboard | traefik.dev.viloforge.com | traefik | Traefik admin UI |

Additional services added as Ingress resources — wildcard DNS + wildcard cert means zero DNS/cert work per service.

## Secrets management

**Ansible Vault** for all secrets. Encrypted vault file committed to git, decrypted at deploy time.

```
ansible/inventory/group_vars/vault.yml  (encrypted with ansible-vault)
  vault_cloudflare_api_token: "..."
  vault_harbor_admin_password: "..."
```

Ansible tasks create k8s Secrets from the decrypted vault values:
- `cloudflare-api-token` Secret in `cert-manager` namespace (for DNS-01 solver)
- `harbor-admin` Secret in `harbor` namespace (for Harbor admin login)

**WireGuard private key** is the exception — generated on the host at first run, stays on the host at `/etc/wireguard/privatekey`, never committed to git. Public key fetched as an ansible fact for peer configuration.

**Vault password** stored in a file outside the repo (e.g., `~/.ansible/vafi-vault-password`) and referenced via `ansible.cfg`:
```ini
[defaults]
vault_password_file = ~/.ansible/vafi-vault-password
```

## Ansible playbook structure

Updated `site.yml` play order:

```
1. common       — packages, timezone, UFW
2. wireguard    — VPN mesh (NEW)
3. k3s          — cluster install + namespaces
4. (post-k3s)   — Helm charts: cert-manager, Traefik, registry
```

Steps 1-3 are ansible roles. Step 4 could be:
- **Ansible tasks** using `kubernetes.core.helm` module
- **Makefile targets** run after ansible completes
- **Separate k8s provisioning playbook**

Recommendation: Helm installs as a separate ansible role (`k3s-apps`) or a post-install playbook. Keeps the k3s role clean (just the cluster) and the app layer separate.

## Updated inventory

```yaml
# inventory/dev.yml
all:
  children:
    k3s:
      hosts:
        fuji.dev.viloforge.com:
          ansible_host: 192.168.2.91
          ansible_user: ansible
          ansible_ssh_private_key_file: ~/.ssh/id_rsa

# group_vars/k3s.yml
k3s_version: "v1.31.4+k3s1"
k3s_server_args: >-
  --disable=traefik
  --write-kubeconfig-mode=644
k3s_kubeconfig_local_path: "~/.kube/vafi-dev.yaml"
k3s_namespaces:
  - vafi-system
  - vafi-agents
  - traefik
  - cert-manager
  - harbor

# WireGuard
wg_address: "10.200.0.1/24"
wg_port: 51820
wg_peers: []
```

## Implementation order

| Phase | What | Ansible role / action |
|-------|------|-----------------------|
| 1 | Update inventory (IP, hostname) | inventory edit |
| 2 | OS baseline | `common` role (existing) |
| 3 | WireGuard hub | `wireguard` role (new) |
| 4 | k3s install | `k3s` role (existing, add namespaces) |
| 5 | cert-manager | Helm install + ClusterIssuer + Cloudflare secret |
| 6 | Traefik | Helm install + default TLS store + wildcard cert |
| 7 | Harbor | Helm install (minimal profile) + Ingress |
| 8 | vtf | k8s manifests (existing, add Ingress) |
| 9 | Verify | curl https://vtf.dev.viloforge.com from LAN |

## Gaps identified during review

**G1: UFW rules incomplete** — `common` role must add UDP 51820 (WireGuard) and TCP 80/443 (Traefik hostPorts). Without these, ingress and VPN traffic is dropped by the default-deny firewall.

**G2: k3s registry template outdated** — `registries.yaml.j2` references `192.168.2.90:30500` (insecure HTTP). Must be updated to `harbor.dev.viloforge.com` over HTTPS. Valid LE cert means no insecure registry config needed.

**G3: Old 192.168.2.90 references** — all references to the decommissioned server must be cleaned up across the repo (inventory, templates, k8s manifests, docs).

**Reviewed and deferred:**
- Swap: keep enabled (dev server)
- Helm: runs on dev laptop where ansible runs, not on the server
- Image migration: rebuild with proper Harbor tags, no re-push
- Disk budget: not needed (dev server)
- Monitoring: future scope

## Resolved questions

1. **Cloudflare API token** — user will provide a scoped token (`Zone:DNS:Edit` on `viloforge.com`)
2. **Email for Let's Encrypt** — `admin@viloforge.com`
3. **Container registry** — Harbor (minimal footprint: core + registry + postgres + redis, Trivy/Notary/chartmuseum disabled). Postgres uses PVC with k3s local-path provisioner (same pattern as vtf Postgres StatefulSet). Single-user, dev-only.
4. **WireGuard mesh subnet** — `10.200.0.0/24` confirmed. Fuji as hub at `10.200.0.1`.
5. **Future spokes** — none yet. Peers configurable via `wg_peers` in ansible inventory, add a spoke by adding an entry and re-running the playbook.
