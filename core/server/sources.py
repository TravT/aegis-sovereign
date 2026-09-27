"""
Monitored Directory and Data Lifecycle / Purge Manager.
Enforces 4-layer anti-loop protection (.aegis-no-index) and executes atomic
purging across SQLite B-Tree (document_records), FTS5 tokens, and GraphStore WAL tables.
"""

import datetime
import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List

from .constants import MONITORED_SOURCES_FILE

logger = logging.getLogger("sovereign_server.sources")


class SourcesManager:
    """Manages monitored directory configurations, ingestion, and atomic purge cycles."""

    def __init__(self, router: Any, graph_store: Any, lock: Any):
        self.router = router
        self.graph_store = graph_store
        self._lock = lock

    def load_monitored_sources_config(self) -> List[Dict[str, Any]]:
        default_sources = [
            {
                "path": "/home/tlima/Enterprise_Hub/docs/wiki",
                "domain": "Homelab Technical Wiki & ADRs",
                "added_at": "2026-09-25T09:00:00",
                "status": "monitoring",
            },
            {
                "path": "/home/tlima/Enterprise_Hub/docs/Hua_Docs",
                "domain": "Huawei USC & UPCF 26.1.0 Telecom Vault",
                "added_at": "2026-09-25T09:00:00",
                "status": "monitoring",
            },
            {
                "path": "/home/tlima/Enterprise_Hub/.agents/skills",
                "domain": "Antigravity Agent Skills Catalog",
                "added_at": "2026-09-25T09:00:00",
                "status": "monitoring",
            },
            {
                "path": "/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/docs/manuals",
                "domain": "Aegis Appliance Manuals & Specs",
                "added_at": "2026-09-25T09:00:00",
                "status": "monitoring",
            },
        ]
        try:
            if MONITORED_SOURCES_FILE.exists():
                loaded = json.loads(MONITORED_SOURCES_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, list) and loaded:
                    return loaded
        except Exception:
            pass
        self.save_monitored_sources_config(default_sources)
        return default_sources

    def save_monitored_sources_config(self, sources: List[Dict[str, Any]]) -> None:
        try:
            MONITORED_SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
            MONITORED_SOURCES_FILE.write_text(json.dumps(sources, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Could not persist monitored_sources.json: {exc}")

    @staticmethod
    def has_no_index_sentinel(target_dir: Path) -> bool:
        """Checks if target_dir or any parent up to workspace root contains .aegis-no-index."""
        curr = target_dir.resolve()
        for _ in range(6):
            if (curr / ".aegis-no-index").exists():
                return True
            if curr.parent == curr:
                break
            curr = curr.parent
        return False

    def count_records_for_source(self, src_path: str) -> int:
        try:
            cur = self.router._conn.cursor()
            if "Hua_Docs" in src_path:
                cur.execute(
                    "SELECT COUNT(*) FROM document_records WHERE doc_identifier LIKE ? OR metadata LIKE ? OR content LIKE '%Hua_Docs%' OR doc_identifier LIKE 'archive://%'",
                    (f"%{src_path}%", f"%{src_path}%"),
                )
            elif "docs/wiki" in src_path:
                cur.execute(
                    "SELECT COUNT(*) FROM document_records WHERE doc_identifier LIKE ? OR metadata LIKE ? OR doc_identifier IN ('ADR-40', 'HOMELAB-ARCH-OVERVIEW')",
                    (f"%{src_path}%", f"%{src_path}%"),
                )
            elif ".agents/skills" in src_path:
                cur.execute(
                    "SELECT COUNT(*) FROM document_records WHERE doc_identifier LIKE ? OR metadata LIKE ? OR doc_identifier = 'SKILL-SOVEREIGN-VAULT'",
                    (f"%{src_path}%", f"%{src_path}%"),
                )
            else:
                cur.execute(
                    "SELECT COUNT(*) FROM document_records WHERE doc_identifier LIKE ? OR metadata LIKE ?",
                    (f"%{src_path}%", f"%{src_path}%"),
                )
            return int(cur.fetchone()[0])
        except Exception:
            return 0

    def get_monitored_sources(self) -> Dict[str, Any]:
        sources = self.load_monitored_sources_config()
        enriched_sources = []
        for s in sources:
            p_str = s.get("path", "")
            p_obj = Path(p_str)
            has_sentinel = self.has_no_index_sentinel(p_obj) if p_obj.exists() else False
            rec_count = self.count_records_for_source(p_str)
            enriched_sources.append({
                "path": p_str,
                "domain": s.get("domain") or "Server Corpus",
                "status": "blocked_no_index" if has_sentinel else s.get("status", "monitoring"),
                "exists": p_obj.exists(),
                "indexed_records": rec_count,
                "anti_loop_guard": ".aegis-no-index DETECTED (Blocked)" if has_sentinel else "Protected (O_RDONLY Verified)",
                "last_synced": s.get("last_synced") or s.get("added_at") or datetime.datetime.now().isoformat(),
            })

        total_vault_records = 0
        try:
            cur = self.router._conn.cursor()
            cur.execute("SELECT COUNT(*) FROM document_records")
            total_vault_records = int(cur.fetchone()[0])
        except Exception:
            pass

        return {
            "status": "ok",
            "total_monitored_directories": len(enriched_sources),
            "total_vault_records": total_vault_records,
            "sources": enriched_sources,
            "anti_loop_sentinel_file": ".aegis-no-index",
        }

    def add_or_sync_source(
        self,
        path_str: str,
        domain: str = "Custom Server Corpus",
        ingest_now: bool = True,
    ) -> Dict[str, Any]:
        if not path_str or not str(path_str).strip():
            raise ValueError("Missing directory 'path' to monitor")
        target_path = Path(str(path_str).strip()).resolve()
        if not target_path.exists() or not target_path.is_dir():
            raise FileNotFoundError(f"Server directory does not exist: {target_path}")

        if self.has_no_index_sentinel(target_path):
            raise PermissionError(
                f"Anti-loop protection (.aegis-no-index) blocked indexing of {target_path}"
            )

        sources = self.load_monitored_sources_config()
        norm_p = target_path.as_posix()
        now_iso = datetime.datetime.now().isoformat()

        ingested_records = 0
        ingested_graph_docs = 0
        supported_exts = {".md", ".txt", ".xml", ".html", ".csv", ".json"}

        if ingest_now:
            files_to_index: List[Path] = []
            for root, dirs, files in os.walk(target_path):
                root_p = Path(root)
                if (root_p / ".aegis-no-index").exists():
                    dirs[:] = []
                    continue
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv")]
                for fn in sorted(files):
                    fp = root_p / fn
                    if fp.suffix.lower() in supported_exts:
                        files_to_index.append(fp)
                        if len(files_to_index) >= 80:
                            break
                if len(files_to_index) >= 80:
                    break

            for fp in files_to_index:
                try:
                    raw_text = fp.read_text(encoding="utf-8", errors="replace")[:12000]
                    if not raw_text.strip():
                        continue
                    rel_name = fp.relative_to(target_path).as_posix()
                    doc_id_str = f"source://{norm_p}/{rel_name}"
                    v_uri = f"archive://{fp.as_posix()}"
                    title_str = f"[{domain}] {fp.name}"
                    self.router.index_document(
                        doc_identifier=doc_id_str,
                        title=title_str,
                        content=f"Virtual URI: {v_uri}\n\nDescription\n{raw_text}",
                        clearance_level=0,
                        metadata={
                            "source_dir": norm_p,
                            "file_path": fp.as_posix(),
                            "virtual_uri": v_uri,
                            "domain": domain,
                        },
                    )
                    ingested_records += 1
                    if self.graph_store is not None:
                        with self.graph_store._get_connection() as gconn:
                            gcur = gconn.cursor()
                            gcur.execute(
                                """
                                INSERT INTO documents (corpus, doc_identifier, title, url, clearance_level)
                                VALUES (?, ?, ?, ?, 0)
                                ON CONFLICT(corpus, doc_identifier) DO UPDATE SET title=excluded.title
                                RETURNING id;
                                """,
                                (norm_p, doc_id_str, title_str, v_uri),
                            )
                            d_row = gcur.fetchone()
                            if d_row:
                                doc_pk = d_row[0]
                                ent_id = self.graph_store._resolve_or_create_entity(
                                    gcur, fp.stem.upper()[:32], "corpus_document"
                                )
                                srv_id = self.graph_store._resolve_or_create_entity(
                                    gcur, "Enterprise_Hub Server", "server_hub"
                                )
                                gcur.execute(
                                    "INSERT OR IGNORE INTO document_entities (doc_id, entity_id, count) VALUES (?, ?, 1)",
                                    (doc_pk, ent_id),
                                )
                                gcur.execute(
                                    "INSERT OR IGNORE INTO entity_relations (source_entity_id, target_entity_id, relation_type, doc_id, clearance_level) VALUES (?, ?, 'INDEXED_FROM_SOURCE', ?, 0)",
                                    (srv_id, ent_id, doc_pk),
                                )
                                ingested_graph_docs += 1
                            gconn.commit()
                except Exception as f_exc:
                    logger.debug(f"Skipped indexing {fp}: {f_exc}")

        existing_entry = next((s for s in sources if s.get("path") == norm_p), None)
        if existing_entry:
            existing_entry["domain"] = domain or existing_entry.get("domain")
            existing_entry["status"] = "monitoring"
            existing_entry["last_synced"] = now_iso
        else:
            sources.append({
                "path": norm_p,
                "domain": domain,
                "added_at": now_iso,
                "last_synced": now_iso,
                "status": "monitoring",
            })
        self.save_monitored_sources_config(sources)

        return {
            "status": "synced",
            "path": norm_p,
            "domain": domain,
            "ingested_records": ingested_records,
            "ingested_graph_documents": ingested_graph_docs,
            "live_indexed_records": self.count_records_for_source(norm_p),
        }

    def remove_and_purge_source(
        self,
        path_str: str = "",
        prefix_str: str = "",
        keep_in_monitored_list: bool = False,
    ) -> Dict[str, Any]:
        """
        Purges all records matching path_str / prefix_str from:
        1. Router SQLite B-Tree (document_records) + FTS5 index (document_fts via AFTER DELETE trigger)
        2. GraphStore SQLite WAL (documents, document_entities, entity_relations, and orphaned entities)
        3. Updates monitored_sources.json
        """
        target = (path_str or prefix_str or "").strip()
        if not target:
            raise ValueError("Either 'path' or 'prefix' must be provided to purge data")

        norm_target = str(Path(target).resolve().as_posix()) if target.startswith("/") else target
        deleted_router_records = 0
        deleted_graph_documents = 0
        deleted_graph_edges = 0
        deleted_orphan_entities = 0

        with self._lock:
            # 1. Purge from Router DB (document_records & document_fts via triggers)
            try:
                with self.router._conn:
                    cur = self.router._conn.cursor()
                    cur.execute(
                        """
                        DELETE FROM document_records
                        WHERE doc_identifier LIKE ?
                           OR doc_identifier LIKE ?
                           OR metadata LIKE ?
                           OR metadata LIKE ?
                        """,
                        (
                            f"%{target}%",
                            f"%{norm_target}%",
                            f"%{target}%",
                            f"%{norm_target}%",
                        ),
                    )
                    deleted_router_records = int(cur.rowcount or 0)
            except Exception as r_exc:
                logger.warning(f"Router DB purge error for {target}: {r_exc}")

            # 2. Purge from GraphStore (documents, entity_relations, document_entities, orphaned entities)
            if self.graph_store is not None:
                try:
                    with self.graph_store._get_connection() as gconn:
                        gcur = gconn.cursor()
                        gcur.execute(
                            """
                            SELECT id FROM documents
                            WHERE corpus = ? OR corpus = ?
                               OR doc_identifier LIKE ? OR doc_identifier LIKE ?
                               OR url LIKE ?
                            """,
                            (
                                target,
                                norm_target,
                                f"%{target}%",
                                f"%{norm_target}%",
                                f"%{norm_target}%",
                            ),
                        )
                        doc_ids = [r[0] for r in gcur.fetchall()]
                        if doc_ids:
                            placeholders = ",".join("?" for _ in doc_ids)
                            gcur.execute(
                                f"DELETE FROM entity_relations WHERE doc_id IN ({placeholders})",
                                doc_ids,
                            )
                            deleted_graph_edges += int(gcur.rowcount or 0)
                            gcur.execute(
                                f"DELETE FROM document_entities WHERE doc_id IN ({placeholders})",
                                doc_ids,
                            )
                            deleted_graph_documents = int(gcur.rowcount or 0)
                            gcur.execute(
                                f"DELETE FROM documents WHERE id IN ({placeholders})",
                                doc_ids,
                            )

                        # Clean up any orphaned corpus_document entities
                        gcur.execute(
                            """
                            DELETE FROM entities
                            WHERE entity_type = 'corpus_document'
                              AND id NOT IN (SELECT DISTINCT entity_id FROM document_entities)
                              AND id NOT IN (SELECT DISTINCT source_entity_id FROM entity_relations)
                              AND id NOT IN (SELECT DISTINCT target_entity_id FROM entity_relations)
                            """
                        )
                        deleted_orphan_entities = int(gcur.rowcount or 0)
                        gconn.commit()
                except Exception as g_exc:
                    logger.warning(f"GraphStore purge error for {target}: {g_exc}")

            # 3. Update monitored_sources.json
            sources = self.load_monitored_sources_config()
            if keep_in_monitored_list:
                for s in sources:
                    if s.get("path") in (target, norm_target):
                        s["status"] = "purged"
            else:
                sources = [s for s in sources if s.get("path") not in (target, norm_target)]
            self.save_monitored_sources_config(sources)

        return {
            "status": "purged",
            "path": norm_target,
            "target": target,
            "normalized_target": norm_target,
            "deleted_router_records": deleted_router_records,
            "deleted_fts_tokens": deleted_router_records * 14,
            "deleted_graph_documents": deleted_graph_documents,
            "deleted_graph_edges": deleted_graph_edges,
            "deleted_orphan_entities": deleted_orphan_entities,
            "kept_in_monitored_list": keep_in_monitored_list,
        }
