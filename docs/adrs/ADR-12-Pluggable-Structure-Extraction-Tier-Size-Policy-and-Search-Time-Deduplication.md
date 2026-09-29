---
title: "ADR-12: Pluggable Structure Extraction, Tier-Aware Size Policy & Search-Time De-Duplication"
type: "adr"
category: "architecture"
status: "accepted"
date: "2026-09-29"
last_reviewed: "2026-09-29"
node: "homelab"
domain: "ingestion-structure"
tags:
  - aegis/adrs
  - architecture/decisions
  - ingestion/structure
  - ingestion/modular
  - product/appliance
  - tiering/footprint
aliases:
  - "ADR-12"
  - "Structure Extraction Contract"
  - "Tier Size Policy"
---

# ADR-12: Pluggable Structure Extraction, Tier-Aware Size Policy & Search-Time De-Duplication

## Status
Accepted (engine on branch `feat/topic-tree`; Stage 1 schema applied to the live vault on 2026-09-29).

## Date
2026-09-29

## Context

[ADR-11](ADR-11-Universal-Multimodal-Ingestion-and-TelcoTrace-Signaling.md) rules out bespoke parsers per proprietary format and reduces every input to three primitives (structural text, layout, metadata). Deep ingestion of the Huawei 26.1.0 HedEx packages showed what is still missing between "text is indexed" and "the manual's own organisation is indexed":

1. **Structure was lost.** 55% of the 48,978 indexed records (27,002) had a flat two-level breadcrumb with no parent, so no relational view of the manuals was possible.
2. **Content was silently truncated.** Hard slices (`[:26000]`, and `paras[:220]` + `[:22000]` for `.docx`) discarded about 80% of the ReleaseDoc manual text (≈5.2M of 6.4M characters in the USC set) with no warning.
3. **Footprint concerns.** Curated duplicate records (7,653 records, 29.9M characters) shadow native pages; the product must still fit a laptop (Tier 1) and must not require a frontier model at ingest time (Tiers 1–2 ingest deterministically; only RAPTOR summaries are GPU/Tier-3 work).
4. **No extension point.** Parsers are separate classes without a shared interface, and one Huawei-specific 1,393-line indexer lives in `tools/`. Each new format (mailboxes, decks, LLDs, traces) would repeat the same ad-hoc work.

## Decision

### 1. One contract: `StructureExtractor`
`core/structure/base.py` defines the interface every source type implements: `detect(source)`, `build_tree()`, `claims(record)`, `assign(record) -> Assignment(topic_key, kind, console, review)`. Extractors are deterministic, stdlib-only, stream their source in memory (or, for folders, never open the files) and never call a model. Adding a format is one subclass plus `@register`; the runner, schema, graph and viewers do not change.

### 2. Registry with priorities
`core/structure/registry.py` orders extractors by priority; specialised extractors (HedEx, priority 10) are tried before the generic fallback (`pathtree`, priority 90). `extractor_for(source, label)` picks the plugin.

### 3. Built-in extractors
| Extractor | Tree comes from | Join key |
| :--- | :--- | :--- |
| `hedex` | DITA bookmaps (`pid_bookmap_*.xml`) + narrative `navi.xml` | page `<meta name="DC.Identifier">` = bookmap topic id; `navi.xml` by exact file path |
| `pathtree` | folder hierarchy of a directory or zip; sheets / row chunks become child nodes | the record's own path (created on demand) |

### 4. Relational schema (additive, nullable, idempotent)
`topic_nodes`, `topic_edges` (a topic under two parents keeps both edges, exactly one `is_primary`), the `topic_paths` view (full path derived from the primary parent chain), `structure_meta` (what was applied and with which profile), and on `document_records`: `topic_id`, `record_kind`, `console`, `plane` (reserved). Record kinds: `native` (the record is the source item), `composite` (curated record standing on a native item, same topic), `synthetic` (no reliable source item), `external` (no configured source claims it). Every topic has exactly one native record.

### 5. Tier size profiles — never truncate
`core/structure/policy.py`: profiles `desktop` (Tier 1), `edge` (Tier 2), `datacenter` (Tier 3) set chunk size and overlap, whether `path_text` is stored (desktop derives paths from the `topic_paths` view instead) and whether search collapses derived records. Text longer than a chunk is split into overlapping spans that cover every character; nothing is ever dropped to fit a limit.

### 6. Search-time de-duplication before any deletion
`collapse_by_topic()` folds curated `composite` records under their native topic at query time, keeping the best rank and preferring the native record. Duplicates are not deleted: they may carry unique enrichment (alarm procedures, dossiers) and are removed only after a measured, per-topic review.

### 7. Deterministic first, models optional
Structure comes from the source's own organisation. Any model assistance (e.g. the embedded NER agreed for humanities collections in the master plan) is a separate, tier-gated step and is never required for structure.

## Consequences

**Positive**
- New document families need one extractor, not a pipeline fork; the same code runs from laptop to datacenter and only the profile changes.
- The manual tree gives a deterministic skeleton for the hierarchical (RAPTOR-style) layers without generating a single summary token.
- Graph and visualisation work can draw real edges (manual tree, alarm/command chains) instead of a static sample.

**Negative / costs**
- Structure is a post-hoc step until indexers emit `topic_id`/`record_kind` at ingest (an `INSERT OR REPLACE` in the enrichment tool would blank them). Re-running the runner restores them.
- Measured cost of the Huawei tree: ≈21.7 MB on a ≈450 MB database (about 5%), mostly stored `path_text`, which the desktop profile avoids.

## Measurements (live vault, 2026-09-29)
| Item | Value |
| :--- | :--- |
| Records needing a parent | 28,646 (USC 17,297 flat + 652 no breadcrumb; UPCF 9,705 flat + 992 no breadcrumb) |
| Matched to a topic | 48,352 of 48,365 Huawei product-doc records (99.97%) |
| Topics (nodes) | USC 21,640 · UPCF 19,162 (ReleaseDoc path trees: 242 + 87) |
| Multi-parent topics | 23 (1 USC, 22 UPCF) |
| Native / composite / synthetic / external | 40,998 / 7,653 / 13 / 314 |
| Unindexed `.docx` text (USC ReleaseDoc) | ≈5.2M of 6.4M chars; 4 `.xls` and 2 nested `.zip` not indexed |

## Rollout
1. **Done:** Stage 1 tree on the live vault (dead-man rollback tested; content hash unchanged).
2. **Next:** emit structure at ingest; remove the truncating slices by chunking (`docx` by heading style); ingest the `.xls`/nested `.zip` files; then the 3D/2D graph viewer over `topic_nodes`/`topic_edges`.

## Alternatives considered
- **Keep a Huawei-specific script and copy it per format** — rejected: repeats the current debt and cannot scale to mailboxes, decks and traces.
- **Let a frontier model classify structure at ingest** — rejected: violates the Tier 1–2 constraint and would not run on a laptop.
- **Delete duplicate records now** — rejected until per-topic review; collapse at search time is reversible.
