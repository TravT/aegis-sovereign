---
title: "ADR-05: Security Clearance Governance, Mandatory Access Control (MAC) & Multi-Tier Resource Quotas"
type: adr
category: adr
status: accepted
date: 2026-09-19
domain: security-governance
tags:
  - homelab/adrs
  - architecture/decisions
  - security/mac
  - access-control
  - qdrant/pre-filtering
  - product/appliance
  - commercial/governance
aliases:
  - ADR-05
  - Security Clearance Governance
  - Mandatory Access Control Architecture
---

# ADR-05: Security Clearance Governance, Mandatory Access Control (MAC) & Multi-Tier Resource Quotas

## Status
Accepted

## Date
2026-09-19

## Context
Deploying the Aegis Sovereign Knowledge Appliance into regulated enterprise environments (Multi-Family Offices, Corporate M&A, Healthcare Hospital Networks, and Defense Contractors) introduces strict security and monetization boundaries:

1. **Information Isolation & Data Leak Risks**:
   - Multiple users and departments share a single appliance instance, yet documents carry different sensitivity tiers (e.g. public press releases vs. internal memos vs. confidential payrolls vs. restricted M&A contracts).
2. **The Naive Post-Filtering Fallacy**:
   - Systems that execute flat vector search and subsequently filter out results exceeding a user's clearance fail catastrophically: if the top 10 vector hits belong to a restricted document, an unprivileged user receives an empty result set (0 results) despite the presence of hundreds of matching public paragraphs. Furthermore, timing variations create side-channel oracle attacks leaking the existence of classified records.
3. **Graph Inference Attacks**:
   - In relational GraphRAG, entity-relationship triples (e.g., `Holding Company -> acquires -> Secret Target Corp`) can inadvertently reveal sensitive business transactions to unprivileged users even if the underlying source document is unreadable.
4. **Air-Gapped Monetization & Resource Quota Enforcement**:
   - The appliance must differentiate between standard (Free) and premium (Pro/Enterprise) commercial tiers without calling external SaaS billing endpoints (Stripe, Auth0) across air-gapped perimeters.

---

## Decisions

### 1. The 4-Level Hierarchical Clearance Model (MAC)
The appliance establishes a 4-tier Mandatory Access Control hierarchy:
- **Level 0 (`public`)**: Public domain records, marketing releases, open literature. Accessible to guest web portals and unauthenticated agents.
- **Level 1 (`internal`)**: General operational SOPs, organizational handbooks, non-sensitive cluster logs. Requires standard authenticated user session.
- **Level 2 (`confidential`)**: Financial balance sheets, HR compensation records, customer PII, clinical patient charts. Requires departmental role authorization.
- **Level 3 (`restricted`)**: Privileged attorney-client work product, unannounced M&A targets, sealed criminal court records. Requires explicit cryptographic clearance key.

### 2. Strict In-Engine Pre-Filtering (Zero Post-Filtering Invariant)
To eliminate information starvation and side-channel timing leaks:
- **Qdrant Vector Database**: Clearance pre-filtering is injected directly into the HNSW index query before distance computation using payload match filters:
  ```python
  Filter(must=[
      FieldCondition(
          key="clearance_level",
          match=MatchAny(any=user_clearance.authorized_levels())
      )
  ])
  ```
- **HNSW Graph Safety**: Pre-filtering ensures the vector search only explores authorized nodes, guaranteeing a full top-$k$ evidence package with zero classified vector inspection.

### 3. Graph Inference Prevention in SQLite WAL
To prevent structural topology leaks in GraphRAG:
- The `entities` and `entity_relations` tables in SQLite WAL enforce row-level security:
  ```sql
  CREATE TABLE entity_relations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_id INTEGER REFERENCES entities(id),
      target_id INTEGER REFERENCES entities(id),
      relation_type TEXT NOT NULL,
      clearance_level INTEGER DEFAULT 0,
      document_id TEXT NOT NULL
  );
  CREATE INDEX idx_rel_clearance ON entity_relations(clearance_level);
  ```
- All multi-hop BFS queries, neighborhood traversals, and dossier compilations enforce `WHERE clearance_level <= :max_clearance`, hiding the existence of sensitive edges from unprivileged callers.

### 4. Document-Level Inheritance with Section-Level Overrides
- **Document Inheritance**: By default, all chunks and extracted graph triples inherit the security clearance declared in the document's YAML frontmatter (`clearance: confidential`).
- **Section Overrides**: Individual sections can be elevated or de-escalated using inline markdown directives (`<!-- clearance: restricted -->`), allowing redacted summaries of sensitive reports to be safely surfaced to general staff.

### 5. Multi-Tier Resource Plan Enforcer (`PlanEnforcer`)
To support commercial tiering across air-gapped perimeters, resource governance is decoupled from search algorithms into a dedicated policy enforcer:
- **Volume Gating**:
  - `Free`: Capped at **100 documents**.
  - `Pro` & `Enterprise`: **Unlimited** document indexing.
- **Compute & Feature Gating**:
  - `Free`: Restricted to Level 1 (`flash_needle`) micro-chunks and CPU inference. Prohibits heavy tree synthesis and multimodal CLIP.
  - `Pro`: Unlocks Level 2 (`relational_audit`), Level 3 (`deep_synthesis` RAPTOR), and Multimodal CLIP ViT-B-32.
  - `Enterprise`: Unlocks distributed cluster delegation (Ray/Docling, vLLM multi-GPU) and custom ontology pipelines.

### 6. The Five High-Signal Executive Dials
The appliance standardizes client-facing customization into five ergonomic controls, eliminating low-level mathematical parameter leakage:
1. **Analytical Depth**: `flash_needle` (L1), `relational_audit` (L2), `deep_synthesis` (L3). User-driven control.
2. **Evidence Grounding**: `verbatim_footnotes` (exact sentence quotes & offsets) vs `executive_abstract` (synthesized executive brief).
3. **Visual Enrichment**: Toggle for Multimodal CLIP ViT-B-32 evidence plates (engravings, signed seals, diagrams).
4. **Security Clearance**: Active session clearance token (L0–L3).
5. **Critical Posture**: `neutral`, `compliance_auditor` (flags missing exhibits and legal risks), or `scholarly`.

---

## Consequences

### Positive
- **Guaranteed Zero-Leakage**: Pre-filtering at the HNSW and SQLite levels mathematically prevents classified data exposure and timing oracle attacks.
- **Clear Monetization Boundaries**: Dual-axis gating (document volume + compute features) provides unambiguous upgrade incentives for enterprise clients.
- **Air-Gap Compatibility**: Security and plan enforcement execute 100% locally in-process without outbound HTTP callbacks.

### Negative & Mitigations
- **Qdrant Index Overhead**: Integer payload indexing on `clearance_level` increases memory usage slightly (~5MB per 100k vectors), mitigated by scalar int8 quantization.
- **Graph Partitioning Cost**: Filtering SQLite edges on clearance requires compound B-Tree indexes (`idx_rel_clearance`), adding minor write overhead during initial ingestion.

---

## Related Architecture & References
* [ADR-35: Sovereign Knowledge Appliance Packaging](ADR-35-Sovereign-Knowledge-Appliance-Packaging-and-Commercial-Architecture.md)
* [ADR-37: Zero-Copy Workstation Indexing & Serverless Desktop Engine](ADR-37-Zero-Copy-Workstation-Indexing-and-Serverless-Desktop-Engine.md)
* [Manual 06: Executive Tuning, Retrieval Modes & Client Knobs](../appliance/06_executive_tuning_and_client_knobs.md)
* [Manual 10: Hierarchical Library Retrieval & RAPTOR Summaries](../appliance/10_hierarchical_library_retrieval_and_raptor_summaries.md)
