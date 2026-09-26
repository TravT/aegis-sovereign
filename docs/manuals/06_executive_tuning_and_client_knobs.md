---
title: "Manual 06: Executive Tuning, Retrieval Modes & Client Knobs"
category: operations
type: documentation
node: homelab
domain: ai-data
tags:
  - homelab/appliance
  - product/appliance
  - ai/tuning
  - commercial/manual
status: active
last_reviewed: 2026-09-17
aliases:
  - Executive Tuning & Client Knobs
  - Retrieval Calibration Guide
---

# 🎛️ Manual 06: Executive Tuning, Retrieval Modes & Client Knobs

> **Parent Suite**: [Sovereign Appliance Manual Index](README.md)  
> **Previous Step**: [Manual 05: Ingestion & Tagging Runbook](05_ingestion_and_tagging_runbook.md)  
> **Target Audiences**: Managing Partners, Family Office CIOs, Compliance Officers, AI Operators  

---

## 1. The Philosophy of Client-Facing Knobs

In high-stakes enterprise sectors (elite law firms, private wealth management, diagnostic healthcare), **one-size-fits-all AI fails**. 

A tax lawyer reviewing a merger contract requires **broad, exhaustive discovery** where missing a single indemnity subclause can cost millions. Conversely, a family office CFO checking quarterly server expenses demands **high-precision, single-chunk factual answers** to minimize cloud token expenditure.

The Aegis Sovereign Appliance provides an **Executive Tuning Console** with calibrated knobs and dials allowing clients to dictate the AI's retrieval behavior.

---

## 2. The Three Retrieval Modes

The appliance supports three distinct retrieval strategies switchable at runtime via MCP tool calls or web UI:

```text
Retrieval Strategy Matrix:
  ├── 1. High-Precision Mode   -> Strict threshold, 2-3 chunks, 99%+ token reduction (Default)
  ├── 2. Legal Discovery Mode  -> Broad recall, 7-10 chunks, deep cross-exhibit referencing
  └── 3. Exact Entity Mode     -> 2.0x BM25 lexical priority for CNPJ, docket & transaction IDs
```

### Mode Comparison Matrix

| Tuning Dimension | High-Precision (`high_precision`) | Legal Discovery (`legal_discovery`) | Exact Entity (`exact_entity`) |
| :--- | :--- | :--- | :--- |
| **Primary Goal** | Instant Factual Precision & Max Token Savings | Zero-Omission Exhibit & Precedent Discovery | Strict Numeric & Identifier Matching |
| **Default Chunks** | 2 to 3 chunks | 7 to 10 chunks | 3 to 5 chunks |
| **Cosine Threshold** | Strict ($\ge 0.025$ RRF) | Permissive ($\ge 0.010$ RRF) | Moderate |
| **Lexical vs Dense Weight** | Balanced ($1.0 : 1.0$) | Balanced with flat distribution ($k=30$) | Lexical Priority ($2.0 \times \text{BM25}$) |
| **Token Reduction** | **99.3% to 99.7%** (~200 tokens) | **97.5% to 98.5%** (~900 tokens) | **99.0% to 99.4%** (~350 tokens) |
| **Best For** | "What was our total rent in Q2?", quick checks | Contract reviews, litigation subpoenas, due diligence | Searching by CNPJ, CPF, TED code, Court Docket |

---

## 3. The Executive Knobs & Sliders

### A. Discovery Depth (`max_chunks`)
- **Range**: `1` to `10` blocks.
- **Client Knob Effect**: Controls the volume of evidence fed into the AI context.
- **Visual Feedback**: The Executive UI displays a live estimated token consumption badge:
  - $1\text{ chunk} \approx 150\text{ tokens}$ (Flash answer)
  - $3\text{ chunks} \approx 280\text{ tokens}$ (Standard balanced context)
  - $10\text{ chunks} \approx 950\text{ tokens}$ (Comprehensive multi-exhibit dossier)

### B. Confidence Floor (`confidence_floor`)
- **Range**: `0.00` to `0.05` RRF score.
- **Client Knob Effect**: Discards marginal, low-confidence paragraphs that score below the threshold, ensuring the model never sees irrelevant noise.

### C. Relational Graph Link Injection (`include_graph_dossier`)
- **Type**: Boolean Toggle.
- **Client Knob Effect**: When enabled, the engine automatically traverses the SQLite WAL graph to extract corporate shareholdings, associated individuals, and monetary flows, appending a structured relational dossier directly to the evidence package.

---

## 4. How to Calibrate via MCP and API

### Via Model Context Protocol (`agy` / Claude Desktop)
```json
{
  "name": "sovereign_optimize_context",
  "arguments": {
    "query": "Cláusulas de indenização e responsabilidade civil do contrato social",
    "corpus": "paperless",
    "max_chunks": 8,
    "retrieval_mode": "legal_discovery",
    "confidence_floor": 0.012,
    "include_graph_dossier": true
  }
}
```

### Via Direct REST Gateway
```bash
curl -s -X POST http://<APPLIANCE_IP>:8765/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Traefik port 443 invariant",
    "retrieval_mode": "legal_discovery",
    "max_chunks": 5,
    "confidence_floor": 0.015
  }' | jq .token_economics
```

---

## 5. Summary & Full Manual Complete

You have completed the **Aegis Sovereign Knowledge Appliance Manual Suite**. For architecture references and cluster inventory, consult:
* [Master Manual Index](README.md)
* [ADR-35: Sovereign Knowledge Appliance Packaging](../adrs/ADR-35-Sovereign-Knowledge-Appliance-Packaging-and-Commercial-Architecture.md)
* [Chapter 23: Sovereign Knowledge Appliance Architecture](../23_sovereign_knowledge_appliance_and_commercial_stack.md)
