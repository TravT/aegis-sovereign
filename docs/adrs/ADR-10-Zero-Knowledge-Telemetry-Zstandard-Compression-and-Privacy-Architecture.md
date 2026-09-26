---
title: "ADR-10: Zero-Knowledge Telemetry, Zstandard Compression & Privacy Architecture"
type: adr
category: decision
status: accepted
date: 2026-09-22
last_reviewed: 2026-09-22
node: homelab
domain: privacy-telemetry
tags:
  - homelab/adrs
  - architecture/decisions
  - privacy/zero-knowledge
  - telemetry/fleet
  - compression/zstandard
  - product/appliance
  - compliance/lgpd-gdpr
aliases:
  - ADR-10
  - Zero-Knowledge Telemetry
  - Zstandard Fleet Compression
  - Privacy Architecture
---

# ADR-10: Zero-Knowledge Telemetry, Zstandard Compression & Privacy Architecture

## Status
Accepted

## Context & Motivation

Enterprise fleet deployments require aggregated analytics for IT governance — token savings, CPU utilization, adoption metrics — but cannot expose raw file paths, document content, or user identities to central servers. Standard JSON telemetry payloads are verbose (2-4 KB each) and transmit over enterprise proxies that log cleartext, creating compliance risk.

Three specific problems require simultaneous resolution:

1. **Privacy Paradox**: Fleet analytics are required for organizational value; raw data transmission violates LGPD/GDPR
2. **Payload Size**: Standard JSON payloads (3.5 KB) are too large for per-user, per-hour reporting at enterprise scale
3. **Community Trust**: The free Community/Desktop tier must be mathematically verifiable as containing zero telemetry code — not just a policy promise

## Decision

### 1. Network Hermeticism Tier Model

| Tier | Telemetry Behavior | Verification |
| :--- | :--- | :--- |
| **Community / Free** | Contains **zero** networking code, telemetry SDKs, or external sockets. Outbound traffic is mathematically zero | Static binary analysis: no socket syscalls in community build |
| **Corporate Fleet Edition** | Opt-in only via administrative Group Policy Object (GPO) or signed configuration profile | Requires explicit admin action; cannot be enabled by end user |

### 2. Zstandard Dictionary Compression

Standard compression algorithms perform poorly on small payloads because generic dictionary headers exceed data savings. Sovereign uses an **offline-trained 32 KB dictionary** (`fleet_v1.zstd_dict`) built from a representative corpus of fleet telemetry JSON samples.

**Compression Pipeline:**

```
Raw Telemetry JSON (3.5 KB)
         │
         ▼
Zstandard Compressor ──► Loaded Dictionary (fleet_v1.zstd_dict, 32 KB)
(Level 3: < 0.2ms CPU)
         │
         ▼
Compressed Binary Payload (174 bytes)
         │
         ▼
Cryptographic Nonce + AES-256-GCM Envelope (202 bytes total wire footprint)
```

**Result**: 3,500-byte JSON → **under 180 bytes** (95% reduction) with `< 0.2 ms` CPU overhead.

### 3. Privacy-Preserving Transformation Pipeline

All telemetry undergoes a four-stage transformation before serialization:

| Stage | Transformation | LGPD/GDPR Basis |
| :--- | :--- | :--- |
| **User Pseudonymization** | `HMAC-SHA256(username, salt_fleet)` — irreversible one-way hash | Pseudonymization under GDPR Rec. 26 |
| **Content Discard** | File paths, filenames, and raw document chunks are **completely excluded** from serialization | Data minimization principle (LGPD Art. 6.III) |
| **Statistical Aggregation** | Only aggregate metrics transmitted: chunk counts, query latency percentiles, token savings totals | Legitimate interest (LGPD Art. 7.IX) |
| **MinHash Signature** | Team overlap alerts use 128-integer MinHash (see [ADR-43](ADR-43-Enterprise-Cloud-Ingestion-Fleet-Intelligence-and-Operational-Boundaries.md)) | Anonymous data safe harbor (LGPD Art. 12) |

### 4. The "Glass Box" Inspector

The desktop UI provides an **explicit telemetry inspection dialog** accessible from Settings that:

- Shows a real-time preview of the exact bytes that would be transmitted
- Provides a **24-hour pause toggle** (no re-enrollment prompt for 24 hours)
- Displays timestamp of last transmission and receiving server endpoint
- Allows full opt-out with immediate local cache purge

### 5. Fleet Payload Schema

The transmitted payload (pre-compression) contains only aggregate, non-personal fields:

```json
{
  "fleet_id": "<HMAC-SHA256 of org domain>",
  "station_id": "<HMAC-SHA256 of machine SID>",
  "report_hour_utc": "2026-09-22T21:00Z",
  "chunks_indexed": 12400,
  "queries_total": 847,
  "p50_latency_ms": 1.2,
  "p99_latency_ms": 3.8,
  "tokens_saved_estimate": 2840000,
  "minhash_sig": [/* 128 integers */]
}
```

**No file paths. No filenames. No document content. No raw user identifiers.**

## Consequences

**Positive:**
- Community tier verifiably contains zero networking code — a measurable, auditable claim that can be validated by enterprise security teams
- 95% payload compression reduces fleet telemetry infrastructure costs proportionally
- Glass Box Inspector builds user trust and satisfies LGPD Art. 18 transparency obligations
- Privacy-preserving MinHash signatures provide fleet intelligence without violating data minimization principles

**Negative:**
- Pre-trained Zstandard dictionary (`fleet_v1.zstd_dict`) must be versioned and distributed with corporate fleet binaries; dictionary mismatches cause decompression failures
- One-way HMAC pseudonymization prevents debugging individual station issues by fleet administrators — requires station self-reporting diagnostics

## Supersedes / Complements
- Complements [ADR-43: Enterprise Cloud Ingestion & Fleet Intelligence](ADR-43-Enterprise-Cloud-Ingestion-Fleet-Intelligence-and-Operational-Boundaries.md) (defines the data that MinHash operates on)
- Complements [ADR-42: Zero-Friction Onboarding](ADR-42-Zero-Friction-Onboarding-Ambient-Connectors-and-Data-Portability.md) (capsule uses same AES-256-GCM envelope)
- Complements [ADR-39: Security Clearance Governance](ADR-39-Security-Clearance-Governance-and-Resource-Quotas.md)

## Related
- [Manual 07: Scaling Topologies, Bottlenecks & Commercial Playbook](../appliance/07_scaling_topologies_bottlenecks_and_commercial_playbook.md)
- [Chapter 23: Sovereign Knowledge Appliance & Commercial Stack Architecture](../23_sovereign_knowledge_appliance_and_commercial_stack.md)
