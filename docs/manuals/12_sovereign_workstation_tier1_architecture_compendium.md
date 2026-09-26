---
title: "Manual 12: Sovereign Workstation Tier 1 — Architecture Compendium & Technical Directives Suite"
type: documentation
category: operations
status: active
last_reviewed: 2026-09-22
tags:
  - homelab/appliance
  - product/appliance
  - ai/rag
  - commercial/manual
  - desktop/workstation
  - hardware/dimensioning
  - architecture/tier1
aliases:
  - Manual 12
  - Sovereign Workstation Architecture Compendium
  - Tier 1 Technical Directives
---

# Manual 12: Sovereign Workstation Tier 1 — Architecture Compendium & Technical Directives Suite

> **Tier**: Tier 1 (Unprivileged Corporate Workstation Edition)
> **Related ADRs**: [ADR-40](../adrs/ADR-40-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md), [ADR-41](../adrs/ADR-41-Virtual-Container-Streaming-and-Cognitive-Graph-Intelligence.md), [ADR-42](../adrs/ADR-42-Zero-Friction-Onboarding-Ambient-Connectors-and-Data-Portability.md), [ADR-43](../adrs/ADR-43-Enterprise-Cloud-Ingestion-Fleet-Intelligence-and-Operational-Boundaries.md), [ADR-44](../adrs/ADR-44-Zero-Knowledge-Telemetry-Zstandard-Compression-and-Privacy-Architecture.md)
> **Audience**: Desktop software engineers, product architects, corporate IT integration leads

---

## Table of Contents

1. [Session Master Synthesis & Commercial Continuum](#1-session-master-synthesis--commercial-continuum)
2. [Two-Pronged Hybrid Retrieval & Intent Router](#2-two-pronged-hybrid-retrieval--intent-router)
3. [Enterprise IT Infiltration & Endpoint Hardening (ADR-40)](#3-enterprise-it-infiltration--endpoint-hardening)
4. [UI/UX: The Sovereign Cognitive Workspace](#4-uiux-the-sovereign-cognitive-workspace)
5. [Virtual Container Streaming & Cognitive Graph (ADR-41)](#5-virtual-container-streaming--cognitive-graph)
6. [Zero-Friction Onboarding & Data Portability (ADR-42)](#6-zero-friction-onboarding--data-portability)
7. [Enterprise Cloud Ingestion & Fleet Boundaries (ADR-43)](#7-enterprise-cloud-ingestion--fleet-boundaries)
8. [Zero-Knowledge Telemetry & Privacy (ADR-44)](#8-zero-knowledge-telemetry--privacy)
9. [Hardware Matrix & Instruction Set Dimensioning](#9-hardware-matrix--instruction-set-dimensioning)

---

## 1. Session Master Synthesis & Commercial Continuum

The Tier 1 Workstation Edition expands the Sovereign Knowledge Appliance into a portable, unprivileged binary that runs entirely on standard office laptops. Five core architectural bottlenecks are resolved:

| Bottleneck | Resolution |
| :--- | :--- |
| Battery & Thermal Tax | `IDLE_PRIORITY_CLASS` / `nice 19`; debounced kernel watchers |
| Lexical vs. Semantic False Dichotomy | Two-pronged intent router (exact IDs → SQLite; concepts → RRF) |
| Enterprise IT & EDR Hurdle | `O_RDONLY` traversal; DPAPI encryption; hermetic zero-egress IPC |
| Proprietary Data Silos | In-memory virtual container streaming (`.hdx`, `.zip`); MAPI COM Outlook access |
| Worker Privacy & Fleet Value | Zstandard dictionary-compressed, differentially private MinHash telemetry (<180 bytes) |

### Architecture Continuum Map

```
                            SOVEREIGN ARCHITECTURE CONTINUUM
                                           │
    ┌────────────────────────────────────────┼──────────────────────────────────────────┐
    ▼                                        ▼                                          ▼
Core Engine & Retrieval           Endpoint & Security                Product Experience & Fleet
───────────────────────           ───────────────────                ──────────────────────────
• Two-Pronged Hybrid Retrieval    • Enterprise IT Infiltration       • Minimalist Omni-Search UI/UX
• Virtual Container Streaming     • Zero-Knowledge Telemetry         • Zero-Friction Onboarding
  (ADR-41)                          (ADR-44)                        • Enterprise Cloud Fleet (ADR-43)
```

---

## 2. Two-Pronged Hybrid Retrieval & Intent Router

### Query Routing Taxonomy

```
                            Incoming User Query
                                    │
              ┌─────────────────────┴─────────────────────┐
              ▼                                           ▼
    Deterministic Fast-Path                   Intent & Semantic Dispatch
(Alphanumeric IDs, Hex, Filenames)           (Natural Language, Concepts)
              │                                           │
              ▼                                           ▼
   SQLite Trigram / B-Tree               Dense + Sparse Hybrid Search
    (Exact / Fuzzy Lookup)                (FastEmbed int8 + BM25 RRF)
        [Latency: < 2ms]                               │
                                                       ▼
                                           Top-K Evidence Candidates
                                                       │
                                      Is Synthesis / Reasoning Required?
                                           ┌───────────┴────────────┐
                                          YES                       NO
                                           ▼                         ▼
                                       RAG Context              Direct Record
                                    Window + Synthesis            Navigation
```

### Architectural Invariants

- **Zero Hallucination on Identifiers**: B-Tree and FTS5 indexers always take priority over dense vector similarity for ticket numbers, license keys, or exact hashes
- **Resource Discipline**: No ONNX dense embedding forward passes for filename or identifier lookups
- **Selective LLM Activation**: Reserve LLM synthesis strictly for queries requesting explanation, summarization, or reasoning

---

## 3. Enterprise IT Infiltration & Endpoint Hardening

### 4 EDR Compliance Invariants

**Invariant 1: Anti-Ransomware Heuristic Evasion**
- `O_RDONLY` kernel flags on all file reads
- No rapid recursive walks on startup — hook `ReadDirectoryChangesW` / `inotify` with 3,000ms sliding-window debounce
- Zero `atime` header touching during ingestion

**Invariant 2: Cryptographic Storage at Rest**
- Windows: DPAPI (`CryptProtectData`), binding to active domain user SID
- Linux/macOS: OS Secret Service API / macOS Keychain

**Invariant 3: Zero Outbound Egress & Hermetic Loopback**
- Never bind to `0.0.0.0` or open WAN socket
- All IPC via Named Pipes (`\\.\pipe\sovereign-ipc-<SessionSID>`) on Windows, or Unix Domain Sockets

**Invariant 4: Workplace Privacy & Statutory Fencing (LGPD / GDPR)**
- Strict whitelist roots: designated business containers only
- Hardcoded blacklist: browser profile dirs, password manager vaults (`.kdbx`, `.1password`), chat caches (WhatsApp, Slack)

---

## 4. UI/UX: The Sovereign Cognitive Workspace

### Design Philosophy: "Radical Simplicity with Latent Power"

The omni-bar pairs a Google-style minimalist input with an expandable evidence canvas:

```
┌────────────────────────────────────────────────────────────────────────────┐
│ [≡] Vaults / Folders    ⚡ Sovereign Desktop (Tier 1)  [🛡️ Air-Gapped] [👤] │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│                                  SOVEREIGN                                 │
│                  Local Cognitive Engine & MCP Memory Substrate             │
│                                                                            │
│          ┌────────────────────────────────────────────────────┐            │
│          │  🔍 Search tickets, code, emails, or ask...        │            │
│          └────────────────────────────────────────────────────┘            │
│                 [⚡ Fast-Path: TCK-102]   [🧠 Semantic Intent]              │
│                                                                            │
│  ┌────────────────────────────────────┐ ┌──────────────────────────────┐   │
│  │ 📄 Q3_Financial_Audit_2026.pdf     │ │ High-DPI Source Canvas       │   │
│  │ "...operating expenses increased  │ │ [ Bounding Box Highlight ]   │   │
│  │  by 14% due to cloud migration..."│ │ [Open Local File] [Reveal Dir]│   │
│  └────────────────────────────────────┘ └──────────────────────────────┘   │
│                                                                            │
├────────────────────────────────────────────────────────────────────────────┤
│ 🟢 MCP Server: Active | 12,410 files indexed | RAM: 142 MB | AVX2/512     │
└────────────────────────────────────────────────────────────────────────────┘
```

### Core UI Components

| Component | Function |
| :--- | :--- |
| **Minimalist Omni-Bar** | Real-time intent route pill: Green `[⚡ Lexical <1ms]` or Amber `[🧠 Hybrid RAG]` |
| **Left Management Drawer** | Watched roots, MCP Agent Bridge status, hardware telemetry (AVX2 vs AVX-512) |
| **Split-View Evidence Canvas** | Right-slide on result select: citation tags + high-DPI source document with gold bounding boxes |

### Dual Form Factor

- **Spotlight HUD (`Alt + Space`)**: Global frameless hotkey overlay for 2-second lookups
- **Studio Web Portal (`localhost:8765`)**: Browser workspace for deep exploration and capsule imports

---

## 5. Virtual Container Streaming & Cognitive Graph

See **[ADR-41: Virtual Container Streaming & Cognitive Graph Intelligence](../adrs/ADR-41-Virtual-Container-Streaming-and-Cognitive-Graph-Intelligence.md)** for full specification.

**Key parameters:**
- Max compression ratio: 100×
- Max uncompressed member: 500 MB
- Supported formats: `.html`, `.xhtml`, `.xml`, `.txt`, `.md` within `.hdx`, `.zip`, `.tar.gz`
- Virtual URI scheme: `virtual://<path_to_archive>#<member_path>`

---

## 6. Zero-Friction Onboarding & Data Portability

See **[ADR-42: Zero-Friction Onboarding, Ambient Connectors & Data Portability](../adrs/ADR-42-Zero-Friction-Onboarding-Ambient-Connectors-and-Data-Portability.md)** for full specification.

**Key implementation notes:**
- Auto-discovery completes in < 15ms via Registry and config file inspection
- Outlook lock breaker uses COM/MAPI STA thread — no admin rights required
- `.sovereign-capsule`: AES-256-GCM + Zstandard level 19; restores in < 4 seconds

---

## 7. Enterprise Cloud Ingestion & Fleet Boundaries

See **[ADR-43: Enterprise Cloud Ingestion, Fleet Intelligence & Operational Boundaries](../adrs/ADR-43-Enterprise-Cloud-Ingestion-Fleet-Intelligence-and-Operational-Boundaries.md)** for full specification.

**Epistemic Fallback threshold**: `S_confidence < 0.35` → disable synthesis, display amber warning, show nearest lexical matches.

---

## 8. Zero-Knowledge Telemetry & Privacy

See **[ADR-44: Zero-Knowledge Telemetry, Zstandard Compression & Privacy Architecture](../adrs/ADR-44-Zero-Knowledge-Telemetry-Zstandard-Compression-and-Privacy-Architecture.md)** for full specification.

**Wire footprint summary:**
- Raw JSON: ~3,500 bytes → Zstd compressed: **~174 bytes** → AES-256-GCM envelope: **~202 bytes**

---

## 9. Hardware Matrix & Instruction Set Dimensioning

| Dimension | Latitude 7390 (AVX2, i7-8650U) | MateBook X Pro (AVX-512 VNNI, i7-1165G7) | Architectural Directive |
| :--- | :--- | :--- | :--- |
| **Vector Width** | 256-bit (YMM0–YMM15) | 512-bit (ZMM0–ZMM31) | AVX-512 holds 2× data per register without DRAM spill |
| **Quantized int8 Math** | Emulated via 16-bit unpack/repack | Native 1-cycle `VPDPBUSD` | FastEmbed 2.5× faster on AVX-512 |
| **RAM Bandwidth** | DDR4-2400 (~38 GB/s) | LPDDR4x-4266 (~60 GB/s) | Local LLM: 10–14 tok/s vs 4–6 tok/s |
| **Search Latency (10k docs)** | 4.5 ms | 2.1 ms | Both provide instant sub-5ms response |
| **Office Corpus (10k docs)** | 2.5 min background CPU | 1.0 min background CPU | Fully viable as unprivileged Community engine |
| **RAPTOR Tree (5 Books)** | ~1.75 hours (heavy throttling) | ~38 minutes | **Paid Pro / Datacenter feature only** |

---

## 10. Related Documentation

- [Manual 08: Desktop Workstation & Corporate DLP](08_desktop_workstation_and_corporate_dlp.md)
- [Manual 07: Scaling Topologies, Bottlenecks & Commercial Playbook](07_scaling_topologies_bottlenecks_and_commercial_playbook.md)
- [Manual 11: Hardware Sizing & Infrastructure Capacity Planning](11_hardware_sizing_and_infrastructure_capacity_planning.md)
- [Chapter 24: Sovereign Workstation Engine — EE Foundations & Commercial Architecture](../24_sovereign_workstation_engine_ee_foundations_and_commercial_architecture.md)
- [ADR-40: Two-Pronged Hybrid Retrieval](../adrs/ADR-40-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md)
- [System Overview & Live Fleet Inventory](../system_overview.md)
