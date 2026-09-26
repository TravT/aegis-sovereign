---
title: "ADR-02: Sovereign Knowledge Appliance Fleet Scaling, Hybrid Cloud Control & Modular Pro Topology"
type: adr
category: adr
status: accepted
date: 2026-09-17
domain: product-architecture
tags:
  - homelab/adrs
  - architecture/decisions
  - product/appliance
  - commercial/architecture
  - cloud/hybrid
  - business/model
aliases:
  - ADR-02
  - Appliance Scaling and Fleet Architecture
  - Commercial Playbook and Pro Topology
---

# ADR-02: Sovereign Knowledge Appliance Fleet Scaling, Hybrid Cloud Control & Modular Pro Topology

## Status
Accepted

## Date
2026-09-17

## Context
Following the successful deployment of the standalone Sovereign Knowledge Appliance on staging hardware ([ADR-35](ADR-35-Sovereign-Knowledge-Appliance-Packaging-and-Commercial-Architecture.md)) and its native integration into agent harnesses via Model Context Protocol (MCP), productization demands answering fundamental scaling, operational, and commercial questions:

1. **Hardware & Deployment Packaging**: What standard configurations should be packaged for distinct customer segments (personal/home prosumers vs boutique law firms vs mid-market enterprise)?
2. **Computational Bottlenecks**: High-throughput OCR ingestion, vector embedding computation, SQLite write concurrency, and memory consumption under multi-user loads create potential failure modes on entry-level hardware.
3. **Hybrid Cloud Fleet Governance**: How can a central operator manage their personal homelab instance while simultaneously overseeing a distributed fleet of B2B client appliances without violating zero-trust and client privacy guarantees?
4. **Service Cross-Pollination**: How can other production-hardened services from the homelab stack (Pi-hole, Traefik, Netdata, Maintainerr, ADB Gateway, Zstandard Backups) be modularized as value-add commercial modules?
5. **Local LLM Bundling Strategy**: Should the appliance bundle an on-device Large Language Model (e.g. Qwen2.5/Llama 3.2), or remain strictly a high-efficiency retrieval and context optimization engine?

---

## Decisions

### 1. Multi-Tier Hardware Packaging Topologies
The appliance is standardized across three physical delivery profiles and one virtual profile:

| Tier | Form Factor | Target Segment | Hardware Baseline | Capacity |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1: Sovereign Edge (Home/Prosumer)** | Ultra-Compact Mini-PC (Intel N100 / Ryzen 5) | Solopreneurs, doctors, high-net-worth individuals, homelab enthusiasts | 4 Cores, 16 GB DDR4/5, 512 GB NVMe (< 15W idle) | Up to 50,000 pages (~100,000 chunks) |
| **Tier 2: Enterprise 1U (B2B SME)** | 1U Rackmount / Micro-Workstation (Dell R250 / Minisforum MS-01) | Law firms (10–50 seats), CPA practices, regional hospitals | 8–16 Cores, 32–64 GB ECC RAM, 2 TB NVMe RAID-1, 10GbE | Up to 500,000 pages (~1,000,000 chunks) |
| **Tier 3: Air-Gapped Vault (Institutional)** | Tamper-Evident Rugged Chassis with Hardware Security Module (HSM) | Defense, public sector, cross-border arbitration | 16–32 Cores, 128 GB ECC RAM, 4–8 TB NVMe Encrypted (LUKS + YubiKey) | 2,000,000+ pages with instantaneous vector recall |
| **Tier V: Virtual Appliance (VPC/Cloud)** | Hardened OVA / Cloud-Init Terraform image | Enterprise clients with existing AWS/Hetzner/Azure private VPCs | 8 vCPU, 32 GB vRAM, 500 GB GP3 EBS | Scalable elastic volume |

### 2. Bottleneck Isolation & Architectural Mitigations

- **Ingestion & OCR Bottleneck**:
  - *Mitigation*: Celery task worker queuing decoupled from the synchronous HTTP gateway. OCR is set to `mode: skip` for text-native PDFs (90% of legal PDFs have digital text layers, slashing compute time by 95%). Heavy scans are processed at `nice -n 19` with a batch concurrency limit equal to physical CPU cores minus one.
- **Embedding Compute & Memory Bottleneck**:
  - *Mitigation*: FastEmbed ONNX Runtime with int8 quantization (`BAAI/bge-small-en-v1.5`), requiring only ~130 MB RAM and ~20 ms per chunk on AVX2 CPU instructions, entirely circumventing GPU dependencies.
- **SQLite Concurrency Bottleneck**:
  - *Mitigation*: Write-Ahead Logging (`PRAGMA journal_mode=WAL;`), synchronous normal mode, and a 5,000 ms busy timeout. For Tier 2+ enterprise deployments, the graph store dynamically delegates to the PostgreSQL container already provisioned for Paperless.
- **Memory Pressure on Constrained Nodes**:
  - *Mitigation*: Strict Docker memory limits (`mem_limit: 1.5g` on Paperless, `1.0g` on Qdrant, `512m` on Postgres). Qdrant uses `on_disk_payload: true` to prevent payload bloat in RAM.

### 3. Zero-Knowledge Hybrid Cloud Fleet Governance
To allow centralized management without client data contamination:
- **Strict Plane Separation**:
  - **Data Plane (100% Local / Air-Gapped)**: Raw documents, OCR text, vector embeddings, and SQLite graph stores **never** leave the client's local network.
  - **Control Plane (Telemetry & Management Gateway)**: A lightweight, outbound-only WireGuard/Tailscale telemetry daemon emits encrypted heartbeats (uptime, disk space, Qdrant collection count, container health) to a central multi-tenant dashboard.
- **Remote Orchestration**: Container updates, security patches, and subscription feature licenses are pushed via Ansible / Nomad playbooks over private Tailnet routes without exposing inbound open ports.

### 4. Modular Commercialization of Homelab Stack Services
Homelab services are productized as add-on "Expansion Packs":
1. **Aegis DNS Shield (Pi-hole Engine)**: Network-wide threat intelligence, ad blocking, and telemetry quarantine for corporate offices.
2. **Aegis Zero-Trust Ingress (Traefik v3 Engine)**: Dynamic Let's Encrypt TLS termination and Tailscale Funnel reverse proxy for internal ERPs.
3. **Aegis Retention & Compliance Engine (Maintainerr Pattern)**: Automated watch-and-delete compliance rules (e.g. GDPR 30-day purge, 7-year fiscal invoice archiving).
4. **Aegis Fleet Device Bridge (ws-scrcpy / ADB Engine)**: Remote control and telemetry dispatching for corporate Android devices and field kiosks.
5. **Aegis Cold Vault (Zstandard + rclone Engine)**: Automated, encrypted application state snapshots synced to zero-knowledge cloud cold storage (Wasabi / Backblaze B2).

### 5. Local LLM Bundling Strategy: The "Cerebellum vs Brain" Architecture
- **The Core Product is a Cerebellum**: The primary commercial appliance is intentionally packaged as a **Retrieval & Context Optimization Engine**, not an LLM host.
  - *Rationale*: RAG + Context Synthesis requires minimal compute (low-power CPU, $250 box), while LLM inference requires expensive GPUs, generates intense heat, and models become obsolete every 90 days.
  - *Integration*: Exposes high-level MCP tools to the client's preferred LLM (Claude, ChatGPT, Antigravity, or on-prem Ollama).
- **Pro Add-On: Sovereign Brain Node**:
  - Clients requiring 100% complete air-gap LLM generation can purchase the *Sovereign Brain Expansion* (featuring an on-demand RTX 5070 GPU host, Mac Studio M2/M4, or CPU-quantized Qwen2.5-7B/14B Q4_K_M running via Ollama), seamlessly connected via the existing `homelab-gpu` and `sovereign-vault` MCP interfaces.

### 6. Value-Add Pro Feature Monetization Ladder
- **Community / Open Baseline**: FastEmbed ONNX hybrid search, headless Paperless drop folder, basic MCP tools.
- **Pro Tier (B2B SME)**:
  - *Executive Tuning Drawer* (interactive confidence floor, legal discovery & exact entity modes).
  - *Automated PII Redaction Pipeline* (presidio regex scrubbing of tax IDs, SSNs, credit cards before context injection).
  - *Interactive Visual Knowledge Graph* (force-directed relational graph of contracts, clients, and assets).
  - *Cryptographic Audit Ledger* (immutable record of which employee or agent queried what document).
- **Enterprise Tier (Institutional)**:
  - Multi-tenant RBAC (departmental document fences).
  - Hardware Security Module (HSM) encryption-at-rest.
  - Multi-node high-availability clustering and zero-knowledge cloud disaster recovery.

---

## Consequences

### Positive
- Clarifies exact hardware BOM (Bill of Materials) and pricing models for client engagements.
- Keeps base hardware under $350 while offering high-margin enterprise software upsells.
- Completely shields operator from compliance liability by enforcing Zero-Knowledge data plane isolation.
- Unlocks immediate commercial reuse of 6 proven homelab cluster services.

### Negative
- Managing a distributed fleet of edge appliances requires robust automated testing and rollback playbooks.
- Zero-Knowledge control plane prevents direct remote debugging of client data issues without customer-initiated support access tokens.

---

## References
- [ADR-35: Sovereign Knowledge Appliance Packaging](ADR-35-Sovereign-Knowledge-Appliance-Packaging-and-Commercial-Architecture.md)
- [ADR-33: Hybrid RAG Engine Architecture](ADR-33-Hybrid-RAG-Engine-Architecture.md)
- [Chapter 23: Sovereign Knowledge Appliance Architecture](../23_sovereign_knowledge_appliance_and_commercial_stack.md)
- [Sovereign Appliance Operator Manuals](../appliance/README.md)
