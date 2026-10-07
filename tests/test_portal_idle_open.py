"""ADR-15 phase 1 / ADR-16: the portal opens idle and previews a result only on a tap; the server streams
previews concurrently and serializes only the diagram path (a whole inner package).

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


# --- server: previews stream and overlap; only the diagram path (whole inner package) is serialized ----------

def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


def _fire_four_inspects(base_url, payload):
    """Four simultaneous POST /archive/inspect against a slow fake; returns (statuses, peak concurrency)."""
    manager = SovereignHTTPHandler.manager
    state = {"now": 0, "peak": 0}
    guard = threading.Lock()

    def slow_inspect(**_kwargs):
        with guard:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.3)
        with guard:
            state["now"] -= 1
        return {"content_text": "ok"}

    original = manager.inspect_archive
    manager.inspect_archive = slow_inspect
    try:
        results = []
        threads = [threading.Thread(target=lambda: results.append(_post(f"{base_url}/archive/inspect", payload))) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        manager.inspect_archive = original
    return [status for status, _ in results], state["peak"]


def test_plain_previews_are_not_serialized(base_url):
    statuses, peak = _fire_four_inspects(base_url, {"virtual_uri": "archive://x.zip!/a#resources/a.html"})
    assert statuses == [200, 200, 200, 200]
    assert peak >= 2          # streaming previews need tens of MB each: no reason to queue them


def test_diagram_extraction_still_reads_one_package_at_a_time(base_url):
    # ADR-16 phase 2 has not landed: this path still loads a whole inner package, so it queues
    for payload in ({"virtual_uri": "archive://x.zip!/a#resources/a.html", "extract_diagram_to_artifact": True},
                    {"virtual_uri": "archive://x.zip!/a#figure/pic.png"}):
        statuses, peak = _fire_four_inspects(base_url, payload)
        assert statuses == [200, 200, 200, 200]    # waiting is fine, failing is not
        assert peak == 1


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
