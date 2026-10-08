import pytest
from pathlib import Path
from core.graphview.tree import TreeLayer
from core.graphview.service import GraphService

VAULT_ROUTER_DB = Path("/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db")

@pytest.mark.skipif(not VAULT_ROUTER_DB.exists(), reason="Vault sovereign_router.db required")
def test_relational_graph_edges_generation():
    tl = TreeLayer(str(VAULT_ROUTER_DB))
    tv = tl.build(1)

    assert len(tv.nodes) > 40000
    assert len(tv.edges) > 80000

    kinds = {e[2] for e in tv.edges}
    assert "CHILD_OF" in kinds
    assert "COMPANION_PACKAGE" in kinds, "Ecosystem backbone COMPANION_PACKAGE must be present"
    assert "CORE_NETWORK_PEER" in kinds, "5G Core peer edge CORE_NETWORK_PEER must be present"
    assert "FUNCTIONAL_BRIDGE" in kinds, "Release-to-HedEx FUNCTIONAL_BRIDGE must be present"
    assert "SHARED_ALARM" in kinds, "Shared alarm relational edges must be present"
    assert "SHARED_MML" in kinds, "Shared MML relational edges must be present"

    # Check companion packages explicitly
    companion_edges = [e for e in tv.edges if e[2] == "COMPANION_PACKAGE"]
    assert len(companion_edges) >= 2
    companion_pairs = {(e[0], e[1]) for e in companion_edges}
    assert ("pkg:REL_UPCF", "pkg:UPCF") in companion_pairs
    assert ("pkg:REL_USC", "pkg:USC") in companion_pairs

    # Check slice serialization via GraphService
    VAULT_GRAPH_DB = Path("/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_graph.db")
    svc = GraphService(router_db=str(VAULT_ROUTER_DB), graph_db=str(VAULT_GRAPH_DB))
    slice_data = svc.slice(layer="tree", mode="all", clearance="restricted")
    assert slice_data is not None
    assert "edges" in slice_data
    assert "k" in slice_data["edges"]
    slice_kinds = set(slice_data["edges"]["k"])
    assert "COMPANION_PACKAGE" in slice_kinds
    assert "CORE_NETWORK_PEER" in slice_kinds
    assert "SHARED_ALARM" in slice_kinds
