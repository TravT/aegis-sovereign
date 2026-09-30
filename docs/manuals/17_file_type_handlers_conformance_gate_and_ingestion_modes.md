---
title: "Manual 17: File-Type Handlers, the Conformance Gate & Ingestion Modes"
category: operations
type: documentation
node: homelab
domain: ai-data
tags:
  - homelab/appliance
  - product/appliance
  - ingestion/formats
  - operations/lifecycle
status: active
last_reviewed: 2026-09-29
aliases:
  - Manual 17 File-Type Handlers
  - Ingestion Modes
  - Conformance Gate
---

# Manual 17: File-Type Handlers, the Conformance Gate & Ingestion Modes

Rationale and measurements: [ADR-13](../adrs/ADR-13-File-Type-Handlers-Conformance-Gate-and-Tiered-Fidelity-Ingestion.md). Structure layer: [Manual 16](16_structure_extraction_tier_profiles_and_adding_a_format.md). This manual is the operator and developer how-to.

## 1. Supported file types

| Handler | Extensions | What it understands |
| :--- | :--- | :--- |
| `docx` | `.docx .docm .dotx` | heading tree from paragraph styles (incl. `basedOn`, outline levels), tables as `cell \| cell` rows, footnotes, content controls; table of contents skipped |
| `xlsx` | `.xlsx .xlsm .xltx` | sheets, shared strings, cached formula values, merged cells (headers combined `Parent > Child`), hidden-sheet flag |
| `xls` | `.xls` (BIFF8) | same grid logic; own OLE2 + BIFF8 reader (encrypted and Excel 5/95 files are rejected with a clear error) |
| `pptx` | `.pptx .pptm .potx` | one section per slide, title, tables, speaker notes |
| `html` | `.html .htm .xhtml` | h1-h6 outline, tables, lists; script/style ignored |
| `xml` | `.xml .wsdl .xsd ...` | WSDL (services, operations, messages, types), XSD types, generic path lines |
| `markdown` `text` `csv` | `.md .txt .log .yaml .csv .tsv ...` | ATX headings; plain text; header + rows for CSV |

Unsupported files are listed in the report (`unsupported_extensions`) and skipped, never guessed.

## 2. Running an ingestion (always a snapshot first, dry-run before writing)

```bash
sqlite3 docs/.aegis_vault/sovereign_router.db ".backup /path/snapshot.db"
python3 tools/ingest_files.py --db /path/snapshot.db --profile edge --mode grow --dry-run \
  --source REL_USC="docs/Hua_Docs/USC 26.1.0_ReleaseDoc_EN (VM).zip" --report dry.json
python3 tools/ingest_files.py --db /path/snapshot.db --profile edge --mode grow \
  --source REL_USC="docs/Hua_Docs/USC 26.1.0_ReleaseDoc_EN (VM).zip"      # then verify, then the live DB
```

Sources can be a folder (read in place, nothing copied), a zip (nested zips followed two levels deep) or one file. `--formats docx,xls` restricts the handlers; `--profile desktop|edge|datacenter` sets chunk size and the tabular cap.

| Mode | Behaviour |
| :--- | :--- |
| `missing` (default) | only files with no record yet; never touches existing records |
| `changed` | re-ingest a file only when its SHA-256 differs from the stored one |
| `grow` | re-ingest only when the new parse holds >1.5× the indexed text; repairs truncated files, leaves complete ones alone, **never shrinks** |
| `replace` | always re-ingest; replaces only the file's own records |

Only records *owned by the file* are replaced (its identifier, `::part::N`, and the older `::sheet::` / `#rows` patterns). Curated records that merely point at the file are kept.

## 3. Fidelity: prose in full, bulk tables capped, nothing silent

Prose is always indexed in full. Tabular rows above the tier cap (desktop 300k, edge 1M characters per file, datacenter none) are replaced, largest sheet first, by a flagged **catalog card**: size, row count, column legend, first rows and the source path. The report lists them under `catalog_cards`, and their records carry `fidelity=catalog`.

## 4. Verifying a run (do this on the snapshot, then again live)

Check that: no surviving pre-existing record changed; every deleted record belongs to the ingested package; record arithmetic matches the report; no dangling `topic_id` / edges / duplicate edges; FTS integrity check passes; new content is searchable; the service answers. For live changes use a backup and an atomic apply-verify-cancel script with a dead-man rollback that restores the exact pre-ingest state (records, nodes, edges).

## 5. Adding a file type (bounded work)

```python
from core.ingest import FormatHandler, ParsedDocument, Section, HandlerError
from core.ingest.registry import register

@register
class EmlHandler(FormatHandler):
    name, version, extensions = "eml", "1", (".eml",)

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        doc = ParsedDocument(name=name, format=self.name, title=self.title_from(name))
        doc.sections.append(Section(("Headers",), "..."))   # heading path, text, locator, kind
        return doc
```

1. Implement `parse`; raise `HandlerError` (or let a parser error escape: the base class converts it).
2. Add a fixture and run `check_handler(handler, name, data, get_profile("edge"))`: it must return no problems (lossless, deterministic, bounded, well-formed, corrupt-input safe).
3. Done. The pipeline, chunker, schema and tiers do not change.

## 6. Known limits

PDF / scanned documents / images (OCR or layout models, higher tiers), `.msg` and mailbox families, packet captures, `.7z` / `.tar`; spreadsheet dates stay raw Excel serials; the hybrid `/query` path does not fold curated duplicates yet.
