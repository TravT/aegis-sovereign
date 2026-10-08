"""Playwright live verification for ancestor sibling retention and 3D relational graph connections."""

import time
import urllib.parse
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8765"

def verify_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # =====================================================================
        # 1. HIERARCHY TREE ANCESTOR SIBLING RETENTION TEST
        # =====================================================================
        print("\n--- 1. Testing Deep Tree Ancestor Sibling Retention ---")
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Deep article: "Services Management" under USC Commands
        deep_topic_id = "USC:CONCEPT_0234031539"
        url = f"{BASE_URL}/archive/view?package=USC&topic_id={urllib.parse.quote(deep_topic_id)}"
        print(f"Navigating to deep article: {url}")
        page.goto(url)
        page.wait_for_selector(".hierarchy-sidebar", timeout=12000)

        # Allow lazy tree rendering
        page.wait_for_timeout(1500)

        # Verify ancestor sibling folders are present in the sidebar
        sidebar_text = page.locator(".hierarchy-sidebar").inner_text()
        print("Checking sibling categories in sidebar...")

        # Siblings of Operation and Maintenance Commands (under Commands)
        assert "Machine-Machine Commands" in sidebar_text, "Sibling 'Machine-Machine Commands' missing under Commands"
        assert "Engineering Commands" in sidebar_text, "Sibling 'Engineering Commands' missing under Commands"
        print("  ✓ Sibling command folders under Commands are present!")

        # Siblings of USC Operation and Maintenance Commands
        assert "USCDB Operation and Maintenance Commands" in sidebar_text or "Operation and Maintenance Commands" in sidebar_text
        print("  ✓ Intermediate ancestor subcategories are present!")

        # Siblings of Services Management (under USC O&M Commands)
        assert "Framework Management" in sidebar_text, "Sibling 'Framework Management' missing under USC O&M Commands"
        assert "DBS Management" in sidebar_text, "Sibling 'DBS Management' missing under USC O&M Commands"
        print("  ✓ Sibling groups under USC O&M Commands are present!")

        # Active article
        assert "Services Management" in sidebar_text, "Active topic 'Services Management' missing in sidebar"
        print("  ✓ Active topic 'Services Management' is present!")

        # Take screenshot of restored hierarchy sidebar
        page.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_ancestor_siblings_restored.png")
        print("Saved verified_ancestor_siblings_restored.png")

        # =====================================================================
        # 2. 3D WEBGL GRAPH VIEW WITH RELATIONAL EDGES TEST
        # =====================================================================
        print("\n--- 2. Testing 3D WebGL Graph with Relational Edges ---")
        page_graph = context.new_page()
        portal_url = f"{BASE_URL}/portal/#/graph"
        print(f"Navigating to: {portal_url}")
        page_graph.goto(portal_url)
        page_graph.wait_for_selector("#gv-canvas", timeout=15000)

        # Verify edge control checkboxes
        edges_box = page_graph.locator("#gv-edges")
        eco_box = page_graph.locator("#gv-edges-ecosystem")
        rel_box = page_graph.locator("#gv-edges-relational")

        assert edges_box.is_visible(), "Hierarchy edges checkbox missing"
        assert eco_box.is_visible(), "Family Backbone edges checkbox missing"
        assert rel_box.is_visible(), "Relational Bridges edges checkbox missing"
        assert eco_box.is_checked(), "Family Backbone should be checked by default"
        assert rel_box.is_checked(), "Relational Bridges should be checked by default"
        print("  ✓ Edge control checkboxes (Hierarchy, Family Backbone, Relational Bridges) are verified!")

        # Switch to 3D mode
        print("Switching to 3D mode...")
        dim3_btn = page_graph.locator("#gv-dim3")
        dim3_btn.click()
        page_graph.wait_for_timeout(2000)

        # Verify node status
        status_text = page_graph.locator("#gv-status").inner_text()
        print(f"Graph status: '{status_text}'")
        assert "nodes" in status_text.lower(), f"Unexpected status: {status_text}"

        # Capture desktop 3D graph with relational backbone
        page_graph.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_3d_relational_graph.png")
        print("Saved verified_3d_relational_graph.png")

        # Search for a package node or entity to inspect relational connections in Inspector
        print("Testing search and Node Inspector relational connections...")
        search_box = page_graph.locator("#gv-search")
        search_box.fill("UPCF")
        page_graph.wait_for_selector(".gv-result", timeout=8000)
        results = page_graph.locator(".gv-result")
        print(f"Found {results.count()} search results for 'UPCF'. Clicking first...")
        results.first.click()
        page_graph.wait_for_timeout(1500)

        # Verify inspector details
        inspector = page_graph.locator("#graph-node-details")
        assert inspector.is_visible(), "Inspector card not visible"
        inspector_text = inspector.inner_text()
        print(f"Inspector snippet:\n{inspector_text[:300]}...")

        # Check for relational connection headings
        has_relational = any(h in inspector_text for h in ["Product Family", "5G Core Network Peer", "Functional Bridge", "Shared", "Connections"])
        print(f"Relational connections listed: {has_relational}")
        assert has_relational, "Expected relational connection info in inspector"

        page_graph.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_node_inspector_relational.png")
        print("Saved verified_node_inspector_relational.png")

        # =====================================================================
        # 3. MOBILE VIEWPORT TEST
        # =====================================================================
        print("\n--- 3. Testing Mobile Layout (390x844) ---")
        mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        page_mobile = mobile_context.new_page()
        page_mobile.goto(portal_url)
        page_mobile.wait_for_selector("#gv-canvas", timeout=15000)
        page_mobile.wait_for_timeout(2000)

        page_mobile.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_mobile_relational_graph.png")
        print("Saved verified_mobile_relational_graph.png")

        browser.close()
        print("\nAll Playwright live verifications PASSED successfully!")

if __name__ == "__main__":
    verify_all()
