"""Phase 12.1: wiki documents render correctly in the portal inspector (PRJ-06 §0.1, defects R-a to R-e).

Runs against a temporary wiki directory and an in-memory router database: the production vault is never opened.
The browser tests use the pre-installed Chromium through Playwright.
"""

import hashlib
import json
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from core.server import SovereignHTTPHandler, create_app

APPLIANCE = Path(__file__).resolve().parents[1]
VENDOR = APPLIANCE / "web" / "portal" / "vendor"

# Every construct the 157 wiki files use that the old renderer showed raw (counts from a 14 Oct survey).
SAMPLE_DOC = r"""---
title: "Rendering sample"
status: active
tags:
  - aegis
---

# Rendering sample

Intro with **bold**, *italic*, ~~struck~~, `code with **stars** and $${1}` and a [relative link](other.md).

> [!CAUTION]
> Never write to the backing SSD.

> [!NOTE]
> A note.

> A plain quote line.

1. First step
    - nested bullet A
    - nested bullet B
        1. deep ordered
2. Second step

- [ ] open task
- [x] done task

| Column | Value |
| :--- | ---: |
| pipe | a \| b |
| break | one<br>two |

---

Inline math $\mathbb{R}^{384}$ and $D=384$ here, but a price of $5 and $10 stays text.

Escaped dollar and underscore in text mode: $\ge \text{R\$} 1.000,00$ and $C.\text{topic_id}$.

  > [!NOTE] Informational context.
  > [!TIP] Recommended practice.

$$RRF(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

```mermaid
flowchart LR
    A["Question"] --> B{"Router"}
    B --> C["Answer"]
```

```bash
echo "code stays code: **not bold** $$x$$"
```

LAST-LINE-MARKER
"""

RAW_MARKERS = ("```", "**", "[!", "$$", "flowchart", "<br>", "&lt;", "\\|", "~~", "- [ ]", "- [x]", ":---")


def _long_doc() -> str:
    body = "\n\n".join(f"## Section {i}\n\nParagraph {i} " + ("lorem ipsum " * 40) for i in range(40))
    return f"# Long document\n\n{body}\n\nEND-OF-LONG-DOC\n"


@pytest.fixture(scope="module")
def wiki_server(tmp_path_factory):
    wiki = tmp_path_factory.mktemp("wiki")
    (wiki / "sample.md").write_text(SAMPLE_DOC, encoding="utf-8")
    (wiki / "long.md").write_text(_long_doc(), encoding="utf-8")
    create_app(router_db_path=":memory:", wiki_dir=str(wiki))
    server = ThreadingHTTPServer(("127.0.0.1", 0), SovereignHTTPHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", wiki
    server.shutdown()
    server.server_close()


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def _inspect(base: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base}/archive/inspect", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        assert r.status == 200
        return json.loads(r.read())


# --- Vendored libraries (R-c, R-d): pinned, inside the image, served by the portal -------------------------------


def test_vendored_files_match_the_manifest():
    manifest = (VENDOR / "VENDOR.md").read_text(encoding="utf-8")
    rows = re.findall(r"`([\w.\-/]+\.(?:js|css))` \| `([0-9a-f]{64})`", manifest)
    assert len(rows) == 3, rows
    for rel, digest in rows:
        assert hashlib.sha256((VENDOR / rel).read_bytes()).hexdigest() == digest, rel
    assert (VENDOR / "mermaid-12.2.0" / "LICENSE").exists()
    assert (VENDOR / "katex-0.19.0" / "LICENSE").exists()
    assert len(list((VENDOR / "katex-0.19.0" / "fonts").glob("*.woff2"))) == 20


def test_vendor_holds_only_listed_files():
    manifest = (VENDOR / "VENDOR.md").read_text(encoding="utf-8")
    for f in VENDOR.rglob("*"):
        if f.is_file() and f.suffix in (".js", ".css", ".mjs"):
            assert f"`{f.relative_to(VENDOR).as_posix()}`" in manifest, f"unpinned vendor file {f}"


def test_portal_serves_vendor_assets_with_types(wiki_server):
    base, _ = wiki_server
    for rel, ctype in (
        ("mermaid-12.2.0/mermaid.min.js", "javascript"),
        ("katex-0.19.0/katex.min.js", "javascript"),
        ("katex-0.19.0/katex.min.css", "text/css"),
        ("katex-0.19.0/fonts/KaTeX_Main-Regular.woff2", "font/woff2"),
    ):
        status, got_type, body = _get(f"{base}/portal/vendor/{rel}")
        assert status == 200, rel
        assert ctype in got_type, (rel, got_type)
        assert len(body) > 1000
    assert _get(f"{base}/portal/vendor/../index.html")[0] in (403, 404)
    assert _get(f"{base}/portal/vendor/nothing.js")[0] == 404


# --- R-b: no silent truncation -----------------------------------------------------------------------------------


def test_inspect_flags_truncation_and_pages(wiki_server):
    base, wiki = wiki_server
    uri = f"archive://{wiki / 'long.md'}"
    total = len((wiki / "long.md").read_text(encoding="utf-8"))
    assert total > 20_000

    first = _inspect(base, {"virtual_uri": uri, "max_chars": 8000})
    assert len(first["content_text"]) == 8000
    assert first["truncated"] is True
    assert first["total_chars"] == total
    assert first["next_offset"] == 8000

    pieces, offset = [first["content_text"]], first["next_offset"]
    while offset is not None:
        page = _inspect(base, {"virtual_uri": uri, "max_chars": 8000, "char_offset": offset})
        pieces.append(page["content_text"])
        offset = page["next_offset"]
    assert "".join(pieces) == (wiki / "long.md").read_text(encoding="utf-8")
    assert page["truncated"] is False

    whole = _inspect(base, {"virtual_uri": uri, "max_chars": 0})
    assert whole["truncated"] is False and whole["next_offset"] is None
    assert whole["content_text"].rstrip().endswith("END-OF-LONG-DOC")

    past_end = _inspect(base, {"virtual_uri": uri, "max_chars": 8000, "char_offset": total + 5})
    assert past_end["content_text"] == "" and past_end["truncated"] is False


# --- R-a, R-c, R-d, R-e in a real browser --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _open_in_inspector(browser, base: str, uri: str, width: int):
    page = browser.new_page(viewport={"width": width, "height": 1000})
    errors: list = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # Air-gapped: every request, vendored Mermaid and KaTeX included, stays on the portal's origin.
    page.on("request", lambda r: None if r.url.startswith((base, "data:", "blob:")) else errors.append(f"external {r.url}"))
    page.goto(f"{base}/portal", wait_until="load")
    page.evaluate("u => openSourceInInspector(u, '', false)", uri)
    page.wait_for_function(
        "() => { const el = document.getElementById('inspector-content');"
        " return el && el.dataset.renderState === 'done'; }",
        timeout=20_000,
    )
    return page, errors


@pytest.mark.parametrize("width", [1440, 390])
def test_inspector_renders_every_construct(wiki_server, browser, width):
    base, wiki = wiki_server
    page, errors = _open_in_inspector(browser, base, f"archive://{wiki / 'sample.md'}", width)
    try:
        el = page.locator("#inspector-content")
        # R-a: a block container that wraps, not a <pre>.
        assert el.evaluate("e => e.tagName") == "DIV"
        assert el.evaluate("e => getComputedStyle(e).whiteSpace") == "normal"
        assert el.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "content overflows horizontally"

        text = el.inner_text()
        html = el.inner_html()
        # Code is shown verbatim on purpose, so the check reads the text outside code elements.
        prose = el.evaluate(
            "e => { const c = e.cloneNode(true); c.querySelectorAll('code, pre').forEach(x => x.remove());"
            " document.body.appendChild(c); const t = c.innerText; c.remove(); return t; }"
        )
        raw = [m for m in RAW_MARKERS if m in prose]
        assert raw == [], f"raw markdown visible: {raw}"
        assert "LAST-LINE-MARKER" in text

        # R-c: Mermaid drawn as SVG, the source not shown.
        assert page.locator("#inspector-content .md-mermaid svg").count() == 1
        assert "-->" not in text
        # R-d: display and inline math through KaTeX; prices stay text.
        assert page.locator("#inspector-content .md-math-display .katex").count() == 1
        assert page.locator("#inspector-content .md-math-inline .katex").count() == 4
        assert page.locator("#inspector-content .katex-error").count() == 0
        assert "$5 and $10" in text
        # R-e: CAUTION callout, plain quote, nested lists three deep, tasks.
        assert page.locator("#inspector-content .callout-caution").count() == 1
        assert page.locator("#inspector-content .callout-note").count() == 2  # one, plus one from the callout list
        assert page.locator("#inspector-content .callout-tip").count() == 1
        assert page.locator("#inspector-content blockquote.md-quote").count() == 1
        assert page.locator("#inspector-content ol.md-ol > li ul.md-ul > li ol.md-ol > li").count() == 1
        assert page.locator("#inspector-content input[type=checkbox]").count() == 2
        assert page.locator("#inspector-content hr").count() == 1
        assert page.locator("#inspector-content del").count() == 1
        # Tables: escaped pipe stays in its cell, <br> becomes a line break (and nothing else is unescaped).
        cells = page.locator("#inspector-content table.md-table td").all_inner_texts()
        assert "a | b" in cells
        assert "<br" not in html.replace("<br>", "")
        # Code keeps its content verbatim.
        assert "**not bold** $$x$$" in page.locator("#inspector-content pre.code-pre").last.inner_text()
        assert "code with **stars** and $${1}" in page.locator("#inspector-content .md-inline-code").first.inner_text()
        assert errors == []
    finally:
        page.close()


def test_wide_diagram_fits_and_offers_full_size(wiki_server, browser):
    base, wiki = wiki_server
    chain = " --> ".join(f'N{i}["Step number {i} of the pipeline"]' for i in range(12))
    (wiki / "wide.md").write_text(f"# Wide\n\n```mermaid\nflowchart LR\n    {chain}\n```\n", encoding="utf-8")
    page, errors = _open_in_inspector(browser, base, f"archive://{wiki / 'wide.md'}", 390)
    try:
        box = page.locator("#inspector-content .md-mermaid")
        svg = box.locator("svg")
        assert svg.evaluate("e => e.getBoundingClientRect().width") <= box.evaluate("e => e.clientWidth")  # fits
        btn = box.locator(".md-mermaid-zoom")
        assert btn.inner_text().strip() == "⤢ Full size"
        btn.click()
        natural = float(svg.get_attribute("data-natural-width"))
        assert abs(svg.evaluate("e => e.getBoundingClientRect().width") - natural) < 2
        assert box.evaluate("e => e.scrollWidth > e.clientWidth")  # its own frame scrolls, not the page
        assert page.locator("#inspector-content").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        btn.click()
        assert svg.evaluate("e => e.getBoundingClientRect().width") <= box.evaluate("e => e.clientWidth")
        assert errors == []
    finally:
        page.close()


def test_inspector_shows_whole_wiki_document(wiki_server, browser):
    base, wiki = wiki_server
    page, errors = _open_in_inspector(browser, base, f"archive://{wiki / 'long.md'}", 1440)
    try:
        text = page.locator("#inspector-content").inner_text()
        assert "END-OF-LONG-DOC" in text
        assert "Section 39" in text
        assert errors == []
    finally:
        page.close()


def test_render_markdown_escapes_html(wiki_server, browser):
    base, _ = wiki_server
    page = browser.new_page()
    try:
        page.goto(f"{base}/portal", wait_until="load")
        out = page.evaluate(
            "() => renderMarkdown('<script>alert(1)</script> <img src=x onerror=alert(1)> [x](javascript:alert(1))\\n\\n"
            "| a |\\n| --- |\\n| <b>b</b><br/> |', '')"
        )
        assert "<script" not in out and "<img" not in out and "<b>" not in out
        assert 'href="javascript:' not in out
        assert "<br>" in out
    finally:
        page.close()
