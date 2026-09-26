---
title: "Manual 01: Turn-Key Deployment & Hardware Provisioning"
category: operations
type: documentation
node: homelab
domain: ai-data
tags:
  - homelab/appliance
  - deployment/ansible
  - deployment/docker
  - product/appliance
status: active
last_reviewed: 2026-09-17
aliases:
  - Appliance Deployment Guide
  - Sovereign Vault Provisioning
---

# 🚀 Manual 01: Turn-Key Deployment & Hardware Provisioning

> **Parent Suite**: [Sovereign Appliance Manual Index](README.md)  
> **Related ADR**: [ADR-35: Sovereign Knowledge Appliance Packaging](../adrs/ADR-35-Sovereign-Knowledge-Appliance-Packaging-and-Commercial-Architecture.md)  
> **Target Environments**: Physical Mini-PC / 1U Server / Proxmox VE / VMware ESXi / KVM  

---

## 1. Hardware Sizing & Pre-Requisites

The Aegis Sovereign Appliance runs completely on CPU compute with CPU-native int8 ONNX quantization, eliminating the need for expensive, heat-generating server GPUs.

| Specification Tier | Target Workload | CPU | RAM | Storage |
| :--- | :--- | :--- | :--- | :--- |
| **Tier A: Executive Mini-PC** | 1–5 Concurrent Users (< 50,000 pages) | 4 Cores (Intel N100 / i5 / AMD Ryzen 5) | 8 GB DDR4/DDR5 | 128 GB NVMe SSD |
| **Tier B: Enterprise VM / Rackmount** | 5–25 Concurrent Users (Up to 500,000 pages) | 8 Cores (Intel Xeon / AMD EPYC / Ryzen 7) | 16–32 GB ECC RAM | 512 GB–1 TB NVMe RAID-1 |
| **Tier C: Sovereign Hyper-Scale** | Institutional Discovery (> 2,000,000 pages) | 16+ Cores (Dual Socket or Mac Studio M2/M3) | 64 GB+ RAM | 2 TB+ Enterprise NVMe |

### Software Pre-Requisites
- **Operating System**: Ubuntu Server 22.04 / 24.04 LTS or Debian 12 (Bookworm).
- **Runtime**: Docker Engine 24.0+ and Docker Compose v2.20+ (or Docker Compose v5+ plugin).
- **Networking**: Local static IP or Tailscale mesh address. Inbound port 8765 exposed only to trusted LAN.

---

## 2. Automated GitOps Rollout via Ansible

In the enterprise repository, appliance rollout to staging or production is fully automated via the Ansible Phoenix Protocol.

### Step 1: Inventory Configuration
Declare the appliance target host in `ansible/inventory.ini`:
```ini
[staging]
appliance_node ansible_host=192.168.1.100 ansible_user=sovereign-admin ansible_become_pass={{ vault_sudo_password }}
```

### Step 2: Trigger Automated Playbook
Execute the standalone deployment playbook:
```bash
ansible-playbook -i ansible/inventory.ini ansible/deploy_appliance_staging.yml --vault-password-file ansible/.vault_pass
```

The playbook executes the complete lifecycle:
1. Provisions target directory tree: `/opt/sovereign-vault/{data,scripts,docs}`.
2. Synchronizes container manifests, Dockerfile, scripts, and initial document seed.
3. Builds and launches the container stack: `docker compose up -d --build`.
4. Polls Qdrant (`:6333`) and Sovereign Core (`:8765`) until healthchecks report active.

---

## 3. Standalone Docker Compose Deployment

For third-party clients without Ansible, deploy using standard Docker Compose:

### Step 1: Directory Setup
```bash
sudo mkdir -p /opt/sovereign-vault/{data/appliance/{qdrant,postgres,paperless/{data,media,export,consume},rag},scripts,docs/wiki}
sudo chown -R $USER:docker /opt/sovereign-vault
```

### Step 2: Copy Stack Files
Place `docker-compose.appliance.yml`, `Dockerfile.appliance`, `requirements.txt`, and `scripts/` into `/opt/sovereign-vault`.

### Step 3: Launch Stack
```bash
cd /opt/sovereign-vault
docker compose -f docker-compose.appliance.yml up -d --build
```

---

## 4. Port Allocations & Network Security Posture

To protect against data exfiltration, ports are partitioned into strictly isolated scopes:

```text
Host Network Boundary:
  ├── 127.0.0.1:8000   -> Paperless Ghost Engine (Internal ONLY, never exposed to LAN)
  ├── 127.0.0.1:6333   -> Qdrant Vector Engine (Internal ONLY, telemetry disabled)
  ├── 127.0.0.1:5432   -> PostgreSQL Database (Internal container network)
  ├── 127.0.0.1:6379   -> Redis Queue (Internal container network)
  └── 0.0.0.0:8765     -> Aegis Sovereign Core Gateway (Authenticated LAN / Tailscale)
```

---

## 5. Verification & Health Audit

Verify all services in under 5 seconds from the host or client machine:

```bash
# 1. Inspect container states
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 2. Query Core Health Endpoint
curl -s http://127.0.0.1:8765/health | jq .

# Expected Output:
# {
#   "status": "idle",
#   "is_indexing": false,
#   "total_wiki_syncs": 1,
#   "last_result": { "indexed_files": 81, "total_tracked_files": 81 }
# }
```

---

## Next Steps
* Proceed to **[Manual 02: Database Initialization & Vector Store](02_database_initialization_and_vector_store.md)** to configure indexing and embeddings.
