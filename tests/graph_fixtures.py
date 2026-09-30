"""Tiny synthetic vault for the graph service tests: every expected value in the tests is
derived by hand from the picture below, never recomputed from the code under test.

Tree layer (router DB), record clearance in brackets, PUBLIC=0 INTERNAL=1 CONFIDENTIAL=2 RESTRICTED=3:

    package P1                          package P2
      t1 Root A [0]                       t7 Root B [0]
        t2 Child A1 [0 and 3]               t8 Sealed B1 [3]
                                              t9 Open under sealed [0]   <- hidden with its parent
          t4 Leaf A1a [0]   <- also a second parent: t3
          t5 Leaf A1b [1]
        t3 Child A2 (no records of its own)
          t6 Leaf A2a [2]
          t10 Bare leaf (no records)  <- structure only: inherits its parent's level (2)
      (t7 also has t11 Bare leaf (no records) -> inherits 0)

Derived node clearance = minimum over its records; a node without records takes the minimum of
its PRIMARY children (t3 -> 2: the second-parent link from t4 is a cross-reference, not
containment, so the public t4 must not pull the restricted container t3 into view).
A node is visible when that minimum is <= the caller's clearance.
"""

import sqlite3
from pathlib import Path
from typing import Tuple

ROUTER_DDL = """
CREATE TABLE topic_nodes (
    topic_id TEXT PRIMARY KEY, package TEXT NOT NULL, name TEXT NOT NULL,
    depth INTEGER NOT NULL, source TEXT NOT NULL, path_text TEXT);
CREATE TABLE topic_edges (
    child TEXT NOT NULL REFERENCES topic_nodes(topic_id),
    parent TEXT REFERENCES topic_nodes(topic_id),
    is_primary INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (child, parent));
CREATE TABLE document_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_identifier TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL, content TEXT NOT NULL, clearance_level INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    topic_id TEXT, record_kind TEXT, console TEXT, plane TEXT);
"""

GRAPH_DDL = """
CREATE TABLE entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, normalized_name TEXT NOT NULL,
    entity_type TEXT NOT NULL, clearance_level INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(normalized_name, entity_type));
CREATE TABLE entity_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id INTEGER NOT NULL, target_entity_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL, doc_id INTEGER, clearance_level INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_entity_id, target_entity_id, relation_type, doc_id));
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, corpus TEXT NOT NULL, doc_identifier TEXT NOT NULL,
    title TEXT, created_date TEXT, url TEXT, clearance_level INTEGER DEFAULT 0,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(corpus, doc_identifier));
CREATE TABLE document_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER NOT NULL, entity_id INTEGER NOT NULL,
    count INTEGER DEFAULT 1, context TEXT, UNIQUE(doc_id, entity_id));
"""

# (topic_id, package, name, depth)
TOPICS = [
    ("t1", "P1", "Root A", 1),
    ("t2", "P1", "Child A1", 2),
    ("t3", "P1", "Child A2", 2),
    ("t4", "P1", "Leaf A1a", 3),
    ("t5", "P1", "Leaf A1b", 3),
    ("t6", "P1", "Leaf A2a", 3),
    ("t7", "P2", "Root B", 1),
    ("t8", "P2", "Sealed B1", 2),
    ("t9", "P2", "Open under sealed", 3),
    ("t10", "P1", "Bare leaf under A2", 3),
    ("t11", "P2", "Bare leaf under B", 2),
]
# (child, parent, is_primary)
EDGES = [
    ("t1", None, 1), ("t7", None, 1),
    ("t2", "t1", 1), ("t3", "t1", 1),
    ("t4", "t2", 1), ("t5", "t2", 1),
    ("t6", "t3", 1),
    ("t8", "t7", 1), ("t9", "t8", 1),
    ("t10", "t3", 1), ("t11", "t7", 1),
    ("t4", "t3", 0),
]
# (topic_id, clearance, console)
RECORDS = [
    ("t1", 0, "om_mml"), ("t2", 0, "om_mml"), ("t2", 3, "om_mml"), ("t4", 0, "engineering"),
    ("t5", 1, "engineering"), ("t6", 2, "engineering"), ("t7", 0, None),
    ("t8", 3, None), ("t9", 0, None),
]


# Entity graph (name, type, clearance). Only alarms, MML commands, KPIs, features and releases
# belong in the entity layer; everything else must never reach the viewer.
ENTITIES = [
    ("ALM-1", "telecom_alarm", 0),
    ("ALM-2", "telecom_alarm", 1),
    ("MML-A", "mml_command", 0),
    ("MML-B", "mml_command", 1),
    ("K-1", "telecom_kpi", 1),
    ("F-1", "telecom_feature", 0),
    ("REL-1", "product_release", 0),
    ("R$ 10,00", "monetary", 0),        # personal finance: excluded type
    ("plate-1", "visual_plate", 0),     # diagram plate: excluded type
    ("ADR-9", "adr", 0),                # not a Huawei entity: excluded type
    ("Nota 123", "document", 0),        # paperless document: excluded type
    ("novel", "brand_new_type", 0),     # an allow-list, not a deny-list: unknown types stay out
]
# (source, target, relation, clearance)
RELATIONS = [
    ("ALM-1", "MML-A", "DIAGNOSED_BY_MML", 0),
    ("ALM-1", "MML-B", "REMEDIATED_BY_MML", 0),      # MML-B is INTERNAL: dropped for a public caller
    ("ALM-2", "MML-A", "DIAGNOSED_BY_MML", 0),       # ALM-2 is INTERNAL
    ("ALM-1", "K-1", "MEASURED_BY_COUNTER", 1),      # relation and K-1 both INTERNAL
    ("ALM-2", "ALM-1", "CANONICAL_ALARM_SPEC", 1),
    ("REL-1", "ALM-1", "DEFINES_ALARM", 0),
    ("REL-1", "F-1", "IMPLEMENTS_FEATURE", 0),
    ("ALM-1", "plate-1", "HAS_DIAGRAM", 0),          # excluded relation kind and target type
    ("ADR-9", "ALM-1", "AFFECTS_NE", 0),             # spurious ADR -> alarm link: excluded
    ("Nota 123", "R$ 10,00", "has_amount", 0),       # personal
    ("ALM-1", "F-1", "SOMETHING_NEW", 0),            # relation kinds are an allow-list too
]


def build_vault(tmp_path: Path) -> Tuple[str, str]:
    """Create the router and graph DBs in tmp_path and return their paths."""
    router = tmp_path / "router.db"
    graph = tmp_path / "graph.db"
    con = sqlite3.connect(router)
    con.executescript(ROUTER_DDL)
    con.executemany(
        "INSERT INTO topic_nodes (topic_id, package, name, depth, source) VALUES (?, ?, ?, ?, 'fixture')",
        TOPICS,
    )
    con.executemany("INSERT INTO topic_edges (child, parent, is_primary) VALUES (?, ?, ?)", EDGES)
    for n, (tid, clr, console) in enumerate(RECORDS):
        con.execute(
            "INSERT INTO document_records (doc_identifier, title, content, clearance_level, topic_id, "
            "record_kind, console) VALUES (?, ?, 'body', ?, ?, 'native', ?)",
            (f"rec{n}", f"record {n}", clr, tid, console),
        )
    con.commit()
    con.close()
    con = sqlite3.connect(graph)
    con.executescript(GRAPH_DDL)
    for name, etype, clr in ENTITIES:
        con.execute(
            "INSERT INTO entities (name, normalized_name, entity_type, clearance_level) VALUES (?, ?, ?, ?)",
            (name, name.lower(), etype, clr),
        )
    ids = dict(con.execute("SELECT name, id FROM entities"))
    for src, tgt, rel, clr in RELATIONS:
        con.execute(
            "INSERT INTO entity_relations (source_entity_id, target_entity_id, relation_type, clearance_level) "
            "VALUES (?, ?, ?, ?)",
            (ids[src], ids[tgt], rel, clr),
        )
    con.commit()
    con.close()
    return str(router), str(graph)


# Wiki fixture: relative path -> text. Expected graph (drawn by hand, see test_graph_service):
#   a -> b, a -> sub/c (LINKS_TO)   b -> a (LINKS_TO)   b -> adrs/ADR-1 (GOVERNED_BY: a note governed by an ADR)
#   sub/c -> a, sub/c -> b (LINKS_TO; the second one is an absolute file:// link into the wiki)
#   adrs/ADR-1 -> a (LINKS_TO: ADR to note is not "governed by")
# and NOT: the link inside a code fence or inline code (a -> d), the dead link, the image, the
# external and anchor-only links, the .csv link.
WIKI = {
    "a.md": (
        '---\ntitle: "Alpha"\ntype: moc\ndomain: infrastructure\ncategory: architecture\n---\n'
        "# Alpha\n"
        "See [B](b.md), [C](sub/c.md#part), [ext](https://example.org), [top](#top),\n"
        "![pic](pic.png), [data](data.csv), [dead](missing.md) and `[Nope](d.md)`.\n"
        "```\n[Code](d.md)\n```\n"
    ),
    "b.md": (
        '---\ntitle: Bravo\ntype: documentation\ncategory: ops\n---\n'
        "Back to [A](a.md); decided in [ADR](adrs/ADR-1.md).\n"
    ),
    "sub/c.md": (
        "# Charlie heading\n"
        "Up: [A](../a.md) and [B](file:///somewhere/docs/wiki/b.md).\n"
    ),
    "d.md": '---\ntitle: Delta\ntype: documentation\ncategory: misc\nclearance_level: 1\n---\nAlone.\n',
    "adrs/ADR-1.md": (
        '---\ntitle: "ADR-1: Something"\ntype: decision\n---\n'
        "Affects [A](../a.md).\n"
    ),
    "broken.md": "---\ntitle: never closed\nno end marker and a [link](a.md)\n",
}


def build_wiki(tmp_path: Path) -> str:
    root = tmp_path / "wiki"
    for rel, text in WIKI.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return str(root)
