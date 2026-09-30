"""GraphService interface tests (Task 14.1): behaviour is checked through slice/meta/find only,
against the hand-drawn vault in graph_fixtures.py (see its docstring for the expected values)."""

import pytest

from core.graphview import GraphService
from tests.graph_fixtures import build_vault, build_wiki


@pytest.fixture()
def svc(tmp_path):
    router, graph = build_vault(tmp_path)
    return GraphService(router, graph)


def node_ids(res):
    return set(res["nodes"]["id"])


def edge_set(res):
    ids = res["nodes"]["id"]
    e = res["edges"]
    return {(ids[s], ids[t], k) for s, t, k in zip(e["s"], e["t"], e["k"])}


def test_tree_all_mode_drops_nodes_and_edges_above_clearance(svc):
    res = svc.slice("tree", clearance="public", mode="all")

    # t3 (min of its children = 2), t5 (1) and t6 (2) are hidden from a public caller
    assert node_ids(res) == {"pkg:P1", "pkg:P2", "t:t1", "t:t2", "t:t4", "t:t7", "t:t11"}
    # the second-parent edge t4 -> t3 is dropped with t3; nothing dangles
    assert edge_set(res) == {
        ("t:t1", "pkg:P1", "CHILD_OF"),
        ("t:t7", "pkg:P2", "CHILD_OF"),
        ("t:t2", "t:t1", "CHILD_OF"),
        ("t:t4", "t:t2", "CHILD_OF"),
        ("t:t11", "t:t7", "CHILD_OF"),
    }


def test_hidden_parent_hides_its_whole_subtree(svc):
    # t9 has a public record, but its parent t8 is restricted: no orphans, fail closed
    for level in ("public", "internal", "confidential"):
        ids = node_ids(svc.slice("tree", clearance=level, mode="all"))
        assert "t:t8" not in ids and "t:t9" not in ids


def test_higher_clearance_reveals_more_including_second_parent_edges(svc):
    internal = svc.slice("tree", clearance="internal", mode="all")
    assert node_ids(internal) == {"pkg:P1", "pkg:P2", "t:t1", "t:t2", "t:t4", "t:t5", "t:t7", "t:t11"}

    confidential = svc.slice("tree", clearance="confidential", mode="all")
    assert node_ids(confidential) == {
        "pkg:P1", "pkg:P2", "t:t1", "t:t2", "t:t3", "t:t4", "t:t5", "t:t6", "t:t7", "t:t10", "t:t11",
    }
    assert ("t:t4", "t:t3", "SECOND_PARENT") in edge_set(confidential)
    assert ("t:t6", "t:t3", "CHILD_OF") in edge_set(confidential)

    restricted = svc.slice("tree", clearance="restricted", mode="all")
    assert {"t:t8", "t:t9"} <= node_ids(restricted)
    assert len(node_ids(restricted)) == 13
    # every edge endpoint is a sent node
    assert len(edge_set(restricted)) == 12  # 11 CHILD_OF (incl. 2 package roots) + 1 SECOND_PARENT


def column(res, name):
    return dict(zip(res["nodes"]["id"], res["nodes"][name]))


def test_clustered_view_returns_top_levels_with_visible_descendant_counts(svc):
    res = svc.slice("tree", clearance="public", mode="clustered", levels=1)

    assert node_ids(res) == {"pkg:P1", "pkg:P2", "t:t1", "t:t7"}
    assert edge_set(res) == {("t:t1", "pkg:P1", "CHILD_OF"), ("t:t7", "pkg:P2", "CHILD_OF")}
    # only what a public caller can see is counted: t1 -> t2 -> t4, never the hidden t3/t5/t6
    assert column(res, "n_desc") == {"pkg:P1": 3, "pkg:P2": 2, "t:t1": 2, "t:t7": 1}
    assert column(res, "expandable") == {"pkg:P1": 0, "pkg:P2": 0, "t:t1": 1, "t:t7": 1}


def test_all_mode_counts_but_nothing_is_expandable(svc):
    res = svc.slice("tree", clearance="public", mode="all")
    assert column(res, "n_desc")["t:t1"] == 2
    assert set(column(res, "expandable").values()) == {0}


def test_focus_expands_one_node_and_its_next_levels(svc):
    res = svc.slice("tree", clearance="public", focus="t:t1", mode="clustered", levels=1)

    assert node_ids(res) == {"t:t1", "t:t2"}
    assert edge_set(res) == {("t:t2", "t:t1", "CHILD_OF")}
    assert column(res, "expandable") == {"t:t1": 0, "t:t2": 1}  # t2 still has t4 below it

    deeper = svc.slice("tree", clearance="confidential", focus="t:t1", mode="clustered", levels=2)
    assert node_ids(deeper) == {"t:t1", "t:t2", "t:t3", "t:t4", "t:t5", "t:t6", "t:t10"}
    assert ("t:t4", "t:t3", "SECOND_PARENT") in edge_set(deeper)


def test_default_clustered_view_shows_two_levels(svc):
    res = svc.slice("tree", clearance="confidential")
    assert node_ids(res) == {"pkg:P1", "pkg:P2", "t:t1", "t:t2", "t:t3", "t:t7", "t:t11"}


def test_hidden_and_unknown_focus_are_indistinguishable(svc):
    with pytest.raises(KeyError) as hidden:
        svc.slice("tree", clearance="public", focus="t:t3")  # exists, but restricted for public
    with pytest.raises(KeyError) as unknown:
        svc.slice("tree", clearance="public", focus="t:nope")
    assert str(hidden.value).replace("t:t3", "X") == str(unknown.value).replace("t:nope", "X")


def test_structure_only_leaves_inherit_their_parents_clearance(svc):
    # t10 and t11 have no records and no children: they carry no content of their own
    assert "t:t11" in node_ids(svc.slice("tree", clearance="public", mode="all"))   # parent t7 is 0
    for level in ("public", "internal"):
        assert "t:t10" not in node_ids(svc.slice("tree", clearance=level, mode="all"))  # parent t3 is 2
    assert "t:t10" in node_ids(svc.slice("tree", clearance="confidential", mode="all"))


def test_content_version_is_stable_until_the_vault_changes_and_results_follow(tmp_path):
    import sqlite3

    router, graph = build_vault(tmp_path)
    svc = GraphService(router, graph)
    first = svc.slice("tree", clearance="public", mode="all")
    again = svc.slice("tree", clearance="public", mode="all")
    assert first["content_version"] == again["content_version"]
    assert "t:t5" not in node_ids(first)  # t5's only record is INTERNAL

    con = sqlite3.connect(router)
    con.execute("UPDATE document_records SET clearance_level = 0 WHERE topic_id = 't5'")
    con.commit()
    con.close()

    changed = svc.slice("tree", clearance="public", mode="all")
    assert changed["content_version"] != first["content_version"]
    assert "t:t5" in node_ids(changed)


def positions(res, cols):
    n = res["nodes"]
    return {nid: tuple(n[c][i] for c in cols) for i, nid in enumerate(n["id"])}


def norm(p):
    return sum(v * v for v in p) ** 0.5


@pytest.mark.parametrize("cols", [("x", "y"), ("x3", "y3", "z3")])
def test_layout_is_finite_distinct_and_radial(svc, cols):
    res = svc.slice("tree", clearance="restricted", mode="all")
    pos = positions(res, cols)
    assert len(set(pos.values())) == len(pos)  # no two nodes on the same spot
    assert all(v == v and abs(v) != float("inf") for p in pos.values() for v in p)
    ids = res["nodes"]["id"]
    for s, t, k in zip(res["edges"]["s"], res["edges"]["t"], res["edges"]["k"]):
        if k == "CHILD_OF":  # a child sits farther out than its parent
            assert norm(pos[ids[s]]) > norm(pos[ids[t]])


def test_layout_is_deterministic_and_the_same_for_clustered_and_all(tmp_path):
    router, graph = build_vault(tmp_path)
    a = positions(GraphService(router, graph).slice("tree", "restricted", mode="all"), ("x", "y", "x3", "y3", "z3"))
    b = positions(GraphService(router, graph).slice("tree", "restricted", mode="all"), ("x", "y", "x3", "y3", "z3"))
    assert a == b
    clustered = positions(GraphService(router, graph).slice("tree", "restricted", levels=1), ("x", "y", "x3", "y3", "z3"))
    assert all(a[nid] == p for nid, p in clustered.items())  # expanding a node never moves the others


def test_hidden_nodes_never_move_what_the_caller_can_see(tmp_path):
    import sqlite3

    router, graph = build_vault(tmp_path)
    cols = ("x", "y", "x3", "y3", "z3")
    before = positions(GraphService(router, graph).slice("tree", "public", mode="all"), cols)

    con = sqlite3.connect(router)  # a big restricted subtree appears under t1
    for i in range(20, 60):
        con.execute("INSERT INTO topic_nodes VALUES (?, 'P1', ?, 2, 'fixture', NULL)", (f"t{i}", f"hidden {i}"))
        con.execute("INSERT INTO topic_edges VALUES (?, 't1', 1)", (f"t{i}",))
        con.execute(
            "INSERT INTO document_records (doc_identifier, title, content, clearance_level, topic_id) "
            "VALUES (?, 'h', 'h', 3, ?)", (f"hid{i}", f"t{i}"))
    con.commit()
    con.close()

    after = positions(GraphService(router, graph).slice("tree", "public", mode="all"), cols)
    assert after == before


def test_crowded_shallow_leaves_are_spread_apart(tmp_path):
    """Four adjacent leaf roots beside a 500-leaf subtree used to land within 0.8 units of each other."""
    import sqlite3

    router, graph = build_vault(tmp_path)
    con = sqlite3.connect(router)
    for i in range(100, 104):  # bare leaf roots in P2, next to t7's subtree
        con.execute("INSERT INTO topic_nodes VALUES (?, 'P2', ?, 1, 'fixture', NULL)", (f"t{i}", f"leaf root {i}"))
        con.execute("INSERT INTO topic_edges VALUES (?, NULL, 1)", (f"t{i}",))
        con.execute(
            "INSERT INTO document_records (doc_identifier, title, content, clearance_level, topic_id) "
            "VALUES (?, 'l', 'l', 0, ?)", (f"lr{i}", f"t{i}"))
    for i in range(1000, 1500):  # 500 leaves under t7
        con.execute("INSERT INTO topic_nodes VALUES (?, 'P2', ?, 2, 'fixture', NULL)", (f"t{i}", f"leaf {i}"))
        con.execute("INSERT INTO topic_edges VALUES (?, 't7', 1)", (f"t{i}",))
        con.execute(
            "INSERT INTO document_records (doc_identifier, title, content, clearance_level, topic_id) "
            "VALUES (?, 'l', 'l', 0, ?)", (f"lf{i}", f"t{i}"))
    con.commit()
    con.close()

    res = GraphService(router, graph).slice("tree", "restricted", mode="all")
    for cols in (("x", "y"), ("x3", "y3", "z3")):
        pts = list(positions(res, cols).values())
        closest = min(
            norm(tuple(a - b for a, b in zip(p, q)))
            for i, p in enumerate(pts) for q in pts[i + 1:]
        )
        assert closest >= 2.0, (cols, closest)


def _closest_pair(points, cell=6.0):
    """Smallest distance between any two points (grid-hashed, so ~2k-45k points are fine)."""
    import collections
    import itertools
    import math

    grid = collections.defaultdict(list)
    key = lambda p: tuple(int(c // cell) for c in p)  # noqa: E731
    for i, p in enumerate(points):
        grid[key(p)].append(i)
    best = float("inf")
    for i, p in enumerate(points):
        for off in itertools.product((-1, 0, 1), repeat=len(p)):
            for j in grid.get(tuple(a + b for a, b in zip(key(p), off)), ()):
                if j > i:
                    best = min(best, math.dist(p, points[j]))
    return best


def test_no_two_nodes_of_a_large_uneven_tree_overlap(tmp_path):
    """A seeded random tree (heavy-tailed fan-out, ~2,000 nodes, 300 roots) that used to put nodes
    of the same ring on the very same spot where a spread-out crowd wrapped onto the ring's start."""
    import random
    import sqlite3

    router, graph = build_vault(tmp_path)
    con = sqlite3.connect(router)
    for table in ("document_records", "topic_edges", "topic_nodes"):
        con.execute(f"DELETE FROM {table}")
    rnd = random.Random(3)
    counter, frontier = 0, [None]
    for depth in range(1, 6):
        nxt = []
        for parent in frontier:
            if depth == 1:
                kids = 300
            else:
                kids = 0 if rnd.random() < 0.45 else min(int(rnd.paretovariate(1.2)), 60)
            for _ in range(kids):
                counter += 1
                tid = f"n{counter}"
                con.execute("INSERT INTO topic_nodes VALUES (?, 'A', ?, ?, 'fixture', NULL)", (tid, tid, depth))
                con.execute("INSERT INTO topic_edges VALUES (?, ?, 1)", (tid, parent))
                nxt.append(tid)
        frontier = nxt if depth > 1 else [n for n in nxt]
    con.commit()
    con.close()

    res = GraphService(router, graph).slice("tree", "restricted", mode="all")
    assert len(res["nodes"]["id"]) > 1500  # the seed really produced a big tree
    for cols in (("x", "y"), ("x3", "y3", "z3")):
        assert _closest_pair(list(positions(res, cols).values())) >= 1.0, cols


def test_find_matches_visible_nodes_case_insensitively_with_their_ancestor_path(svc):
    hits = svc.find("LEAF a1", clearance="restricted")
    assert [(h["id"], h["path"]) for h in hits] == [
        ("t:t4", ["pkg:P1", "t:t1", "t:t2", "t:t4"]),
        ("t:t5", ["pkg:P1", "t:t1", "t:t2", "t:t5"]),
    ]
    assert hits[0]["label"] == "Leaf A1a" and hits[0]["layer"] == "tree"


def test_find_never_reveals_nodes_above_the_callers_clearance(svc):
    public = [h["id"] for h in svc.find("leaf", clearance="public")]
    # Leaf A1b (INTERNAL), Leaf A2a and the bare leaf under A2 (CONFIDENTIAL) stay hidden;
    # "Leaf A1a" is a prefix match, "Bare leaf under B" a contains match
    assert public == ["t:t4", "t:t11"]
    assert svc.find("sealed", clearance="confidential") == []
    assert [h["id"] for h in svc.find("sealed", clearance="restricted")] == ["t:t8", "t:t9"]


def test_find_ranks_exact_then_prefix_then_contains_and_honours_limit(svc):
    hits = svc.find("root", clearance="restricted")
    assert [h["id"] for h in hits] == ["t:t1", "t:t7"]  # "Root A", "Root B", both prefix matches, by depth then label
    assert [h["id"] for h in svc.find("Leaf A1a", clearance="restricted")][0] == "t:t4"  # exact first
    assert len(svc.find("a", clearance="restricted", limit=3)) == 3  # many labels contain an "a"
    assert svc.find("   ", clearance="restricted") == []  # a blank query matches nothing


def test_tree_nodes_carry_a_theme_from_their_records_console_inherited_downwards(svc):
    theme = column(svc.slice("tree", clearance="restricted", mode="all"), "theme")
    assert theme["t:t1"] == "om_mml"          # own record
    assert theme["t:t4"] == "engineering"     # own record
    assert theme["t:t3"] == "om_mml"          # no records of its own: inherits from t1
    assert theme["t:t10"] == "om_mml"         # bare leaf under t3: inherits through t3
    assert theme["t:t6"] == "engineering"     # its own console wins over the parent's
    assert theme["t:t7"] == "" and theme["t:t11"] == ""  # nothing to inherit
    assert theme["pkg:P1"] == "" and theme["pkg:P2"] == ""


def eid(name, etype):
    return f"e:{etype}:{name}"


def test_entity_layer_shows_only_allowed_types_and_relations_within_clearance(svc):
    res = svc.slice("entity", clearance="public")

    assert node_ids(res) == {
        eid("ALM-1", "telecom_alarm"), eid("MML-A", "mml_command"),
        eid("F-1", "telecom_feature"), eid("REL-1", "product_release"),
    }
    assert edge_set(res) == {
        (eid("ALM-1", "telecom_alarm"), eid("MML-A", "mml_command"), "DIAGNOSED_BY_MML"),
        (eid("REL-1", "product_release"), eid("ALM-1", "telecom_alarm"), "DEFINES_ALARM"),
        (eid("REL-1", "product_release"), eid("F-1", "telecom_feature"), "IMPLEMENTS_FEATURE"),
    }
    assert column(res, "theme")[eid("ALM-1", "telecom_alarm")] == "telecom_alarm"
    assert column(res, "kind")[eid("ALM-1", "telecom_alarm")] == "entity"


def test_entity_layer_internal_clearance_adds_restricted_nodes_and_their_relations(svc):
    res = svc.slice("entity", clearance="internal")
    alarm, mml_a, mml_b = eid("ALM-1", "telecom_alarm"), eid("MML-A", "mml_command"), eid("MML-B", "mml_command")
    alarm2, kpi = eid("ALM-2", "telecom_alarm"), eid("K-1", "telecom_kpi")
    assert {alarm2, mml_b, kpi} <= node_ids(res)
    assert {
        (alarm, mml_b, "REMEDIATED_BY_MML"), (alarm2, mml_a, "DIAGNOSED_BY_MML"),
        (alarm, kpi, "MEASURED_BY_COUNTER"), (alarm2, alarm, "CANONICAL_ALARM_SPEC"),
    } <= edge_set(res)


def test_entity_layer_never_contains_personal_or_unlisted_entities_at_any_clearance(svc):
    res = svc.slice("entity", clearance="restricted")
    types = {n.split(":")[1] for n in node_ids(res)}
    assert types == {"telecom_alarm", "mml_command", "telecom_kpi", "telecom_feature", "product_release"}
    assert {k for _, _, k in edge_set(res)} == {
        "DIAGNOSED_BY_MML", "REMEDIATED_BY_MML", "MEASURED_BY_COUNTER", "CANONICAL_ALARM_SPEC",
        "DEFINES_ALARM", "IMPLEMENTS_FEATURE",
    }


def test_entity_layer_reports_the_visible_degree_of_each_node(svc):
    degree = column(svc.slice("entity", clearance="public"), "degree")
    assert degree == {
        eid("ALM-1", "telecom_alarm"): 2, eid("MML-A", "mml_command"): 1,
        eid("F-1", "telecom_feature"): 1, eid("REL-1", "product_release"): 2,
    }


def test_find_searches_the_entity_layer_within_clearance(svc):
    assert [h["id"] for h in svc.find("alm", clearance="public", layer="entity")] == [eid("ALM-1", "telecom_alarm")]
    assert [h["id"] for h in svc.find("alm", clearance="internal", layer="entity")] == [
        eid("ALM-1", "telecom_alarm"), eid("ALM-2", "telecom_alarm")]
    assert svc.find("R$", clearance="restricted", layer="entity") == []  # personal data is not searchable here


@pytest.fixture()
def wsvc(tmp_path):
    router, graph = build_vault(tmp_path)
    return GraphService(router, graph, wiki_dir=build_wiki(tmp_path))


def test_wiki_layer_links_notes_and_ignores_code_dead_external_and_non_note_links(wsvc):
    res = wsvc.slice("wiki", clearance="restricted")

    assert node_ids(res) == {
        "w:a.md", "w:b.md", "w:sub/c.md", "w:d.md", "w:adrs/ADR-1.md", "w:broken.md",
    }
    assert edge_set(res) == {
        ("w:a.md", "w:b.md", "LINKS_TO"),
        ("w:a.md", "w:sub/c.md", "LINKS_TO"),
        ("w:b.md", "w:a.md", "LINKS_TO"),
        ("w:b.md", "w:adrs/ADR-1.md", "GOVERNED_BY"),
        ("w:sub/c.md", "w:a.md", "LINKS_TO"),
        ("w:sub/c.md", "w:b.md", "LINKS_TO"),
        ("w:adrs/ADR-1.md", "w:a.md", "LINKS_TO"),
        ("w:broken.md", "w:a.md", "LINKS_TO"),   # unclosed frontmatter: the file is just a note with a link
    }


def test_wiki_notes_get_title_kind_theme_and_degree_from_frontmatter_with_fallbacks(wsvc):
    res = wsvc.slice("wiki", clearance="restricted")
    assert column(res, "label") == {
        "w:a.md": "Alpha", "w:b.md": "Bravo", "w:sub/c.md": "Charlie heading", "w:d.md": "Delta",
        "w:adrs/ADR-1.md": "ADR-1: Something", "w:broken.md": "broken",
    }
    kind, theme = column(res, "kind"), column(res, "theme")
    assert kind["w:a.md"] == "moc" and kind["w:sub/c.md"] == "note" and kind["w:adrs/ADR-1.md"] == "decision"
    # domain, else category, else the folder, else nothing
    assert theme["w:a.md"] == "infrastructure" and theme["w:b.md"] == "ops"
    assert theme["w:sub/c.md"] == "sub" and theme["w:broken.md"] == ""
    assert column(res, "degree")["w:a.md"] == 6  # 2 out + b, sub/c, adrs/ADR-1 and broken pointing in


def test_wiki_clearance_comes_from_frontmatter_and_defaults_to_public(wsvc):
    assert "w:d.md" not in node_ids(wsvc.slice("wiki", clearance="public"))   # clearance_level: 1
    assert "w:d.md" in node_ids(wsvc.slice("wiki", clearance="internal"))
    assert "w:a.md" in node_ids(wsvc.slice("wiki", clearance="public"))       # no field: public


def test_wiki_layer_is_absent_without_a_wiki_directory_and_find_searches_it(tmp_path, wsvc):
    other = tmp_path / "other"
    other.mkdir()
    router, graph = build_vault(other)
    with pytest.raises(ValueError):
        GraphService(router, graph).slice("wiki", clearance="public")
    assert [h["id"] for h in wsvc.find("alpha", clearance="public", layer="wiki")] == ["w:a.md"]
    assert wsvc.find("delta", clearance="public", layer="wiki") == []


def test_content_version_follows_wiki_edits(tmp_path, wsvc):
    before = wsvc.content_version()
    (tmp_path / "wiki" / "d.md").write_text("---\ntitle: Delta\nclearance_level: 0\n---\nchanged\n")
    assert wsvc.content_version() != before
    assert "w:d.md" in node_ids(wsvc.slice("wiki", clearance="public"))


def test_alarms_point_to_the_manual_topics_that_describe_them_within_clearance(tmp_path):
    import sqlite3

    router, graph = build_vault(tmp_path)
    con = sqlite3.connect(router)
    for tid, name, clearance in (
        ("t20", "ALM-1 Module Fault", 0),
        ("t21", "ALM-1 Restricted variant", 3),
        ("t22", "ALM-2 Something", 0),
        ("t23", "ALM-10 Other alarm", 0),      # ALM-10 is not ALM-1
        ("t24", "Not an ALM-1 topic", 0),       # the id must start the title
    ):
        con.execute("INSERT INTO topic_nodes VALUES (?, 'P1', ?, 2, 'fixture', NULL)", (tid, name))
        con.execute("INSERT INTO topic_edges VALUES (?, 't1', 1)", (tid,))
        con.execute(
            "INSERT INTO document_records (doc_identifier, title, content, clearance_level, topic_id) "
            "VALUES (?, 'r', 'r', ?, ?)", (f"r{tid}", clearance, tid))
    con.commit()
    con.close()
    svc = GraphService(router, graph)

    alarm1, alarm2, mml = eid("ALM-1", "telecom_alarm"), eid("ALM-2", "telecom_alarm"), eid("MML-A", "mml_command")
    public = column(svc.slice("entity", clearance="public"), "see_also")
    assert public[alarm1] == ["t:t20"]            # t21 is restricted: never revealed
    assert public[mml] == []                      # no deterministic key for MML commands
    assert alarm2 not in public                   # ALM-2 itself is INTERNAL

    restricted = column(svc.slice("entity", clearance="restricted"), "see_also")
    assert restricted[alarm1] == ["t:t20", "t:t21"]
    assert restricted[alarm2] == ["t:t22"]


def test_meta_describes_layers_counts_themes_and_reserved_edge_kinds_within_clearance(wsvc):
    meta = wsvc.meta("public")
    layers = {layer["id"]: layer for layer in meta["layers"]}

    assert list(layers) == ["tree", "entity", "wiki"]
    assert (layers["tree"]["nodes"], layers["tree"]["edges"]) == (7, 5)
    assert layers["tree"]["edge_kinds"] == {"CHILD_OF": 5}          # no second parents visible to public
    assert layers["tree"]["themes"] == [{"theme": "om_mml", "count": 2}, {"theme": "engineering", "count": 1}]

    assert (layers["entity"]["nodes"], layers["entity"]["edges"]) == (4, 3)
    assert layers["entity"]["edge_kinds"] == {"DIAGNOSED_BY_MML": 1, "DEFINES_ALARM": 1, "IMPLEMENTS_FEATURE": 1}
    assert [t["theme"] for t in layers["entity"]["themes"]] == [
        "mml_command", "product_release", "telecom_alarm", "telecom_feature"]  # equal counts: alphabetical

    assert (layers["wiki"]["nodes"], layers["wiki"]["edges"]) == (5, 8)  # d.md is INTERNAL
    assert layers["wiki"]["edge_kinds"] == {"LINKS_TO": 7, "GOVERNED_BY": 1}
    assert [t["theme"] for t in layers["wiki"]["themes"]] == ["adrs", "infrastructure", "ops", "sub"]

    # the MML-chain relationships are part of the contract now and arrive with Task 14.3
    assert meta["reserved_edge_kinds"] == ["CAUSED_BY", "NEXT_STEP"]
    assert meta["clearance"] == 0 and meta["content_version"] == wsvc.content_version()
    assert all(layer["label"] for layer in meta["layers"])


def test_meta_lists_only_the_layers_that_exist(svc):
    assert [layer["id"] for layer in svc.meta("restricted")["layers"]] == ["tree", "entity"]
    tree = {layer["id"]: layer for layer in svc.meta("restricted")["layers"]}["tree"]
    assert tree["edge_kinds"] == {"CHILD_OF": 11, "SECOND_PARENT": 1}
