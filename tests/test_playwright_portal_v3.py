"""Playwright E2E UX verification for Portal v3 items A through E."""

import os
import sys
import time
import threading
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from core.server import SovereignHTTPHandler, create_app
from core.server.constants import DEFAULT_ROUTER_DB, DEFAULT_GRAPH_DB

WIKI_DIR = "/home/tlima/Enterprise_Hub/docs/wiki"
ROUTER_DB = str(DEFAULT_ROUTER_DB)
GRAPH_DB = str(DEFAULT_GRAPH_DB)


def run_e2e_tests():
    # Spin up server with actual vault & wiki
    app = create_app(
        router_db_path=ROUTER_DB if os.path.exists(ROUTER_DB) else None,
        wiki_dir=WIKI_DIR if os.path.exists(WIKI_DIR) else None,
    )
    SovereignHTTPHandler.manager = app
    server = ThreadingHTTPServer(("127.0.0.1", 8799), SovereignHTTPHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = "http://127.0.0.1:8799"
    time.sleep(1.0)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # -------------------------------------------------------------
            # 1. Desktop Test (1440x900)
            # -------------------------------------------------------------
            print("--- Testing Desktop Viewport (1440x900) ---")
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.on("console", lambda msg: print(f"BROWSER LOG: {msg.text}"))
            page.on("pageerror", lambda err: print(f"BROWSER ERROR: {err}"))

            # Open portal
            page.goto(f"{base_url}/portal")
            page.wait_for_selector("#portal-query-input")

            # Search Homelab Wiki document
            print("Searching for 'MOC_projects'...")
            page.fill("#portal-query-input", "MOC_projects")
            page.locator("#portal-search-btn").click()
            page.wait_for_selector(".source-card", timeout=10000)

            # Verify Item C & D: Glassmorphic Breadcrumbs & Meta Pills
            breadcrumbs = page.locator(".card-breadcrumb-bar")
            assert breadcrumbs.count() > 0, "No breadcrumb bars rendered"
            first_bc = breadcrumbs.first.inner_text()
            print(f"Breadcrumb text: {first_bc}")
            assert "Homelab Wiki" in first_bc or "projects" in first_bc

            # Verify Item E: Ambient Knowledge Mesh
            page.wait_for_selector(".ambient-mesh-card", timeout=8000)
            mesh_canvas = page.locator("#ambient-mesh-canvas")
            assert mesh_canvas.is_visible(), "Ambient mesh canvas is not visible"
            print("Ambient Knowledge Mesh card and canvas verified.")

            # Open slide-over drawer for MOC_projects
            drawer_btn = page.locator(".action-btn:has-text('Side Drawer')").first
            drawer_btn.click()
            page.wait_for_selector(".inspector-drawer.open", timeout=4000)
            page.wait_for_selector("#inspector-content.inspector-content-rendered", timeout=8000)

            # Verify Item B: Context-aware tabs (Homelab Wiki should NOT have alarm buttons)
            tabs_text = page.locator("#inspector-section-tabs").inner_text()
            print(f"Inspector tabs for Homelab Wiki: {tabs_text}")
            assert "Possible Causes" not in tabs_text, "Telecom alarm tab leaked into Homelab Wiki!"
            assert "Signaling Diagram" not in tabs_text, "Diagram tab leaked into Homelab Wiki!"
            assert "Full Document" in tabs_text or "Full Entry" in tabs_text

            # Verify Item A: Clickable markdown links inside inspector
            page.wait_for_selector("#inspector-content a.internal-wiki-link", timeout=5000)
            wiki_links = page.locator("#inspector-content a.internal-wiki-link")
            print(f"Found {wiki_links.count()} internal wiki links in drawer.")
            assert wiki_links.count() > 0, "No internal wiki links parsed in drawer content"

            # Click a link inside the drawer
            first_link = wiki_links.first
            link_href = first_link.get_attribute("href")
            link_text = first_link.inner_text()
            print(f"Clicking wiki link: '{link_text}' -> {link_href}")
            first_link.click()
            time.sleep(1.0)

            # Check that drawer updated and back button is visible
            back_btn = page.locator(".inspector-tab.back-btn")
            assert back_btn.is_visible(), "Back button did not appear after following drawer link"
            print("Drawer transitioned smoothly to linked document with back navigation!")

            # Close drawer before starting next search
            page.locator(".drawer-close-btn").click()
            time.sleep(0.5)

            # -------------------------------------------------------------
            # 2. Telecom Alarm Test (ALM-20104)
            # -------------------------------------------------------------
            print("\n--- Testing Telecom Alarm Archetype (ALM-20104) ---")
            page.fill("#portal-query-input", "ALM-20104")
            with page.expect_response("**/router/query"):
                page.locator("#portal-search-btn").click()
            time.sleep(0.5)
            page.wait_for_selector(".source-card", timeout=8000)

            alarm_bc = page.locator(".card-breadcrumb-bar").first.inner_text()
            print(f"Alarm Breadcrumb: {alarm_bc}")
            assert "Telecom" in alarm_bc or "Alarms" in alarm_bc or "20104" in alarm_bc

            # Open drawer on ALM-20104
            with page.expect_response("**/archive/inspect"):
                page.locator(".action-btn:has-text('Side Drawer')").first.click()
            page.wait_for_selector(".inspector-drawer.open", timeout=4000)
            page.wait_for_selector("#inspector-section-tabs button:has-text('Possible Causes')", timeout=6000)

            alarm_tabs = page.locator("#inspector-section-tabs").inner_text()
            print(f"Alarm inspector tabs: {alarm_tabs}")
            assert "Possible Causes" in alarm_tabs, "Missing Possible Causes tab on telecom alarm"
            assert "Procedure" in alarm_tabs, "Missing Procedure tab on telecom alarm"

            # Close drawer before mobile test
            page.locator(".drawer-close-btn").click()
            time.sleep(0.5)

            # -------------------------------------------------------------
            # 3. Mobile Viewport Test (390x844)
            # -------------------------------------------------------------
            print("\n--- Testing Mobile Viewport (390x844) ---")
            mobile_context = browser.new_context(viewport={"width": 390, "height": 844})
            mobile_page = mobile_context.new_page()
            mobile_page.goto(f"{base_url}/portal")
            mobile_page.wait_for_selector("#portal-query-input")

            # Check search input box size
            input_box = mobile_page.locator("#portal-query-input").bounding_box()
            print(f"Mobile search input width: {input_box['width']}px (must be > 300px)")
            assert input_box["width"] > 300, f"Mobile input squished! width: {input_box['width']}px"

            # Check drawer width on mobile
            mobile_page.fill("#portal-query-input", "MOC_projects")
            with mobile_page.expect_response("**/router/query"):
                mobile_page.locator("#portal-search-btn").click()
            time.sleep(0.5)
            mobile_page.wait_for_selector(".source-card", timeout=8000)
            mobile_page.locator(".action-btn:has-text('Side Drawer')").first.click()
            mobile_page.wait_for_selector("#source-inspector-drawer.open", timeout=4000)

            drawer_box = mobile_page.locator("#source-inspector-drawer").bounding_box()
            print(f"Mobile drawer width: {drawer_box['width']}px")
            assert drawer_box["width"] >= 380, f"Drawer not full width on mobile: {drawer_box['width']}"

            context.close()
            mobile_context.close()
            browser.close()

            print("\nALL PORTAL V3 UX & AMBIENT GRAPH TESTS PASSED CLEANLY!")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run_e2e_tests()
