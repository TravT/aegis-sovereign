#!/usr/bin/env python3
"""Tests for `tools/migrate_topic_tree.py` (Stage 1: bookmap/navi topic tree + record classification)."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

AEGIS_ROOT = Path(__file__).resolve().parent.parent
if str(AEGIS_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(AEGIS_ROOT / "tools"))

import migrate_topic_tree as mtt  # noqa: E402

PKG_STEM = "Fake Product Doc 1.0"

BOOKMAP = """<?xml version="1.0"?>
<topics>
  <topic name="Commands" id="ROOT_1">
    <topic name="Operation and Maintenance Commands" id="CAT_1">
      <topic name="Add Widget (ADD WIDGET)" id="MMLREF_1"/>
      <topic name="Shared Topic" id="SHARED_1"/>
    </topic>
    <topic name="PGW Web LMT Commands" id="CAT_2">
      <topic name="Shared Topic" id="SHARED_1"/>
      <topic name="List Binding (LST BINDINFO)" id="MMLREF_2"/>
    </topic>
  </topic>
  <topic name="Counters" id="ROOT_2">
    <topic name="1753409340 Successful Processed Rate of Diameter Messages" id="PMIREF_1"/>
  </topic>
</topics>"""

NAVI = """<?xml version="1.0"?>
<topics>
  <topic txt="Feature Guide" url="toctopics/fg.html">
    <topic txt="Feature X Description" url="feature/x.html"/>
  </topic>
</topics>"""


def _html(ident: str | None) -> bytes:
    meta = f'<meta name="DC.Identifier" content="EN-US_{ident}">' if ident else ""
    return f"<html><head>{meta}</head><body>x</body></html>".encode()


def _build_package(tmp_path: Path) -> Path:
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("resources/infocenter_service/map/pid_bookmap_1.xml", BOOKMAP)
        z.writestr("resources/navi.xml", NAVI)
        z.writestr("resources/mml/add_widget.html", _html("MMLREF_1"))
        z.writestr("resources/mml/lst_bindinfo.html", _html("MMLREF_2"))
        z.writestr("resources/kpi/1753409340.html", _html("PMIREF_1"))
        z.writestr("resources/feature/x.html", _html(None))
        z.writestr("resources/toctopics/fg.html", _html(None))
    outer = tmp_path / f"{PKG_STEM}.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr(f"{PKG_STEM}.hwics", inner.getvalue())
    return outer


def _uri(path: str) -> str:
    return f"archive:///x/{PKG_STEM}.zip!{PKG_STEM}.hwics#{path}"


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "router.db"
    c = sqlite3.connect(db)
    c.executescript(
        """
        CREATE TABLE document_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, doc_identifier TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL, content TEXT NOT NULL, clearance_level INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE VIRTUAL TABLE document_fts USING fts5(title, content, content='document_records', content_rowid='id');
        CREATE TRIGGER document_records_ai AFTER INSERT ON document_records BEGIN
            INSERT INTO document_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
        END;
        """
    )
    rows = [
        # native: identifier is the file's own path
        (_uri("resources/mml/add_widget.html"), "USC 26.1.0: Add Widget (ADD WIDGET)", {"virtual_uri": _uri("resources/mml/add_widget.html")}),
        # curated record for the same topic, title agrees -> composite
        ("ADD WIDGET", "ADD WIDGET — Add a widget (ADD WIDGET) (USC 26.1.0)", {"virtual_uri": _uri("resources/mml/add_widget.html")}),
        # curated record borrowing the wrong file -> synthetic, no topic
        ("DSP GADGET", "DSP GADGET — Display gadget (DSP GADGET)", {"virtual_uri": _uri("resources/mml/lst_bindinfo.html")}),
        # native KPI page
        (_uri("resources/kpi/1753409340.html"), "USC 26.1.0: 1753409340 Successful Processed Rate", {"virtual_uri": _uri("resources/kpi/1753409340.html")}),
        # navi-only narrative topic (no DC.Identifier)
        (_uri("resources/feature/x.html"), "USC 26.1.0: Feature X Description", {"virtual_uri": _uri("resources/feature/x.html")}),
        # not from any package
        ("/wiki/notes.md", "Some wiki note", {}),
        # release-doc record: no bookmap yet
        ("archive:///x/Fake_ReleaseDoc.zip#a/b.docx", "OpenXML Manual: b.docx", {"virtual_uri": "archive:///x/Fake_ReleaseDoc.zip#a/b.docx"}),
    ]
    for ident, title, meta in rows:
        c.execute("INSERT INTO document_records (doc_identifier,title,content,metadata) VALUES (?,?,?,?)", (ident, title, "body of " + title, json.dumps(meta)))
    c.commit()
    c.close()
    return db


@pytest.fixture()
def migrated(tmp_path):
    pkg = _build_package(tmp_path)
    db = _make_db(tmp_path)
    report = mtt.migrate(db, {"FP": pkg})
    return db, report, pkg


def _kinds(db):
    c = sqlite3.connect(db)
    return {r[0]: r[1:] for r in c.execute("SELECT doc_identifier, record_kind, topic_id, console FROM document_records")}


def test_tree_nodes_edges_and_multi_parent(migrated):
    db, report, _ = migrated
    c = sqlite3.connect(db)
    assert report["multi_parent_topics"]["FP"] == 1
    assert c.execute("SELECT COUNT(*) FROM topic_edges WHERE child='FP:SHARED_1'").fetchone()[0] == 2
    assert c.execute("SELECT COUNT(*) FROM topic_edges WHERE child='FP:SHARED_1' AND is_primary=1").fetchone()[0] == 1
    # the primary parent is the first occurrence
    assert c.execute("SELECT parent FROM topic_edges WHERE child='FP:SHARED_1' AND is_primary=1").fetchone()[0] == "FP:CAT_1"
    assert c.execute("SELECT path_text FROM topic_nodes WHERE topic_id='FP:MMLREF_1'").fetchone()[0] == (
        "Commands > Operation and Maintenance Commands > Add Widget (ADD WIDGET)"
    )
    # every bookmap node has exactly one primary edge
    assert c.execute(
        "SELECT COUNT(*) FROM topic_nodes n WHERE (SELECT COUNT(*) FROM topic_edges e WHERE e.child=n.topic_id AND e.is_primary=1)<>1"
    ).fetchone()[0] == 0


def test_record_classification(migrated):
    db, _, _ = migrated
    k = _kinds(db)
    assert k[_uri("resources/mml/add_widget.html")][:2] == ("native", "FP:MMLREF_1")
    assert k["ADD WIDGET"][:2] == ("composite", "FP:MMLREF_1")          # same topic, curated
    assert k["DSP GADGET"][:2] == ("synthetic", None)                   # borrowed file, title disagrees
    assert k[_uri("resources/kpi/1753409340.html")][1] == "FP:PMIREF_1"
    assert k["/wiki/notes.md"][:2] == ("external", None)
    # no configured source claims it => external (a path-tree source makes it native, see test_structure_extraction)
    assert k["archive:///x/Fake_ReleaseDoc.zip#a/b.docx"][:2] == ("external", None)


def test_navi_only_topic_is_materialized_with_ancestors(migrated):
    db, _, _ = migrated
    k = _kinds(db)
    kind, tid, _ = k[_uri("resources/feature/x.html")]
    assert kind == "native" and tid.startswith("FP:navi:")
    c = sqlite3.connect(db)
    path = c.execute("SELECT path_text FROM topic_nodes WHERE topic_id=?", (tid,)).fetchone()[0]
    assert path == "Feature Guide > Feature X Description"


def test_console_derived_from_bookmap_path(migrated):
    db, _, _ = migrated
    assert _kinds(db)[_uri("resources/mml/add_widget.html")][2] == "om_mml"
    assert _kinds(db)[_uri("resources/kpi/1753409340.html")][2] is None  # not a command topic
    assert mtt.console_for("Commands > PGW Web LMT Commands > X") == "pgw_web_lmt"
    assert mtt.console_for("Commands > Engineering Commands > X") == "engineering"
    assert mtt.console_for("Counters > USC Measurement Counters > X") is None


def test_one_native_record_per_topic_and_content_untouched(migrated):
    db, _, _ = migrated
    c = sqlite3.connect(db)
    assert c.execute(
        "SELECT COUNT(*) FROM (SELECT topic_id FROM document_records WHERE record_kind='native' AND topic_id IS NOT NULL GROUP BY 1 HAVING COUNT(*)>1)"
    ).fetchone()[0] == 0
    assert c.execute("SELECT content FROM document_records WHERE doc_identifier='ADD WIDGET'").fetchone()[0].startswith("body of ADD WIDGET")
    c.execute("INSERT INTO document_fts(document_fts) VALUES('integrity-check')")  # raises if FTS is inconsistent


def test_idempotent_and_dry_run_writes_nothing(tmp_path):
    pkg = _build_package(tmp_path)
    db = _make_db(tmp_path)
    mtt.migrate(db, {"FP": pkg}, dry_run=True)
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='topic_nodes'").fetchone()[0] == 0
    assert "topic_id" not in {r[1] for r in c.execute("PRAGMA table_info(document_records)")}
    c.close()
    mtt.migrate(db, {"FP": pkg})
    first = _kinds(db)
    mtt.migrate(db, {"FP": pkg})
    assert _kinds(db) == first
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM topic_nodes").fetchone()[0] == sqlite3.connect(db).execute("SELECT COUNT(*) FROM topic_nodes").fetchone()[0]


def test_entity_declarations_are_rejected(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("resources/infocenter_service/map/pid_bookmap_1.xml", '<!DOCTYPE x [<!ENTITY a "b">]><topics/>')
    outer = tmp_path / "Evil.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("Evil.hwics", inner.getvalue())
    with pytest.raises(mtt.TopicTreeError):
        mtt.parse_bookmaps(mtt.open_hwics(outer), "EV")


def test_title_matching_rules():
    assert mtt.title_matches_topic("LST BINDINFO — List Binding Information", "List Binding Information of Subscriber (LST BINDINFO)")
    assert mtt.title_matches_topic("USC 26.1.0: ALM-20104 Link Bear Quality", "ALM-20104 Link Bear Quality")
    assert not mtt.title_matches_topic("DSP OPTMODULE — Display Optical Module", "Display Adaptation Package Loading Status (DSP ADPPKG)")
