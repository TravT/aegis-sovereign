"""Static guarantees of the portal graph viewer: air-gapped, wired into the graph tab."""

import re
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent / "web" / "portal"
LOCAL = ("127.0.0.1", "localhost", "0.0.0.0")


def _portal_files():
    return [p for p in PORTAL.rglob("*") if p.is_file() and p.suffix in {".html", ".js", ".css"}]


def test_the_portal_references_no_external_origin_so_it_works_air_gapped():
    offenders = []
    for path in _portal_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for url in re.findall(r"""(?:https?:)?//[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}[^\s"'`)>]*""", text):
            host = re.sub(r"^(?:https?:)?//", "", url).split("/")[0]
            if not host.startswith(LOCAL):
                offenders.append(f"{path.name}: {url[:70]}")
    assert offenders == [], offenders


def test_graph_tab_is_wired_to_the_viewer_scripts_in_dependency_order():
    html = (PORTAL / "index.html").read_text(encoding="utf-8")
    for element_id in ("gv-canvas", "gv-legend", "gv-search", "gv-layers", "gv-clearance", "graph-node-details"):
        assert f'id="{element_id}"' in html, element_id
    order = [html.index(f"/portal/js/{name}") for name in ("graph_gl.js", "graph_force.js", "graph_view.js")]
    assert order == sorted(order)
    assert "AegisGraphView.open()" in (PORTAL / "js" / "portal.js").read_text(encoding="utf-8")


def test_viewer_code_has_no_third_party_dependency():
    for name in ("graph_gl.js", "graph_force.js", "graph_view.js"):
        text = (PORTAL / "js" / name).read_text(encoding="utf-8")
        assert not re.search(r"\b(?:import\s+.+\s+from|require\()", text), name
        assert "THREE." not in text and "d3." not in text, name
