#!/usr/bin/env python3
"""
Aegis Sovereign Unified Server Vault Lifecycle & Consolidation Engine.
Manages unified server knowledge ingestion, cross-DB GraphStore merging,
status telemetry, and deterministic prefix purging across:
- /home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db
- /home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_graph.db
- /home/tlima/Enterprise_Hub/docs/.aegis_vault/monitored_sources.json

CLI Usage:
  python3 -m tools.vault_lifecycle --status
  python3 -m tools.vault_lifecycle --consolidate-all
  python3 -m tools.vault_lifecycle --ingest <dir_path> --domain <name>
  python3 -m tools.vault_lifecycle --purge <path_or_prefix>
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

APPLIANCE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APPLIANCE_ROOT.parent.parent
if str(APPLIANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLIANCE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.router.query_router import SovereignQueryRouter
from core.graph.store import GraphStore
from core.security import ClearanceLevel, PlanTier

PROD_VAULT_DIR = REPO_ROOT / "docs" / ".aegis_vault"
DEFAULT_ROUTER_DB = PROD_VAULT_DIR / "sovereign_router.db"
DEFAULT_GRAPH_DB = PROD_VAULT_DIR / "sovereign_graph.db"
MONITORED_SOURCES_PATH = PROD_VAULT_DIR / "monitored_sources.json"


def _extract_markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    m = re.search(r"^title:\s*[\"']?([^\"'\n]+)[\"']?", text, flags=re.MULTILINE | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return fallback


def merge_external_graph_db(target_graph_db: Path, source_graph_db: Path) -> Dict[str, int]:
    """
    Merges all unique documents, entities, document_entities, and entity_relations
    from an external SQLite graph_store.db into the unified sovereign_graph.db.
    """
    if not source_graph_db.exists() or source_graph_db.is_symlink():
        return {"merged_docs": 0, "merged_entities": 0, "merged_relations": 0}
    if source_graph_db.resolve() == target_graph_db.resolve():
        return {"merged_docs": 0, "merged_entities": 0, "merged_relations": 0}

    src_conn = sqlite3.connect(str(source_graph_db))
    src_conn.row_factory = sqlite3.Row
    try:
        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception:
        pass

    dst_store = GraphStore(db_path=target_graph_db)
    dst_conn = dst_store._get_connection()
    dst_cur = dst_conn.cursor()

    doc_id_map: Dict[int, int] = {}
    ent_id_map: Dict[int, int] = {}
    merged_docs = 0
    merged_entities = 0
    merged_relations = 0

    # 1. Merge documents
    for row in src_conn.execute("SELECT * FROM documents").fetchall():
        d = dict(row)
        corpus = d.get("corpus") or "homelab_rag"
        ident = d.get("doc_identifier") or ""
        if not ident:
            continue
        dst_cur.execute(
            """
            INSERT INTO documents (corpus, doc_identifier, title, created_date, url, clearance_level)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(corpus, doc_identifier) DO UPDATE SET
                title = COALESCE(excluded.title, documents.title),
                url = COALESCE(excluded.url, documents.url)
            RETURNING id;
            """,
            (
                corpus,
                ident,
                d.get("title") or ident,
                d.get("created_date"),
                d.get("url"),
                int(d.get("clearance_level") or 0),
            ),
        )
        new_doc_id = dst_cur.fetchone()[0]
        doc_id_map[d["id"]] = new_doc_id
        merged_docs += 1

    # 2. Merge entities
    for row in src_conn.execute("SELECT * FROM entities").fetchall():
        e = dict(row)
        name = (e.get("name") or "").strip()
        norm = (e.get("normalized_name") or name.lower()).strip()
        etype = (e.get("entity_type") or "concept").strip()
        if not name:
            continue
        new_ent_id = dst_store._resolve_or_create_entity(
            dst_cur,
            name=name,
            entity_type=etype,
            normalized_name=norm,
            clearance_level=int(e.get("clearance_level") or 0),
        )
        ent_id_map[e["id"]] = new_ent_id
        merged_entities += 1

    # 3. Merge document_entities
    for row in src_conn.execute("SELECT * FROM document_entities").fetchall():
        de = dict(row)
        new_d = doc_id_map.get(de["doc_id"])
        new_e = ent_id_map.get(de["entity_id"])
        if new_d and new_e:
            dst_cur.execute(
                """
                INSERT INTO document_entities (doc_id, entity_id, count, context)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(doc_id, entity_id) DO UPDATE SET
                    count = MAX(document_entities.count, excluded.count);
                """,
                (new_d, new_e, int(de.get("count") or 1), de.get("context")),
            )

    # 4. Merge entity_relations
    for row in src_conn.execute("SELECT * FROM entity_relations").fetchall():
        er = dict(row)
        src_e = ent_id_map.get(er["source_entity_id"])
        tgt_e = ent_id_map.get(er["target_entity_id"])
        new_d = doc_id_map.get(er.get("doc_id")) if er.get("doc_id") else None
        if src_e and tgt_e:
            dst_cur.execute(
                """
                INSERT INTO entity_relations (source_entity_id, target_entity_id, relation_type, doc_id, clearance_level)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_entity_id, target_entity_id, relation_type, doc_id) DO NOTHING;
                """,
                (
                    src_e,
                    tgt_e,
                    er.get("relation_type") or "RELATED_TO",
                    new_d,
                    int(er.get("clearance_level") or 0),
                ),
            )
            merged_relations += 1

    dst_conn.commit()
    dst_store.close()
    src_conn.close()
    return {
        "merged_docs": merged_docs,
        "merged_entities": merged_entities,
        "merged_relations": merged_relations,
    }


def ingest_directory(
    dir_path: Path,
    domain: str,
    router_db: Path = DEFAULT_ROUTER_DB,
    graph_db: Path = DEFAULT_GRAPH_DB,
) -> Dict[str, Any]:
    """
    Ingests all markdown/text documents inside dir_path into SovereignQueryRouter
    and GraphStore with rich domain metadata and deterministic identifier aliases.
    """
    dir_path = dir_path.resolve()
    if not dir_path.exists():
        return {"status": "error", "error": f"Directory does not exist: {dir_path}"}

    gs = GraphStore(db_path=graph_db)
    router = SovereignQueryRouter(db_path=router_db, graph_store=gs, plan=PlanTier.ENTERPRISE)
    gcur = gs._get_connection().cursor()
    rcur = router._conn.cursor()

    indexed_docs = 0
    indexed_aliases = 0
    indexed_entities = 0
    indexed_relations = 0

    hub_entity_id = gs._resolve_or_create_entity(gcur, "Enterprise_Hub", "system", "enterprise_hub")
    homelab_entity_id = gs._resolve_or_create_entity(gcur, "Homelab", "cluster", "homelab")
    aegis_entity_id = gs._resolve_or_create_entity(gcur, "Aegis_Appliance", "appliance", "aegis_appliance")

    # Core architectural invariant edges required by Task 1.2
    adr30_eid = gs._resolve_or_create_entity(gcur, "ADR-30", "adr", "adr-30")
    adr40_eid = gs._resolve_or_create_entity(gcur, "ADR-40", "adr", "adr-40")
    traefik_eid = gs._resolve_or_create_entity(gcur, "Traefik", "service", "traefik")
    ts_inv_eid = gs._resolve_or_create_entity(gcur, "Tailscale_Port_443_Invariant", "invariant", "tailscale_port_443_invariant")

    for s_id, t_id, r_type in [
        (homelab_entity_id, adr30_eid, "GOVERNED_BY"),
        (traefik_eid, ts_inv_eid, "ENFORCES"),
        (aegis_entity_id, adr40_eid, "ARCHITECTED_IN"),
        (hub_entity_id, aegis_entity_id, "HOSTS_APPLIANCE"),
    ]:
        gcur.execute(
            """
            INSERT INTO entity_relations (source_entity_id, target_entity_id, relation_type, clearance_level)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(source_entity_id, target_entity_id, relation_type, doc_id) DO NOTHING;
            """,
            (s_id, t_id, r_type),
        )

    files = sorted(
        p for p in dir_path.rglob("*")
        if p.is_file() and p.suffix.lower() in (".md", ".txt", ".json", ".html")
        and "/.git/" not in str(p)
        and "/.aegis_vault/" not in str(p)
    )

    for fpath in files:
        try:
            raw_text = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not raw_text.strip():
            continue

        title = _extract_markdown_title(raw_text, fpath.stem)
        doc_ident = str(fpath)
        meta = {
            "domain": domain,
            "source_dir": str(dir_path),
            "file_path": str(fpath),
            "virtual_uri": str(fpath),
            "filename": fpath.name,
        }

        # 1. Index full path record in SovereignQueryRouter
        rcur.execute(
            """
            INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(doc_identifier) DO UPDATE SET
                title=excluded.title,
                content=excluded.content,
                metadata=excluded.metadata
            """,
            (doc_ident, title, raw_text[:25000], json.dumps(meta)),
        )
        indexed_docs += 1

        # 2. Register in GraphStore documents
        gcur.execute(
            """
            INSERT INTO documents (corpus, doc_identifier, title, url, clearance_level)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(corpus, doc_identifier) DO UPDATE SET
                title=excluded.title,
                url=excluded.url
            RETURNING id;
            """,
            (domain, doc_ident, title, str(fpath)),
        )
        g_doc_id = gcur.fetchone()[0]

        # 3. Domain-specific deterministic ID & Graph enrichment
        # Case A: ADR files (e.g., ADR-01-Hypervisor.md, ADR-30-..., or 30_...)
        adr_match = re.match(r"^(?:ADR-)?(\d{2})[-_]", fpath.name, re.IGNORECASE)
        if ("/adrs/" in str(fpath) or domain == "homelab_wiki") and adr_match and "/adrs/" in str(fpath):
            adr_num = adr_match.group(1)
            adr_code = f"ADR-{adr_num}"
            adr_meta = {**meta, "adr_id": adr_code}
            rcur.execute(
                """
                INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(doc_identifier) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    metadata=excluded.metadata
                """,
                (adr_code, f"{adr_code}: {title}", raw_text[:25000], json.dumps(adr_meta)),
            )
            indexed_aliases += 1

            adr_eid = gs._resolve_or_create_entity(gcur, adr_code, "adr", adr_code.lower())
            indexed_entities += 1
            gcur.execute(
                "INSERT OR IGNORE INTO document_entities (doc_id, entity_id, count, context) VALUES (?, ?, 1, ?)",
                (g_doc_id, adr_eid, title),
            )
            gcur.execute(
                """
                INSERT INTO entity_relations (source_entity_id, target_entity_id, relation_type, doc_id, clearance_level)
                VALUES (?, ?, 'GOVERNED_BY', ?, 0)
                ON CONFLICT(source_entity_id, target_entity_id, relation_type, doc_id) DO NOTHING;
                """,
                (homelab_entity_id, adr_eid, g_doc_id),
            )
            indexed_relations += 1

        # Also extract ADR-40 from Chapter 24 / system_overview if present
        if "ADR-40" in raw_text and ("24_sovereign" in fpath.name or "system_overview" in fpath.name):
            adr40_meta = {**meta, "adr_id": "ADR-40"}
            rcur.execute(
                """
                INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata)
                VALUES ('ADR-40', ?, ?, 0, ?)
                ON CONFLICT(doc_identifier) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    metadata=excluded.metadata
                """,
                (f"ADR-40: Two-Pronged Hybrid Retrieval & Resilient Intent Router ({title})", raw_text[:25000], json.dumps(adr40_meta)),
            )
            indexed_aliases += 1
            gcur.execute(
                "INSERT OR IGNORE INTO document_entities (doc_id, entity_id, count, context) VALUES (?, ?, 1, ?)",
                (g_doc_id, adr40_eid, title),
            )

        # Case B: Agent Skills (.agents/skills/<skill_name>/SKILL.md)
        if fpath.name == "SKILL.md" or domain == "agent_skills":
            skill_name = fpath.parent.name
            skill_meta = {**meta, "skill_name": skill_name}
            rcur.execute(
                """
                INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(doc_identifier) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    metadata=excluded.metadata
                """,
                (skill_name, f"Agent Skill: {skill_name} — {title}", raw_text[:25000], json.dumps(skill_meta)),
            )
            indexed_aliases += 1

            skill_eid = gs._resolve_or_create_entity(gcur, skill_name, "agent_skill", skill_name.lower())
            indexed_entities += 1
            gcur.execute(
                "INSERT OR IGNORE INTO document_entities (doc_id, entity_id, count, context) VALUES (?, ?, 1, ?)",
                (g_doc_id, skill_eid, title),
            )
            gcur.execute(
                """
                INSERT INTO entity_relations (source_entity_id, target_entity_id, relation_type, doc_id, clearance_level)
                VALUES (?, ?, 'HAS_SKILL', ?, 0)
                ON CONFLICT(source_entity_id, target_entity_id, relation_type, doc_id) DO NOTHING;
                """,
                (hub_entity_id, skill_eid, g_doc_id),
            )
            indexed_relations += 1

        # Case C: General document entity node in GraphStore
        doc_entity_name = fpath.stem
        doc_eid = gs._resolve_or_create_entity(gcur, doc_entity_name, domain, doc_entity_name.lower())
        indexed_entities += 1
        gcur.execute(
            "INSERT OR IGNORE INTO document_entities (doc_id, entity_id, count, context) VALUES (?, ?, 1, ?)",
            (g_doc_id, doc_eid, title),
        )
        gcur.execute(
            """
            INSERT INTO entity_relations (source_entity_id, target_entity_id, relation_type, doc_id, clearance_level)
            VALUES (?, ?, 'CONTAINS_DOC', ?, 0)
            ON CONFLICT(source_entity_id, target_entity_id, relation_type, doc_id) DO NOTHING;
            """,
            (hub_entity_id, doc_eid, g_doc_id),
        )
        indexed_relations += 1

    router._conn.commit()
    gs._get_connection().commit()
    router.close()
    gs.close()

    update_monitored_sources(router_db=router_db, graph_db=graph_db)
    return {
        "status": "ingested",
        "directory": str(dir_path),
        "domain": domain,
        "indexed_documents": indexed_docs,
        "indexed_deterministic_aliases": indexed_aliases,
        "indexed_entities": indexed_entities,
        "indexed_relations": indexed_relations,
    }


def update_monitored_sources(
    router_db: Path = DEFAULT_ROUTER_DB,
    graph_db: Path = DEFAULT_GRAPH_DB,
) -> Dict[str, Any]:
    """
    Computes live document and entity counts per monitored server source directory
    and writes /home/tlima/Enterprise_Hub/docs/.aegis_vault/monitored_sources.json.
    """
    r_conn = sqlite3.connect(str(router_db))
    g_conn = sqlite3.connect(str(graph_db))

    sources_spec = [
        {
            "id": "huawei_telecom_vault",
            "path": "/home/tlima/Enterprise_Hub/docs/Hua_Docs",
            "domain": "huawei_telecom",
            "description": "Huawei 5G Core & Signaling (UDG, USC, UDM, E9000, S5720) .hdx/.zip archives & alarm catalogs",
            "query_filter": "%Hua_Docs%",
        },
        {
            "id": "homelab_technical_wiki",
            "path": "/home/tlima/Enterprise_Hub/docs/wiki",
            "domain": "homelab_wiki",
            "description": "Enterprise Hub Technical Wiki (111+ chapters, MOCs, runbooks, ADRs 01-40)",
            "query_filter": "%/docs/wiki%",
        },
        {
            "id": "agent_skills_catalog",
            "path": "/home/tlima/Enterprise_Hub/.agents/skills",
            "domain": "agent_skills",
            "description": "Specialized AI Agent Skills Catalog (50+ operational SKILL.md modules)",
            "query_filter": "%/.agents/skills%",
        },
        {
            "id": "aegis_operator_manuals",
            "path": "/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/docs/manuals",
            "domain": "aegis_manuals",
            "description": "Aegis Sovereign Knowledge Appliance Operator & Engineering Manuals (01-15)",
            "query_filter": "%/docs/manuals%",
        },
        {
            "id": "commercial_and_licensing_docs",
            "path": "/home/tlima/Enterprise_Hub/docs/commercial",
            "domain": "commercial_docs",
            "description": "Commercial GTM Playbooks, Pricing Tiers, and Licensing Specifications",
            "query_filter": "%/docs/commercial%",
        },
    ]

    monitored_list = []
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for spec in sources_spec:
        qfilter = spec["query_filter"]
        doc_cnt = r_conn.execute(
            "SELECT COUNT(*) FROM document_records WHERE doc_identifier LIKE ? OR metadata LIKE ?",
            (qfilter, qfilter),
        ).fetchone()[0]
        if spec["domain"] == "huawei_telecom":
            # Include ALM- and MML/Counter records belonging to the Huawei corpus
            doc_cnt = r_conn.execute(
                """
                SELECT COUNT(*) FROM document_records
                WHERE doc_identifier LIKE '%Hua_Docs%'
                   OR metadata LIKE '%Hua_Docs%'
                   OR doc_identifier LIKE 'ALM-%'
                   OR doc_identifier LIKE 'MML:%'
                   OR doc_identifier LIKE 'COUNTER:%'
                """
            ).fetchone()[0]

        g_doc_cnt = g_conn.execute(
            "SELECT COUNT(*) FROM documents WHERE doc_identifier LIKE ? OR COALESCE(url, '') LIKE ? OR corpus = ?",
            (qfilter, qfilter, spec["domain"]),
        ).fetchone()[0]

        monitored_list.append({
            "id": spec["id"],
            "path": spec["path"],
            "domain": spec["domain"],
            "description": spec["description"],
            "router_record_count": doc_cnt,
            "graph_document_count": g_doc_cnt,
            "status": "active" if doc_cnt > 0 else "purged",
            "exists_on_disk": Path(spec["path"]).exists(),
            "last_verified_at": now_iso,
        })

    total_router = r_conn.execute("SELECT COUNT(*) FROM document_records").fetchone()[0]
    total_fts = r_conn.execute("SELECT COUNT(*) FROM document_fts").fetchone()[0]
    total_g_docs = g_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    total_g_ents = g_conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    total_g_rels = g_conn.execute("SELECT COUNT(*) FROM entity_relations").fetchone()[0]

    r_conn.close()
    g_conn.close()

    payload = {
        "vault_location": str(PROD_VAULT_DIR),
        "canonical_router_db": str(router_db),
        "canonical_graph_db": str(graph_db),
        "updated_at": now_iso,
        "totals": {
            "router_records": total_router,
            "fts5_indexed_records": total_fts,
            "graph_documents": total_g_docs,
            "graph_entities": total_g_ents,
            "graph_relations": total_g_rels,
        },
        "sources": monitored_list,
    }
    MONITORED_SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    MONITORED_SOURCES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def purge_source(
    prefix: str,
    router_db: Path = DEFAULT_ROUTER_DB,
    graph_db: Path = DEFAULT_GRAPH_DB,
) -> Dict[str, Any]:
    """
    Purges all records, FTS5 tokens, graph documents, relations, and orphaned entities
    matching `prefix` from the unified server vault, and updates monitored_sources.json.
    """
    t0 = time.perf_counter()
    gs = GraphStore(db_path=graph_db)
    router = SovereignQueryRouter(db_path=router_db, graph_store=gs, plan=PlanTier.ENTERPRISE)

    r_res = router.purge_records_by_prefix(prefix)
    g_res = gs.purge_documents_by_prefix(prefix)

    try:
        router._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        gs._get_connection().execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception:
        pass

    router.close()
    gs.close()
    manifest = update_monitored_sources(router_db=router_db, graph_db=graph_db)
    return {
        "status": "purged",
        "prefix": prefix,
        **r_res,
        **g_res,
        "remaining_totals": manifest["totals"],
        "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
    }


def consolidate_all_server_knowledge() -> Dict[str, Any]:
    """
    Executes the complete Unified Server Knowledge Consolidation:
    1. Merges /home/tlima/Enterprise_Hub/data/rag/graph_store.db & appliance data/rag/graph_store.db into sovereign_graph.db
    2. Replaces scattered graph_store.db files with symlinks to docs/.aegis_vault/sovereign_graph.db
    3. Ingests Homelab Wiki & ADRs (docs/wiki), Agent Skills (.agents/skills), Aegis Manuals, and Commercial Docs
    4. Checkpoints WAL and writes monitored_sources.json
    """
    t0 = time.perf_counter()
    merge_reports = {}

    # 1. Merge existing RAG graph databases
    server_rag_db = REPO_ROOT / "data" / "rag" / "graph_store.db"
    appliance_rag_db = APPLIANCE_ROOT / "data" / "rag" / "graph_store.db"

    if server_rag_db.exists() and not server_rag_db.is_symlink():
        merge_reports["server_rag_graph_db"] = merge_external_graph_db(DEFAULT_GRAPH_DB, server_rag_db)
        for suf in ("", "-wal", "-shm"):
            p = REPO_ROOT / "data" / "rag" / f"graph_store.db{suf}"
            if p.exists() or p.is_symlink():
                p.unlink()
        server_rag_db.symlink_to(DEFAULT_GRAPH_DB)

    if appliance_rag_db.exists() and not appliance_rag_db.is_symlink():
        merge_reports["appliance_rag_graph_db"] = merge_external_graph_db(DEFAULT_GRAPH_DB, appliance_rag_db)

    # Remove stray dev/aegis-sovereign-appliance/data/rag directory
    stray_rag_dir = APPLIANCE_ROOT / "data" / "rag"
    if stray_rag_dir.exists():
        shutil.rmtree(stray_rag_dir)

    # 2. Ingest all server knowledge directories
    ingestion_reports = {}
    for path_rel, domain in [
        ("docs/wiki", "homelab_wiki"),
        (".agents/skills", "agent_skills"),
        ("dev/aegis-sovereign-appliance/docs/manuals", "aegis_manuals"),
        ("docs/commercial", "commercial_docs"),
    ]:
        full_p = REPO_ROOT / path_rel
        if full_p.exists():
            ingestion_reports[domain] = ingest_directory(full_p, domain=domain)

    # 3. Checkpoint both databases so main .db files contain 100% of data
    for db_p in (DEFAULT_ROUTER_DB, DEFAULT_GRAPH_DB):
        conn = sqlite3.connect(str(db_p))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.close()

    manifest = update_monitored_sources()
    return {
        "status": "consolidated",
        "merge_reports": merge_reports,
        "ingestion_reports": ingestion_reports,
        "manifest": manifest,
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Aegis Sovereign Unified Vault Lifecycle CLI")
    parser.add_argument("--status", action="store_true", help="Show unified database breakdown by server directory/domain")
    parser.add_argument("--consolidate-all", action="store_true", help="Merge and ingest all server knowledge into sovereign_router.db & sovereign_graph.db")
    parser.add_argument("--ingest", type=str, help="Directory path to ingest into the unified vault")
    parser.add_argument("--domain", type=str, default="custom_corpus", help="Domain tag when using --ingest")
    parser.add_argument("--purge", type=str, help="Source path or identifier prefix to purge from router DB, FTS5, and GraphStore")
    args = parser.parse_args()

    if args.consolidate_all:
        res = consolidate_all_server_knowledge()
        print(json.dumps(res, indent=2))
    elif args.ingest:
        res = ingest_directory(Path(args.ingest), domain=args.domain)
        print(json.dumps(res, indent=2))
    elif args.purge:
        res = purge_source(args.purge)
        print(json.dumps(res, indent=2))
    else:
        manifest = update_monitored_sources()
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
