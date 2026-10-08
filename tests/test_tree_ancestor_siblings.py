import sqlite3
import pytest
from pathlib import Path
from core.server.app import SovereignApplianceManager

VAULT_ROUTER_DB = Path("/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db")
VAULT_GRAPH_DB = Path("/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_graph.db")

@pytest.mark.skipif(not VAULT_ROUTER_DB.exists(), reason="Vault sovereign_router.db required")
def test_tree_ancestor_siblings_retention():
    server = SovereignApplianceManager(
        router_db_path=str(VAULT_ROUTER_DB),
    )

    # Deep article in USC: "Services Management" under Commands -> Operation and Maintenance Commands -> USC O&M Commands
    deep_topic_id = "USC:CONCEPT_0234031539"
    tree = server.get_package_bookmap_tree(package="USC", topic_id=deep_topic_id)
    assert tree is not None
    assert tree["package"] == "USC"
    assert tree["active_topic_id"] == deep_topic_id
    
    nodes = {n["topic_id"]: n for n in tree["nodes"]}
    assert deep_topic_id in nodes
    
    # 1. Check Commands (Depth 1) has all 10 children
    commands_id = "USC:TOPIC_0183031439"
    assert commands_id in nodes
    cmd_children = [n for n in nodes.values() if n["parent_id"] == commands_id]
    assert len(cmd_children) == 10, f"Expected 10 children for Commands, got {len(cmd_children)}"
    
    # 2. Check Operation and Maintenance Commands (Depth 2) has all 4 children
    om_cmd_id = "USC:TOPIC_018537109" if "USC:TOPIC_018537109" in nodes else "USC:TOPIC_0181537109"
    assert om_cmd_id in nodes
    om_children = [n for n in nodes.values() if n["parent_id"] == om_cmd_id]
    assert len(om_children) == 4, f"Expected 4 children for O&M Commands, got {len(om_children)}"
    
    # 3. Check USC Operation and Maintenance Commands (Depth 3) has all 3 children
    usc_om_id = "USC:TOPIC_0000001697964666"
    assert usc_om_id in nodes
    usc_om_children = [n for n in nodes.values() if n["parent_id"] == usc_om_id]
    assert len(usc_om_children) == 3, f"Expected 3 children for USC O&M Commands, got {len(usc_om_children)}"
    
    # 4. Check Services Management (Depth 4) has all 13 children
    services_children = [n for n in nodes.values() if n["parent_id"] == deep_topic_id]
    assert len(services_children) == 13, f"Expected 13 children under Services Management, got {len(services_children)}"

    # 5. Confirm size is bounded
    assert len(nodes) < 4000
