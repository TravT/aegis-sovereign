"""Phase 12.2: /archive/view renders wiki markdown (was 500, "missing '#'"), with the portal's own renderer.

Answer citations link to /archive/view?uri=archive://<wiki file>. Runs against a temporary wiki directory and an
in-memory router database: the production vault is never opened.
"""

import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from core.server import SovereignHTTPHandler, create_app

DOC = """---
title: "Viewer sample"
---

# Viewer sample

See [the other note](sub/other.md) and [an anchor](#second-part).

```mermaid
flowchart LR
    A --> B
```

$$E = mc^2$$

## Second part

VIEWER-END-MARKER
"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url: str, follow: bool = True):
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=15) as r:
            return r.status, r.headers, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", errors="replace")


def _view(base: str, path) -> str:
    return f"{base}/archive/view?uri={urllib.parse.quote('archive://' + str(path))}"


@pytest.fixture(scope="module")
def view_server(tmp_path_factory):
    wiki = tmp_path_factory.mktemp("wiki")
    (wiki / "sub").mkdir()
    (wiki / "sample.md").write_text(DOC, encoding="utf-8")
    (wiki / "sub" / "other.md").write_text("# Other\n\nOTHER-NOTE\n", encoding="utf-8")
    (wiki / "hostile.md").write_text(
        "# Hostile\n\n</script><script>window.pwned = 1</script>\n\n<img src=x onerror=\"window.pwned = 2\">\n",
        encoding="utf-8",
    )
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.md").write_text("# Not in the wiki\n", encoding="utf-8")
    create_app(router_db_path=":memory:", wiki_dir=str(wiki))
    server = ThreadingHTTPServer(("127.0.0.1", 0), SovereignHTTPHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", wiki, outside
    server.shutdown()
    server.server_close()


def test_wiki_file_returns_a_page_that_uses_the_portal_renderer(view_server):
    base, wiki, _ = view_server
    status, headers, body = _get(_view(base, wiki / "sample.md"))
    assert status == 200, body[:300]
    assert "text/html" in headers["Content-Type"]
    assert '<script src="/portal/js/markdown.js' in body
    assert 'id="doc-source"' in body
    assert "<title>Viewer sample" in body


def test_double_encoded_uri_and_wiki_redirect_both_land(view_server):
    base, wiki, _ = view_server
    twice = f"{base}/archive/view?uri={urllib.parse.quote(urllib.parse.quote('archive://' + str(wiki / 'sample.md')))}"
    assert _get(twice)[0] == 200
    chunk = f"{base}/archive/view?uri={urllib.parse.quote(str(wiki / 'sample.md') + '::part::0002')}"
    assert _get(chunk)[0] == 200  # a wiki chunk id, bare path, as stored in document_records
    status, headers, _ = _get(f"{base}/wiki/sample.md", follow=False)
    assert status == 302
    assert _get(base + headers["Location"])[0] == 200


def test_paths_outside_the_wiki_or_missing_are_404_not_500(view_server):
    base, wiki, outside = view_server
    assert _get(_view(base, outside / "secret.md"))[0] == 404
    assert _get(_view(base, wiki / "nope.md"))[0] == 404
    assert _get(_view(base, f"{wiki}/../{outside.name}/secret.md"))[0] == 404


def test_document_text_cannot_break_out_of_its_script_block(view_server):
    base, wiki, _ = view_server
    status, _, body = _get(_view(base, wiki / "hostile.md"))
    assert status == 200
    assert "</script><script>window.pwned" not in body


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _open(browser, base: str, url: str, width: int = 1440):
    page = browser.new_page(viewport={"width": width, "height": 900})
    problems: list = []
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("request", lambda r: None if r.url.startswith((base, "data:", "blob:")) else problems.append(f"external {r.url}"))
    page.goto(url, wait_until="load")
    page.wait_for_function("() => document.getElementById('doc-content').dataset.renderState === 'done'", timeout=20_000)
    return page, problems


@pytest.mark.parametrize("width", [1440, 390])
def test_viewer_page_renders_like_the_inspector(view_server, browser, width):
    base, wiki, _ = view_server
    page, problems = _open(browser, base, _view(base, wiki / "sample.md"), width)
    try:
        doc = page.locator("#doc-content")
        text = doc.inner_text()
        assert "VIEWER-END-MARKER" in text
        assert page.locator("#doc-content .md-mermaid svg").count() == 1
        assert page.locator("#doc-content .md-math-display .katex").count() == 1
        assert "```" not in text and "$$" not in text and "title:" not in text
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert problems == []
    finally:
        page.close()


def test_viewer_links_open_other_wiki_files_in_the_viewer(view_server, browser):
    base, wiki, _ = view_server
    page, problems = _open(browser, base, _view(base, wiki / "sample.md"))
    try:
        page.locator("#doc-content a.internal-wiki-link").first.click()
        page.wait_for_function("() => document.getElementById('doc-content')?.dataset.renderState === 'done'")
        assert "OTHER-NOTE" in page.locator("#doc-content").inner_text()
        assert problems == []
    finally:
        page.close()


def test_hostile_markup_stays_text(view_server, browser):
    base, wiki, _ = view_server
    page, problems = _open(browser, base, _view(base, wiki / "hostile.md"))
    try:
        assert page.evaluate("() => window.pwned === undefined")
        assert "</script>" in page.locator("#doc-content").inner_text()
        assert problems == []
    finally:
        page.close()
