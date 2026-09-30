#!/usr/bin/env python3
"""Tests for the pluggable structure layer (`core/structure`, ADR-12): contract, registry,
path-tree plugin, tier size profiles, lossless chunking, derived paths and search-time collapsing."""

from __future__ import annotations

import io
import json
import random
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

AEGIS_ROOT = Path(__file__).resolve().parent.parent
if str(AEGIS_ROOT) not in sys.path:
    sys.path.insert(0, str(AEGIS_ROOT))

from core import structure as st  # noqa: E402
from core.structure import registry as reg  # noqa: E402
from core.structure.pathtree import PathTreeExtractor, split_inner  # noqa: E402


def _db(tmp_path: Path, rows) -> Path:
    db = tmp_path / "r.db"
    c = sqlite3.connect(db)
    c.executescript(
        """CREATE TABLE document_records (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_identifier TEXT UNIQUE NOT NULL,
           title TEXT NOT NULL, content TEXT NOT NULL, clearance_level INTEGER DEFAULT 0, metadata TEXT DEFAULT '{}',
           created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"""
    )
    for ident, title, meta in rows:
        c.execute("INSERT INTO document_records (doc_identifier,title,content,metadata) VALUES (?,?,?,?)",
                  (ident, title, "body " + title, json.dumps(meta)))
    c.commit()
    c.close()
    return db


def _release_zip(tmp_path: Path) -> Path:
    p = tmp_path / "Fake_ReleaseDoc.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("04. NorthBound/Alarm List.xlsx", b"x")
        z.writestr("13. Guide/Install.docx", b"x")
    return p


def _uri(zip_name: str, inner: str) -> str:
    return f"archive:///x/{zip_name}#{inner}"


def test_production_shapes_sheets_keep_their_own_node_and_dossiers_are_composite(tmp_path):
    """In production, sheet/row records carry the plain file path in metadata.virtual_uri and the
    suffix only in doc_identifier; a curated dossier points at a file but is not that file."""
    z = _release_zip(tmp_path)
    wb = _uri(z.name, "04. NorthBound/Alarm List.xlsx")
    rows = [
        (wb, "Workbook", {"virtual_uri": wb}),
        (wb + "::sheet::Cover", "Sheet Cover", {"virtual_uri": wb}),
        (wb + "::sheet::Alarms", "Sheet Alarms", {"virtual_uri": wb}),
        (wb + "#Alarms_rows_1", "Rows 1", {"virtual_uri": wb}),
        ("ALARM-LIST-DOSSIER", "Curated dossier about the alarm list", {"virtual_uri": wb}),
    ]
    db = _db(tmp_path, rows)
    rep = st.apply_structure(db, {"REL": z}, st.get_profile("edge"))
    c = sqlite3.connect(db)
    kinds = dict(c.execute("SELECT title, record_kind FROM document_records"))
    assert kinds == {"Workbook": "native", "Sheet Cover": "native", "Sheet Alarms": "native", "Rows 1": "native",
                     "Curated dossier about the alarm list": "composite"}
    topics = dict(c.execute("SELECT title, topic_id FROM document_records"))
    assert len({topics["Workbook"], topics["Sheet Cover"], topics["Sheet Alarms"], topics["Rows 1"]}) == 4
    assert topics["Curated dossier about the alarm list"] == topics["Workbook"]  # stands on the workbook node
    assert rep["stats"].get("topics-with-several-native", 0) == 0


# ---------------------------------------------------------------- registry / contract
def test_builtin_extractors_registered_in_priority_order():
    names = st.registered()
    assert "hedex" in names and "pathtree" in names
    assert names.index("hedex") < names.index("pathtree")  # specialised before generic


def test_detection_routes_sources_to_the_right_plugin(tmp_path):
    hw = tmp_path / "Pkg.zip"
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("resources/navi.xml", "<topics/>")
    with zipfile.ZipFile(hw, "w") as z:
        z.writestr("Pkg.hwics", inner.getvalue())
    assert st.extractor_for(hw, "HW").name == "hedex"
    assert st.extractor_for(_release_zip(tmp_path), "REL").name == "pathtree"
    folder = tmp_path / "work"
    folder.mkdir()
    assert st.extractor_for(folder, "WORK").name == "pathtree"
    notes = tmp_path / "notes.txt"
    notes.write_text("hi")
    with pytest.raises(st.NoExtractorError):
        st.extractor_for(notes, "N")


def test_new_format_is_one_subclass_and_a_registration(tmp_path):
    class DummyExtractor(st.StructureExtractor):
        name = "dummy"
        priority = 1

        @classmethod
        def detect(cls, source):
            return Path(source).suffix == ".dummy"

        def build_tree(self):
            self.tree.nodes["D:root"] = st.Node("D:root", "root", 1, "dummy", "root")
            self.tree.edges.append(("D:root", None, 1))
            return self.tree

        def claims(self, rec):
            return rec.doc_identifier.startswith("dummy:")

        def assign(self, rec):
            return st.Assignment("D:root", "native")

    src = tmp_path / "x.dummy"
    src.write_text("")
    st.register(DummyExtractor)
    try:
        assert st.extractor_for(src, "D").name == "dummy"
        db = _db(tmp_path, [("dummy:1", "one", {}), ("other", "two", {})])
        rep = st.apply_structure(db, {"D": src})
        c = sqlite3.connect(db)
        assert dict(c.execute("SELECT doc_identifier, record_kind FROM document_records")) == {"dummy:1": "native", "other": "external"}
        assert rep["extractors"] == {"D": "dummy"}
    finally:
        reg._REGISTRY.remove(DummyExtractor)


# ---------------------------------------------------------------- path-tree plugin
def test_split_inner_handles_sheets_and_row_chunks():
    assert split_inner("archive:///x/R.zip#04. N/A.xlsx") == ("04. N/A.xlsx", None)
    assert split_inner("archive:///x/R.zip#04. N/A.xlsx::sheet::Cover") == ("04. N/A.xlsx", "Cover")
    assert split_inner("archive:///x/R.zip#04. N/A.xlsx#Counters_rows_108") == ("04. N/A.xlsx", "Counters_rows_108")
    assert split_inner("/plain/path.md") is None


def test_release_zip_gets_a_real_tree_with_one_root(tmp_path):
    z = _release_zip(tmp_path)
    rows = [
        (_uri(z.name, "13. Guide/Install.docx"), "OpenXML Manual: Install.docx", {}),
        (_uri(z.name, "04. NorthBound/Alarm List.xlsx"), "OpenXML Workbook: Alarm List", {}),
        (_uri(z.name, "04. NorthBound/Alarm List.xlsx::sheet::Cover"), "Sheet Cover", {}),
        (_uri(z.name, "04. NorthBound/Alarm List.xlsx#Alarms_rows_1"), "Rows 1", {}),
    ]
    db = _db(tmp_path, rows)
    rep = st.apply_structure(db, {"REL": z}, st.get_profile("edge"))
    c = sqlite3.connect(db)
    assert rep["kinds"] == {"native": 4}
    roots = c.execute("SELECT COUNT(*) FROM topic_edges WHERE parent IS NULL AND is_primary=1").fetchone()[0]
    assert roots == 1
    path = c.execute(
        "SELECT path_text FROM topic_nodes n JOIN document_records r ON r.topic_id=n.topic_id WHERE r.title='Sheet Cover'"
    ).fetchone()[0]
    assert path == "REL > 04. NorthBound > Alarm List.xlsx > Cover"
    # the workbook node is the parent of its sheet and row-chunk nodes
    wb = c.execute("SELECT topic_id FROM document_records WHERE title='OpenXML Workbook: Alarm List'").fetchone()[0]
    kids = c.execute("SELECT COUNT(*) FROM topic_edges WHERE parent=?", (wb,)).fetchone()[0]
    assert kids == 2
    # exactly one native record per topic
    assert c.execute("SELECT COUNT(*) FROM (SELECT topic_id FROM document_records GROUP BY 1 HAVING COUNT(*)>1)").fetchone()[0] == 0


def test_folder_source_is_zero_copy_and_only_claims_its_own_files(tmp_path):
    root = tmp_path / "work"
    root.mkdir()  # note: the files below do not exist; the extractor never opens them
    inside = str(root / "emails" / "2026" / "a.eml")
    outside = str(tmp_path / "elsewhere" / "b.eml")
    db = _db(tmp_path, [(inside, "mail a", {}), (outside, "mail b", {})])
    st.apply_structure(db, {"WORK": root}, st.get_profile("desktop"))
    c = sqlite3.connect(db)
    kinds = dict(c.execute("SELECT title, record_kind FROM document_records"))
    assert kinds == {"mail a": "native", "mail b": "external"}
    assert c.execute("SELECT path FROM topic_paths WHERE topic_id=(SELECT topic_id FROM document_records WHERE title='mail a')").fetchone()[0] == "WORK > emails > 2026 > a.eml"


# ---------------------------------------------------------------- derived paths / profiles
def test_desktop_profile_stores_no_paths_but_view_derives_them(tmp_path):
    z = _release_zip(tmp_path)
    db = _db(tmp_path, [(_uri(z.name, "13. Guide/Install.docx"), "Manual", {})])
    st.apply_structure(db, {"REL": z}, st.get_profile("desktop"))
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM topic_nodes WHERE path_text IS NOT NULL").fetchone()[0] == 0
    tid = c.execute("SELECT topic_id FROM document_records").fetchone()[0]
    assert c.execute("SELECT path FROM topic_paths WHERE topic_id=?", (tid,)).fetchone()[0] == "REL > 13. Guide > Install.docx"
    meta = dict(c.execute("SELECT key, value FROM structure_meta"))
    assert json.loads(meta["policy"])["name"] == "desktop"


def test_edge_profile_stored_paths_equal_derived_paths(tmp_path):
    z = _release_zip(tmp_path)
    db = _db(tmp_path, [(_uri(z.name, "13. Guide/Install.docx"), "Manual", {}), (_uri(z.name, "04. NorthBound/Alarm List.xlsx"), "WB", {})])
    st.apply_structure(db, {"REL": z}, st.get_profile("edge"))
    c = sqlite3.connect(db)
    for tid, stored, derived in c.execute("SELECT n.topic_id, n.path_text, p.path FROM topic_nodes n JOIN topic_paths p USING(topic_id)"):
        assert stored == derived


def test_reapplying_is_idempotent(tmp_path):
    z = _release_zip(tmp_path)
    db = _db(tmp_path, [(_uri(z.name, "13. Guide/Install.docx"), "Manual", {})])
    st.apply_structure(db, {"REL": z})
    first = sqlite3.connect(db).execute("SELECT topic_id, record_kind FROM document_records").fetchall()
    st.apply_structure(db, {"REL": z})
    assert sqlite3.connect(db).execute("SELECT topic_id, record_kind FROM document_records").fetchall() == first


# ---------------------------------------------------------------- size policy: never truncate
@pytest.mark.parametrize("profile", ["desktop", "edge", "datacenter"])
def test_chunking_is_lossless_bounded_and_ordered(profile):
    pol = st.get_profile(profile)
    rnd = random.Random(7)
    words = ["alpha", "beta", "gamma", "delta", "MML", "ADD", "SCTPPP", "x" * 40]
    for text in (
        "".join(rnd.choice(words) + rnd.choice([" ", "\n", "\n\n", " "]) for _ in range(4000)),
        "z" * 25_000,  # no whitespace at all
        "short",
    ):
        spans = st.chunk_spans(text, pol)
        assert spans[0][0] == 0 and spans[-1][1] == len(text)
        covered = 0
        for (a, b), nxt in zip(spans, spans[1:] + [None]):
            assert 0 < b - a <= pol.chunk_chars
            assert nxt is None or nxt[0] <= b  # consecutive spans touch or overlap: nothing is skipped
            assert nxt is None or nxt[0] > a  # and the scan always advances
            covered = max(covered, b)
        assert covered == len(text)
        assert st.chunk_text(text, pol) == [text[a:b] for a, b in spans]


def test_chunk_edge_cases_and_policy_validation():
    pol = st.get_profile("edge")
    assert st.chunk_spans("", pol) == [] and st.chunk_text("x", pol) == ["x"]
    with pytest.raises(ValueError):
        st.get_profile("laptop")
    with pytest.raises(ValueError):
        st.SizePolicy("bad", chunk_chars=100, chunk_overlap=10, store_paths=True, collapse_derived=True)
    with pytest.raises(ValueError):
        st.SizePolicy("bad", chunk_chars=1000, chunk_overlap=900, store_paths=True, collapse_derived=True)
    assert st.get_profile("desktop").store_paths is False and st.get_profile("datacenter").collapse_derived is False


# ---------------------------------------------------------------- search-time de-duplication
def test_collapse_folds_composites_under_their_native_but_never_natives_together():
    ranked = [
        {"id": 1, "topic_id": "T1", "record_kind": "composite"},
        {"id": 2, "topic_id": "T2", "record_kind": "native"},
        {"id": 3, "topic_id": "T1", "record_kind": "native"},
        {"id": 4, "topic_id": None, "record_kind": "external"},
        {"id": 5, "topic_id": "T2", "record_kind": "native"},  # another chunk of the same section: separate evidence
        {"id": 6, "topic_id": "T2", "record_kind": "composite"},
        {"id": 7, "topic_id": "T9", "record_kind": "composite"},  # its native is not in the results: kept
    ]
    out = st.collapse_by_topic(ranked)
    assert [(r["id"], r["collapsed"]) for r in out] == [(2, 1), (3, 1), (4, 0), (5, 0), (7, 0)]
    assert "collapsed" not in ranked[0]  # input untouched
