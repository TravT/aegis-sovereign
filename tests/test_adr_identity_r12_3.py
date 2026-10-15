"""Phase 12.3 (R-g): two ADR series with the same numbers, and one document filling the top 5.

Homelab ADRs keep "ADR-nn"; Aegis ADRs are "Aegis ADR-nn" (owner decision, 13 Oct: titles, aliases, router
prefix; no file renames). Before: one `ADR-nn` record per number, whichever series was written last (ADR-01..11
were Aegis, ADR-12..35 homelab), and "ADR-16" returned four parts of one document in the top 5.
Runs on temporary vaults only.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from core.router import SovereignQueryRouter
from tools.adr_identity import adr_identity, sync_adr_records

TRAEFIK = "---\ntitle: 'ADR-16: Traefik as Dynamic Ingress'\naliases:\n- ADR-16\n---\n\n# ADR 16: Traefik as Dynamic Ingress\n\nTraefik routes.\n"
VISION = "---\ntitle: 'ADR-40: Tiered Vision'\n---\n\n# ADR-40: Tiered Vision\n\nEdge to homelab.\n"
ARCHIVE = "---\ntitle: 'Aegis ADR-16: Archive Streaming'\n---\n\n# Aegis ADR-16: Archive Streaming\n\nCheckpoint index.\n"


@pytest.fixture()
def wiki(tmp_path):
    w = tmp_path / "wiki"
    (w / "adrs").mkdir(parents=True)
    (w / "projects" / "aegis" / "adrs").mkdir(parents=True)
    (w / "adrs" / "ADR-16-Traefik-Dynamic-Ingress.md").write_text(TRAEFIK, encoding="utf-8")
    (w / "adrs" / "ADR-40-Tiered-Vision.md").write_text(VISION, encoding="utf-8")
    (w / "adrs" / "README.md").write_text("# ADRs\n", encoding="utf-8")
    (w / "projects" / "aegis" / "adrs" / "ADR-16-Archive-Streaming.md").write_text(ARCHIVE, encoding="utf-8")
    return w


def _record(conn, ident, title, content, meta):
    conn.execute(
        "INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata) VALUES (?, ?, ?, 0, ?)",
        (ident, title, content, json.dumps(meta)),
    )


@pytest.fixture()
def vault(tmp_path, wiki):
    """A vault in today's broken state: ADR-16 holds the Aegis ADR, ADR-40 the Chapter 24 alias, ADR-99 is stale."""
    db = tmp_path / "router.db"
    SovereignQueryRouter(db_path=str(db))._conn.close()
    aegis = wiki / "projects" / "aegis" / "adrs" / "ADR-16-Archive-Streaming.md"
    traefik = wiki / "adrs" / "ADR-16-Traefik-Dynamic-Ingress.md"
    with sqlite3.connect(db) as conn:
        _record(conn, "ADR-16", "ADR-16: ADR-16: Archive Streaming", "Checkpoint index.", {"file_path": str(aegis)})
        _record(conn, "ADR-40", "ADR-40: Two-Pronged Router (Chapter 24)", "router", {"file_path": str(wiki / "24.md")})
        _record(conn, "ADR-99", "ADR-99: Gone", "gone", {"file_path": str(wiki / "adrs" / "ADR-99-Gone.md")})
        for i in range(1, 5):  # wiki chunks as the watcher stores them, all mentioning the id
            _record(conn, f"{aegis}::part::000{i}", f"ADR-16: Archive Streaming [{i}/4]",
                    f"ADR-16 archive streaming part {i}", {"virtual_uri": str(aegis)})
        _record(conn, f"{traefik}::part::0001", "ADR-16: Traefik [1/1]", "ADR-16 traefik ingress", {"virtual_uri": str(traefik)})
    return db


def test_identity_per_series_without_doubled_prefix(wiki):
    t = adr_identity(wiki / "adrs" / "ADR-16-Traefik-Dynamic-Ingress.md", "ADR 16: Traefik as Dynamic Ingress")
    assert t == ("ADR-16", "ADR-16: Traefik as Dynamic Ingress", "homelab")
    a = adr_identity(wiki / "projects" / "aegis" / "adrs" / "ADR-16-Archive-Streaming.md", "ADR-16: Archive Streaming")
    assert a == ("Aegis ADR-16", "Aegis ADR-16: Archive Streaming", "aegis")
    again = adr_identity(wiki / "projects" / "aegis" / "adrs" / "ADR-16-Archive-Streaming.md", "Aegis ADR-16: Archive Streaming")
    assert again[1] == "Aegis ADR-16: Archive Streaming"
    assert adr_identity(wiki / "adrs" / "README.md", "ADRs") is None
    assert adr_identity(wiki / "notes" / "ADR-16-copy.md", "x") is None  # only files in an adrs folder


def test_router_recognises_the_aegis_prefix():
    r = SovereignQueryRouter(db_path=":memory:")
    assert r.analyze_query("Aegis ADR-16").extracted_identifier.normalized_value == "Aegis ADR-16"
    assert r.analyze_query("what did aegis adr-7 decide").extracted_identifier.normalized_value == "Aegis ADR-07"
    assert r.analyze_query("ADR-16").extracted_identifier.normalized_value == "ADR-16"


def test_sync_dry_run_changes_nothing_then_apply_fixes_identity(vault, wiki):
    before = sqlite3.connect(vault).execute("SELECT COUNT(*), group_concat(title, '|') FROM document_records").fetchone()
    plan = sync_adr_records(vault, wiki, apply=False)
    assert plan["applied"] is False
    assert sorted(plan["upsert"]) == ["ADR-16", "ADR-40", "Aegis ADR-16"]
    assert plan["delete"] == ["ADR-99"]
    assert sqlite3.connect(vault).execute("SELECT COUNT(*), group_concat(title, '|') FROM document_records").fetchone() == before

    done = sync_adr_records(vault, wiki, apply=True)
    assert done["applied"] is True
    conn = sqlite3.connect(vault)
    rows = dict(conn.execute("SELECT doc_identifier, title FROM document_records WHERE doc_identifier NOT LIKE '%::part::%'"))
    assert rows == {
        "ADR-16": "ADR-16: Traefik as Dynamic Ingress",
        "ADR-40": "ADR-40: Tiered Vision",
        "Aegis ADR-16": "Aegis ADR-16: Archive Streaming",
    }
    meta = json.loads(conn.execute("SELECT metadata FROM document_records WHERE doc_identifier = 'Aegis ADR-16'").fetchone()[0])
    assert meta["adr_series"] == "aegis" and meta["file_path"].endswith("projects/aegis/adrs/ADR-16-Archive-Streaming.md")
    # The full-text index follows (triggers): the new id is searchable, the stale one is not.
    fts = lambda q: conn.execute("SELECT COUNT(*) FROM document_fts WHERE document_fts MATCH ?", (q,)).fetchone()[0]
    assert fts('"Aegis ADR-16"') >= 1 and fts('"ADR-99"') == 0

    assert sync_adr_records(vault, wiki, apply=True)["upsert"] == []  # idempotent


def test_adr16_returns_both_series_labelled_one_slot_per_document(vault, wiki):
    sync_adr_records(vault, wiki, apply=True)
    router = SovereignQueryRouter(db_path=str(vault))
    res = router.route_and_execute("ADR-16", user_clearance="restricted", limit=5)
    titles = [r["title"] for r in res["results"]]
    assert any(t.startswith("ADR-16: Traefik") for t in titles), titles
    assert any(t.startswith("Aegis ADR-16:") for t in titles), titles
    docs = [r.get("virtual_uri") for r in res["results"]]
    assert len(docs) == len(set(docs)) == 2, docs  # 7 matching records, 2 documents

    aegis = router.route_and_execute("Aegis ADR-16", user_clearance="restricted", limit=5)
    assert aegis["results"][0]["title"].startswith("Aegis ADR-16:")
    assert aegis["route_type"] == "deterministic_direct"
