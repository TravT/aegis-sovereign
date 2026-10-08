"""
Tests for on-demand diagram streaming and HedEx/.hwics topic tree navigation.
Asserts that embedded figures (like DRA Positioning) stream with zero disk extraction,
and that topic hierarchies (parent, siblings, previous/next) resolve cleanly.
"""

import sqlite3
import pytest
from pathlib import Path

from core.server.app import SovereignApplianceManager
from core.server.viewer import DocumentViewer
from core.server.constants import DEFAULT_ROUTER_DB

ROUTER_DB_PATH = DEFAULT_ROUTER_DB
REAL_VAULT_EXISTS = ROUTER_DB_PATH.exists() and ROUTER_DB_PATH.stat().st_size > 0

DRA_URI = (
    "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/"
    "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip!"
    "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics#"
    "resources/toctopics/en-us_topic_0315370554.html"
)
DRA_DIAGRAM = "en-us_image_0000001410094526.png"


@pytest.mark.skipif(not REAL_VAULT_EXISTS, reason="Real sovereign_router.db required")
def test_stream_diagram_on_demand_real_corpus():
    app = SovereignApplianceManager(router_db_path=str(ROUTER_DB_PATH))
    result = app.stream_diagram(DRA_DIAGRAM)

    assert result is not None, f"Failed to stream {DRA_DIAGRAM} on demand"
    ctype, data = result
    assert ctype == "image/png"
    assert len(data) == 18844
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(not REAL_VAULT_EXISTS, reason="Real sovereign_router.db required")
def test_get_topic_hierarchy_dra_positioning():
    app = SovereignApplianceManager(router_db_path=str(ROUTER_DB_PATH))
    tree = app.get_topic_hierarchy(virtual_uri=DRA_URI)

    assert tree is not None
    assert tree["current"]["name"] == "DRA Product Positioning"
    assert tree["current"]["topic_id"] == "USC:TOPIC_0315370554"
    assert tree["parent"] is not None
    assert tree["parent"]["name"] == "Product Positioning"

    # Siblings check
    assert tree["siblings_count"] == 5
    sib_names = [s["name"] for s in tree["siblings"]]
    assert "DRA Product Positioning" in sib_names
    assert "SEPP Product Positioning" in sib_names
    assert "STP Product Positioning" in sib_names

    # Prev and Next pointers
    assert tree["prev_topic"] is not None
    assert tree["prev_topic"]["name"] == "SEPP Product Positioning"
    assert tree["next_topic"] is not None
    assert tree["next_topic"]["name"] == "STP Product Positioning"


def test_document_viewer_rewrites_nested_diagram_paths():
    class MockEntry:
        entry_name = "resources/toctopics/en-us_topic_0315370554.html"
        raw_bytes = b'<p>Figure: <img class="imgResize" src="../images/en-us_image_0000001410094526.png"></p>'

    html_out = DocumentViewer.format_entry_to_styled_html(MockEntry(), virtual_uri="archive://test#entry.html")
    assert 'src="/diagrams/en-us_image_0000001410094526.png"' in html_out


def test_document_viewer_renders_topic_navigation():
    class MockEntry:
        entry_name = "test.html"
        content_text = "Some topic text"

    mock_hierarchy = {
        "current": {"name": "Current Topic", "path_text": "Manual > Chapter > Current Topic"},
        "parent": {"name": "Chapter", "uri": "archive://test#chapter.html"},
        "prev_topic": {"name": "Previous Topic", "uri": "archive://test#prev.html"},
        "next_topic": {"name": "Next Topic", "uri": "archive://test#next.html"},
        "siblings": [
            {"name": "Previous Topic", "uri": "archive://test#prev.html", "is_current": False},
            {"name": "Current Topic", "uri": "archive://test#current.html", "is_current": True},
            {"name": "Next Topic", "uri": "archive://test#next.html", "is_current": False},
        ],
    }

    html_out = DocumentViewer.format_entry_to_styled_html(
        MockEntry(), virtual_uri="archive://test#current.html", topic_hierarchy=mock_hierarchy
    )

    assert "topic-nav-container" in html_out
    assert "Manual &gt; Chapter &gt; Current Topic" in html_out
    assert "Previous Topic" in html_out
    assert "Next Topic" in html_out
    assert "Chapter Contents" in html_out


UPCF_URI = (
    "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/"
    "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).zip!"
    "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).hwics#"
    "resources/upcc/description/product_desc/cn_22_03_000002.html"
)


@pytest.mark.skipif(not REAL_VAULT_EXISTS, reason="Real sovereign_router.db required")
def test_get_topic_hierarchy_upcf_root_positioning():
    app = SovereignApplianceManager(router_db_path=str(ROUTER_DB_PATH))
    tree = app.get_topic_hierarchy(virtual_uri=UPCF_URI)

    assert tree is not None
    assert tree["current"]["name"] == "Product Positioning"
    assert tree["current"]["package"] == "UPCF"
    assert "UPCF &gt;" in tree["current"]["path_text"] or "UPCF >" in tree["current"]["path_text"]
    assert tree["parent"] is not None
    assert "UPCF" in tree["parent"]["name"]

    # Root Siblings check from same bookmap
    assert tree["siblings_count"] == 11
    sib_names = [s["name"] for s in tree["siblings"]]
    assert "Background" in sib_names
    assert "Product Positioning" in sib_names
    assert "Product Architecture" in sib_names

    # Prev and Next pointers
    assert tree["prev_topic"] is not None
    assert tree["prev_topic"]["name"] == "Background"
    assert tree["next_topic"] is not None
    assert tree["next_topic"]["name"] == "Product Architecture"


def test_document_viewer_strips_external_stylesheets_and_rewrites_links():
    class MockEntry:
        entry_name = "resources/upcc/description/product_desc/cn_22_03_000002.html"
        raw_bytes = (
            b'<link rel="stylesheet" type="text/css" href="../../../public_sys-resources/commonltr.css">\n'
            b'<p>See <a href="cn_90_03_000013.html">Architecture</a> and figure: '
            b'<img class="vsd" src="figure/en-us_image_0169024719.png"></p>'
        )

    html_out = DocumentViewer.format_entry_to_styled_html(
        MockEntry(),
        virtual_uri="archive:///path/to/archive.zip!inner.hwics#resources/upcc/description/product_desc/cn_22_03_000002.html"
    )

    # Stylesheet stripped
    assert "commonltr.css" not in html_out
    # Diagram rewritten to /diagrams/
    assert 'src="/diagrams/en-us_image_0169024719.png"' in html_out
    # Internal document link rewritten to /archive/view?uri=
    assert '/archive/view?uri=' in html_out
    assert 'cn_90_03_000013.html' in html_out

