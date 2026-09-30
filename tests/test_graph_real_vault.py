"""Smoke test of the graph viewer against the real vault (skipped where there is none).

Expected numbers come from independent SQL counts, never from the service itself."""

import gzip
import json
import sqlite3
import time

import pytest

from core.graphview import GraphService
from core.graphview.policy import ENTITY_TYPES
from core.server.constants import DEFAULT_GRAPH_DB, DEFAULT_ROUTER_DB, DEFAULT_WIKI_DIR

pytestmark = pytest.mark.skipif(
    not DEFAULT_ROUTER_DB.exists() or DEFAULT_ROUTER_DB.stat().st_size == 0,
    reason="no real vault on this machine",
)


def _scalar(sql, db=DEFAULT_ROUTER_DB):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


@pytest.fixture(scope="module")
def svc():
    try:
        _scalar("SELECT count(*) FROM topic_nodes")
    except sqlite3.Error:
        pytest.skip("the vault has no topic tree yet")
    return GraphService(str(DEFAULT_ROUTER_DB), str(DEFAULT_GRAPH_DB), wiki_dir=str(DEFAULT_WIKI_DIR) if DEFAULT_WIKI_DIR else None)


def test_every_topic_of_the_real_tree_is_reachable_and_placed_apart(svc):
    started = time.time()
    res = svc.slice("tree", "restricted", mode="all")
    assert time.time() - started < 15  # first build of ~45k nodes, layout included

    topics = _scalar("SELECT count(*) FROM topic_nodes")
    packages = _scalar("SELECT count(DISTINCT package) FROM topic_nodes")
    assert len(res["nodes"]["id"]) == topics + packages
    assert len(res["edges"]["s"]) == _scalar("SELECT count(*) FROM topic_edges")  # roots link to their package

    n = res["nodes"]
    assert len(set(zip(n["x"], n["y"]))) == len(n["id"])
    assert len(set(zip(n["x3"], n["y3"], n["z3"]))) == len(n["id"])

    raw = json.dumps(res, separators=(",", ":")).encode()
    assert len(gzip.compress(raw)) < 3_000_000  # the "show all" payload stays well under 3 MB on the wire


def test_a_lower_clearance_sees_fewer_or_equal_nodes_and_no_orphan_edges(svc):
    sizes = [len(svc.slice("tree", level, mode="all")["nodes"]["id"]) for level in ("public", "internal", "restricted")]
    assert sizes == sorted(sizes)
    res = svc.slice("tree", "public", mode="all")
    assert all(0 <= i < len(res["nodes"]["id"]) for i in res["edges"]["s"] + res["edges"]["t"])


def test_default_clustered_view_is_small_enough_to_open_instantly(svc):
    res = svc.slice("tree", "restricted")
    assert 0 < len(res["nodes"]["id"]) < 5000


def test_entity_layer_holds_only_allowed_types_and_no_personal_data(svc):
    res = svc.slice("entity", "restricted")
    assert {theme for theme in res["nodes"]["theme"]} <= set(ENTITY_TYPES)
    labels = " ".join(res["nodes"]["label"])
    assert "R$" not in labels  # monetary amounts from the paperless corpus


def test_wiki_layer_covers_every_note_that_exists(svc):
    if not DEFAULT_WIKI_DIR:
        pytest.skip("no wiki directory")
    notes = len([p for p in DEFAULT_WIKI_DIR.rglob("*.md") if not any(x.startswith(".") for x in p.relative_to(DEFAULT_WIKI_DIR).parts)])
    assert len(svc.slice("wiki", "restricted")["nodes"]["id"]) == notes
