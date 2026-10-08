"""Playwright live verification for embedded documents, hierarchy depth, and 2D/3D graph UI."""

import time
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8765"

def verify_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # =====================================================================
        # 1. EMBEDDED DOCUMENT TEST (UPCF Communication Matrix)
        # =====================================================================
        print("\n--- 1. Testing Embedded Document in HedEx Article ---")
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        article_uri = (
            "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/"
            "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).zip!"
            "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).hwics#"
            "resources/upcc/description/function_desc/security_desc/cn_90_13_000065.html"
        )
        import urllib.parse
        url = f"{BASE_URL}/archive/view?uri={urllib.parse.quote(article_uri)}"
        print(f"Navigating to: {url}")
        page.goto(url)
        page.wait_for_selector(".embedded-attachment-plate", timeout=10000)

        plate = page.locator(".embedded-attachment-plate").first
        assert plate.is_visible(), "Embedded attachment plate not visible"
        plate_title = plate.locator(".attachment-plate-title").inner_text()
        print(f"Plate title: '{plate_title}'")
        assert "Communication Matrix" in plate_title, f"Unexpected title: {plate_title}"

        preview_btn = plate.locator("a.preview-btn")
        download_btn = plate.locator("a.download-btn")
        assert preview_btn.is_visible(), "Preview button missing"
        assert download_btn.is_visible(), "Download button missing"
        print(f"Preview URL: {preview_btn.get_attribute('href')}")
        print(f"Download URL: {download_btn.get_attribute('href')}")

        page.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_embedded_attachment_plate.png")
        print("Saved verified_embedded_attachment_plate.png")

        # Click View Online
        print("Clicking '👁️ View Online'...")
        preview_btn.click()
        page.wait_for_selector(".sheet-viewer-controls", timeout=10000)
        hero_title = page.locator(".doc-hero-title").inner_text()
        print(f"Spreadsheet viewer opened: '{hero_title}'")
        assert "communication_matrix" in hero_title.lower(), f"Unexpected hero title: {hero_title}"

        tabs = page.locator(".sheet-tab-btn")
        print(f"Found {tabs.count()} sheet tabs.")
        assert tabs.count() > 0, "No sheet tabs found"
        for i in range(min(tabs.count(), 4)):
            print(f"  Sheet {i+1}: {tabs.nth(i).inner_text()}")

        page.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_embedded_excel_viewer.png")
        print("Saved verified_embedded_excel_viewer.png")

        # =====================================================================
        # 2. HIERARCHY DEPTH & TREE EXPANSION TEST
        # =====================================================================
        print("\n--- 2. Testing Tree Depth & Hierarchy Expansion in Sidebar ---")
        alarm_uri = (
            "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/"
            "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).zip!"
            "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).hwics#"
            "resources/alarms/100001.html"
        )
        alarm_url = f"{BASE_URL}/archive/view?uri={urllib.parse.quote(alarm_uri)}"
        page.goto(alarm_url)
        page.wait_for_selector("#sidebar", timeout=10000)
        sidebar = page.locator("#sidebar")
        assert sidebar.is_visible(), "Viewer sidebar not visible"

        # Look for tree nodes
        tree_nodes = page.locator(".tree-node")
        print(f"Rendered sidebar topics in Alarm Handling manual: {tree_nodes.count()}")
        assert tree_nodes.count() > 50, f"Too few sidebar topics rendered: {tree_nodes.count()}"

        # Check toggle buttons
        toggles = page.locator(".node-toggle")
        print(f"Interactive folder toggles: {toggles.count()}")
        if toggles.count() > 0:
            first_toggle = toggles.first
            first_toggle.click()
            time.sleep(0.5)
            print("Successfully clicked folder toggle in sidebar.")

        page.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_hierarchy_tree_sidebar.png")
        print("Saved verified_hierarchy_tree_sidebar.png")

        # =====================================================================
        # 3. KNOWLEDGE GRAPH EXPLORER (2D / 3D & FULL WEB) - DESKTOP
        # =====================================================================
        print("\n--- 3. Testing 2D/3D Knowledge Graph Explorer (Desktop 1440x900) ---")
        page.goto(f"{BASE_URL}/portal")
        page.wait_for_selector("#portal-query-input")
        print("Switching to Knowledge Graph tab via switchCommandTab('graph')...")
        page.evaluate("switchCommandTab('graph')")
        page.wait_for_selector(".graph-workspace", timeout=8000)

        # Verify #gv-showall is checked by default
        showall_cb = page.locator("#gv-showall")
        assert showall_cb.is_checked(), "Full Article Web (45k) should be checked by default!"
        print("Verified: Full Article Web (45k) is checked by default.")

        # Wait for graph nodes to finish loading
        print("Waiting for graph to finish loading nodes...")
        page.wait_for_function(
            '() => { const el = document.getElementById("gv-status"); return el && !el.innerText.includes("Loading") && el.innerText.includes("nodes"); }',
            timeout=30000,
        )
        status_text = page.locator("#gv-status").inner_text()
        print(f"Graph Status Ready: '{status_text}'")

        # Test selecting a node via search
        search_input = page.locator("#gv-search")
        search_input.fill("UPCF")
        page.wait_for_selector(".gv-result:not(.none)", timeout=8000)
        results = page.locator(".gv-result:not(.none)")
        print(f"Search results for 'UPCF': {results.count()}")
        results.first.click()
        time.sleep(1.0)

        # Verify Inspector Card styling
        inspector = page.locator(".gv-inspector-card")
        assert inspector.is_visible(), "Inspector card not visible"

        node_title = page.locator(".gv-node-title").inner_text()
        print(f"Selected Node in Inspector: '{node_title}'")
        assert len(node_title) > 0, "Empty node title"

        # Check facts table contrast & format
        facts = page.locator(".gv-facts tr")
        print(f"Facts table rows: {facts.count()}")
        assert facts.count() > 0, "No facts rendered"
        for i in range(facts.count()):
            row_text = facts.nth(i).inner_text().replace("\n", ": ")
            print(f"  Fact: {row_text}")

        # Check action buttons
        actions = page.locator(".gv-actions .action-btn")
        print(f"Action buttons rendered: {actions.count()}")
        assert actions.count() >= 2, "Missing action buttons"
        for i in range(actions.count()):
            print(f"  Button: '{actions.nth(i).inner_text().strip()}'")

        page.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_graph_desktop_inspector.png")
        print("Saved verified_graph_desktop_inspector.png")

        # Test 3D Mode
        print("Switching to 3D mode...")
        page.locator("#gv-dim3").click()
        time.sleep(1.0)
        dim3_btn = page.locator("#gv-dim3")
        assert "active" in dim3_btn.get_attribute("class"), "3D mode button not active"
        print("3D mode active.")
        page.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_graph_3d_desktop.png")
        print("Saved verified_graph_3d_desktop.png")

        context.close()

        # =====================================================================
        # 4. KNOWLEDGE GRAPH EXPLORER - MOBILE VIEWPORT (390x844)
        # =====================================================================
        print("\n--- 4. Testing Knowledge Graph Explorer (Mobile 390x844) ---")
        mobile_context = browser.new_context(viewport={"width": 390, "height": 844})
        mobile_page = mobile_context.new_page()

        mobile_page.goto(f"{BASE_URL}/portal")
        mobile_page.wait_for_selector("#portal-query-input")
        mobile_page.evaluate("switchCommandTab('graph')")
        mobile_page.wait_for_selector(".graph-workspace", timeout=8000)

        # Check canvas stage dimensions on mobile
        stage_box = mobile_page.locator(".gv-stage").bounding_box()
        print(f"Mobile Stage size: {stage_box['width']}x{stage_box['height']}px")
        assert stage_box["width"] > 340, "Mobile stage width squished"
        assert stage_box["height"] >= 360, "Mobile stage height too short"

        # Check zoom controls
        zoom_in = mobile_page.locator("#gv-zoom-in").bounding_box()
        print(f"Mobile zoom button size: {zoom_in['width']}x{zoom_in['height']}px (must be >= 36px for touch)")
        assert zoom_in["width"] >= 36 and zoom_in["height"] >= 36, "Zoom button too small for touch"

        # Check inspector card below stage
        mobile_page.wait_for_selector(".gv-inspector-card")
        inspector_box = mobile_page.locator(".gv-inspector-card").bounding_box()
        print(f"Mobile Inspector size: {inspector_box['width']}x{inspector_box['height']}px")
        assert inspector_box["width"] > 340, "Mobile inspector squished"
        assert inspector_box["y"] >= stage_box["y"] + stage_box["height"] - 5, "Inspector not stacked below stage!"

        mobile_page.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_graph_mobile_layout.png")
        print("Saved verified_graph_mobile_layout.png")

        mobile_context.close()
        browser.close()

        print("\n=======================================================")
        print("ALL LIVE VERIFICATION TESTS PASSED SUCCESSFULLY (100%)!")
        print("=======================================================\n")

if __name__ == "__main__":
    verify_all()
