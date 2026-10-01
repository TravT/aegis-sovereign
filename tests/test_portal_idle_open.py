"""ADR-15 phase 1 / ADR-16 phase 0: the portal opens idle, previews a result only on a tap, and the
server reads at most one archive for a preview at a time.

Opening the portal used to fire a search and then an automatic preview of the first result. The preview
reads a 330 MB zip whole (about 1 GB), which out-of-memory-killed the server on every page load.
"""

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest

from core.server import SovereignHTTPHandler, create_app

A_RESULT = {
    "route_type": "deterministic_direct",
    "status": "success",
    "needs_synthesis": False,
    "latency_ms": 1.0,
    "results": [{"virtual_uri": "archive://x.zip!/a.html", "content": "alarm text", "title": "ALM-1"}],
}


@pytest.fixture(scope="module")
def base_url():
    previous = getattr(SovereignHTTPHandler, "manager", None)
    create_app(searcher=MagicMock())
    server = ThreadingHTTPServer(("127.0.0.1", 0), SovereignHTTPHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    SovereignHTTPHandler.manager = previous


# --- server: one archive preview at a time -----------------------------------------------------------------

def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


def test_concurrent_archive_previews_run_one_at_a_time(base_url):
    manager = SovereignHTTPHandler.manager
    state = {"now": 0, "peak": 0}
    guard = threading.Lock()

    def slow_inspect(**_kwargs):
        with guard:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.2)
        with guard:
            state["now"] -= 1
        return {"content_text": "ok"}

    original = manager.inspect_archive
    manager.inspect_archive = slow_inspect
    try:
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(_post(f"{base_url}/archive/inspect", {"virtual_uri": "archive://x.zip!/a"})))
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        manager.inspect_archive = original

    assert [status for status, _ in results] == [200, 200, 200, 200]   # waiting is fine, failing is not
    assert state["peak"] == 1


def test_archive_view_shares_the_same_one_at_a_time_limit(base_url):
    manager = SovereignHTTPHandler.manager
    state = {"now": 0, "peak": 0}
    guard = threading.Lock()

    def slow(*_args, **_kwargs):
        with guard:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.2)
        with guard:
            state["now"] -= 1
        return {"content_text": "ok"} if _kwargs.get("virtual_uri") else "<html></html>"

    original_inspect, original_view = manager.inspect_archive, manager.render_archive_document_html
    manager.inspect_archive, manager.render_archive_document_html = slow, slow
    try:
        def view():
            urllib.request.urlopen(f"{base_url}/archive/view?uri=archive://x.zip!/a", timeout=30).read()

        threads = [threading.Thread(target=view) for _ in range(2)] + [
            threading.Thread(target=lambda: _post(f"{base_url}/archive/inspect", {"virtual_uri": "archive://x.zip!/a"})) for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        manager.inspect_archive, manager.render_archive_document_html = original_inspect, original_view

    assert state["peak"] == 1


# --- portal page: opens idle, previews on tap ---------------------------------------------------------------

@pytest.fixture(scope="module")
def page(base_url):
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync_api.sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as err:  # no browser installed on this machine
        pytest.skip(f"no usable Chromium: {err}")
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    pg.requests = []
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("request", lambda r: pg.requests.append((r.method, r.url.split(base_url)[-1])) if base_url in r.url else None)
    pg.route("**/router/query", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(A_RESULT)))
    pg.route("**/archive/inspect", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"content_text": "previewed"})))
    pg.goto(base_url + "/")
    pg.wait_for_timeout(6000)   # a page-load crash needs a few seconds to show: hold the page open
    yield pg
    browser.close()
    pw.stop()


def _count(page, path):
    return sum(1 for _method, url in page.requests if url.startswith(path))


def test_page_load_fires_no_search_and_no_archive_preview(page):
    assert _count(page, "/router/query") == 0
    assert _count(page, "/archive/inspect") == 0
    assert page.errors == []


def test_the_idle_screen_tells_the_user_what_to_do(page):
    assert page.locator("#idle-hint").count() == 1
    assert page.inner_text("#idle-hint").strip() != ""


def test_a_search_does_not_preview_and_a_tap_previews_exactly_once(page):
    page.click(".preset-chip >> nth=0")
    page.wait_for_selector(".source-card .action-btn", timeout=10000)
    page.wait_for_timeout(2000)
    assert _count(page, "/router/query") == 1
    assert _count(page, "/archive/inspect") == 0                      # results are shown, nothing is read yet

    page.click("text=Open in Side Drawer >> nth=0")
    page.wait_for_function("document.getElementById('inspector-content').textContent.includes('previewed')", timeout=10000)
    assert _count(page, "/archive/inspect") == 1
    assert page.errors == []
