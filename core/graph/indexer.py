#!/usr/bin/env python3
"""
GraphRAG Dual-Corpus Indexer for Aegis Sovereign Knowledge Appliance.
Extracts entities and relational links from Markdown documents and Paperless/OCR records,
populating the SQLite Knowledge Graph store.

Invariants:
- Zero Plaintext Secrets.
- Strictly local CPU execution using SQLite (WAL mode).
"""

import datetime
import os
import sys
import time
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional

from .store import GraphStore
from .extractor import (
    extract_wiki_entities,
    extract_paperless_entities,
    ExtractedEntity,
    ExtractedRelation,
)


class GraphIndexer:
    def __init__(
        self,
        store: Optional[GraphStore] = None,
        docs_dir: Optional[Path] = None,
    ):
        self.store = store or GraphStore()
        self.docs_dir = Path(docs_dir) if docs_dir else Path("docs")

    def index_markdown_directory(self, target_dir: Optional[Path] = None, corpus: str = "docs") -> Dict[str, Any]:
        """Indexes all markdown files in the specified directory into the graph store."""
        search_dir = Path(target_dir) if target_dir else self.docs_dir
        start_time = time.time()
        indexed_files = 0
        total_entities_found = 0
        total_relations_found = 0

        if not search_dir.exists():
            return {
                "corpus": corpus,
                "indexed_files": 0,
                "elapsed_seconds": 0.0,
                "error": f"Directory not found: {search_dir}",
            }

        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for file in files:
                if not file.endswith(".md"):
                    continue

                full_path = Path(root) / file
                rel_path = str(full_path.relative_to(search_dir))

                try:
                    content = full_path.read_text(encoding="utf-8")
                except Exception as e:
                    continue

                # Parse frontmatter
                frontmatter = {}
                body = content
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        try:
                            frontmatter = yaml.safe_load(parts[1]) or {}
                            body = parts[2]
                        except Exception:
                            frontmatter = {}

                extraction = extract_wiki_entities(
                    file_path=rel_path,
                    frontmatter=frontmatter,
                    content=body
                )

                title = frontmatter.get("title") or full_path.stem
                created_date = str(frontmatter.get("last_reviewed") or "2026-09-18")
                url = f"file://{full_path.resolve()}"

                doc_clr_raw = (
                    frontmatter.get("clearance")
                    or frontmatter.get("clearance_level")
                    or frontmatter.get("security_level")
                    or 0
                )
                try:
                    from core.security import ClearanceLevel
                    doc_clr = ClearanceLevel.from_string(doc_clr_raw).value
                except Exception:
                    doc_clr = 0

                self.store.index_document(
                    corpus=corpus,
                    doc_identifier=rel_path,
                    title=title,
                    created_date=created_date,
                    url=url,
                    entities=extraction.entities,
                    relations=extraction.relations,
                    clearance_level=doc_clr
                )

                indexed_files += 1
                total_entities_found += len(extraction.entities)
                total_relations_found += len(extraction.relations)

        elapsed = time.time() - start_time
        return {
            "corpus": corpus,
            "indexed_files": indexed_files,
            "total_entities_found": total_entities_found,
            "total_relations_found": total_relations_found,
            "elapsed_seconds": round(elapsed, 2)
        }

    def index_document_record(
        self,
        doc_id: int,
        title: str,
        correspondent: str,
        doc_type: str,
        tags: List[str],
        content: str,
        created_date: Optional[str] = None,
        corpus: str = "archive",
        clearance_level: int = 0
    ) -> int:
        """Indexes a single ingested document record into the graph store."""
        extraction = extract_paperless_entities(
            doc_id=doc_id,
            title=title,
            correspondent=correspondent,
            doc_type=doc_type,
            tags=tags,
            content=content
        )

        return self.store.index_document(
            corpus=corpus,
            doc_identifier=str(doc_id),
            title=title,
            created_date=created_date or datetime.date.today().isoformat(),
            url=f"archive://{doc_id}",
            entities=extraction.entities,
            relations=extraction.relations,
            clearance_level=clearance_level
        )
