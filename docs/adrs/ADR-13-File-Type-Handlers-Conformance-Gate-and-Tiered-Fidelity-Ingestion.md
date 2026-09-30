---
title: "ADR-13: File-Type Handlers, Conformance Gate & Tiered-Fidelity Ingestion"
type: "adr"
category: "architecture"
status: "accepted"
date: "2026-09-29"
last_reviewed: "2026-09-29"
node: "homelab"
domain: "ingestion-formats"
tags:
  - aegis/adrs
  - architecture/decisions
  - ingestion/formats
  - ingestion/modular
  - product/appliance
  - tiering/footprint
aliases:
  - "ADR-13"
  - "File-Type Handlers"
  - "Conformance Gate"
  - "Tiered Fidelity"
---

# ADR-13: File-Type Handlers, Conformance Gate & Tiered-Fidelity Ingestion

## Status
Accepted. Implemented on branch `feat/topic-tree` (`core/ingest`); applied to the live vault on 2026-09-29. Builds on [ADR-11](ADR-11-Universal-Multimodal-Ingestion-and-TelcoTrace-Signaling.md) (no bespoke parsers per format) and [ADR-12](ADR-12-Pluggable-Structure-Extraction-Tier-Size-Policy-and-Search-Time-Deduplication.md) (structure layer).

## Date
2026-09-29

## Context

Deep ingestion of the Huawei ReleaseDoc packages showed a systematic pattern, not a one-off bug: each file type was ingested by its own ad-hoc code with its own silent limits.

- `.docx` manuals were clipped by `paras[:220]` and `[:22000]`: about 80% of the USC manual text (≈5.2M of 6.4M characters) was not searchable, with no warning.
- Workbooks held 1–35% of their text in the index (the four vulnerability lists: 1%); merged headers were not propagated.
- Four legacy `.xls` files (including the 359 KB Communication Matrix) and two nested zips (WSDL/XSD) were not ingested at all: no reader existed, and no spreadsheet library is available in the air-gapped appliance.
- The product must still fit a laptop (Tier 1) and must not need a frontier model at ingest time, and new document families (mailboxes, decks, LLDs, traces) are coming. The risk was reopening the pipeline for every format.

## Decision

### 1. One contract per file type: `FormatHandler`
`core/ingest/base.py`. A handler turns the bytes of one file into a `ParsedDocument`: `Section`s with a heading path, text, a locator and a kind (`text` | `rows`). It knows its format deeply and knows nothing about databases, tiers or chunk sizes. Handlers are deterministic, standard-library only and never call a model. The base class converts every parser failure (zlib, zip, XML, struct, index errors...) into `HandlerError`, so a corrupt file is reported and skipped and can never crash a run.

Built in: `docx` (heading levels resolved from `styles.xml` incl. `basedOn` and outline levels, TOC skipped, tables, content controls, footnotes, streamed), `xlsx`/`xlsm`, `xls` (own OLE2 + BIFF8 reader incl. shared strings across CONTINUE records), `pptx`, `html`, `xml` (WSDL, XSD and generic views), `markdown`, `text`, `csv`. Spreadsheet grids share one logic: merged cells expanded, title rows kept, multi-row headers combined as `Parent > Child`, one self-contained row per line (`12: Header: value | ...`), long column labels shown short in each row with one legend line.

### 2. A conformance gate makes "adding a format" bounded work
`core/ingest/conformance.check_handler` is the acceptance test every handler must pass: **lossless** (proved from chunk source spans, not sampled), **deterministic**, **bounded** (no chunk over the tier's size), **well-formed**, and **robust** (empty, truncated, garbage and bit-flipped input raise only `HandlerError`). A new format is done when it passes the gate on a fixture; the pipeline, schema and tiers do not change. The gate already caught a real robustness bug on real files before it reached production.

### 3. One shared chunker, never truncating
`core/ingest/chunking.py`: small sibling sections merge, large ones split with overlap at paragraph / line / word boundaries, each chunk starts with a context header `[document > heading > sub-heading]`, and every chunk records the source spans it covers.

### 4. Tiered fidelity: prose in full, bulk tables capped, never silently
Prose is always indexed in full. Only *tabular rows* are subject to a tier's cap (`SizePolicy.max_file_chars`: desktop 300k, edge 1M, datacenter none, counted over a file's row sections). Above it the largest sheets are replaced, one at a time, by a flagged **catalog card** (size, row count, column legend, first rows, source path) until the rest fits, so small sheets stay complete. Cards are marked `fidelity=catalog` and listed in the report.

### 5. Pipeline with incremental modes and structure at ingest
`core/ingest/pipeline.py` walks a folder (read in place), a zip or nested zips (zip-bomb guarded) and writes chunk records with `topic_id` and `record_kind` at ingest time, plus a node per heading (a complete outline). Modes: `missing` (default; never touches existing records), `changed` (SHA-256), `grow` (re-ingest only when the new parse holds >1.5× the indexed text; never shrinks) and `replace`. Only records owned by the file are replaced (its identifier, `::part::N` and the older `::sheet::` / `#rows` patterns); curated records that merely point at the file are kept. `--dry-run` reports the footprint before anything is written.

## Consequences

**Positive**
- New formats are one handler + one fixture + the gate; the tier decides fidelity, not the format.
- Repairs are incremental and auditable (hash-verified) instead of re-indexing everything.

**Negative / costs**
- Structure and content are now written by two layers (ADR-12 migration for HedEx HTML, ADR-13 pipeline for files); records from the older indexers still need the ADR-12 runner.
- Dates in spreadsheets are kept as raw Excel serials; images and charts are counted, not indexed (PDF / OCR / image handlers belong to the higher tiers, see below).

## Measurements (live vault, 2026-09-29, edge profile, `grow` over both ReleaseDoc packages)
| Item | Value |
| :--- | :--- |
| Files re-ingested / already complete / kept | 78 re-ingested (42 docx, 19 xlsx, 4 xls, 13 xml), 32 already complete, 7 kept (cards not larger) |
| Records | +5,850 chunks, −156 old file-owned records (all ReleaseDoc package records) → 54,672 |
| Characters | +12.30M inserted, −1.80M removed, **net +10.50M (+5.5%)** |
| Workbooks with a sheet above the edge cap (1M) | 8 (four 5M-char vulnerability lists, two performance-counter lists, two data-table dumps). A card replaced existing text in 1 case; in the other 7 the existing partial records were kept, because a card would hold less than what is already indexed (`grow` never shrinks) |
| Untouched | 0 pre-existing records modified in place; curated ALM / dossier records intact |
| Verification | 19 independent checks passed (hash arithmetic, structure invariants, FTS integrity, searchability, service health); rollback proven identical on a copy |
| Real files through the conformance gate | 30 real docx / xlsx / xlsm / xls files, including corrupt-input fuzzing: 0 problems |

## Known limits and next formats
Not covered (deliberately, not forgotten): PDF and scanned documents / images (need OCR or layout models: optional Tier-2/3 handler per ADR-11), e-mail (`.msg` can reuse the OLE2 reader; mbox has a parser in `core/formats`), packet captures and traces (TelcoTrace, ADR-11), `.7z`/`.tar` containers, and the retrieval-side collapse of curated duplicates (`collapse_by_topic` exists but is not wired into the served search).
