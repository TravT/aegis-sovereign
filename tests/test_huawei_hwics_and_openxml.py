#!/usr/bin/env python3
"""Unit & Real-World Integration Tests for Huawei .HWICS/.HDX & OpenXML (.xlsx/.docx) Containers.

Validates:
1. `SovereignArchiveStreamer`:
   - `.hwics`, `.xlsx`, `.xlsm`, `.docx` in `SUPPORTED_EXTENSIONS`.
   - Configurable 2 GB `max_total_bytes` and `150.0` `max_compression_ratio`.
   - Transparent nested ZIP-in-ZIP (`.zip -> .hwics`) streaming and compound URI resolution
     (`archive://<outer.zip>!<inner.hwics>#<entry>`) 100% in memory (`io.BytesIO`).
2. `HdxTelecomIngestor`:
   - `_XXE_GUARD_RE` allows W3C HTML4/XHTML `<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" ...>`
     while strictly blocking `<!ENTITY`, `<!DOCTYPE ... [`, and `SYSTEM "file:..."`.
   - Parses Huawei `profile.xml`, `resources/navi.xml` (`<topic txt="..." url="..."/>`),
     `resources/infocenter_service/map/pid_bookmap_*.xml`, and `resources/images.xml`.
   - Extracts `<img class="vsd" src="figure/..."/>` ladder/alarm diagrams into `HdxAlarmSpec.diagram_uris`
     and indexes `HAS_DIAGRAM` edges in `GraphStore`.
   - Routes 4-digit (`ALM-1003`) and 6-digit (`ALM-125001`) Huawei alarms in `<1ms` via Prong 1.
3. `OpenXmlReleaseDocParser`:
   - Pure stdlib (`zipfile` + `xml.etree.ElementTree`) in-memory parser for `.xlsx` (`Alarm List`,
     `Event List`, `Performance Counter List`) and `.docx` engineering guides.
4. Real-World Telecom Corpus Verification (`/tmp/docs_rag_gemini/` if present).
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.containers.archive_streamer import (
    ArchiveSecurityError,
    SovereignArchiveStreamer,
)
from core.containers.hdx_parser import HdxTelecomIngestor, _XXE_GUARD_RE
from core.formats.openxml_parser import OpenXmlReleaseDocParser
from core.graph.store import GraphStore
from core.router.query_router import QueryRouteType, SovereignQueryRouter
from core.security import ClearanceLevel, PlanTier


def _build_deterministic_hwics_wrapped_zip(target_zip_path: Path) -> Path:
    """Build a deterministic `.zip` wrapping an inner `.hwics` with Huawei HedEx structure."""
    hwics_bio = io.BytesIO()
    with zipfile.ZipFile(hwics_bio, mode="w", compression=zipfile.ZIP_DEFLATED) as hzf:
        hzf.writestr(
            "profile.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<profile>
  <buildVersion>V600R001C10SPC300</buildVersion>
  <libId>2008148953_EN</libId>
  <libVersion>02</libVersion>
  <libName>USC 26.1.0 Product Documentation (VM Container)</libName>
  <productType>USC</productType>
  <productVersion>26.1.0</productVersion>
  <topicNumber>21540</topicNumber>
  <navi>resources/navi.xml</navi>
  <homePage>resources/hedex-homepage.html</homePage>
  <hedexVersion>V100R002C00</hedexVersion>
</profile>""",
        )
        hzf.writestr(
            "resources/navi.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<topics quickComparison="0">
  <topic txt="O&amp;M" url="toctopics/om_root.html" id="EN-US_TOPIC_OM">
    <topic txt="Alarm Reference" url="toctopics/alarm_ref.html" id="EN-US_TOPIC_ALM_REF">
      <topic txt="ALM-1003 Module Fault" url="alarm_cgplite/alarms/1003.html" id="EN-US_ALARMREF_0269895188"/>
      <topic txt="ALM-125001 Signaling Link Down" url="alarm_cgplite/alarms/125001.html" id="EN-US_ALARMREF_125001"/>
    </topic>
  </topic>
</topics>""",
        )
        hzf.writestr(
            "resources/infocenter_service/map/pid_bookmap_0001.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<topics>
  <topic name="Alarm Management" id="TOPIC_ALM_MGT">
    <topic name="CGP Lite Alarms" id="CONCEPT_CGP_ALM">
      <topic name="ALM-1003 Module Fault" id="ALARMREF_0269895188"/>
    </topic>
  </topic>
</topics>""",
        )
        hzf.writestr(
            "resources/images.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<images>
  <image url="alarm_cgplite/alarms/figure/en-us_image_0269895191.png" msg="be461761ec1a03776873909794fdac95" libId="2008148953_EN"/>
  <image url="alarm_cgplite/alarms/figure/en-us_image_0269895193.png" msg="cada1292bfcf0ded1548a1d42e0cc973" libId="2008148953_EN"/>
</images>""",
        )
        hzf.writestr(
            "resources/alarm_cgplite/alarms/1003.html",
            """<!DOCTYPE html
  PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html lang="en-us" xml:lang="en-us">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta name="DC.Type" content="alarmref">
<meta name="DC.Title" content="ALM-1003 Module Fault">
<meta name="DC.Identifier" content="EN-US_ALARMREF_0269895188">
<title>ALM-1003 Module Fault</title>
</head>
<body>
<h1 class="topicTitle-h1">ALM-1003 Module Fault</h1>
<div class="alarmdesc">
  <h2 class="sectiontitle"><a href="#EN-US_ALARMREF_0269895188" class="sectiontitle2contents">Description</a></h2>
  <p>This alarm is generated when the USC module is stopped abnormally or is killed.</p>
  <div class="fignone" id="fig_3"><span class="figcap"><b>Figure 1 </b>Root alarm</span><br>
    <span><img class="vsd" src="figure/en-us_image_0269895191.png" width="NaN" height="NaN"></span>
  </div>
  <div class="fignone" id="fig1"><span class="figcap"><b>Figure 2 </b>Alarm mechanism</span><br>
    <span><img class="vsd" src="figure/en-us_image_0269895193.png" width="NaN" height="NaN"></span>
  </div>
</div>
<div class="alarmattrs">
  <h2 class="sectiontitle"><a href="#EN-US_ALARMREF_0269895188" class="sectiontitle2contents">Attribute</a></h2>
  <table>
    <tr><th id="mcps1">Alarm ID</th><th id="mcps2">Alarm Severity</th><th id="mcps3">Auto Clear</th></tr>
    <tr><td headers="mcps1"><p>1003</p></td><td headers="mcps2"><p>Major</p></td><td headers="mcps3"><p>Yes</p></td></tr>
  </table>
</div>
<div class="possiblecauses">
  <h2 class="sectiontitle"><a href="#EN-US_ALARMREF_0269895188" class="sectiontitle2contents">Possible Causes</a></h2>
  <ul>
    <li>The arbitration PMU module detects abnormal process termination on SCU or CDB.</li>
    <li>Container memory quota exhausted during peak signaling load.</li>
  </ul>
</div>
<div class="procedure">
  <h2 class="sectiontitle"><a href="#EN-US_ALARMREF_0269895188" class="sectiontitle2contents">Procedure</a></h2>
  <ul>
    <li>Run DSP MODULE to check the operational state of the faulty USC module.</li>
    <li>Run ACT MODULE or restart the faulty container pod if automatic switchover fails.</li>
  </ul>
</div>
</body>
</html>""",
        )
        hzf.writestr(
            "resources/alarm_cgplite/alarms/125001.html",
            """<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html><head><meta name="DC.Title" content="ALM-125001 Signaling Link Down"><title>ALM-125001 Signaling Link Down</title></head>
<body>
<h1>ALM-125001 Signaling Link Down</h1>
<table><tr><th>Alarm ID</th><th>Alarm Severity</th></tr><tr><td>125001</td><td>Critical</td></tr></table>
<h2><a href="#top">Possible Causes</a></h2>
<ul><li>SCTP multi-homing path failure toward peer UPCF.</li></ul>
<h2><a href="#top">Procedure</a></h2>
<ul><li>Run DSP SCTPLNK to verify link status and execute MOD SCTPLNK.</li></ul>
</body></html>""",
        )

    with zipfile.ZipFile(target_zip_path, mode="w", compression=zipfile.ZIP_STORED) as outer_zf:
        outer_zf.writestr("USC_26.1.0_Doc.hwics", hwics_bio.getvalue())

    return target_zip_path


def _build_deterministic_openxml_release_zip(target_zip_path: Path) -> Path:
    """Build a deterministic ReleaseDoc `.zip` containing `.xlsx` and `.docx` OpenXML archives."""
    xlsx_bio = io.BytesIO()
    with zipfile.ZipFile(xlsx_bio, mode="w", compression=zipfile.ZIP_DEFLATED) as xzf:
        xzf.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Alarms" sheetId="1" r:id="rId1"/>
    <sheet name="Counters" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>""",
        )
        xzf.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Target="worksheets/sheet2.xml"/>
</Relationships>""",
        )
        strings = [
            "AlarmID",
            "AlarmName",
            "AlarmLevel",
            "AlarmType",
            "Location Information",
            "Alarm Explain",
            "Revise Advice",
            "Impact on the System",
            "System Actions",
            "Possible Causes",
            "15501",
            "Loading Data to Microservice Failed",
            "2",
            "6",
            "Instance ID=%s",
            "Microservice failed to load configuration data",
            "Check microservice database connectivity",
            "Service provisioning degraded",
            "None",
            "Database connection timeout;Invalid schema version",
            "Counter ID",
            "Counter Name",
            "Object Name",
            "FunctionSet Name",
            "FunctionSubSet Name",
            "Counter Unit",
            "Formula",
            "1727317513",
            "Number of Attempted N7 Session Establishment Requests",
            "PCFHLB",
            "PCF Performance Measurement",
            "Interworking Between PCF and SMF",
            "times",
            "SUM",
        ]
        sst_items = "".join(f"<si><t>{s}</t></si>" for s in strings)
        xzf.writestr(
            "xl/sharedStrings.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{sst_items}</sst>',
        )
        xzf.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c>
      <c r="D1" t="s"><v>3</v></c><c r="E1" t="s"><v>4</v></c><c r="F1" t="s"><v>5</v></c>
      <c r="G1" t="s"><v>6</v></c><c r="H1" t="s"><v>7</v></c><c r="I1" t="s"><v>8</v></c>
      <c r="J1" t="s"><v>9</v></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>10</v></c><c r="B2" t="s"><v>11</v></c><c r="C2" t="s"><v>12</v></c>
      <c r="D2" t="s"><v>13</v></c><c r="E2" t="s"><v>14</v></c><c r="F2" t="s"><v>15</v></c>
      <c r="G2" t="s"><v>16</v></c><c r="H2" t="s"><v>17</v></c><c r="I2" t="s"><v>18</v></c>
      <c r="J2" t="s"><v>19</v></c>
    </row>
  </sheetData>
</worksheet>""",
        )
        xzf.writestr(
            "xl/worksheets/sheet2.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="s"><v>20</v></c><c r="B1" t="s"><v>21</v></c><c r="C1" t="s"><v>22</v></c>
      <c r="D1" t="s"><v>23</v></c><c r="E1" t="s"><v>24</v></c><c r="F1" t="s"><v>25</v></c>
      <c r="G1" t="s"><v>26</v></c>
    </row>
    <row r="2">
      <c r="A2" t="s"><v>27</v></c><c r="B2" t="s"><v>28</v></c><c r="C2" t="s"><v>29</v></c>
      <c r="D2" t="s"><v>30</v></c><c r="E2" t="s"><v>31</v></c><c r="F2" t="s"><v>32</v></c>
      <c r="G2" t="s"><v>33</v></c>
    </row>
  </sheetData>
</worksheet>""",
        )

    docx_bio = io.BytesIO()
    with zipfile.ZipFile(docx_bio, mode="w", compression=zipfile.ZIP_DEFLATED) as dzf:
        dzf.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>UPCF 26.1.0.5 Patch Installation Procedure</w:t></w:r></w:p>
    <w:p><w:r><w:t>Verify that ALM-15501 is cleared before executing rolling VM container patch upgrade.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Run DSP MODULE and LST ALMAF on the active OMU before cutover.</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Step</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Action</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Pre-check health via DSP MODULE</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>""",
        )

    with zipfile.ZipFile(target_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as ozf:
        ozf.writestr("04 NMS Adaptation List File/HUAWEI UPCF 26.1.0.5 Alarm List.xlsx", xlsx_bio.getvalue())
        ozf.writestr("03 Upgrade Guide/HUAWEI UPCF 26.1.0.5 Patch Installation Guide.docx", docx_bio.getvalue())

    return target_zip_path


def test_01_streamer_extensions_and_nested_zip_hwics(tmp_path: Path) -> None:
    """Verify SUPPORTED_EXTENSIONS, 2GB/150:1 defaults, and transparent .zip -> .hwics streaming."""
    streamer = SovereignArchiveStreamer()
    for ext in (".hwics", ".xlsx", ".xlsm", ".docx"):
        assert ext in streamer.SUPPORTED_EXTENSIONS
    assert streamer.max_total_bytes == 2 * 1024 * 1024 * 1024
    assert streamer.max_compression_ratio == 150.0

    wrapped_zip = _build_deterministic_hwics_wrapped_zip(tmp_path / "huawei_usc_doc.zip")
    entries = list(streamer.stream_archive(wrapped_zip))
    entry_names = {e.entry_name for e in entries}
    assert "profile.xml" in entry_names
    assert "resources/navi.xml" in entry_names
    assert "resources/alarm_cgplite/alarms/1003.html" in entry_names

    # Verify compound virtual URI resolution without disk extraction
    compound_uri = f"archive://{wrapped_zip}!USC_26.1.0_Doc.hwics#resources/alarm_cgplite/alarms/1003.html"
    resolved = streamer.resolve_virtual_uri(compound_uri)
    assert "ALM-1003 Module Fault" in resolved.content_text


def test_02_xxe_guard_allows_w3c_html4_doctype_and_blocks_xxe() -> None:
    """Verify _XXE_GUARD_RE allows W3C HTML4 Transitional DOCTYPE while blocking <!ENTITY and <!DOCTYPE [."""
    w3c_header = (
        '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" '
        '"http://www.w3.org/TR/html4/loose.dtd">\n<html><body>ALM-1003</body></html>'
    )
    assert _XXE_GUARD_RE.search(w3c_header) is None

    malicious_entity = '<!DOCTYPE html [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>'
    assert _XXE_GUARD_RE.search(malicious_entity) is not None

    malicious_nav_dtd = '<!DOCTYPE nav SYSTEM "http://attacker.example/evil.dtd">'
    assert _XXE_GUARD_RE.search(malicious_nav_dtd) is not None


def test_03_hwics_profile_navi_diagrams_and_sub_1ms_routing(tmp_path: Path) -> None:
    """Verify Huawei .hwics ingestion extracts profile.xml, resources/navi.xml, diagrams, and ALM-1003 (<1ms)."""
    wrapped_zip = _build_deterministic_hwics_wrapped_zip(tmp_path / "huawei_usc_doc.zip")
    router = SovereignQueryRouter(db_path=":memory:", plan=PlanTier.ENTERPRISE)
    graph_store = GraphStore(db_path=":memory:")
    router.graph_store = graph_store

    ingestor = HdxTelecomIngestor()
    summary = ingestor.ingest_hdx_package(
        hdx_path=wrapped_zip,
        router=router,
        graph_store=graph_store,
        clearance_level=ClearanceLevel.INTERNAL,
    )
    assert summary["status"] == "success"
    manifest = summary["manifest"]

    # 1. Profile metadata
    assert manifest.profile_metadata["libName"] == "USC 26.1.0 Product Documentation (VM Container)"
    assert manifest.profile_metadata["productType"] == "USC"
    assert manifest.profile_metadata["productVersion"] == "26.1.0"
    assert manifest.profile_metadata["hedexVersion"] == "V100R002C00"
    assert len(manifest.images_catalog) >= 2

    # 2. ALM-1003 (4-digit) & ALM-125001 (6-digit) extraction + vsd diagram URIs
    alm_map = {a.alarm_id: a for a in manifest.alarms}
    assert "ALM-1003" in alm_map
    assert "ALM-125001" in alm_map

    alm_1003 = alm_map["ALM-1003"]
    assert alm_1003.alarm_name == "Module Fault"
    assert alm_1003.severity == "Major"
    assert len(alm_1003.diagram_uris) == 2
    assert any(u.endswith("#resources/alarm_cgplite/alarms/figure/en-us_image_0269895191.png") for u in alm_1003.diagram_uris)
    assert any("arbitration PMU" in c for c in alm_1003.possible_causes)

    # 3. GraphStore HAS_DIAGRAM edges
    neighborhood = graph_store.get_entity_neighborhood(
        entity_name="ALM-1003",
        max_depth=1,
        max_clearance=ClearanceLevel.INTERNAL.value,
    )
    rel_types = {n["relation"] for n in neighborhood["neighbors"]}
    assert "HAS_DIAGRAM" in rel_types
    assert "AFFECTS_NE" in rel_types
    assert "CAUSED_BY" in rel_types

    # 4. Sub-1ms Prong 1 routing for both 4-digit ALM-1003 and 6-digit ALM-125001
    for q_id in ("ALM-1003", "ALM-125001"):
        dec = router.analyze_query(q_id)
        assert dec.route_type == QueryRouteType.DETERMINISTIC_DIRECT
        assert dec.extracted_identifier is not None
        assert dec.extracted_identifier.normalized_value == q_id
        runs = [router.route_and_execute(q_id, user_clearance=ClearanceLevel.INTERNAL) for _ in range(3)]
        best_ms = min(r["latency_ms"] for r in runs)
        assert runs[-1]["status"] == "success"
        assert best_ms < 1.0, f"Expected <1ms lookup for {q_id}, got {best_ms:.3f}ms"

    router.close()
    graph_store.close()


def test_04_openxml_release_doc_parser_xlsx_and_docx(tmp_path: Path) -> None:
    """Verify OpenXmlReleaseDocParser extracts Alarms, Counters, and DOCX procedures in memory."""
    release_zip = _build_deterministic_openxml_release_zip(tmp_path / "UPCF_ReleaseDoc.zip")
    router = SovereignQueryRouter(db_path=":memory:", plan=PlanTier.ENTERPRISE)
    graph_store = GraphStore(db_path=":memory:")
    router.graph_store = graph_store

    parser = OpenXmlReleaseDocParser()
    res = parser.ingest_release_package(
        package_path=release_zip,
        router=router,
        graph_store=graph_store,
        clearance_level=ClearanceLevel.INTERNAL,
    )
    assert res["status"] == "success"
    assert res["alarms_extracted"] == 1
    assert res["counters_extracted"] == 1
    assert res["doc_sections_extracted"] >= 1

    # Verify ALM-15501 from XLSX resolves via Prong 1
    alm_res = router.route_and_execute("ALM-15501", user_clearance=ClearanceLevel.INTERNAL)
    assert alm_res["status"] == "success"
    assert "Loading Data to Microservice Failed" in alm_res["results"][0]["content"]

    # Verify Counter 1727317513 resolves in router and GraphStore
    ctr_hits = router.execute_deterministic_lookup("1727317513", user_clearance=ClearanceLevel.INTERNAL)
    assert len(ctr_hits) == 1
    assert "PCFHLB" in ctr_hits[0]["content"]

    router.close()
    graph_store.close()


@pytest.mark.skipif(
    not Path("/tmp/docs_rag_gemini").exists(),
    reason="Real Huawei 26.1.0 corpus /tmp/docs_rag_gemini not present on this machine",
)
def test_05_real_world_huawei_26_1_0_corpus_in_tmp() -> None:
    """Verify real wild Huawei 26.1.0 .zip->.hwics and ReleaseDoc .xlsx/.docx packages in /tmp/docs_rag_gemini/."""
    usc_zip = Path(
        "/tmp/docs_rag_gemini/HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip"
    )
    upcf_rel_zip = Path(
        "/tmp/docs_rag_gemini/UPCF 26.1.0.5_ReleaseDoc_EN (Virtual Machine Container).zip"
    )

    if usc_zip.exists():
        router = SovereignQueryRouter(db_path=":memory:", plan=PlanTier.ENTERPRISE)
        graph_store = GraphStore(db_path=":memory:")
        router.graph_store = graph_store
        ingestor = HdxTelecomIngestor(
            streamer=SovereignArchiveStreamer(max_compression_ratio=150.0)
        )
        # Stream real slice of USC 26.1.0 .hwics (profile.xml, resources/navi.xml, resources/images.xml, 1003.html, 1010.html)
        summary = ingestor.ingest_hdx_package(
            hdx_path=usc_zip,
            router=router,
            graph_store=graph_store,
            clearance_level=ClearanceLevel.INTERNAL,
            entry_filter={
                "resources/alarm_cgplite/alarms/1003.html",
                "resources/alarm_cgplite/alarms/1010.html",
            },
        )
        manifest = summary["manifest"]
        assert manifest.profile_metadata.get("productType") == "USC"
        assert manifest.profile_metadata.get("productVersion") == "26.1.0"
        alm_1003 = next(a for a in manifest.alarms if a.alarm_id == "ALM-1003")
        assert alm_1003.alarm_name == "Module Fault"
        assert alm_1003.severity == "Major"
        assert len(alm_1003.diagram_uris) >= 2

        lookup = router.route_and_execute("ALM-1003", user_clearance=ClearanceLevel.INTERNAL)
        assert lookup["status"] == "success"
        assert lookup["latency_ms"] < 1.5
        router.close()
        graph_store.close()

    if upcf_rel_zip.exists():
        router = SovereignQueryRouter(db_path=":memory:", plan=PlanTier.ENTERPRISE)
        graph_store = GraphStore(db_path=":memory:")
        parser = OpenXmlReleaseDocParser()
        rel_summary = parser.ingest_release_package(
            package_path=upcf_rel_zip,
            router=router,
            graph_store=graph_store,
            clearance_level=ClearanceLevel.INTERNAL,
            max_rows_per_sheet=200,
        )
        assert rel_summary["alarms_extracted"] > 0
        assert rel_summary["counters_extracted"] > 0
        assert rel_summary["doc_sections_extracted"] > 0

        alm_15501 = router.route_and_execute("ALM-15501", user_clearance=ClearanceLevel.INTERNAL)
        assert alm_15501["status"] == "success"
        router.close()
        graph_store.close()
