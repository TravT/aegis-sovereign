---
title: "ADR-07: Virtual Container Streaming & Cognitive Graph Intelligence"
type: adr
category: decision
status: accepted
date: 2026-09-22
last_reviewed: 2026-09-22
node: homelab
domain: indexing-graph
tags:
  - homelab/adrs
  - architecture/decisions
  - indexing/virtual-streams
  - archive/hdx
  - graph/knowledge
  - product/appliance
  - security/edrsafe
aliases:
  - ADR-07
  - Virtual Container Streaming
  - Cognitive Graph Intelligence
  - HedEx Streaming Architecture
---

# ADR-07: Virtual Container Streaming & Cognitive Graph Intelligence

## Status
Accepted

## Context & Motivation

Enterprise technical documentation is frequently distributed inside proprietary compressed container formats such as Huawei HedEx (`.hdx`), nested `.zip` archives, and `.tar.gz` bundles. Naively extracting these archives to disk introduces several critical failure modes:

1. **Zip Bomb Exposure**: Malformed or adversarially crafted archives can decompress to hundreds of gigabytes, exhausting disk space and triggering kernel OOM events.
2. **Anti-Ransomware Heuristic Trips**: Writing thousands of extracted files to disk at high speed triggers CrowdStrike Falcon, SentinelOne, and Microsoft Defender heuristics trained to detect ransomware bulk-write patterns.
3. **Disk Quota Violations**: Temporary extraction doubles the required storage footprint for every archive indexed.
4. **File Path Ambiguity**: Nested archives can contain members with identical relative paths, causing naming collisions.

Additionally, enterprise knowledge graphs require structured entity and relationship extraction beyond flat text retrieval — linking People, Organizations, Ticket IDs, Server Hostnames, and Alarm Codes into a traversable force-directed graph.

## Decision

### 1. Zero-Decompression In-Memory Virtual Container Streaming

All compressed archive formats (`.hdx`, `.zip`, `.tar.gz`) are processed exclusively as **in-memory virtual byte streams** using OS read-only kernel flags (`O_RDONLY`). Files are **never extracted to disk**.

**Processing Pipeline:**

```
Target Archive: `S6730_V200R021_Manual.hdx`
                      │
          OS Kernel Read: O_RDONLY
                      │
           Streaming Buffer (zipfile)
                      │
   ┌───────────────────────────────────────┐
   ▼                                       ▼
Read profile.xml                    Iterate Members
(Extract Hardware Model,            (Filter: .html, .xml,
 Firmware, Command Tree)             .txt, .md)
   │                                       │
   └───────────────────┬───────────────────┘
                       ▼
       Zip Bomb & Decompression Guardrails
       (Size Ratio < 100x & Uncompressed < 500 MB)
                       │
                       ▼
         Selectolax Clean Text Extraction
                       │
   ┌───────────────────────────────────────┐
   ▼                                       ▼
Prong 1: SQLite FTS5               Prong 2: FastEmbed int8
(CLI commands & hex alarms)        (Natural-language troubleshooting)
```

**Composite Virtual URIs**: Every indexed archive member receives a deterministic virtual URI:

```
virtual://C:/Manuals/S6730.hdx#topics/alarm_0x40000001.html
```

**Safety Guardrails:**
- Compression ratio must be `< 100×` (`file_size / compress_size`)
- Uncompressed member must be `< 500 MB`
- Path traversal sanitized: members with `..` prefixes or absolute paths are silently dropped
- Only text-bearing members processed: `.html`, `.xhtml`, `.xml`, `.txt`, `.md`

### 2. Obsidian-Style Force-Directed Graph Explorer

The Cognitive Graph module extracts and stores named entities and their relationships in the SQLite WAL graph store, rendered via a physics-simulated D3-Force / WebGL visualization:

- **Entity Node Types**: `Person`, `Server`, `Organization`, `TicketID`, `AlarmCode`, `Document`, `Theme`
- **Edge Relation Types**: `signed_by`, `deployed_on`, `authored`, `references`, `resolves`, `managed_by`
- **2-Hop Neighborhood Isolation**: Selecting any node isolates its immediate entity neighborhood and renders a contextual dossier
- **Semantic Cluster Rendering**: Visual grouping of documents, people, technical entities by thematic affinity

### 3. Executive KPI & Gamification Engine

The desktop UI surfaces three live cognitive value metrics:

| KPI | Formula |
| :--- | :--- |
| **Tokens Saved Odometer** | `Σ(Corpus Tokens − Retrieved Evidence Tokens)` |
| **Averted Cloud Cost** | `Tokens Saved × $3.00/M tokens` |
| **Dark Data Resurrected** | Count of indexed OCR plates, diagrams, and proprietary archive topics |

## Consequences

**Positive:**
- Zero disk write side-effects during archive ingestion eliminates anti-ransomware heuristic trips
- Zip bomb protection guardrails prevent resource exhaustion
- Virtual URI addressing provides stable, globally unique references for citations
- Graph Explorer enables cross-document entity traversal unavailable in flat-file retrieval systems

**Negative:**
- In-memory streaming requires the full archive to be buffered in RAM for processing; very large (>500 MB uncompressed) archives require chunked streaming or skipping
- D3-Force WebGL graph rendering requires a Chromium-based web view and is not available in terminal-only deployments

## Supersedes / Complements
- Complements [ADR-40: Two-Pronged Hybrid Retrieval](ADR-40-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md) (virtual URIs feed both retrieval prongs)
- Complements [ADR-37: Zero-Copy Workstation Indexing](ADR-37-Zero-Copy-Workstation-Indexing-and-Serverless-Desktop-Engine.md) (same O_RDONLY discipline)
- Complements [ADR-35: Sovereign Knowledge Appliance Packaging](ADR-35-Sovereign-Knowledge-Appliance-Packaging-and-Commercial-Architecture.md)

## Related
- [Manual 08: Desktop Workstation & Corporate DLP](../appliance/08_desktop_workstation_and_corporate_dlp.md)
- [Chapter 21: Hybrid RAG & Semantic Retrieval Architecture](../21_hybrid_rag_and_semantic_retrieval_architecture.md)
