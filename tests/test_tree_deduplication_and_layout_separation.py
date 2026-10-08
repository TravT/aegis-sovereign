import sqlite3
import math
import pytest
from pathlib import Path
from core.server.app import SovereignApplianceManager
from core.graphview.layout import radial_layout

VAULT_ROUTER_DB = Path("/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db")

@pytest.mark.skipif(not VAULT_ROUTER_DB.exists(), reason="Vault sovereign_router.db required")
def test_tree_deduplication():
    server = SovereignApplianceManager(
        router_db_path=str(VAULT_ROUTER_DB),
    )

    # 1. Test get_package_bookmap_tree for LST DMLNK
    dmlnk_topic_id = "USC:MMLREF_0311943589"
    tree = server.get_package_bookmap_tree(package="USC", topic_id=dmlnk_topic_id)
    assert tree is not None
    assert tree["active_topic_id"] == dmlnk_topic_id

    # Assert topic IDs in nodes are strictly unique (zero duplicates)
    tids = [n["topic_id"] for n in tree["nodes"]]
    assert len(tids) == len(set(tids)), f"Duplicate topic IDs in bookmap tree: {len(tids)} vs {len(set(tids))}"

    # Assert exactly 8 children under Diameter Link
    dmlnk_parent = "USC:CONCEPT_0311945109"
    children = [n for n in tree["nodes"] if n["parent_id"] == dmlnk_parent]
    assert len(children) == 8, f"Expected 8 children under Diameter Link, got {len(children)}"
    child_names = [c["name"] for c in children]
    assert len(child_names) == len(set(child_names)), f"Duplicate child names: {child_names}"

    # 2. Test get_topic_children directly
    direct_children = server.get_topic_children(dmlnk_parent)
    assert len(direct_children) == 8, f"Expected 8 direct children, got {len(direct_children)}"
    direct_tids = [c["topic_id"] for c in direct_children]
    assert len(direct_tids) == len(set(direct_tids)), "Duplicate topic IDs in get_topic_children"


def test_2d_layout_sibling_separation():
    # Construct a parent with 8 leaf children
    roots = ["pkg:TEST"]
    depths = {"pkg:TEST": 0, "topic:parent": 1}
    children = {"pkg:TEST": ["topic:parent"], "topic:parent": [f"topic:child_{i}" for i in range(8)]}
    for i in range(8):
        depths[f"topic:child_{i}"] = 2

    pos = radial_layout(depths, children, roots)
    assert len(pos) == 10

    # Assert euclidean distance between consecutive siblings is >= 20 px
    for i in range(7):
        c1 = pos[f"topic:child_{i}"]
        c2 = pos[f"topic:child_{i+1}"]
        dist_2d = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
        assert dist_2d >= 20.0, f"Distance between child {i} and {i+1} is too small: {dist_2d:.2f} px (expected >= 20.0 px)"
