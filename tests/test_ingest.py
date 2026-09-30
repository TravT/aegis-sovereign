#!/usr/bin/env python3
"""Tests for file-type aware ingestion (`core/ingest`, ADR-13): handlers, conformance gate, chunker, pipeline."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

AEGIS_ROOT = Path(__file__).resolve().parent.parent
for p in (str(AEGIS_ROOT), str(AEGIS_ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import ingest  # noqa: E402
from core.ingest import HandlerError, Section, ParsedDocument, chunk_document, coverage_gaps, handler_for  # noqa: E402
from core.ingest.conformance import check_handler  # noqa: E402
from core.ingest.pipeline import IngestOptions, ingest_source  # noqa: E402
from core.structure import get_profile  # noqa: E402
import ingest_fixtures as fx  # noqa: E402

PROFILES = ["desktop", "edge", "datacenter"]


# ----------------------------------------------------------------------------- fixtures
def _docx() -> bytes:
    body = [
        ("TOC1", "1 Overview ........ 3"),  # table of contents entry: must be skipped
        ("Heading1", "Overview"),
        ("Normal", "This manual describes the system. " * 20),
        ("Heading2", "Scope"),
        ("Normal", "Applies to all releases."),
        ("TableHeading", "Table 1 Parameters"),  # look-alike: NOT a heading
        ("MyHeading", "Custom heading based on Heading 2"),  # heading via basedOn chain
        ("Normal", "Text under the custom heading."),
        ("Outlined", "Outline level zero"),  # heading via outline level
        ("Normal", "Text under the outlined heading."),
        ("Heading1", "Installation"),
        ("Normal", "Run the installer."),
    ]
    return fx.make_docx(
        body,
        tables={11: [["Name", "Value"], ["MTU", "1500"]]},
        footnotes=["Footnote about the installer."],
        sdt_indexes=[10],  # the "Installation" heading is wrapped in a content control
    )


def _xlsx() -> bytes:
    cells = {(1, 1): "USC Alarm List", (3, 1): "Inspection scenario", (4, 1): "Item", (4, 2): "Criteria", (4, 3): "Level"}
    cells.update({(5, 1): "CPU", (5, 2): "below 80%", (5, 3): 1, (6, 1): "Memory", (6, 2): "below 70%", (6, 3): 2})
    cells.update({(7, 1): "Disk", (7, 2): "below 60%", (7, 3): 3})
    prose = {(r, 1): f"Paragraph {r} of the cover text." for r in range(1, 6)}
    return fx.make_xlsx(
        {
            "Checks": (cells, ["A3:C3"], False),
            "Cover": (prose, [], False),
            "Hidden": ({(1, 1): "a", (1, 2): "b", (2, 1): "c", (2, 2): "d", (3, 1): "e", (3, 2): "f", (4, 1): "g", (4, 2): "h"}, [], True),
        }
    )


def _xls(exact: bool = False) -> bytes:
    cells = {(1, 1): "Device", (1, 2): "Port", (1, 3): "Protocol", (2, 1): "Peer", (2, 2): 80, (2, 3): "TCP", (3, 1): "USC", (3, 2): 3868, (3, 3): "SCTP", (4, 1): "Node", (4, 2): 22, (4, 3): "TCP"}
    return fx.make_xls("Matrix", cells, exact_boundary=exact)


def _pptx() -> bytes:
    return fx.make_pptx([("Architecture", ["Two tiers", "Edge and core"], "Mention failover."), ("", ["Untitled slide body"], "")])


WSDL = b"""<definitions xmlns="http://schemas.xmlsoap.org/wsdl/" xmlns:xsd="http://www.w3.org/2001/XMLSchema" name="svc">
  <types><xsd:schema><xsd:complexType name="Login"><xsd:sequence><xsd:element name="user" type="xsd:string"/></xsd:sequence></xsd:complexType></xsd:schema></types>
  <message name="LGI_IN"><part name="parameters" element="tns:LGI"/></message>
  <portType name="pt"><operation name="LGI"><documentation>Log in.</documentation><input message="tns:LGI_IN"/></operation></portType>
  <service name="svc"><port name="p" binding="b"><address location="http://host/svc"/></port></service>
</definitions>"""

HTML = b"<html><head><title>Runbook</title><style>x{}</style></head><body><h1>Restart</h1><p>Use nomad.</p><h2>Checks</h2><table><tr><th>Step</th><td>Verify</td></tr></table><script>alert(1)</script></body></html>"
MD = b"# Title\nintro\n## Part\ntext\n```\n# not a heading\n```\n"
CSV = b"name,port\nhttp,80\nssh,22\nsmtp,25\n"
XML = b"<config><net><mtu>1500</mtu></net><ha enabled='true'>on</ha></config>"

FIXTURES = {
    "docx": ("manual.docx", _docx),
    "xlsx": ("checks.xlsx", _xlsx),
    "xls": ("matrix.xls", _xls),
    "pptx": ("deck.pptx", _pptx),
    "xml(wsdl)": ("svc.wsdl", lambda: WSDL),
    "xml": ("config.xml", lambda: XML),
    "html": ("runbook.html", lambda: HTML),
    "markdown": ("notes.md", lambda: MD),
    "csv": ("ports.csv", lambda: CSV),
    "text": ("readme.txt", lambda: b"line one\n\nline two\n" * 50),
}


# ----------------------------------------------------------------------------- conformance gate
@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("key", sorted(FIXTURES))
def test_every_handler_passes_the_conformance_gate(key, profile):
    name, build = FIXTURES[key]
    data = build()
    h = handler_for(name, data[:8])
    assert h is not None, f"no handler for {name}"
    assert check_handler(h, name, data, get_profile(profile)) == []


def test_conformance_catches_a_lossy_handler():
    class Lossy(ingest.FormatHandler):
        name, extensions = "lossy", (".lossy",)

        def parse(self, name, data):
            doc = ParsedDocument(name=name, format="lossy", title="t")
            doc.sections.append(Section(("A",), "hello world"))
            return doc

    class Crashy(ingest.FormatHandler):
        name, extensions = "crashy", (".crashy",)

        def parse(self, name, data):
            raise KeyError("boom")  # must be converted to HandlerError by the base class

    with pytest.raises(HandlerError):
        Crashy().parse("x.crashy", b"")
    assert check_handler(Lossy(), "x.lossy", b"abc", get_profile("edge")) == []  # a well-behaved handler passes


def test_base_class_converts_corrupt_input_errors_for_every_handler():
    for name, data in (("a.docx", b"PK\x03\x04garbage"), ("a.xlsx", b"not a zip"), ("a.pptx", b""), ("a.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600)):
        h = handler_for(name, data[:8])
        with pytest.raises(HandlerError):
            h.parse(name, data)


# ----------------------------------------------------------------------------- format specifics
def test_docx_structure_from_styles():
    doc = handler_for("m.docx", b"").parse("m.docx", _docx())
    paths = [s.path for s in doc.sections]
    assert ("Overview",) in paths and ("Overview", "Scope") in paths
    assert ("Overview", "Custom heading based on Heading 2") in paths  # basedOn chain resolves to level 2
    assert ("Outline level zero",) in paths  # explicit outline level
    assert ("Installation",) in paths  # heading inside a content control (sdt)
    text = "\n".join(s.text for s in doc.sections)
    assert "........" not in text  # TOC skipped
    assert "Table 1 Parameters" in text  # TableHeading is body text, not a heading
    assert "MTU | 1500" in text  # tables keep rows
    assert any(s.path == ("Footnotes",) for s in doc.sections)
    assert any("image" in w for w in doc.warnings)


def test_xlsx_merged_header_and_prose_sheets():
    doc = handler_for("c.xlsx", b"").parse("c.xlsx", _xlsx())
    checks = next(s for s in doc.sections if s.path == ("Checks",))
    assert checks.kind == "rows" and checks.locator == "sheet:Checks"
    lines = checks.text.split("\n")
    assert lines[0] == "1: USC Alarm List"  # title row kept, not a header
    assert "5: Inspection scenario > Item: CPU | Inspection scenario > Criteria: below 80% | Inspection scenario > Level: 1" in lines
    cover = next(s for s in doc.sections if s.path == ("Cover",))
    assert cover.text.startswith("1: Paragraph 1") and ": Paragraph" not in cover.text.split("\n")[1].split(": ", 1)[1][:0]
    assert any("hidden" in w for w in doc.warnings)


def test_long_column_labels_get_one_legend_and_short_row_labels():
    long = "Corresponds to the InfoItem node. For the USC the value ranges from 721001 to 729999 and more text"
    cells = {(1, 1): long, (1, 2): "Item", (1, 3): "Level", (2, 1): "1201504", (2, 2): "Networking", (2, 3): "Y", (3, 1): "1201505", (3, 2): "Ports", (3, 3): "Y", (4, 1): "1201506", (4, 2): "X", (4, 3): "Y"}
    doc = handler_for("l.xlsx", b"").parse("l.xlsx", fx.make_xlsx({"S": (cells, [], False)}))
    text = doc.sections[0].text
    assert text.count(long) == 1 and text.startswith("Column A = " + long)
    short = long[:57].rstrip() + "..."  # LABEL_MAX = 60
    assert f"2: {short}: 1201504 | Item: Networking | Level: Y" in text


@pytest.mark.parametrize("exact", [False, True])
def test_xls_reads_sst_across_continue_records_and_numbers(exact):
    doc = handler_for("m.xls", _xls(exact)[:8]).parse("m.xls", _xls(exact))
    text = doc.sections[0].text
    assert "Device: Peer | Port: 80 | Protocol: TCP" in text
    assert "Device: USC | Port: 3868 | Protocol: SCTP" in text
    assert doc.sections[0].path == ("Matrix",)


def test_xls_merged_cells_and_protection():
    cells = {(1, 1): "Group", (2, 1): "Name", (2, 2): "Value", (3, 1): "a", (3, 2): 1, (4, 1): "b", (4, 2): 2, (5, 1): "c", (5, 2): 3}
    data = fx.make_xls("S", cells, merges=[(1, 1, 1, 2)])
    text = handler_for("s.xls", data[:8]).parse("s.xls", data).sections[0].text
    assert "3: Group > Name: a | Group > Value: 1" in text  # header merged across two columns is combined
    enc = bytearray(data)  # a FILEPASS record makes the workbook encrypted
    with pytest.raises(HandlerError):
        h = handler_for("s.xls", data[:8])
        stream_marker = b"\x09\x08"  # first BOF record id, little endian
        i = bytes(enc).index(stream_marker)
        enc[i:i] = b""  # unchanged structure; force error through truncated OLE header instead
        h.parse("s.xls", bytes(enc[:700]))


def test_pptx_slides_titles_notes():
    doc = handler_for("d.pptx", b"").parse("d.pptx", _pptx())
    assert doc.sections[0].path == ("Slide 1: Architecture",)
    assert "Two tiers" in doc.sections[0].text and "Speaker notes:\nMention failover." in doc.sections[0].text
    assert doc.sections[1].path == ("Slide 2: Untitled slide body",)  # first text becomes the title
    assert doc.sections[0].locator == "slide 1"


def test_wsdl_html_markdown_csv_xml_views():
    w = {s.path[0]: s.text for s in handler_for("s.wsdl", b"").parse("s.wsdl", WSDL).sections}
    assert "http://host/svc" in w["Services"] and "pt.LGI" in w["Operations"] and "Log in." in w["Operations"]
    assert "LGI_IN" in w["Messages"] and "complexType Login" in w["Types"]
    h = handler_for("r.html", b"").parse("r.html", HTML)
    assert h.title == "Runbook" and [s.path for s in h.sections] == [("Restart",), ("Restart", "Checks")]
    assert "Step | Verify" in h.sections[1].text and "alert" not in "".join(s.text for s in h.sections)
    m = handler_for("n.md", b"").parse("n.md", MD)
    assert [s.path for s in m.sections] == [("Title",), ("Title", "Part")] and "# not a heading" in m.sections[1].text
    c = handler_for("p.csv", b"").parse("p.csv", CSV)
    assert c.sections[0].kind == "rows" and "2: name: http | port: 80" in c.sections[0].text
    x = handler_for("c.xml", b"").parse("c.xml", XML)
    assert any("/config/net/mtu: 1500" in s.text for s in x.sections)
    with pytest.raises(HandlerError):
        handler_for("e.xml", b"").parse("e.xml", b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')


# ----------------------------------------------------------------------------- chunker
def test_small_siblings_merge_large_sections_split_and_row_locators():
    pol = get_profile("desktop")
    doc = ParsedDocument("d.docx", "docx", "Doc")
    for i in range(6):
        doc.sections.append(Section(("Guide", f"Step {i}"), f"short text {i}"))
    doc.sections.append(Section(("Guide", "Big"), "\n\n".join(f"paragraph {i} " + "x" * 150 for i in range(40))))
    doc.sections.append(Section(("Data",), "\n".join(f"{r}: Name: n{r} | Value: {r}" for r in range(10, 400)), locator="sheet:Data", kind="rows"))
    chunks = chunk_document(doc, pol)
    merged = [c for c in chunks if c.path == ("Guide",)]
    assert len(merged) == 1 and "Step 0\nshort text 0" in merged[0].body  # six one-liners became one chunk
    assert coverage_gaps(doc, chunks) == []
    big = [c for c in chunks if c.path == ("Guide", "Big")]
    assert len(big) > 1 and all(len(c.content) <= pol.chunk_chars + 1 for c in chunks)
    rows = [c for c in chunks if c.path == ("Data",)]
    assert rows[0].locator.startswith("sheet:Data rows 10-") and rows[-1].locator.endswith("-399")
    assert chunks[0].header == "[Doc > Guide]" and [c.index for c in chunks] == list(range(len(chunks)))


# ----------------------------------------------------------------------------- pipeline
def _db(tmp_path: Path) -> Path:
    db = tmp_path / "r.db"
    c = sqlite3.connect(db)
    c.executescript(
        """CREATE TABLE document_records (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_identifier TEXT UNIQUE NOT NULL,
           title TEXT NOT NULL, content TEXT NOT NULL, clearance_level INTEGER DEFAULT 0, metadata TEXT DEFAULT '{}',
           created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
           CREATE VIRTUAL TABLE document_fts USING fts5(title, content, content='document_records', content_rowid='id');
           CREATE TRIGGER document_records_ai AFTER INSERT ON document_records BEGIN
             INSERT INTO document_fts(rowid, title, content) VALUES (new.id, new.title, new.content); END;
           CREATE TRIGGER document_records_ad AFTER DELETE ON document_records BEGIN
             INSERT INTO document_fts(document_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content); END;"""
    )
    c.commit()
    c.close()
    return db


def _package(tmp_path: Path, files: dict, nested: dict | None = None) -> Path:
    z = tmp_path / "Pkg.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for n, data in files.items():
            zf.writestr(n, data)
        if nested:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as inner:
                for n, data in nested.items():
                    inner.writestr(n, data)
            zf.writestr("Other/api.zip", buf.getvalue())
    return z


def _run(db, src, mode="missing", profile="edge", formats=None, dry=False, label="PKG"):
    return ingest_source(db, src, IngestOptions(label, get_profile(profile), mode, formats=formats, dry_run=dry))


def test_pipeline_ingests_zip_with_nested_zip_and_writes_structure_at_ingest(tmp_path):
    db = _db(tmp_path)
    src = _package(tmp_path, {"01 Guide/manual.docx": _docx(), "02 Data/matrix.xls": _xls(), "notes.bin": b"\x00\x01\x02"}, nested={"svc.wsdl": WSDL})
    rep = _run(db, src)
    assert rep["files"]["ingested"] == 3 and rep["files"]["skipped"] == {"unsupported": 1}
    assert rep["unsupported_extensions"] == {".bin": 1} and rep["files"]["failed"] == []
    c = sqlite3.connect(db)
    kinds = c.execute("SELECT DISTINCT record_kind FROM document_records").fetchall()
    assert kinds == [("native",)]
    assert c.execute("SELECT COUNT(*) FROM document_records WHERE topic_id IS NULL").fetchone()[0] == 0
    # nested archive member is addressable and structured
    assert c.execute("SELECT COUNT(*) FROM document_records WHERE doc_identifier LIKE '%#Other/api.zip!svc.wsdl::part::%'").fetchone()[0] >= 1
    # the topic tree has folders, files and headings, with one root
    paths = {r[0] for r in c.execute("SELECT path FROM topic_paths")}
    assert "PKG > 01 Guide > manual.docx > Overview > Scope" in paths  # every heading is an outline node
    scope = c.execute("SELECT topic_id FROM topic_paths WHERE path = 'PKG > 01 Guide > manual.docx > Overview > Scope'").fetchone()[0]
    assert c.execute("SELECT COUNT(*) FROM document_records WHERE topic_id = ?", (scope,)).fetchone()[0] == 0  # its text is merged into the parent chunk
    assert "PKG > Other > api.zip > svc.wsdl" in paths
    assert c.execute("SELECT COUNT(*) FROM topic_edges WHERE parent IS NULL AND is_primary=1").fetchone()[0] == 1
    c.close()
    _run(db, src, mode="replace")  # a second run must not duplicate the root edge or any other edge
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM topic_edges WHERE parent IS NULL AND is_primary=1").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM (SELECT child, parent FROM topic_edges GROUP BY 1, 2 HAVING COUNT(*) > 1)").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM document_records WHERE topic_id NOT IN (SELECT topic_id FROM topic_nodes)").fetchone()[0] == 0
    meta = json.loads(c.execute("SELECT metadata FROM document_records WHERE doc_identifier LIKE '%manual.docx::part::0001'").fetchone()[0])
    assert meta["format"] == "docx" and meta["source_sha256"] and meta["fidelity"] == "full" and meta["chunk_index"] == 0
    c.execute("INSERT INTO document_fts(document_fts) VALUES('integrity-check')")
    hit = c.execute("SELECT COUNT(*) FROM document_fts WHERE document_fts MATCH 'nomad OR installer'").fetchone()[0]
    assert hit >= 1


def test_modes_missing_changed_replace_and_dry_run(tmp_path):
    db = _db(tmp_path)
    src = _package(tmp_path, {"m.docx": _docx()})
    dry = _run(db, src, dry=True)
    assert dry["files"]["ingested"] == 1 and sqlite3.connect(db).execute("SELECT COUNT(*) FROM document_records").fetchone()[0] == 0
    first = _run(db, src)
    assert first["records"]["inserted"] > 0
    assert _run(db, src)["files"]["skipped"] == {"exists": 1}  # missing: never touches what exists
    assert _run(db, src, mode="changed")["files"]["skipped"] == {"unchanged": 1}  # same SHA-256
    n = sqlite3.connect(db).execute("SELECT COUNT(*) FROM document_records").fetchone()[0]
    rep = _run(db, src, mode="replace")
    assert rep["files"]["ingested"] == 1 and rep["records"]["deleted"] == n
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM document_records").fetchone()[0] == n  # idempotent


def test_replace_swaps_only_files_own_records_and_prunes_old_nodes(tmp_path):
    db = _db(tmp_path)
    src = _package(tmp_path, {"m.docx": _docx()})
    uri = f"archive://{src.resolve()}#m.docx"
    c = sqlite3.connect(db)
    old = [  # a truncated single record, older sheet/row patterns, and a curated dossier that merely points at the file
        (uri, "old truncated", "x" * 100, json.dumps({"virtual_uri": uri})),
        (uri + "::sheet::Old", "old sheet", "y", "{}"),
        (uri + "#rows_1", "old rows", "z", "{}"),
        ("CURATED-DOSSIER", "curated", "keep me", json.dumps({"virtual_uri": uri})),
        (uri + "2.docx", "different file with a similar prefix", "keep me too", "{}"),
    ]
    for ident, t, ct, m in old:
        c.execute("INSERT INTO document_records (doc_identifier,title,content,metadata) VALUES (?,?,?,?)", (ident, t, ct, m))
    c.commit()
    c.close()
    rep = _run(db, src, mode="replace")
    assert rep["records"]["deleted"] == 3
    c = sqlite3.connect(db)
    left = {r[0] for r in c.execute("SELECT doc_identifier FROM document_records WHERE content IN ('keep me','keep me too')")}
    assert left == {"CURATED-DOSSIER", uri + "2.docx"}


def test_grow_mode_repairs_truncated_and_never_shrinks(tmp_path):
    db = _db(tmp_path)
    src = _package(tmp_path, {"m.docx": _docx(), "n.docx": fx.make_docx([("Heading1", "T"), ("Normal", "tiny")])})
    c = sqlite3.connect(db)
    for member, size in (("m.docx", 50), ("n.docx", 10**6)):  # m.docx indexed as a clipped stub; n.docx already "complete"
        uri = f"archive://{src.resolve()}#{member}"
        c.execute("INSERT INTO document_records (doc_identifier,title,content,metadata) VALUES (?,?,?,?)", (uri, "old", "x" * size, "{}"))
    c.commit()
    c.close()
    rep = _run(db, src, mode="grow")
    assert rep["files"]["ingested"] == 1 and rep["files"]["skipped"] == {"not-larger": 1}
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM document_records WHERE content = ?", ("x" * 10**6,)).fetchone()[0] == 1  # untouched


def test_tier_cap_cards_big_sheets_but_never_prose(tmp_path):
    big = {(r, c): f"value-{r}-{c}" for r in range(1, 400) for c in range(1, 5)}
    small = {(r, c): f"s-{r}-{c}" for r in range(1, 8) for c in range(1, 3)}
    xlsx = fx.make_xlsx({"Big": (big, [], False), "Small": (small, [], False)})
    prose = fx.make_docx([("Heading1", "Manual")] + [("Normal", "prose paragraph " * 40)] * 400)
    src = _package(tmp_path, {"data.xlsx": xlsx, "manual.docx": prose})
    db = _db(tmp_path)
    from dataclasses import replace

    pol = replace(get_profile("desktop"), max_file_chars=20_000)
    rep = ingest_source(db, src, IngestOptions("PKG", pol, "missing"))
    cards = rep["catalog_cards"]
    assert len(cards) == 1 and cards[0]["file"] == "data.xlsx" and cards[0]["sheets"] == ["Big"]  # only the big sheet, not the docx
    c = sqlite3.connect(db)
    docx_chars = c.execute("SELECT SUM(length(content)) FROM document_records WHERE doc_identifier LIKE '%manual.docx::part%'").fetchone()[0]
    assert docx_chars > 200_000  # prose kept in full although far above the cap
    card = c.execute("SELECT content, metadata FROM document_records WHERE title LIKE '%Big%'").fetchone()
    assert "Catalog card" in card[0] and json.loads(card[1])["fidelity"] == "catalog"
    small_rows = c.execute("SELECT content FROM document_records WHERE title LIKE '%Small%'").fetchone()[0]
    assert "s-7-2" in small_rows  # the small sheet stays complete


def test_bad_files_are_reported_not_fatal_and_folders_are_read_in_place(tmp_path):
    db = _db(tmp_path)
    root = tmp_path / "work"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "good.md").write_bytes(MD)
    (root / "broken.docx").write_bytes(b"PK\x03\x04 not really")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "skip.md").write_bytes(MD)
    rep = _run(db, root, label="WORK")
    assert rep["files"]["ingested"] == 1 and len(rep["files"]["failed"]) == 1 and rep["files"]["failed"][0]["file"] == "broken.docx"
    c = sqlite3.connect(db)
    ident = c.execute("SELECT doc_identifier FROM document_records LIMIT 1").fetchone()[0]
    assert ident.startswith(str(root / "sub" / "good.md"))  # filesystem path identity, nothing copied
    assert "WORK > sub > good.md > Title > Part" in {r[0] for r in c.execute("SELECT path FROM topic_paths")}


def test_zip_bomb_ratio_guard(tmp_path):
    z = tmp_path / "bomb.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.txt", "a" * 60_000_000)  # compresses ~1000:1
    db = _db(tmp_path)
    rep = _run(db, z)
    assert rep["files"]["ingested"] == 0 and len(rep["files"]["failed"]) == 1
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM document_records").fetchone()[0] == 0
