---
title: "Aegis ADR-17: Universal Layout Parsing, Contextual Chunks & Canonical Knowledge Ontology"
type: "adr"
category: "architecture"
status: "accepted"
date: "2026-10-15"
last_reviewed: "2026-10-15"
node: "homelab"
domain: "ingestion-formats"
tags:
  - aegis/adrs
  - architecture/decisions
  - ingestion/formats
  - knowledge-graph/ontology
  - product/appliance
aliases:
  - "Aegis ADR-17"
  - "Canonical URNs"
  - "Truth Gates"
---

# Aegis ADR-17: Universal Layout Parsing, Contextual Chunks & Canonical Knowledge Ontology

## Status
Accepted by the owner on 2026-10-15 as the target architecture for [PRJ-06](../../PRJ-06-Hybrid-RAG-Engine-Obsidian-Paperless.md) Phases 13 and 14. **Nothing here is implemented yet.** Each decision is adopted for real only when its gate in "How we will know" passes; until then the current pipeline stays. Extends [Aegis ADR-13](ADR-13-File-Type-Handlers-Conformance-Gate-and-Tiered-Fidelity-Ingestion.md) (handler contract and conformance gate, which stay) and [Aegis ADR-12](ADR-12-Pluggable-Structure-Extraction-Tier-Size-Policy-and-Search-Time-Deduplication.md) (structure layer, search-time collapse). Source: the owner's strategic review of 15 Oct 2026 (Antigravity brain, `aegis_cognitive_ontology_critique_and_adr17.md`).

## Date
2026-10-15

## Context
After Phase 12 the vault holds 46,693 native manual pages (Huawei USC and UPCF 26.1.0), 7,654 composite records, 160 wiki notes and Paperless documents, served from the Dell 7390 (job v80). Phase 14 adds many network functions and releases, and about 2,000 enterprise project files: low-level designs (LLDs), spreadsheets, slide decks and TAC email threads. Checked against the code on 15 Oct:

1. **Formats are already handled, deterministically.** Aegis ADR-13 handlers cover docx, xlsx, xls, pptx, eml, html, xml, csv, markdown and text, each passing the conformance gate (lossless from source spans, deterministic, bounded, robust). What they cannot read is layout: PDFs, scanned pages, slides whose meaning is in the arrangement, tables drawn as images.
2. **Chunks carry only local context.** ADR-13 chunks start with `[document > heading > sub-heading]`. The manual vectors (`sovereign_chunks`) embed `title: <page title> | text: <first 1,500 characters>`: one vector per page, so the product and release (in the title) are there, but not the topic path, and the text past 1,500 characters is not in the vector at all.
3. **Identity is tied to paths.** Records are keyed by `doc_identifier`: an archive path with an entry name, a wiki path with `::part::nnnn`, or a short id (`ALM-20104`, `ADR-16`). Moving a corpus rewrites ids (`/tmp/docs_rag_gemini` relocation, Phase 11), the same alarm exists in USC and UPCF under different archive paths, and two ADR series collided on one id until Phase 12.3.
4. **The graph is a fixed vocabulary.** `core/graph/extractor.py` matches entities from static dictionaries (`KNOWN_SERVICES`, `KNOWN_ORGANIZATIONS`) and regular expressions, so a new product line needs code changes; graph and vector retrieval do not inform each other beyond the dossier.
5. **The Dell is the binding constraint.** About 2 GB free; `sovereign-server` goes from ~143 MiB idle to 750-1,483 MiB when the Gemma encoder loads. Layout models and generative models do not fit beside it.

## Decision

### 1. Layout-aware parsing as a handler backend, not a replacement
Documents whose meaning depends on layout (PDF, scanned pages, image tables, complex slides) are parsed by a layout model (Docling or MinerU, choice by the gate below), packaged as an ADR-13 `FormatHandler`. Its output is the same `ParsedDocument` (sections, heading paths, tables kept whole as one atomic section with their header row) and goes through the same chunker and conformance gate. The deterministic handlers stay the default for formats they read losslessly; a layout handler is used where they cannot.

This amends ADR-13 in one point: a layout handler may use a model. The model is vendored (air-gapped, pinned) and runs only in the ingestion plane (decision 5). Because a PDF cannot be proven lossless from byte spans, a layout handler's gate is **coverage** instead: its text covers at least 98 % of the words of the file's text layer (where one exists), every table cell of the fixture set is recovered, and runs are deterministic for a pinned model.

### 2. Contextual embeddings
Before a chunk is embedded, a context header of about 50-100 tokens is prepended, built deterministically from structure, not generated:

```text
[Vendor: Huawei | Product: USC 26.1.0 | Book: Alarm Reference | Topic: Alarms > Link > ALM-20104 | Doc: Link Bear Quality]
<chunk text>
```

For project files: project, document type, revision, system and section path. The header goes into the embedded string (dense and BM25); the stored and displayed text stays the clean chunk. Long manual pages are chunked like other documents instead of truncated at 1,500 characters, each chunk with the page's header. Generated (LLM-written) context summaries are not used: they would need a model on every chunk and could not be checked verbatim.

### 3. Canonical entity URNs
Every document, section and entity gets a canonical, path-free identity:

```text
urn:<domain>:<namespace>:<type>:<slug>[@<revision>][#<fragment>]
```

| Domain | For | Pattern | Example |
| :--- | :--- | :--- | :--- |
| `telco` | Vendor manuals, alarms, MML commands, counters | `urn:telco:<vendor>:<product>:<type>:<id>` | `urn:telco:huawei:usc:alarm:1003@26.1.0`, `urn:telco:huawei:upcf:mml:dsp_optmodule@26.1.0` |
| `infra` | ADRs, runbooks, standards | `urn:infra:<series>:<type>:<id>` | `urn:infra:aegis:adr:adr-17`, `urn:infra:homelab:adr:adr-16`, `urn:infra:3gpp:standard:ts-29.518@rel16` |
| `project` | LLDs, HLDs, matrices, decks | `urn:project:<project>:<doctype>:<slug>` | `urn:project:5gc-brazil:lld:numa-dpdk@v2.1#sec-4.2`, `urn:project:5gc-brazil:matrix:vlan-ip#sheet:upf_n6` |
| `comms` | Email threads, tickets, RCAs | `urn:comms:<channel>:<kind>:<id>` | `urn:comms:email:thread:huawei-tac-sr-2026-9912`, `urn:comms:jira:ticket:core-4821` |
| `asset` | Diagrams, slides, figures | `urn:asset:<source-doc-slug>:<kind>:<id>` | `urn:asset:5gc-brazil-lld:figure:fig-3`, `urn:asset:core-kickoff-deck:slide:18` |

Rules: no host paths; lower-case slugs from a fixed normaliser; the **product is part of the identity** (USC and UPCF alarm 1003 are two URNs, so releases and network functions never cross-talk), the release or revision is a pin (`@`, an unpinned lookup means the latest and says so); fragments address sections, sheets, rows, slides and figure boxes; every URN carries the record's clearance level. Standards live under `infra` (the review's `urn:standard:` would be a sixth domain). The URN is added beside `doc_identifier` (a column and a payload field), not instead of it: existing ids, exact lookups and links keep working, and Phase 13.1 maps them.

### 4. Four truth gates for extracted entities and relations
An entity or relation enters the graph only through these gates, in order:

1. **Syntax**: the id matches its grammar (alarm code range, MML verb and object, counter id, URN pattern).
2. **Verbatim anchor**: the entity and each attribute exist verbatim at a recorded character span of the source chunk. Nothing without an anchor is stored.
3. **Consensus**: mentions are correlated across sources (manual, spreadsheet, incident thread); confidence 0.5 for a single source, 1.0 for agreement of two or more independent sources, lower when sources disagree, and the disagreement is kept.
4. **Inverse check**: a verifier must show the relation is asserted in the anchored text (a question generated from the relation is answered by the source span). This gate needs a language model, so it runs only in the ingestion plane; relations that did not pass it are marked `unverified` and never presented as fact.

Gates 1 and 2 are deterministic and run everywhere (Phase 13.2 adds them to `core/ingest/conformance.py`). The static extractor dictionaries remain as one candidate source among others; candidates still have to pass the gates.

### 5. Asymmetric execution: real-time serving on the Dell, batch ingestion elsewhere
- **Serving plane (Dell 7390, always on)**: exact lookups (SQLite B-tree and FTS5), hybrid search (Qdrant and the Gemma query encoder), graph reads, the portal. It never loads a layout model or a generative model.
- **Ingestion plane (batch)**: layout parsing, chunking with context headers, embedding, URN assignment, gates 3 and 4. Primary: the RTX 5070 desktop, **woken only with the owner's permission for each run** (house rule). Fallback: the Dell's CPU, inside `systemd-run --user --scope -p MemoryMax=2.5G -p CPUQuota=150%` and never 03:30-05:30 (enforced by `tools/bounded_run.py` since step 12.6).
- **Hand-off**: the ingestion plane writes new stores (database copy, Qdrant collection or snapshot), never the live ones; the Dell switches to them after a backup, with a dead-man revert, as every vault change is done today.

## How we will know (adoption gates)
- **Layout handler**: coverage gate on fixtures (decision 1), peak memory measured inside the 2.5 GB cap for the CPU fallback, and a choice between Docling and MinerU on 20 owner-supplied PDFs and decks.
- **Contextual embeddings**: re-embed a sample (GPU desktop, with permission) and re-run the O1 A/B and the Phase 14.1 real-question set; adopted only if hit@1 and hit@5 do not drop on any set and rise on at least one.
- **URNs**: every record of the vault maps to exactly one URN (no collisions, none unmapped) in a dry run before anything is written.
- **Gates**: the anchor gate rejects a seeded set of fabricated attributes (zero accepted); the consensus scores are spot-checked by the owner on 50 relations.
- **Answers**: the Phase 14.1 scorecard (faithfulness, relevance, context recall including cautions and prerequisites, diagram and dossier resolution) is measured before and after each adoption.

## Consequences
- Formats the deterministic handlers already read stay deterministic and provably lossless; only layout-dependent documents depend on a model, and only at ingest.
- Re-embedding is required for decision 2 (46,693 manual pages plus every new corpus): an ingestion-plane run per corpus.
- The schema gains a `urn` column, a URN index and gate fields on graph relations (`anchor`, `confidence`, `verified`); this is a vault schema change and follows the backup and dead-man procedure, reported to the owner before it is deployed.
- Search-time collapse (ADR-12, Phase 12.3) can key on URNs instead of paths.
- Ingestion gets slower and more expensive per document; serving latency and the Dell's memory do not change.

## Alternatives considered
- **Replace all handlers with a layout model**: rejected; the deterministic handlers are lossless by proof and need no model, and the formats of the coming project files (docx, xlsx, pptx, eml) are already covered.
- **LLM-written context summaries per chunk**: rejected for now (decision 2): a model call per chunk, and not checkable verbatim.
- **LLM OpenIE triple extraction** (the review's fifth proposal): deferred to Phase 14; if adopted it is one more candidate source behind the four gates, never a direct writer to the graph.
- **URNs instead of `doc_identifier`**: rejected; side by side keeps every exact lookup, link and test working during the migration.

## Related
- [PRJ-06](../../PRJ-06-Hybrid-RAG-Engine-Obsidian-Paperless.md) §0: steps 13.1 (URN mapping), 13.2 (gates 1-2), 14.2 (universal indexing tool), 14.3 (many NFs and releases).
- [Aegis ADR-11](ADR-11-Universal-Multimodal-Ingestion-and-TelcoTrace-Signaling.md), [Aegis ADR-12](ADR-12-Pluggable-Structure-Extraction-Tier-Size-Policy-and-Search-Time-Deduplication.md), [Aegis ADR-13](ADR-13-File-Type-Handlers-Conformance-Gate-and-Tiered-Fidelity-Ingestion.md), [Aegis ADR-16](ADR-16-Archive-Streaming-Checkpoint-Index-Lazy-Preview-and-Memory-Budget.md).
- [Dell memory budget](../../../operations/dell_memory_budget.md).
