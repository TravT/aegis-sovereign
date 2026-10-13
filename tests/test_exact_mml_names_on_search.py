"""Wave 3 item 3: an MML command name on `/query` must rank its own page first.

On 13 Oct `LST DMPEER` returned `LST DSTVER` (dense) and `RMV DMPEER` (sparse) above the exact page: at the
default limit each leg keeps 10 candidates and the exact page was in neither. The exact-ID router path finds it,
so a query that names an MML command now puts the pages whose title code is that command first.
"""
import threading
from unittest.mock import MagicMock

from core.router.classifier import classify_query_intent
from core.server.app import SovereignApplianceManager


def _page(pid, title, score=0.03):
    return {"id": pid, "doc_identifier": f"archive://x#{pid}", "title": title, "score": score, "rrf_score": score, "confidence_score": 0.6}


def _manager(hybrid_hits, exact_hits):
    m = object.__new__(SovereignApplianceManager)
    m._lock = threading.Lock()
    m.status = {"total_queries": 0}
    m.searcher = MagicMock()
    m.searcher.search.return_value = hybrid_hits
    m.router = MagicMock()
    m.router.analyze_query.side_effect = classify_query_intent
    m.router.execute_deterministic_lookup.return_value = exact_hits
    m.router._fallback_fts_search.return_value = []
    return m


def test_exact_page_ranks_first_and_twins_follow():
    hybrid = [_page("1", "UPCF 26.1.0: List the Target Version (LST DSTVER)"), _page("2", "USC 26.1.0: Remove Diameter Peer (RMV DMPEER)")]
    exact = [_page("10984", "USC 26.1.0: List Diameter Peer (LST DMPEER)", 0.94),
             _page("2", "USC 26.1.0: Remove Diameter Peer (RMV DMPEER)", 0.94),  # FTS phrase hit in "related commands"
             _page("20001", "UPCF 26.1.0: List Diameter Peer (LST DMPEER)", 0.94)]
    hits = _manager(hybrid, exact).search("LST DMPEER", limit=5)
    assert [h["id"] for h in hits] == ["10984", "20001", "1", "2"]
    assert hits[0]["confidence_score"] >= 0.94 and hits[0]["source"] == "exact_mml_name"


def test_exact_page_already_in_hybrid_hits_is_not_duplicated():
    page = _page("7", "USC 26.1.0: Modify SCTP Protocol Parameter (MOD SCTPPP)")
    hits = _manager([_page("5", "Health Check"), page], [dict(page)]).search("MOD SCTPPP", limit=5)
    assert [h["id"] for h in hits] == ["7", "5"]


def test_command_inside_a_question_and_bare_names_both_work():
    exact = [_page("9", "UPCF 26.1.0: NGPING(NGPING)")]
    assert _manager([_page("1", "Guide")], exact).search("NGPING")[0]["id"] == "9"
    assert _manager([_page("1", "Guide")], [_page("3", "USC 26.1.0: List Diameter Peer (LST DMPEER)")]).search("how do I use LST DMPEER on USC")[0]["id"] == "3"


def test_plain_language_query_is_unchanged():
    hybrid = [_page("1", "UPCF 26.1.0: Basic Principles of OSPF"), _page("2", "UPCF 26.1.0: Display OSPF Neighbor State (DSP OSPFPEER)")]
    m = _manager(hybrid, [])
    assert m.search("how do I check the OSPF neighbor state") == hybrid
    m.router.execute_deterministic_lookup.assert_not_called()


def test_limit_is_respected():
    exact = [_page(str(i), f"P{i}: List Diameter Peer (LST DMPEER)") for i in range(4)]
    hybrid = [_page(str(10 + i), f"Other {i}") for i in range(5)]
    assert len(_manager(hybrid, exact).search("LST DMPEER", limit=3)) == 3
