"""Phase 12.4: portal layout bugs U4-U7 and the prong-2 banner wording (findings register, backlog note
docs/wiki/projects/aegis/studies/wave_follow_up_tasks_u4_u7_d1_d8.md). Real browser, temporary server with an
in-memory router database.
"""

import threading
from http.server import ThreadingHTTPServer

import pytest

from core.server import SovereignHTTPHandler, create_app

# The ALM-1003 dossier's HAS_DIAGRAM entries as the live server returned them on 15 Oct (two figures, ten entries).
ALM1003_DIAGRAMS = [
    "ALM-1003 Figure 1 Root alarm",
    "ALM-1003 Figure 2 Alarm mechanism",
    "Figure 1 Root alarm diagram (en-us_image_0269895191.png)",
    "Figure 2 Alarm mechanism ladder diagram (en-us_image_0269895193.png)",
    "archive:///docs/USC 26.1.0.zip!USC.hwics#resources/alarm_cgplite/alarms/../../public_sys-resources/caution_3.0-en-us.png",
    "archive:///docs/USC 26.1.0.zip!USC.hwics#resources/alarm_cgplite/alarms/figure/en-us_image_0269895191.png",
    "archive:///docs/USC 26.1.0.zip!USC.hwics#resources/alarm_cgplite/alarms/figure/en-us_image_0269895193.png",
    "archive:///docs/UPCF 26.1.0.zip!UPCF.hwics#resources/csp/alarm_cgplite/alarms/../../../public_sys-resources/caution_3.0-en-us.png",
    "archive:///docs/UPCF 26.1.0.zip!UPCF.hwics#resources/csp/alarm_cgplite/alarms/figure/en-us_image_0269895191.png",
    "archive:///docs/UPCF 26.1.0.zip!UPCF.hwics#resources/csp/alarm_cgplite/alarms/figure/en-us_image_0269895193.png",
]


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    create_app(router_db_path=":memory:", wiki_dir=str(tmp_path_factory.mktemp("wiki")))
    server = ThreadingHTTPServer(("127.0.0.1", 0), SovereignHTTPHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _page(browser, base, width):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors: list = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{base}/portal", wait_until="load")
    return page, errors


def test_banner_says_what_produced_the_answer(base, browser):
    page, errors = _page(browser, base, 1440)
    try:
        label = lambda m: page.evaluate("m => answerModeLabel(m)", m)
        assert label("extractive_template_fallback") == "Extractive Answer · No LLM"
        assert label("neural_llama_cpp_local") == "Local LLM Summary"
        assert label("epistemic_refusal") == "Refused: Low Confidence"
        assert "LLM Summary" not in label(None)
        assert errors == []
    finally:
        page.close()


def test_u5_each_figure_once_labelled_by_caption(base, browser):
    page, errors = _page(browser, base, 1440)
    try:
        figures = page.evaluate("names => dedupeDiagrams(names.map(n => ({name: n})), 'ALM-1003')", ALM1003_DIAGRAMS)
        assert [f["label"] for f in figures] == ["Figure 1 Root alarm", "Figure 2 Alarm mechanism"]
        assert all("en-us_image" in f["title"] for f in figures)  # the raw names stay in the tooltip
        assert errors == []
    finally:
        page.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_u4_dossier_pills_stay_inside_the_card(base, browser, width):
    page, errors = _page(browser, base, width)
    try:
        page.evaluate(
            """names => renderGraphDossier({
                 entity: {name: 'ALM-1003'},
                 neighbors: names.map(n => ({name: n})),
                 by_relation: {
                   HAS_DIAGRAM: names.map(n => ({name: n})),
                   MEASURED_BY_COUNTER: [{name: 'A_VERY_LONG_COUNTER_NAME_WITHOUT_ANY_BREAK_OPPORTUNITY_1526727001_EXTRA'}],
                 }})""",
            ALM1003_DIAGRAMS,
        )
        pills = page.locator("#graph-dossier-container .entity-pill")
        assert pills.count() == 3  # 2 figures + 1 counter
        overflow = page.evaluate("""() => Array.from(document.querySelectorAll('#graph-dossier-container .entity-pill'))
            .map(p => p.getBoundingClientRect().right - p.closest('.relation-box').getBoundingClientRect().right)""")
        assert max(overflow) <= 1, overflow
        assert errors == []
    finally:
        page.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_u7_placeholder_ends_before_the_controls(base, browser, width):
    page, errors = _page(browser, base, width)
    try:
        gap = page.evaluate("""() => {
            const input = document.getElementById('portal-query-input');
            const r = input.getBoundingClientRect();
            const textRight = r.right - parseFloat(getComputedStyle(input).paddingRight);
            const lefts = ['.btn-clear-query', '.kbd-shortcut-badge']
              .map(s => document.querySelector(s))
              .filter(el => el && getComputedStyle(el).display !== 'none')
              .map(el => el.getBoundingClientRect().left);
            return Math.min(...lefts) - textRight;
        }""")
        assert gap >= 0, f"text area runs {-gap:.0f} px under the controls"
        assert errors == []
    finally:
        page.close()


def test_u6_fit_keeps_nodes_below_the_status_box(base, browser):
    page, errors = _page(browser, base, 1440)
    try:
        # The fit maths on a stand-in renderer (no WebGL needed): 5 nodes, a 60 px overlay band at the top.
        top_y = page.evaluate("""() => {
            const fake = { n: 5, w: 800, h: 500, insetTop: () => 60,
              pos: new Float32Array([0,0,0, 100,40,0, -80,90,0, 30,-70,0, 60,95,0]),
              cam2: { cx: 0, cy: 0, scale: 1, fit: 1 }, cam3: { tx: 0, ty: 0, tz: 0, r: 1, fit: 1 },
              requestRender() {}, _emitView() {} };
            AegisGraphGL.prototype.fit.call(fake, false);
            const c = fake.cam2; let minScreenY = Infinity, maxScreenY = -Infinity;
            for (let i = 0; i < fake.n; i++) {
              const y = fake.h / 2 - (fake.pos[i * 3 + 1] - c.cy) * c.scale;
              minScreenY = Math.min(minScreenY, y); maxScreenY = Math.max(maxScreenY, y);
            }
            return [minScreenY, maxScreenY];
        }""")
        assert top_y[0] >= 60, top_y  # the top node sits below the overlay band
        assert top_y[1] <= 500, top_y
        assert errors == []
    finally:
        page.close()
