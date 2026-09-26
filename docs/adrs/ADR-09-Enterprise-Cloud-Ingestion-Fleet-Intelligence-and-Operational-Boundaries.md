---
title: "ADR-09: Enterprise Cloud Ingestion, Fleet Intelligence & Operational Boundaries"
type: adr
category: decision
status: accepted
date: 2026-09-22
last_reviewed: 2026-09-22
node: homelab
domain: enterprise-fleet
tags:
  - homelab/adrs
  - architecture/decisions
  - enterprise/cloud-ingestion
  - fleet/intelligence
  - privacy/differential
  - product/appliance
  - esg/analytics
aliases:
  - ADR-09
  - Enterprise Cloud Ingestion
  - Fleet Intelligence Architecture
  - ESG Fleet Analytics
---

# ADR-09: Enterprise Cloud Ingestion, Fleet Intelligence & Operational Boundaries

## Status
Accepted

## Context & Motivation

As the Sovereign workstation engine scales from individual deployment to corporate fleet adoption, two complementary architectural concerns emerge:

1. **Enterprise Cloud Connectors**: Organizations increasingly store documents in cloud silos (Amazon S3 WORM archives, SAP S/4HANA OData records, SharePoint libraries). The engine must be able to ingest these read-only sources without becoming a data exfiltration risk or a transactional database load hazard.
2. **Fleet Analytics with Privacy**: Central IT directors need aggregated productivity and ESG metrics across all workstations without the engine reading raw private file content. This requires privacy-preserving differential analytics.

Additionally, the Epistemic Fallback UI pattern addresses the perennial tension between AI engineers (who want LLM-generated answers always) and product managers (who accept some hallucination as tolerable). A strict retrieval confidence threshold resolves this tension deterministically.

## Decision

### 1. Operational Non-Goals (Hard Boundaries)

The following capabilities are **explicitly prohibited** by architectural governance to maintain the EDR compliance and privacy guarantees established in [ADR-40](ADR-40-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md):

| Non-Goal | Rationale |
| :--- | :--- |
| Live In-Place Mutation (`O_RDWR`) | Sovereign is strictly read-only. Never alters source files or modifies document headers |
| Covert Surveillance | No background screen capture, keystroke logging, or continuous microphone streaming |
| Direct OLTP Production Mirroring | Never runs analytical graph queries against active transactional databases (MSSQL, PostgreSQL) |
| Continuous File Polling | No tight-loop polling; all filesystem watchers use debounced kernel events (`ReadDirectoryChangesW` / `inotify`) |

### 2. Epistemic Fallback UI (The Refusal Resolution Pattern)

When document retrieval confidence falls below threshold (`S_confidence < 0.35`):

1. **Disable Generative Synthesis**: Suppress all LLM-generated narrative text to prevent hallucination
2. **Display Confidence Warning**: Surface an amber `[Low Grounding Confidence (< 35%)]` pill in the UI
3. **Present Nearest Lexical Matches**: Display top lexical results with matching terms highlighted, giving users direct access to source files without misleading AI assertions

**Rationale**: This creates a deterministic, auditable behavior contract. Enterprise legal and compliance teams can predict exactly when the system will and will not synthesize answers.

### 3. Read-Only Enterprise Cloud Connectors

All cloud connectors operate exclusively in **read-only, pull mode** via official change-data-capture interfaces:

| Connector | Protocol | Safety Guarantee |
| :--- | :--- | :--- |
| **Amazon S3 WORM** | S3 Event Notifications (SNS/SQS) → ephemeral memory workers | Objects never re-uploaded; read via `GetObject` with signed URLs |
| **SAP S/4HANA OData** | CDC replica via read-only OData v4 `$filter=ModifiedAt ge <timestamp>` | Queries routed to read replicas; zero load on transactional ERP instances |

### 4. Fleet Intelligence & Differential Privacy Equations

Central IT aggregates productivity and ESG metrics without reading private file content. All measurements use privacy-preserving mathematical primitives:

#### ESG Energy Avoidance Formulation

$$E_{\text{saved}} = \sum_{i=1}^{N} \left( E_{\text{cloud\_query}} - E_{\text{local\_lookup}} \right)$$

$$\text{CO}_2\text{e Averted} = E_{\text{saved}} \times \text{Carbon Intensity Factor}$$

#### Privacy-Preserving MinHash LSH Signatures

Document text is converted into a 128-integer MinHash vector before any fleet transmission:

$$h_{\min}(D) = \min_{s \in D} \left( (a \cdot \text{hash}(s) + b) \bmod p \right)$$

Central servers compute Jaccard similarities between MinHash vectors to identify teams working on overlapping problems — without transmitting any raw document content.

**Privacy Guarantee**: Under LGPD Article 12 and GDPR Recital 26, one-way MinHash signatures mathematically cease to be personal data, qualifying for the anonymous data safe harbor.

### 5. Windows PowerToys Ergonomic Standard

Sovereign adopts the **< 16ms render loop** standard established by Windows PowerToys Run, ensuring the interface feels as responsive as native OS tools. Every query result render must complete within a single 60Hz frame budget.

## Consequences

**Positive:**
- Hard operational non-goals create a verifiable, auditable security posture for enterprise CISOs
- Epistemic Fallback UI eliminates hallucination risk in regulated environments (healthcare, legal, finance)
- S3 and OData connectors extend corpus coverage beyond local files while maintaining zero-write safety
- MinHash fleet analytics provide organizational value without violating privacy law

**Negative:**
- Epistemic fallback (silence below confidence threshold) may frustrate users who prefer approximate answers over no answer
- SAP OData CDC requires customer IT to provision read-replica endpoints, adding implementation complexity
- MinHash false-positive rate depends on corpus size; sparse personal corpora may show spurious Jaccard overlaps

## Supersedes / Complements
- Complements [ADR-40: Two-Pronged Hybrid Retrieval](ADR-40-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md)
- Complements [ADR-44: Zero-Knowledge Telemetry](ADR-44-Zero-Knowledge-Telemetry-Zstandard-Compression-and-Privacy-Architecture.md) (fleet payload format)
- Complements [ADR-39: Security Clearance Governance](ADR-39-Security-Clearance-Governance-and-Resource-Quotas.md)

## Related
- [Manual 07: Scaling Topologies, Bottlenecks & Commercial Playbook](../appliance/07_scaling_topologies_bottlenecks_and_commercial_playbook.md)
- [Chapter 23: Sovereign Knowledge Appliance & Commercial Stack Architecture](../23_sovereign_knowledge_appliance_and_commercial_stack.md)
