---
title: "ADR-11: Universal Multimodal Ingestion Primitives & Deep-Tech Telecom Signaling Layer"
type: "adr"
category: "architecture"
status: "accepted"
date: "2026-09-23"
last_reviewed: "2026-09-23"
node: "homelab"
domain: "multimodal-telecom"
tags:
  - aegis/adrs
  - architecture/decisions
  - ingestion/multimodal
  - telecom/signaling
  - spatial/ocr
  - product/appliance
aliases:
  - "ADR-11"
  - "Universal Multimodal Ingestion"
  - "TelcoTrace Signaling Engine"
  - "Spatial OCR Plate Binding"
---

# ADR-11: Universal Multimodal Ingestion Primitives & Deep-Tech Telecom Signaling Layer

## Status
Accepted

## Context & Motivation

As the Aegis Sovereign Knowledge Appliance expands beyond standard document formats (PDF, EML, DOCX), two technical challenges emerge:

1. **Complex Multimodal Formats (CAD, Blueprints, Schematics)**: High-resolution schematics, architectural elevations, and CAD drawings cannot be effectively searched via raw vector embeddings alone. Vector representations fail to capture 2D spatial layouts, component coordinates, or circuit impedances.
2. **Deep-Tech Telecom Signaling (5G SA, 4G, IMS, PTMF)**: Standard text chunking and vectorization flood vector stores with hex dumps and raw protocol headers, rendering search useless for network troubleshooting and forensic analysis.

Maintaining bespoke parsers for every proprietary file format creates unacceptable code complexity and technical debt.

## Decision

### 1. Three Universal Multimodal Ingestion Primitives

All unstructured, graphical, or proprietary formats must be reduced to **Three Universal Ingestion Primitives**:

```
Any Complex Format (.skp, .dwg, .pptx, .eml, .hdx, .pdf, .pcap)
                            │
       ┌────────────────────┼────────────────────┐
       ▼                    ▼                    ▼
1. Structural Text   2. Layout / Plates   3. Metadata Schema
 (Tokens, Tables,      (Rendered Canvas,    (Headers, Senders,
   DOM nodes)            Visual Raster)       Entity Attributes)
```

#### A. Spatial OCR & 2D Plate Binding
- Schematics and elevations are rasterized into 2D visual plates
- FastEmbed CLIP ViT-B-32 indexes macro-visual layout (identifying page type, e.g., elevation drawing)
- Docling / Tesseract extracts spatial bounding boxes $[x_0, y_0, x_1, y_1]$ for all alphanumeric text annotations
- Queries for exact components hit Prong 1 (SQLite FTS5) in $< 1\text{ ms}$, rendering the document canvas with a gold bounding box over graphic coordinates

#### B. Cross-Document Relational Graph Stitching
- Stratum 2 (SQLite WAL Graph) extracts and stores relational triples globally across ingestions:
  $$\text{Presentation} \xrightarrow{\text{EXTRACTS}} (\text{Alice} \xrightarrow{\text{MEMBER\_OF}} \text{Core Networks})$$
  $$\text{Email Header} \xrightarrow{\text{RESOLVES}} (\text{Alice} \xrightarrow{\text{AUTHORED}} \text{Thread \#402})$$
- 2-hop BFS in SQLite resolves cross-document entity ownership in $< 1\text{ ms}$ without external LLM calls

### 2. Deep-Tech Telecom Signaling Layer (TelcoTrace-Core)

Raw multi-generation telecom captures (`.pcap`, `.pcapng`, Huawei `.ptmf`, HTTP/2 JSON logs) are parsed into **State Machines and Synthesized Call Ladders** rather than raw text chunks:

```
                            Raw Multi-Gen Traces
          (.pcap, .pcapng, Huawei .ptmf, HTTP/2 JSON logs)
                                 │
                                 ▼
          ┌─────────────────────────────────────────────┐
          │       Zero-Copy Streaming Dissector         │
          │  (Rust pcap / HTTP2 HPACK / ASN.1 / PTMF)  │
          └──────────────────────┬──────────────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  ▼                             ▼
         [5G Core SBI / N2 / N4]       [4G / IMS / PTMF]
         • HTTP/2 (JSON ProblemDetails)• SIP Call-ID & Responses
         • NGAP RAN/AMF UE IDs         • Diameter Session-Id & AVPs
         • PFCP F-SEID / Node ID       • Huawei Release Causes
                  │                             │
                  └──────────────┬──────────────┘
                                 ▼
          ┌─────────────────────────────────────────────┐
          │     Session Correlator & State Builder      │
          │ (SUPI, SUCI, GPSI, Call-ID, PDU Session ID) │
          └──────────────────────┬──────────────────────┘
                                 │
          ┌──────────────────────┴──────────────────────┐
          ▼                                             ▼
   [Prong 1: SQLite WAL]                       [Prong 2: FastEmbed int8]
   • Exact SUPI/IMSI, GPSI, TEID               • Synthesized Call Ladders
   • 3GPP ProblemDetails, SIP 4xx/5xx          • Vectorized failure reasons
   • Byte offset slicing (< 1ms)               • Cross-modal diagnostic search
```

**FastMCP Interface for Frontier Agents (MiniMax M2.7 / Claude)**:
1. `search_sessions(query, generation, status)`: Hybrid RRF search over synthesized ladders
2. `get_session_ladder(session_key)`: Renders full ASCII sequence diagrams with failing nodes highlighted
3. `get_raw_pcap_slice(session_id, output_path)`: Uses stored `byte_start` and `byte_end` offsets to carve isolated PCAP slices in $< 10\text{ ms}$
4. `trace_subscriber_journey(supi_or_gpsi, time_window)`: Multi-interface timeline correlating N1/N2 Registration $\to$ N7 Policy $\to$ N4 Bearer $\to$ IMS SIP

### 3. Tier 3 Datacenter: Cognitive NWDAF & Closed-Loop Remediation

- **Zero-Copy Optical Ingestion**: AF_XDP and DPDK ring buffers with kernel eBPF probes intercept HTTP/2 SBI payloads before TLS encryption (50k–200k TPS)
- **60-Second Rolling In-Memory Ring Buffer**: Purges raw payloads of successful sessions; persists only metadata and anomalous sessions
- **4-Level Precision Remediation**:
  - Level 1: Assisted Triage (synthesizes sequence diagrams & diagnostic tickets)
  - Level 2: Proposed Fix (one-click approval of API payloads)
  - Level 3: Supervised Closed-Loop (automatic NF drain / rate-limit with instant rollback)
  - Level 4: Autonomous Recovery (real-time traffic diversion, $< 500\text{ ms}$)
- **Safety Circuit Breakers**: 10% max traffic diversion per 15-min window without M-of-N sign-off; pre-flight validation against containerized digital twin sandbox (`my5G-core`); Ceph S3 WORM audit logging

## Consequences

**Positive:**
- Eliminates parser proliferation by reducing all formats to 3 Universal Ingestion Primitives
- Spatial OCR bounding box binding enables sub-millisecond graphical schematic lookups
- TelcoTrace-Core converts noisy packet dumps into actionable state machines and sequence diagrams
- Closed-loop remediation safeguards prevent runaway network disruption

**Negative:**
- CLIP ViT-B-32 visual plate embedding adds ~30MB memory overhead for visual indexers
- DPDK / AF_XDP kernel optical probes require specialized Linux network interface drivers in Tier 3 datacenter deployments

## Related
- [ADR-06: Two-Pronged Hybrid Retrieval](ADR-06-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md)
- [ADR-07: Virtual Container Streaming](ADR-07-Virtual-Container-Streaming-and-Cognitive-Graph-Intelligence.md)
- [Chapter 25: Universal Multimodal Ingestion & TelcoTrace Engine](../../../25_universal_multimodal_ingestion_telcotrace_and_smb_playbook.md)
