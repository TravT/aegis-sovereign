---
title: "Manual 16: Structure Extraction, Tier Size Profiles & Adding a New Format"
category: operations
type: documentation
node: homelab
domain: ai-data
tags:
  - homelab/appliance
  - product/appliance
  - ingestion/structure
  - operations/lifecycle
status: active
last_reviewed: 2026-09-29
aliases:
  - Manual 16 Structure Extraction
  - Tier Size Profiles
  - Adding a StructureExtractor
---

# Manual 16: Structure Extraction, Tier Size Profiles & Adding a New Format

Design rationale and measurements: [ADR-12](../adrs/ADR-12-Pluggable-Structure-Extraction-Tier-Size-Policy-and-Search-Time-Deduplication.md). This manual is the operator and developer how-to.

## 1. What it does

Every indexed record gets a place in its source's own organisation:

| Table / column | Meaning |
| :--- | :--- |
| `topic_nodes(topic_id, package, name, depth, source, path_text)` | one row per manual topic / folder / file / sheet |
| `topic_edges(child, parent, is_primary)` | the tree; a topic under two parents keeps both, one is primary |
| `topic_paths` (view) | full `A > B > C` path derived from the primary parent chain |
| `document_records.topic_id / record_kind / console / plane` | where a record sits; `plane` is reserved |
| `structure_meta` | when it was applied and with which size profile |

`record_kind`: `native` (the record is the item), `composite` (curated record standing on a native item), `synthetic` (no reliable item), `external` (no configured source claims it). Every topic has exactly one native record.

## 2. Running it (always on a snapshot first)

```bash
sqlite3 docs/.aegis_vault/sovereign_router.db ".backup /path/snapshot.db"
python3 tools/migrate_topic_tree.py --db /path/snapshot.db --profile edge \
  --source USC="docs/Hua_Docs/<USC package>.zip" \
  --source UPCF="docs/Hua_Docs/<UPCF package>.zip" \
  --source REL_USC="docs/Hua_Docs/USC 26.1.0_ReleaseDoc_EN (VM).zip" \
  --report report.json            # add --dry-run to write nothing
```

The extractor for each source is detected automatically (`hedex` for HedEx packages, `pathtree` for folders and other zips). The run is additive and idempotent. Verify on the snapshot before touching the live vault:

```sql
-- no dangling references, one native record per topic
SELECT COUNT(*) FROM document_records WHERE topic_id IS NOT NULL AND topic_id NOT IN (SELECT topic_id FROM topic_nodes);
SELECT COUNT(*) FROM (SELECT topic_id FROM document_records WHERE record_kind='native' AND topic_id IS NOT NULL GROUP BY 1 HAVING COUNT(*)>1);
```

Live vault changes need a backup and a dead-man rollback (drop the added tables/columns) as described in the operations runbook.

## 3. Tier size profiles

| Profile | Tier | Chunk / overlap | Stores `path_text` | Collapse duplicates at search |
| :--- | :--- | :---: | :---: | :---: |
| `desktop` | 1 (laptop) | 2000 / 150 | no (use `topic_paths`) | yes |
| `edge` | 2 (appliance) | 3000 / 200 | yes | yes |
| `datacenter` | 3 | 4000 / 300 | yes | no |

Rule for every profile: **never truncate**. `chunk_spans()` returns overlapping spans that cover every character.

Search de-duplicates automatically: `SovereignQueryRouter.route_and_execute` and the in-process MCP search call `core.structure.search.fold_duplicates`, which folds a curated `composite` record under its `native` record when their text is >= 85% similar (records that add information are kept), sets `collapsed` on the native and returns `topic_id` / `record_kind`. Choose the tier with the `AEGIS_SIZE_PROFILE` environment variable (`desktop` | `edge` | `datacenter`, default `edge`; `datacenter` disables folding). It does nothing on vaults without the structure columns. Duplicates are not deleted.

## 4. Adding a new format

```python
from pathlib import Path
from core.structure import Assignment, RecordView, StructureExtractor, register

@register
class MboxExtractor(StructureExtractor):
    name = "mbox"
    priority = 50                       # lower runs first; pathtree (90) is the generic fallback

    @classmethod
    def detect(cls, source: Path) -> bool: ...          # cheap: extension / magic

    def build_tree(self): ...                            # fill self.tree.nodes / self.tree.edges
    def claims(self, rec: RecordView) -> bool: ...      # does this record come from this source?
    def assign(self, rec: RecordView) -> Assignment:     # place it; may add nodes on demand
        return Assignment(topic_key, "native")
```

Rules: deterministic, standard library only, no model calls, stream in memory (or never open the files), and node keys are `"<label>:<local id>"`. Add a test next to `tests/test_structure_extraction.py` (see `test_new_format_is_one_subclass_and_a_registration`).

## 5. Known limits

- Structure is applied after indexing until indexers emit it at ingest; the enrichment tool's `INSERT OR REPLACE` would blank the columns for rows it rewrites (re-run the tool to restore).
- The hybrid `/query` path does not fold duplicates yet, and the graph viewer is a later stage (see ADR-12 rollout). File ingestion is covered by [Manual 17](17_file_type_handlers_conformance_gate_and_ingestion_modes.md).
