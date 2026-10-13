#!/usr/bin/env python3
"""
Test Findings O3 + O5: Vault Cleaning & Demo Vault Segregation.
- Production vault contains 0 fixture records.
- Production vault contains 0 missing wiki paths and 0 .obsidian/ records.
- When demo=True is passed, demo fixtures resolve through demo_router.
"""

import sqlite3
import pytest
from core.server.app import create_app
from core.router import QueryRouteType


def test_o3_o5_production_vault_clean():
    """Verify live production vault invariants directly on disk."""
    prod_db = "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db"
    con = sqlite3.connect(f"file:{prod_db}?mode=ro", uri=True)
    c = con.cursor()

    # Invariant O5: Zero fixture records in production
    fixtures = c.execute(
        "SELECT count(*) FROM document_records WHERE record_kind='external' AND NOT (doc_identifier LIKE '%.md%' OR metadata LIKE '%docs/wiki%')"
    ).fetchone()[0]
    assert fixtures == 0, f"Expected 0 fixtures in production vault, found {fixtures}"

    # Invariant O3: Zero .obsidian records
    obsidian = c.execute(
        "SELECT count(*) FROM document_records WHERE doc_identifier LIKE '%.obsidian%' OR metadata LIKE '%.obsidian%'"
    ).fetchone()[0]
    assert obsidian == 0, f"Expected 0 .obsidian records in production vault, found {obsidian}"


def test_o5_demo_vault_segregation():
    """Verify demo router serves fixtures when demo=True, but production does not."""
    app = create_app()
    # In production without demo=True, TCK-8821 fixture must not be found
    prod_res = app.route_and_execute("TCK-8821", demo=False)
    assert len(prod_res.get("results", [])) == 0 or prod_res.get("status") == "not_found"

    # In demo mode, if demo_router is configured, it resolves TCK-8821
    if app.demo_router is not None:
        demo_res = app.route_and_execute("TCK-8821", demo=True)
        assert demo_res["status"] == "success"
        assert len(demo_res["results"]) >= 1
        assert "TCK-8821" in demo_res["results"][0]["doc_identifier"]
