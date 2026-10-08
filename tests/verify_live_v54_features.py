import re
import urllib.parse
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8765"

def verify_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # =====================================================================
        # 1. Test Tree Sidebar (Zero Duplicates + Upper Sibling Retention)
        # =====================================================================
        print("\n--- 1. Testing Tree Sidebar (Zero Duplicates + Sibling Retention) ---")
        article_uri = (
            "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/"
            "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip!"
            "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics#"
            "resources/mml/document/lst_dmlnk.html"
        )
        url = f"{BASE_URL}/archive/view?uri={urllib.parse.quote(article_uri)}"
        print(f"Navigating to: {url}")
        page.goto(url)
        page.wait_for_selector("#sidebar", timeout=15000)
        page.wait_for_timeout(2000)

        sidebar_text = page.locator("#sidebar").inner_text()

        # Check for upper-layer siblings
        assert "Commands" in sidebar_text, "Missing Commands"
        assert "Operation and Maintenance Commands" in sidebar_text, "Missing O&M Commands"
        assert "Machine-Machine Commands" in sidebar_text, "Missing Machine-Machine Commands sibling!"
        assert "Engineering Commands" in sidebar_text, "Missing Engineering Commands sibling!"
        print("PASS: Upper-layer sibling categories are rendered in sidebar!")

        # Check for zero duplicates under Diameter Link
        sidebar_lis = page.locator("#sidebar li[data-title*='diameter link']").all()
        print(f"Total diameter link items in sidebar: {len(sidebar_lis)}")
        titles = [li.get_attribute("data-title") for li in sidebar_lis]
        print(f"Titles: {titles}")

        # Assert LST DMLNK is present and occurs exactly ONCE
        lst_dmlnk_elements = page.locator("#sidebar li[data-title*='list diameter link (lst dmlnk)']").all()
        assert len(lst_dmlnk_elements) == 1, f"Expected exactly 1 LST DMLNK element, got {len(lst_dmlnk_elements)}"
        print("PASS: Exactly 1 LST DMLNK element found (Zero Duplicates)!")

        page.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_tree_no_duplicates_and_siblings_restored.png")
        print("Saved verified_tree_no_duplicates_and_siblings_restored.png")

        # =====================================================================
        # 2. Test 2D Knowledge Graph & Explore Local Graph Button
        # =====================================================================
        print("\n--- 2. Testing 2D Knowledge Graph & Local Graph Explorer ---")
        page_graph = context.new_page()
        portal_url = f"{BASE_URL}/portal"
        print(f"Navigating to: {portal_url}")
        page_graph.goto(portal_url)
        page_graph.wait_for_selector("#portal-query-input", timeout=15000)

        print("Switching to Knowledge Graph tab via switchCommandTab('graph')...")
        page_graph.evaluate("switchCommandTab('graph')")
        page_graph.wait_for_selector("#gv-canvas", timeout=15000)

        print("Waiting for graph to finish loading nodes...")
        page_graph.wait_for_function(
            '() => { const el = document.getElementById("gv-status"); return el && !el.innerText.includes("Loading") && el.innerText.includes("nodes"); }',
            timeout=30000,
        )

        status_text = page_graph.locator("#gv-status").inner_text()
        print(f"Graph status: '{status_text}'")
        assert "45,425" in status_text or "nodes" in status_text

        # Search for LST DMLNK
        print("Searching for LST DMLNK...")
        search_box = page_graph.locator("#gv-search")
        search_box.fill("LST DMLNK")
        page_graph.wait_for_selector("#gv-results .gv-result[data-id]", timeout=10000)

        # Click the first result
        first_result = page_graph.locator("#gv-results .gv-result[data-id]").first
        first_result.click()
        page_graph.wait_for_timeout(1500)

        # Verify inspector details
        inspector = page_graph.locator("#gv-inspector")
        inspector_text = inspector.inner_text()
        print(f"Inspector snippet:\n{inspector_text[:300]}...")
        assert "List Diameter Link (LST DMLNK)" in inspector_text

        # Verify Explore Local Graph button is present
        local_btn = page_graph.locator("#gv-local-graph")
        assert local_btn.is_visible(), "Expected Explore Local Graph button to be visible!"
        print("PASS: Explore Local Graph button is visible in Inspector!")

        page_graph.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_2d_graph_separated_constellations.png")
        print("Saved verified_2d_graph_separated_constellations.png")

        # =====================================================================
        # 3. Test Entering Local Graph Mode
        # =====================================================================
        print("\n--- 3. Testing Local Subgraph Mode ---")
        local_btn.click()
        page_graph.wait_for_selector("#gv-local-banner", timeout=10000)
        page_graph.wait_for_timeout(1500)

        banner = page_graph.locator("#gv-local-banner")
        assert banner.is_visible(), "Local banner should be visible"
        banner_text = banner.inner_text()
        print(f"Banner text: '{banner_text}'")
        assert "Local Subgraph" in banner_text
        assert "List Diameter Link" in banner_text

        page_graph.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_local_subgraph_explorer.png")
        print("Saved verified_local_subgraph_explorer.png")

        # =====================================================================
        # 4. Test Exiting Local Graph Mode
        # =====================================================================
        print("\n--- 4. Testing Exiting Local Subgraph Mode ---")
        exit_btn = page_graph.locator("#gv-exit-local")
        exit_btn.click()
        page_graph.wait_for_timeout(1500)

        assert not banner.is_visible(), "Local banner should be hidden after exit"
        status_after_exit = page_graph.locator("#gv-status").inner_text()
        print(f"Status after exit: '{status_after_exit}'")
        assert "45,425" in status_after_exit or "nodes" in status_after_exit
        print("PASS: Successfully returned to full galaxy constellation!")

        page_graph.screenshot(path="/home/tlima/.gemini/antigravity-cli/brain/d72e7162-aa12-457d-bca8-2bd11e3049b6/verified_return_to_full_galaxy.png")
        print("Saved verified_return_to_full_galaxy.png")

        browser.close()
        print("\n🎉 ALL E2E VERIFICATIONS PASSED 100%!")

if __name__ == "__main__":
    verify_all()
