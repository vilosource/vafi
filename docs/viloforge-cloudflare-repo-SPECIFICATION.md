# viloforge-cloudflare Repository Specification

## Purpose

Manage all Cloudflare configuration for `viloforge.com` as code via Ansible. Single source of truth for DNS records, with extensibility for future Cloudflare services (page rules, WAF, tunnels, Zero Trust).

This repo is **shared infrastructure** — independent of any single project (vafi, vtf, cielo, etc.). Projects consume the DNS records; this repo owns them.

## Repository

- **Name**: `viloforge-cloudflare`
- **Location**: `vilosource/viloforge-cloudflare` (GitHub)
- **Local checkout**: `~/GitHub/viloforge-cloudflare/`

## Current state of viloforge.com in Cloudflare

- **Zone ID**: `b91c850d557c5e6a75d5101d0dac5305`
- **Plan**: Free
- **Status**: Active
- **Existing records**: 44 DNS records (A, CNAME, MX, TXT)
  - MX records: Namecheap email forwarding (5 records)
  - TXT: SPF record for email
  - A records: mix of LAN IPs, `127.0.0.1` placeholders, and one proxied root domain
  - CNAME: `www` → Namecheap parking page

### Record categories

| Category | Examples | Count | Managed by this repo? |
|----------|---------|-------|-----------------------|
| Hosts (physical servers) | `fuji.host.viloforge.com` | 0 (to create) | Yes |
| Services (k8s ingress) | `vtf.viloforge.com`, `*.dev.viloforge.com` | 1 exists | Yes |
| Lab hosts | `docker-1.lab.viloforge.com`, `postgres-1.lab.viloforge.com` | 8 | Yes |
| Dev hosts | `server-1.dev.viloforge.com`, `rundeck-*.dev.viloforge.com` | ~8 | Yes |
| Cielo project | `cielo.viloforge.com`, `*.cielo.dev.viloforge.com` | ~8 | Yes |
| VF Services | `*.vfservices.viloforge.com` | ~6 | Yes |
| Mail (MX + SPF) | MX records, TXT SPF | 6 | Yes |
| Root domain | `viloforge.com` A record, `www` CNAME | 2 | Yes |

## Directory structure

```
viloforge-cloudflare/
  ansible.cfg
  requirements.yml
  inventory/
    prod.yml                    # single "inventory" — Cloudflare is the target
    group_vars/
      all/
        main.yml                # zone config, record definitions
        vault.yml               # encrypted: Cloudflare API token
  playbooks/
    site.yml                    # full apply: DNS + future services
    dns.yml                     # DNS records only
  roles/
    cloudflare-dns/
      defaults/main.yml
      tasks/main.yml
  CLAUDE.md
```

## Inventory design

Since Cloudflare is an API, not an SSH target, the inventory is a localhost-only setup:

```yaml
# inventory/prod.yml
all:
  hosts:
    localhost:
      ansible_connection: local
```

All DNS records defined in group_vars:

```yaml
# inventory/group_vars/all/main.yml

cloudflare_zone: viloforge.com

# DNS records grouped by purpose
# Each record: { name, type, value, proxied (default false), priority (MX only) }

cloudflare_dns_records:

  # === Mail ===
  - name: "@"
    type: MX
    value: eforward1.registrar-servers.com
    priority: 10
  - name: "@"
    type: MX
    value: eforward2.registrar-servers.com
    priority: 20
  - name: "@"
    type: MX
    value: eforward3.registrar-servers.com
    priority: 30
  - name: "@"
    type: MX
    value: eforward4.registrar-servers.com
    priority: 40
  - name: "@"
    type: MX
    value: eforward5.registrar-servers.com
    priority: 50
  - name: "@"
    type: TXT
    value: "v=spf1 include:spf.efwd.registrar-servers.com ~all"

  # === Root domain ===
  - name: "@"
    type: A
    value: "162.255.119.190"
    proxied: true
  - name: www
    type: CNAME
    value: parkingpage.namecheap.com
    proxied: true

  # === Hosts (physical servers) ===
  - name: fuji.host
    type: A
    value: "192.168.2.91"

  # === k8s services on fuji — production ===
  - name: vtf
    type: A
    value: "192.168.2.91"
  - name: harbor
    type: A
    value: "192.168.2.91"

  # === k8s services on fuji — dev (wildcard) ===
  - name: "*.dev"
    type: A
    value: "192.168.2.91"

  # === Lab hosts ===
  - name: docker-1.lab
    type: A
    value: "192.168.10.11"
  - name: docker-2.lab
    type: A
    value: "192.168.10.12"
  # ... (all existing lab records)

  # === Dev hosts ===
  - name: hostname-1.dev
    type: A
    value: "192.168.2.164"
  # ... (all existing dev records)

  # ... (all remaining records from current zone)
```

### Vault

```yaml
# inventory/group_vars/all/vault.yml (encrypted)
vault_cloudflare_api_token: "<token>"
```

The API token needs broader permissions than the cert-manager token:
- **Zone:DNS:Edit** — create/update/delete DNS records
- **Zone:Zone:Read** — read zone info

Scope: `viloforge.com` zone only.

## Ansible role: cloudflare-dns

### Behavior

- **Declarative for managed records**: ensures each record in `cloudflare_dns_records` exists with the correct value
- **Does NOT delete unmanaged records**: records not in the list are left untouched
- **Idempotent**: re-running changes nothing if records match
- **Reports changes**: outputs which records were created/updated

### Implementation

```yaml
# roles/cloudflare-dns/tasks/main.yml
---
- name: Ensure DNS records exist
  community.general.cloudflare_dns:
    zone: "{{ cloudflare_zone }}"
    record: "{{ item.name }}"
    type: "{{ item.type }}"
    value: "{{ item.value }}"
    proxied: "{{ item.proxied | default(false) }}"
    priority: "{{ item.priority | default(omit) }}"
    solo: "{{ item.solo | default(omit) }}"
    api_token: "{{ vault_cloudflare_api_token }}"
    state: present
  loop: "{{ cloudflare_dns_records }}"
  loop_control:
    label: "{{ item.type }} {{ item.name }}.{{ cloudflare_zone }} → {{ item.value }}"
```

Note on `solo`: For records where only one value should exist (A records), set `solo: true`. For MX records with multiple values, omit it.

### Playbooks

```yaml
# playbooks/dns.yml
---
- name: Manage Cloudflare DNS for viloforge.com
  hosts: localhost
  connection: local
  roles:
    - role: ../roles/cloudflare-dns

# playbooks/site.yml
---
- name: Manage all Cloudflare configuration for viloforge.com
  hosts: localhost
  connection: local
  roles:
    - role: ../roles/cloudflare-dns
    # Future: cloudflare-page-rules, cloudflare-waf, cloudflare-tunnels
```

### Usage

```bash
# First time setup
cd viloforge-cloudflare
ansible-galaxy collection install -r requirements.yml
echo 'vault-password' > ~/.ansible/viloforge-cloudflare-vault-password
# fill in vault.yml and encrypt

# Apply all DNS records
ansible-playbook playbooks/dns.yml

# Dry run (check mode)
ansible-playbook playbooks/dns.yml --check --diff
```

## Requirements

```yaml
# requirements.yml
---
collections:
  - name: community.general
```

## ansible.cfg

```ini
[defaults]
inventory = inventory/prod.yml
vault_password_file = ~/.ansible/viloforge-cloudflare-vault-password
```

## Migration plan

The zone already has 44 records. Migration approach:

1. **Export all current records** into `cloudflare_dns_records` list (script provided below)
2. **Run in check mode** to verify no unintended changes: `ansible-playbook playbooks/dns.yml --check --diff`
3. **Apply** — should show 0 changes (everything matches)
4. **Add new records** (e.g., `vtf.viloforge.com`, `fuji.host.viloforge.com`) and apply
5. Going forward, all DNS changes go through this repo

### Export script

Include a helper script to bootstrap the record list from the current zone:

```bash
# scripts/export-dns.sh
#!/usr/bin/env bash
# Export current Cloudflare DNS records as YAML for inventory
set -euo pipefail

ZONE_ID="${CLOUDFLARE_ZONE_ID:-b91c850d557c5e6a75d5101d0dac5305}"
API_TOKEN="${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN}"

curl -s "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?per_page=100" \
  -H "Authorization: Bearer ${API_TOKEN}" | \
python3 -c "
import sys, json
records = json.load(sys.stdin)['result']
zone = 'viloforge.com'
for r in sorted(records, key=lambda x: (x['type'], x['name'])):
    name = r['name'].replace(f'.{zone}', '').replace(zone, '@')
    proxied = r.get('proxied', False)
    priority = r.get('priority', '')
    line = f'  - name: \"{name}\"'
    line += f'\n    type: {r[\"type\"]}'
    line += f'\n    value: \"{r[\"content\"]}\"'
    if proxied:
        line += f'\n    proxied: true'
    if priority:
        line += f'\n    priority: {priority}'
    print(line)
"
```

## Future extensions

| Service | Role | When |
|---------|------|------|
| Page rules | `cloudflare-page-rules` | When needed for redirects or caching |
| WAF rules | `cloudflare-waf` | When services are exposed publicly |
| Cloudflare Tunnels | `cloudflare-tunnels` | Alternative to WireGuard for external access to dev services |
| Zero Trust Access | `cloudflare-access` | When services need authenticated external access |
| SSL settings | `cloudflare-ssl` | TLS version, HSTS, etc. |

Each becomes a role in this repo, a play in `site.yml`. DNS is the first and most important.

## Relationship to other repos

| Repo | Relationship |
|------|-------------|
| **vafi** | Consumes DNS records (assumes `*.dev.viloforge.com`, `vtf.viloforge.com`, `harbor.dev.viloforge.com` exist). Does not manage DNS. |
| **vtaskforge** | Consumes DNS records. Application manifests reference hostnames. |
| **viloforge-cloudflare** (this repo) | Owns DNS. Source of truth for what hostname points where. |

## Acceptance criteria

- [ ] Repo created at `vilosource/viloforge-cloudflare`
- [ ] All 44 existing DNS records captured in inventory
- [ ] `ansible-playbook playbooks/dns.yml --check` shows 0 changes (migration verified)
- [ ] New records added: `fuji.host.viloforge.com`, `vtf.viloforge.com`
- [ ] `ansible-playbook playbooks/dns.yml` applies cleanly
- [ ] CLAUDE.md written with repo purpose and usage instructions
- [ ] README.md with setup instructions (vault password, API token, first run)
- [ ] Export script works and produces valid YAML
