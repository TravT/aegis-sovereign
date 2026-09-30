#!/usr/bin/env python3
"""Tests for search-time de-duplication (`core.structure.search`, `collapse_by_topic(min_overlap)`, router wiring)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

AEGIS_ROOT = Path(__file__).resolve().parent.parent
if str(AEGIS_ROOT) not in sys.path:
    sys.path.insert(0, str(AEGIS_ROOT))

from core import structure as st  # noqa: E402
from core.router import SovereignQueryRouter  # noqa: E402
from core.security import PlanTier  # noqa: E402
from core.structure.search import active_policy, fold_duplicates  # noqa: E402

PAGE = (
    "The module fault alarm is generated when the module is stopped abnormally or killed and is cleared when the module recovers "
    "This alarm is a high risk alarm and must be handled immediately after it is generated otherwise service configuration will fail "
    "The arbitration PMU module monitors the status of other modules and raises the alarm for the faulty module "
    "Attribute Alarm ID 1003 Alarm Severity Major Auto Clear Yes Parameters ME ID identifies the managed element where the faulty module resides"
)
DOSSIER = PAGE + " Root alarm relationship ALM 6402 file loading failure causes it Auto healing escalates from process to pod to node with waits of ten seventeen and thirty one minutes"


def _hit(i, topic, kind, text):
    return {"id": i, "topic_id": topic, "record_kind": kind, "content": text}


# ------------------------------------------------------------------------- overlap-gated collapse
def test_min_overlap_folds_near_identical_but_keeps_records_that_add_information():
    ranked = [
        _hit(1, "T1", "composite", PAGE + " (copy with a header)"),  # near-identical to the native: folds
        _hit(2, "T1", "native", PAGE),
        _hit(3, "T2", "composite", DOSSIER),  # adds root-alarm information: must stay visible
        _hit(4, "T2", "native", PAGE),
    ]
    out = st.collapse_by_topic(ranked, min_overlap=0.85)
    assert [(r["id"], r["collapsed"]) for r in out] == [(2, 1), (3, 0), (4, 0)]
    assert [r["id"] for r in st.collapse_by_topic(ranked)] == [2, 4]  # without a threshold: legacy behaviour


def test_missing_text_never_folds():
    out = st.collapse_by_topic([_hit(1, "T", "composite", ""), _hit(2, "T", "native", PAGE)], min_overlap=0.85)
    assert [r["id"] for r in out] == [1, 2]


# ------------------------------------------------------------------------- fold_duplicates on a database
def _db(tmp_path: Path, with_columns: bool = True) -> Path:
    db = tmp_path / "r.db"
    c = sqlite3.connect(db)
    extra = ", topic_id TEXT, record_kind TEXT" if with_columns else ""
    c.execute(f"CREATE TABLE document_records (id INTEGER PRIMARY KEY, doc_identifier TEXT, title TEXT, content TEXT{extra})")
    rows = [(1, "a", "t1", PAGE, "T1", "composite"), (2, "b", "t1n", PAGE, "T1", "native"), (3, "c", "t2", DOSSIER, "T2", "composite"), (4, "d", "t2n", PAGE, "T2", "native")]
    for r in rows:
        if with_columns:
            c.execute("INSERT INTO document_records VALUES (?,?,?,?,?,?)", r)
        else:
            c.execute("INSERT INTO document_records VALUES (?,?,?,?)", r[:4])
    c.commit()
    c.close()
    return db


def _hits():
    return [{"id": i, "content": t} for i, t in ((1, PAGE), (2, PAGE), (3, DOSSIER), (4, PAGE))]


def test_fold_duplicates_annotates_folds_and_respects_limit(tmp_path, monkeypatch):
    monkeypatch.delenv("AEGIS_SIZE_PROFILE", raising=False)
    db = str(_db(tmp_path))
    out = fold_duplicates(db, _hits(), limit=10)
    assert [(h["id"], h["record_kind"], h["collapsed"]) for h in out] == [(2, "native", 1), (3, "composite", 0), (4, "native", 0)]
    assert [h["id"] for h in fold_duplicates(db, _hits(), limit=2)] == [2, 3]  # slice AFTER folding


def test_profiles_and_graceful_no_ops(tmp_path, monkeypatch):
    db = str(_db(tmp_path))
    monkeypatch.setenv("AEGIS_SIZE_PROFILE", "datacenter")  # tier 3 keeps every derived record visible
    assert [h["id"] for h in fold_duplicates(db, _hits(), limit=10)] == [1, 2, 3, 4]
    monkeypatch.setenv("AEGIS_SIZE_PROFILE", "desktop")
    assert len(fold_duplicates(db, _hits(), limit=10)) == 3
    monkeypatch.setenv("AEGIS_SIZE_PROFILE", "nonsense")
    assert active_policy().name == "edge"  # unknown value falls back to edge
    monkeypatch.delenv("AEGIS_SIZE_PROFILE")
    old = str(_db(tmp_path / "..", with_columns=False)) if False else None
    plain = tmp_path / "plain.db"
    c = sqlite3.connect(plain)
    c.execute("CREATE TABLE document_records (id INTEGER PRIMARY KEY, doc_identifier TEXT, title TEXT, content TEXT)")
    c.commit()
    c.close()
    assert [h["id"] for h in fold_duplicates(str(plain), _hits(), limit=3)] == [1, 2, 3]  # no structure columns: untouched
    assert [h["id"] for h in fold_duplicates(":memory:", _hits(), limit=2)] == [1, 2]
    assert fold_duplicates(str(tmp_path / "missing.db"), _hits(), limit=2) == _hits()[:2]
    assert fold_duplicates(db, [], limit=5) == []


def test_many_ids_are_batched(tmp_path):
    db = tmp_path / "big.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE document_records (id INTEGER PRIMARY KEY, doc_identifier TEXT, title TEXT, content TEXT, topic_id TEXT, record_kind TEXT)")
    c.executemany("INSERT INTO document_records VALUES (?,?,?,?,?,?)", [(i, str(i), "t", "x", f"T{i}", "native") for i in range(1, 1201)])
    c.commit()
    c.close()
    hits = [{"id": i, "content": "x"} for i in range(1, 1201)]
    assert len(fold_duplicates(str(db), hits, limit=2000)) == 1200


# ------------------------------------------------------------------------- end to end through the router
def test_router_returns_the_requested_number_of_distinct_results(tmp_path, monkeypatch):
    monkeypatch.delenv("AEGIS_SIZE_PROFILE", raising=False)
    router = SovereignQueryRouter(db_path=str(tmp_path / "router.db"), plan=PlanTier.PRO)
    try:
        conn = router._conn
        for col in ("topic_id", "record_kind"):
            conn.execute(f"ALTER TABLE document_records ADD COLUMN {col} TEXT")
        pages = [
            ("native-1", "Alarm module fault page", PAGE, "T1", "native"),
            ("curated-1", "Alarm module fault curated copy", PAGE + " summary", "T1", "composite"),
            ("native-2", "Alarm module fault second page", PAGE + " second variant with other words about disks", "T2", "native"),
            ("native-3", "Alarm module fault third page", PAGE + " third variant about pods and nodes", "T3", "native"),
        ]
        for ident, title, text, topic, kind in pages:
            conn.execute(
                "INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata, topic_id, record_kind) VALUES (?,?,?,?,?,?,?)",
                (ident, title, text, 0, json.dumps({}), topic, kind),
            )
        conn.commit()
        res = router.route_and_execute(query="module fault alarm cleared when module recovers", user_clearance="restricted", limit=3)
        results = res.get("results") or []
        idents = [r.get("doc_identifier") for r in results]
        assert len(results) <= 3
        assert not ("native-1" in idents and "curated-1" in idents), idents  # the near-identical copy is folded away
    finally:
        router.close()
