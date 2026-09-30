---
title: "Aegis Sovereign Knowledge Appliance — Architectural Decision Records (ADRs)"
category: "architecture"
type: "index"
status: "active"
version: "1.0.0"
last_reviewed: "2026-09-23"
tags:
  - aegis/adrs
  - architecture/decisions
  - product/appliance
aliases:
  - "Aegis ADR Index"
  - "Aegis Architectural Decisions"
---

# Aegis Sovereign Knowledge Appliance — Architectural Decision Records (ADRs)

This directory contains the foundational architectural decision records for the **Aegis Sovereign Knowledge Appliance**. These records document the structural choices, security guarantees, retrieval invariants, and commercial deployment models of the standalone product.

---

## Architecture Decision Records Index

| ADR ID | Title | Date | Status | Domain | Core Invariant / Summary |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **[ADR-01](ADR-01-Sovereign-Knowledge-Appliance-Packaging-and-Commercial-Architecture.md)** | Sovereign Knowledge Appliance Packaging & Headless Ingestion | 2026-09-17 | Accepted | Core Packaging | Standalone decoupled repository, air-gapped container packaging, ghost Paperless-ngx ingestion daemon, and 98.9% token reduction proxy. |
| **[ADR-02](ADR-02-Sovereign-Appliance-Scaling-Fleet-and-Business-Topology.md)** | Scaling Fleet Topologies & Commercial Licensing Ladder | 2026-09-18 | Accepted | Fleet & Commercial | Tier 1 (Personal Desktop), Tier 2 (Edge Turnkey 1U Appliance), and Tier 3 (Enterprise Datacenter GPU Cluster) deployment matrix. |
| **[ADR-03](ADR-03-Zero-Copy-Workstation-Indexing-and-Serverless-Desktop-Engine.md)** | Zero-Copy Workstation In-Place Indexing & Serverless Desktop Engine | 2026-09-18 | Accepted | Desktop & Workstation | Single-process desktop daemon, zero-copy read-only traversal (`O_RDONLY`), kernel event watchers, and Cognitive Spotlight HUD. |
| **[ADR-04](ADR-04-Enterprise-Sovereign-Datacenter-Architecture-and-Distributed-Fabric.md)** | Enterprise Sovereign Datacenter Platform & Distributed Fabric | 2026-09-18 | Accepted | Datacenter & HPC | ColPali vision ingestion, Docling Ray clusters, distributed Qdrant/Milvus, Neo4j, vLLM 70B/405B serving, Ceph S3 WORM, and 400G InfiniBand. |
| **[ADR-05](ADR-05-Security-Clearance-Governance-and-Resource-Quotas.md)** | Security Clearance Governance, MAC Pre-Filtering & Resource Quotas | 2026-09-19 | Accepted | Security & Governance | 4-tier MAC hierarchy (`PUBLIC` to `RESTRICTED`), Qdrant payload pre-filtering, SQLite WAL graph inference prevention, and PlanEnforcer feature gating. |
| **[ADR-06](ADR-06-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md)** | Two-Pronged Hybrid Retrieval, Deterministic Fast-Path & Resilient Intent Routing | 2026-09-20 | Accepted | Retrieval & Routing | Deterministic fast-path (<2ms), Shannon entropy & reserved lexicon guards, MAC pushdown via external-content FTS5, and selective synthesis gating. |
| **[ADR-07](ADR-07-Virtual-Container-Streaming-and-Cognitive-Graph-Intelligence.md)** | Virtual Container Streaming & Cognitive Graph Intelligence | 2026-09-22 | Accepted | Indexing & Graph | In-memory `.hdx`/`.zip` virtual streaming (zero disk extraction), zip bomb guardrails, composite virtual URIs, and D3-Force graph explorer. |
| **[ADR-08](ADR-08-Zero-Friction-Onboarding-Ambient-Connectors-and-Data-Portability.md)** | Zero-Friction Onboarding, Ambient Connectors & Data Portability | 2026-09-22 | Accepted | Product & UX | 60-second auto-discovery radar, unprivileged COM/MAPI Outlook lock breaker, and AES-256-GCM Zstandard `.sovereign-capsule` portable vault format. |
| **[ADR-09](ADR-09-Enterprise-Cloud-Ingestion-Fleet-Intelligence-and-Operational-Boundaries.md)** | Enterprise Cloud Ingestion, Fleet Intelligence & Operational Boundaries | 2026-09-22 | Accepted | Enterprise & Fleet | Hard operational non-goals (read-only invariant), Epistemic Fallback UI (<35% confidence), S3 WORM and SAP OData CDC connectors, and MinHash LSH fleet privacy. |
| **[ADR-10](ADR-10-Zero-Knowledge-Telemetry-Zstandard-Compression-and-Privacy-Architecture.md)** | Zero-Knowledge Telemetry, Zstandard Compression & Privacy Architecture | 2026-09-22 | Accepted | Privacy & Telemetry | Community tier with zero networking code; Zstandard dictionary compression; HMAC pseudonymization; Glass Box Inspector; LGPD Art. 12 safe harbor. |
| **[ADR-11](ADR-11-Universal-Multimodal-Ingestion-and-TelcoTrace-Signaling.md)** | Universal Multimodal Ingestion Primitives & Deep-Tech Telecom Signaling Layer | 2026-09-23 | Accepted | Multimodal & Telecom | 3 Universal Ingestion Primitives, 2D plate binding with spatial OCR bounding, cross-doc graph entity stitching, TelcoTrace-Core signaling dissector, FastMCP interface, and Tier 3 Cognitive NWDAF closed-loop remediation. |
| **[ADR-12](ADR-12-Pluggable-Structure-Extraction-Tier-Size-Policy-and-Search-Time-Deduplication.md)** | Pluggable Structure Extraction, Tier-Aware Size Policy & Search-Time De-Duplication | 2026-09-29 | Accepted | Ingestion Structure | One `StructureExtractor` contract + registry (HedEx, path-tree built in); desktop/edge/datacenter size profiles; never truncate (chunk); collapse curated duplicates at search time; deterministic, no model at ingest |
| **[ADR-13](ADR-13-File-Type-Handlers-Conformance-Gate-and-Tiered-Fidelity-Ingestion.md)** | File-Type Handlers, Conformance Gate & Tiered-Fidelity Ingestion | 2026-09-29 | Accepted | Ingestion Formats | One `FormatHandler` contract per file type + automatic conformance gate (lossless, deterministic, bounded, corrupt-safe); prose always full, bulk tables capped via flagged catalog cards; missing/changed/grow/replace modes; structure written at ingest |
| **[ADR-14](ADR-14-Interactive-Graph-Viewer-Clearance-Aware-Layers-Server-Layout-and-Dependency-Free-Renderer.md)** | Interactive Graph Viewer: Clearance-Aware Layers, Server-Side Layout & a Dependency-Free Renderer | 2026-09-30 | Accepted | Product UX | One deep module (`meta / slice / find`) over three layers (manual tree, alarm/MML/KPI entities, wiki); clearance dropped never redacted; allow-lists; server-side radial layout; WebGL renderer with no third-party code; at most three colours (validated all-pairs) |

