"""End-to-end check of the graph viewer in a real browser (skipped when Playwright or Chromium is
missing). Drives the real portal page against the hand-drawn vault of graph_fixtures.py."""

import threading
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from core.graph.store import GraphStore  # noqa: E402
from core.server import SovereignHTTPHandler, create_app  # noqa: E402
from tests.graph_fixtures import build_vault, build_wiki  # noqa: E402

ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("graph_browser")
    router, graph = build_vault(tmp)
    previous = getattr(SovereignHTTPHandler, "manager", None)
    create_app(searcher=MagicMock(), graph_store=GraphStore(db_path=graph), router_db_path=router, wiki_dir=build_wiki(tmp))
    server = ThreadingHTTPServer(("127.0.0.1", 0), SovereignHTTPHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        pw = sync_api.sync_playwright().start()
        browser = pw.chromium.launch(args=ARGS)
    except Exception as err:  # no browser installed on this machine
        server.shutdown()
        pytest.skip(f"no usable Chromium: {err}")
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(f"http://127.0.0.1:{server.server_port}/")
    pg.evaluate("switchCommandTab('graph')")
    pg.errors = errors
    yield pg
    browser.close(); pw.stop(); server.shutdown(); server.server_close()
    SovereignHTTPHandler.manager = previous


def status(page):
    return page.inner_text("#gv-status")


def test_tree_opens_clustered_and_a_search_result_is_revealed_and_inspected(page):
    page.wait_for_function("/nodes ·/.test(document.getElementById('gv-status').textContent)", timeout=30000)
    assert status(page).startswith("8 nodes · 6 edges")           # 2 packages + 2 roots + their 4 children

    page.fill("#gv-search", "leaf a1a")
    page.wait_for_selector(".gv-result[data-id]", timeout=10000)
    page.click(".gv-result[data-id]")
    page.wait_for_function("document.querySelector('.gv-node-title') && document.querySelector('.gv-node-title').textContent === 'Leaf A1a'", timeout=10000)
    assert page.errors == []


def test_layers_clearance_and_isolating_a_legend_category(page):
    page.click("[data-layer='entity']")
    page.wait_for_function("/^7 nodes/.test(document.getElementById('gv-status').textContent) || /^7 nodes/.test(document.getElementById('gv-status').textContent)", timeout=30000)
    chips = page.inner_text("#gv-legend")
    assert "telecom_alarm" in chips and "mml_command" in chips

    page.click(".gv-chip[data-cat='telecom_alarm']")             # isolate: every other type is dimmed
    assert page.evaluate("Array.from(window.AegisGraphView.gl.flags).filter(f => f === 1).length") == 5
    page.click(".gv-chip[data-cat='telecom_alarm']")             # again: show all
    assert page.evaluate("Array.from(window.AegisGraphView.gl.flags).filter(f => f === 1).length") == 0

    page.select_option("#gv-clearance", "public")
    page.wait_for_function("/Alarms · MML · KPIs 4/.test(document.getElementById('gv-layers').textContent)", timeout=30000)
    assert page.errors == []


def test_two_d_three_d_toggle_and_wiki_layer(page):
    page.click("[data-layer='wiki']")
    page.wait_for_function("/^5 nodes/.test(document.getElementById('gv-status').textContent)", timeout=30000)  # d.md is INTERNAL
    page.click("#gv-dim3")
    assert page.evaluate("window.AegisGraphView.gl.mode") == "3d"
    page.click("#gv-dim2")
    assert page.evaluate("window.AegisGraphView.gl.mode") == "2d"
    assert page.errors == []
