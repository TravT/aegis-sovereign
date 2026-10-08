#!/usr/bin/env python3
"""
Integration Test Suite for Universal Email Ingestion (.eml) & Deletion/Tombstone Lifecycle (ADR-13, ADR-37).

Tests:
1. RFC-5322 EmailHandler parsing, thread genealogy, quote stripping, and ADR-13 conformance.
2. Ingestion pipeline of mock email threads containing unique canary tokens (CANARY-CORPUS-99182).
3. FTS5 search verification and topic tree outline construction.
4. Embedded Qdrant vector indexing and payload association.
5. Atomic purge_document lifecycle:
   - 0 rows remaining in SQLite document_records
   - 0 search hits in document_fts
   - 0 orphan nodes in topic_nodes
   - 0 dangling edges in topic_edges
   - 0 invalid references in semantic_bridges
   - 0 points remaining in Qdrant vector collection
   - Sibling and non-targeted documents remain 100% intact
   - Idempotency on repeated purge calls
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.ingest.conformance import check_handler
from core.ingest.deletion import purge_document
from core.ingest.handlers.eml import EmailHandler
from core.ingest.pipeline import IngestOptions, ingest_source
from core.structure import get_profile

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False


# ==============================================================================
# 1. Mock Email Fixtures
# ==============================================================================

MOCK_EMAIL_PROPOSAL = b"""From: engineering-lead@enterprise.lan
To: architecture-board@enterprise.lan
Subject: [PROPOSAL] Air-Gapped High-Availability Sovereign Cluster
Date: Mon, 05 Oct 2026 09:15:00 +0000
Message-ID: <msg-20261005-001@enterprise.lan>
Content-Type: text/plain; charset="utf-8"

Team,
We are proposing the deployment of CANARY-CORPUS-99182 for air-gapped sovereign document management.
Key requirements:
1. Pure local execution on Dell Latitude 7390 and edge appliances.
2. Zero egress policy.
3. Resilient deletion semantics with zero ghost tokens.

Regards,
Engineering Lead
"""

MOCK_EMAIL_REPLY = b"""From: security-officer@enterprise.lan
To: engineering-lead@enterprise.lan
Subject: Re: [PROPOSAL] Air-Gapped High-Availability Sovereign Cluster
Date: Mon, 05 Oct 2026 11:30:00 +0000
Message-ID: <msg-20261005-002@enterprise.lan>
In-Reply-To: <msg-20261005-001@enterprise.lan>
References: <msg-20261005-001@enterprise.lan>
Content-Type: text/plain; charset="utf-8"

Approved from security standpoint. Ensure CANARY-CORPUS-99182 handles GDPR/LGPD article purging cleanly.

> Team,
> We are proposing the deployment of CANARY-CORPUS-99182 for air-gapped sovereign document management.
> Key requirements:
> 1. Pure local execution on Dell Latitude 7390 and edge appliances.
> 2. Zero egress policy.
> 3. Resilient deletion semantics with zero ghost tokens.
> 
> Regards,
> Engineering Lead
"""

MOCK_EMAIL_UNRELATED = b"""From: facility@enterprise.lan
To: all@enterprise.lan
Subject: Scheduled Maintenance Window
Date: Tue, 06 Oct 2026 08:00:00 +0000
Message-ID: <msg-20261006-facility@enterprise.lan>
Content-Type: text/plain; charset="utf-8"

Reminder that primary server room power maintenance will occur this weekend.
Homelab systems should be gracefully quiesced.
"""


def _init_test_db(db_path: Path) -> Path:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE document_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_identifier TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            clearance_level INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            topic_id TEXT,
            record_kind TEXT DEFAULT 'native',
            console TEXT,
            plane TEXT
        );
        CREATE VIRTUAL TABLE document_fts USING fts5(
            title, content, content='document_records', content_rowid='id'
        );
        CREATE TRIGGER document_records_ai AFTER INSERT ON document_records BEGIN
            INSERT INTO document_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
        END;
        CREATE TRIGGER document_records_ad AFTER DELETE ON document_records BEGIN
            INSERT INTO document_fts(document_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
        END;
        CREATE TABLE topic_nodes (
            topic_id TEXT PRIMARY KEY,
            package TEXT,
            name TEXT,
            depth INTEGER,
            source TEXT,
            path_text TEXT
        );
        CREATE TABLE topic_edges (
            child TEXT NOT NULL,
            parent TEXT,
            is_primary INTEGER DEFAULT 1,
            PRIMARY KEY(child, parent)
        );
        CREATE TABLE structure_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE semantic_bridges (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            similarity REAL,
            rationale TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_id, target_id)
        );
        """
    )
    conn.commit()
    conn.close()
    return db_path


# ==============================================================================
# 2. Conformance & Parsing Unit Tests
# ==============================================================================

def test_email_handler_conformance():
    """Validates that EmailHandler strictly passes ADR-13 conformance across all tiers."""
    handler = EmailHandler()
    for profile_name in ("desktop", "edge", "datacenter"):
        problems = check_handler(
            handler,
            "canary_proposal.eml",
            MOCK_EMAIL_PROPOSAL,
            get_profile(profile_name),
            fuzz=True,
        )
        assert problems == [], f"Conformance failed for {profile_name}: {problems}"


def test_email_quote_stripping_and_thread_genealogy():
    """Asserts that thread headers are captured and duplicate blockquotes are stripped."""
    handler = EmailHandler()
    doc = handler.parse("reply.eml", MOCK_EMAIL_REPLY)

    assert doc.title == "Re: [PROPOSAL] Air-Gapped High-Availability Sovereign Cluster"
    section_map = {s.path[0]: s.text for s in doc.sections}

    assert "Headers" in section_map
    assert "Message-ID: <msg-20261005-002@enterprise.lan>" in section_map["Headers"]
    assert "In-Reply-To: <msg-20261005-001@enterprise.lan>" in section_map["Headers"]

    assert "Message Body" in section_map
    body = section_map["Message Body"]
    assert "Approved from security standpoint." in body
    # Verifies quoted tail was stripped to preserve token budget
    assert "> Team," not in body
    assert "> 1. Pure local execution" not in body


# ==============================================================================
# 3. Ingestion, Search, and Complete Deletion Lifecycle
# ==============================================================================

def test_email_ingestion_and_atomic_purge_lifecycle(tmp_path):
    """
    End-to-End Test:
    1. Ingest email corpus with CANARY-CORPUS-99182 into SQLite & Qdrant.
    2. Verify searchability in SQLite FTS5 and presence in topic tree.
    3. Purge the target canary email.
    4. Assert total eradication: 0 records, 0 FTS hits, 0 orphan graph nodes, 0 dangling bridges, 0 Qdrant points.
    5. Assert sibling unrelated emails remain 100% intact.
    """
    db_path = _init_test_db(tmp_path / "sovereign_router.db")
    work_dir = tmp_path / "emails"
    work_dir.mkdir()

    canary_file = work_dir / "proposal.eml"
    canary_file.write_bytes(MOCK_EMAIL_PROPOSAL)

    other_file = work_dir / "maintenance.eml"
    other_file.write_bytes(MOCK_EMAIL_UNRELATED)

    # 1. Ingest both emails via pipeline
    opts = IngestOptions(label="MAIL", policy=get_profile("desktop"), mode="replace")
    rep = ingest_source(db_path, work_dir, opts)
    assert rep["files"]["ingested"] == 2

    conn = sqlite3.connect(str(db_path))
    # Verify records in SQLite
    canary_records = conn.execute(
        "SELECT id, doc_identifier, topic_id FROM document_records WHERE content LIKE '%CANARY-CORPUS-99182%'"
    ).fetchall()
    assert len(canary_records) >= 1
    canary_topic_id = canary_records[0][2]

    # Verify FTS5 match
    fts_hits = conn.execute(
        "SELECT COUNT(*) FROM document_fts WHERE document_fts MATCH '\"CANARY-CORPUS-99182\"'"
    ).fetchone()[0]
    assert fts_hits >= 1

    # Verify topic tree
    assert conn.execute(
        "SELECT COUNT(*) FROM topic_nodes WHERE topic_id = ?", (canary_topic_id,)
    ).fetchone()[0] == 1

    # Add a mock semantic bridge for testing bridge cleanup
    other_topic = conn.execute(
        "SELECT topic_id FROM document_records WHERE doc_identifier LIKE '%maintenance.eml%' LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO semantic_bridges (source_id, target_id, similarity, rationale) VALUES (?, ?, 0.85, 'Test Bridge')",
        (canary_topic_id, other_topic),
    )
    conn.commit()
    conn.close()

    # 2. Setup Qdrant Client (if available)
    qdrant = None
    col_name = "sovereign_test_chunks"
    if HAS_QDRANT:
        qdrant = QdrantClient(location=":memory:")
        qdrant.create_collection(
            collection_name=col_name,
            vectors_config=VectorParams(size=4, distance=Distance.COSINE),
        )
        # Upsert point for canary file and unrelated file
        qdrant.upsert(
            collection_name=col_name,
            points=[
                PointStruct(
                    id=1,
                    vector=[0.1, 0.2, 0.3, 0.4],
                    payload={"file_path": str(canary_file), "token": "CANARY-CORPUS-99182"},
                ),
                PointStruct(
                    id=2,
                    vector=[0.5, 0.6, 0.7, 0.8],
                    payload={"file_path": str(other_file), "token": "MAINTENANCE"},
                ),
            ],
        )
        assert qdrant.count(collection_name=col_name).count == 2

    # 3. Purge target canary document
    purge_stats = purge_document(
        db_path,
        str(canary_file),
        qdrant_client=qdrant,
        collection_name=col_name,
    )

    assert purge_stats["deleted_records"] >= 1
    assert purge_stats["deleted_topics"] >= 1
    assert purge_stats["deleted_bridges"] >= 1

    # 4. Assert Zero Ghost Records & Complete Invalidation
    conn = sqlite3.connect(str(db_path))

    # A. 0 rows in document_records for canary
    assert conn.execute(
        "SELECT COUNT(*) FROM document_records WHERE content LIKE '%CANARY-CORPUS-99182%'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM document_records WHERE doc_identifier LIKE ? OR doc_identifier LIKE ?",
        (f"%{canary_file.name}%", f"%{str(canary_file)}%"),
    ).fetchone()[0] == 0

    # B. 0 search hits in document_fts
    conn.execute("INSERT INTO document_fts(document_fts) VALUES('integrity-check')")
    fts_remaining = conn.execute(
        "SELECT COUNT(*) FROM document_fts WHERE document_fts MATCH '\"CANARY-CORPUS-99182\"'"
    ).fetchone()[0]
    assert fts_remaining == 0

    # C. 0 orphan nodes in topic_nodes
    assert conn.execute(
        "SELECT COUNT(*) FROM topic_nodes WHERE topic_id = ?", (canary_topic_id,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM topic_nodes WHERE name = ?", (canary_file.name,)
    ).fetchone()[0] == 0

    # D. 0 dangling edges in topic_edges
    assert conn.execute(
        "SELECT COUNT(*) FROM topic_edges WHERE child NOT IN (SELECT topic_id FROM topic_nodes)"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM topic_edges WHERE parent IS NOT NULL AND parent NOT IN (SELECT topic_id FROM topic_nodes)"
    ).fetchone()[0] == 0

    # E. 0 dangling bridges in semantic_bridges
    assert conn.execute(
        "SELECT COUNT(*) FROM semantic_bridges WHERE source_id = ? OR target_id = ?",
        (canary_topic_id, canary_topic_id),
    ).fetchone()[0] == 0

    # F. Sibling document remains 100% functional and intact!
    remaining_docs = conn.execute(
        "SELECT COUNT(*) FROM document_records WHERE doc_identifier LIKE '%maintenance.eml%'"
    ).fetchone()[0]
    assert remaining_docs >= 1

    conn.close()

    # G. Qdrant point for canary purged, unrelated preserved
    if HAS_QDRANT and qdrant:
        assert qdrant.count(collection_name=col_name).count == 1
        surviving = qdrant.retrieve(collection_name=col_name, ids=[2])
        assert len(surviving) == 1
        assert surviving[0].payload["token"] == "MAINTENANCE"

    # 5. Idempotent re-purge does not crash or corrupt
    idempotent_stats = purge_document(
        db_path,
        str(canary_file),
        qdrant_client=qdrant,
        collection_name=col_name,
    )
    assert idempotent_stats["deleted_records"] == 0
    assert idempotent_stats["deleted_topics"] == 0
