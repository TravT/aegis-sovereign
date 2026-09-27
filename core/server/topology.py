"""
Server & Knowledge Graph Topology and Dossier Enrichment Builder.
Constructs multi-ring interactive topologies and prioritizes MML commands,
diagrams, and 3GPP KPI counters for Web Portal visualization.
"""

from typing import Dict, Any, Optional, List


def build_enriched_graph_dossier(
    graph_store: Any,
    target_entities: List[str],
    existing_dossier: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Queries GraphStore and prioritizes MML commands, diagrams, and key KPI counters for Web Portal display."""
    if graph_store is None:
        return existing_dossier or {"entity": None, "neighbors": [], "edges": [], "by_relation": {}}

    candidates = [e.strip() for e in target_entities if e and e.strip()]
    if not candidates and existing_dossier and isinstance(existing_dossier.get("entity"), dict):
        ename = existing_dossier["entity"].get("name")
        if ename:
            candidates.append(ename)

    root_entity = None
    raw_neighbors: List[Dict[str, Any]] = []
    nodes_by_id: Dict[Any, Dict[str, Any]] = {}
    raw_edges: List[Dict[str, Any]] = []

    for ent_name in candidates[:3]:
        try:
            nb_res = graph_store.get_entity_neighborhood(ent_name, max_depth=1, max_clearance=5)
            if not root_entity and nb_res.get("entity"):
                root_entity = nb_res["entity"]
            for n in nb_res.get("nodes") or []:
                if isinstance(n, dict) and "id" in n:
                    nodes_by_id[n["id"]] = n
            for nb in nb_res.get("neighbors") or []:
                raw_neighbors.append(nb)
            for ed in nb_res.get("edges") or []:
                raw_edges.append(ed)
        except Exception:
            continue

    def _rel_priority(rel: str, name: str) -> int:
        r_up = (rel or "").upper()
        n_up = (name or "").upper()
        if "DIAGNOSED_BY_MML" in r_up:
            return 0
        if "REMEDIATED_BY_MML" in r_up:
            return 1
        if "CONFIGURED_BY_MML" in r_up:
            return 2
        if "DIAGRAM" in r_up:
            return 3
        if any(k in r_up for k in ("AUTO_HEALING", "SWITCHOVER", "AFFECTS_NE", "CAUSED_BY", "CANONICAL")):
            return 4
        if "MEASURED_BY_COUNTER" in r_up:
            if any(k in n_up for k in ("RTR", "AAD", "ADEV", "SCTP", "THRESHOLD", "DELAY", "SUCCESS")):
                return 5
            return 6
        return 7

    dedup_neighbors: List[Dict[str, Any]] = []
    seen_nb_keys = set()
    for nb in raw_neighbors:
        ent_obj = nb.get("entity") if isinstance(nb.get("entity"), dict) else {}
        ename = ent_obj.get("name") or nb.get("name") or ""
        rel = nb.get("relation") or "RELATED_TO"
        key = (rel, ename)
        if ename and key not in seen_nb_keys:
            seen_nb_keys.add(key)
            dedup_neighbors.append({
                "relation": rel,
                "direction": nb.get("direction", "outgoing"),
                "name": ename,
                "entity_type": ent_obj.get("entity_type") or nb.get("entity_type") or "entity",
                "entity": ent_obj or {"name": ename, "entity_type": "entity"},
                "_prio": _rel_priority(rel, ename),
            })

    dedup_neighbors.sort(key=lambda x: (x["_prio"], x["name"]))
    prioritized_neighbors = []
    by_relation: Dict[str, List[Dict[str, Any]]] = {
        "DIAGNOSED_BY_MML": [],
        "REMEDIATED_BY_MML": [],
        "MEASURED_BY_COUNTER": [],
        "HAS_DIAGRAM": [],
        "AFFECTS_NE": [],
        "CAUSED_BY": [],
    }

    kpi_count = 0
    for item in dedup_neighbors:
        rel = item["relation"]
        if rel == "MEASURED_BY_COUNTER":
            if kpi_count >= 8:
                continue
            kpi_count += 1
        clean_item = {k: v for k, v in item.items() if k != "_prio"}
        prioritized_neighbors.append(clean_item)
        if "DIAGNOSED_BY_MML" in rel:
            by_relation["DIAGNOSED_BY_MML"].append(clean_item)
        elif "REMEDIATED_BY_MML" in rel or "CONFIGURED_BY_MML" in rel:
            by_relation["REMEDIATED_BY_MML"].append(clean_item)
        elif "MEASURED_BY_COUNTER" in rel:
            by_relation["MEASURED_BY_COUNTER"].append(clean_item)
        elif "DIAGRAM" in rel:
            by_relation["HAS_DIAGRAM"].append(clean_item)
        elif "AFFECTS_NE" in rel or "DEFINES_ALARM" in rel or "ADAPTATION" in rel:
            by_relation["AFFECTS_NE"].append(clean_item)
        else:
            by_relation["CAUSED_BY"].append(clean_item)

    prioritized_neighbors = prioritized_neighbors[:24]

    enriched_edges: List[Dict[str, Any]] = []
    seen_edge_keys = set()
    for nb in prioritized_neighbors:
        rel = nb["relation"]
        tgt_name = nb["name"]
        src_name = (root_entity or {}).get("name") or (candidates[0] if candidates else "Entity")
        ekey = (src_name, rel, tgt_name)
        if ekey not in seen_edge_keys:
            seen_edge_keys.add(ekey)
            enriched_edges.append({
                "source": (root_entity or {}).get("id", 1),
                "source_name": src_name,
                "target": (nb.get("entity") or {}).get("id", 2),
                "target_name": tgt_name,
                "target_type": nb.get("entity_type", "entity"),
                "relation": rel,
            })

    return {
        "entity": root_entity or ({"name": candidates[0], "entity_type": "telecom_entity"} if candidates else None),
        "neighbors": prioritized_neighbors,
        "edges": enriched_edges,
        "by_relation": by_relation,
    }


def build_graph_topology(graph_store: Any, filter_term: str = "") -> Dict[str, Any]:
    """
    Builds a rich, interactive Server & Knowledge Graph topology combining:
    - Server Root & Corpus Nodes (Enterprise_Hub Server, Technical Wiki, Agent Skills, Huawei Corpus, Aegis Vault)
    - Program & Architectural Entities (ADR-40, ADR-30, Traefik v3, manage-sovereign-vault)
    - Live GraphStore Entities & Directed Edges (ALM-20104, ALM-20333, ALM-1003, USC, USCCSP, UPCF, NGPING, MOD SCTPPP, DSP OPTMODULE, VS.SCTP.RTX.Pkts, LOTE-202609B)
    """
    category_palette = {
        "server_hub": {"label": "Server Hub & Vaults", "color": "#D4AF37"},
        "wiki_adr": {"label": "Homelab Wiki & ADRs", "color": "#06B6D4"},
        "telecom_alarm": {"label": "Telecom Alarms & NEs", "color": "#F43F5E"},
        "mml_command": {"label": "MML Commands & Fixes", "color": "#10B981"},
        "agent_skill": {"label": "Agent Skills & Harnesses", "color": "#A855F7"},
    }

    base_nodes: List[Dict[str, Any]] = [
        # Ring 0: Primary Server Hub
        {
            "id": "Enterprise_Hub Server",
            "label": "Enterprise_Hub Server (homelab)",
            "category": "server_hub",
            "color": "#D4AF37",
            "ring": 0,
            "query_preset": "How is the Homelab server architecture and Traefik routing organized?",
            "description": "Primary Dell Latitude 7390 invisible server (LAN: 192.168.0.48, Tailscale: 100.125.7.38) orchestrated by HashiCorp Nomad & Ansible.",
        },
        # Ring 1: Core Corpora & Vaults
        {
            "id": "Aegis Vault (docs/.aegis_vault)",
            "label": "Aegis Vault (docs/.aegis_vault)",
            "category": "server_hub",
            "color": "#D4AF37",
            "ring": 1,
            "query_preset": "ADR-40",
            "description": "Air-gapped SQLite B-Tree/FTS5 router DB + WAL GraphRAG store (48,664+ indexed records).",
        },
        {
            "id": "Homelab Technical Wiki (docs/wiki)",
            "label": "Homelab Technical Wiki (docs/wiki)",
            "category": "wiki_adr",
            "color": "#06B6D4",
            "ring": 1,
            "query_preset": "How is the Homelab server architecture and Traefik routing organized?",
            "description": "Obsidian relational knowledge graph, system_overview.md, and 40+ Architectural Decision Records.",
        },
        {
            "id": "Agent Skills (.agents/skills)",
            "label": "Agent Skills (.agents/skills)",
            "category": "agent_skill",
            "color": "#A855F7",
            "ring": 1,
            "query_preset": "SKILL-SOVEREIGN-VAULT",
            "description": "25+ specialized operational skills for Antigravity, Claude Code, and local LLM orchestration.",
        },
        {
            "id": "Huawei 26.1.0 Corpus (docs/Hua_Docs)",
            "label": "Huawei 26.1.0 Corpus (docs/Hua_Docs)",
            "category": "server_hub",
            "color": "#D4AF37",
            "ring": 1,
            "query_preset": "How are the PODs of the USC and their functions organized?",
            "description": "Zero-copy O_RDONLY .zip/.hwics/.hdx Huawei USC & UPCF 26.1.0 engineering manuals.",
        },
        # Ring 2: ADRs, Skills, Telecom Alarms & NEs
        {
            "id": "ADR-40",
            "label": "ADR-40 (Two-Pronged Router)",
            "category": "wiki_adr",
            "color": "#06B6D4",
            "ring": 2,
            "query_preset": "ADR-40",
            "description": "Two-Pronged Hybrid Retrieval (<2ms B-Tree/FTS5 Fast-Path + Multi-Tier Cognitive Synthesis).",
        },
        {
            "id": "ADR-30",
            "label": "ADR-30 (Zigbee & Tuya Local)",
            "category": "wiki_adr",
            "color": "#06B6D4",
            "ring": 2,
            "query_preset": "How is the Homelab server architecture and Traefik routing organized?",
            "description": "Smart Home & Sensor Governance via local TCP 6668 and SONOFF ZBDongle-E coordinator.",
        },
        {
            "id": "Traefik v3 (192.168.0.48:443)",
            "label": "Traefik v3 (192.168.0.48:443)",
            "category": "wiki_adr",
            "color": "#06B6D4",
            "ring": 2,
            "query_preset": "How is the Homelab server architecture and Traefik routing organized?",
            "description": "Docker-native reverse proxy strictly bound to 192.168.0.48:443 (Tailscale 443 invariant).",
        },
        {
            "id": "SKILL-SOVEREIGN-VAULT",
            "label": "manage-sovereign-vault (7-Tool MCP)",
            "category": "agent_skill",
            "color": "#A855F7",
            "ring": 2,
            "query_preset": "SKILL-SOVEREIGN-VAULT",
            "description": "7-Tool Model Context Protocol (MCP v2) specification for Aegis Sovereign Knowledge Appliance.",
        },
        {
            "id": "ALM-20104",
            "label": "ALM-20104 (Link Bear Quality)",
            "category": "telecom_alarm",
            "color": "#F43F5E",
            "ring": 2,
            "query_preset": "ALM-20104",
            "description": "Huawei USC 26.1.0 SCTP link bearer quality degradation alarm (RTR/AAD/ADEV threshold).",
        },
        {
            "id": "ALM-20333",
            "label": "ALM-20333 (STP Link Bear)",
            "category": "telecom_alarm",
            "color": "#F43F5E",
            "ring": 2,
            "query_preset": "ALM-20333",
            "description": "Huawei USC 26.1.0 STP signaling link congestion and DB load threshold alarm.",
        },
        {
            "id": "ALM-1003",
            "label": "ALM-1003 (Module Fault + Diagram)",
            "category": "telecom_alarm",
            "color": "#F43F5E",
            "ring": 2,
            "query_preset": "ALM-1003",
            "description": "Hardware/Module fault alarm with embedded root/correlative alarm signaling diagram.",
        },
        {
            "id": "USC",
            "label": "USC (Unified Signaling Controller)",
            "category": "telecom_alarm",
            "color": "#F43F5E",
            "ring": 2,
            "query_preset": "How are the PODs of the USC and their functions organized?",
            "description": "Huawei 5G/IMS Core Unified Signaling Controller (USCCSP & UPCF cloud-native PODs).",
        },
        {
            "id": "UPCF",
            "label": "UPCF (Unified Policy & Charging)",
            "category": "telecom_alarm",
            "color": "#F43F5E",
            "ring": 2,
            "query_preset": "How to configure a 5G Service on the UPCF and what are the levels?",
            "description": "Huawei 5G Unified Policy and Charging Function microservice architecture.",
        },
        {
            "id": "LOTE-202609B",
            "label": "LOTE-202609B (ANVISA Batch)",
            "category": "telecom_alarm",
            "color": "#F43F5E",
            "ring": 2,
            "query_preset": "LOTE-202609B",
            "description": "ANVISA SNGPC Portaria 344/98 Lista B1 deterministic batch traceability dossier.",
        },
        # Ring 3: MML Commands, KPI Counters & Fixes
        {
            "id": "DSP OPTMODULE",
            "label": "DSP OPTMODULE (Optical MML)",
            "category": "mml_command",
            "color": "#10B981",
            "ring": 3,
            "query_preset": "DSP OPTMODULE",
            "description": "MML command to query SFP+/QSFP28 optical transceiver TX/RX power (dBm) and LOS/LOF thresholds.",
        },
        {
            "id": "MOD SCTPPP",
            "label": "MOD SCTPPP (Tune SCTP Profile)",
            "category": "mml_command",
            "color": "#10B981",
            "ring": 3,
            "query_preset": "ALM-20104",
            "description": "Remediation MML command to tune SCTP retransmission ratio (RTR), AAD, and ADEV parameters.",
        },
        {
            "id": "NGPING",
            "label": "NGPING (Bearer Ping Check)",
            "category": "mml_command",
            "color": "#10B981",
            "ring": 3,
            "query_preset": "ALM-20104",
            "description": "Diagnostic MML command to verify IP bearer packet loss and jitter across signaling planes.",
        },
        {
            "id": "VS.SCTP.RTX.Pkts",
            "label": "VS.SCTP.RTX.Pkts (3GPP Counter)",
            "category": "mml_command",
            "color": "#10B981",
            "ring": 3,
            "query_preset": "ALM-20104",
            "description": "3GPP/Vendor KPI performance counter tracking SCTP retransmitted chunks.",
        },
    ]

    base_edges: List[Dict[str, Any]] = [
        {"source": "Enterprise_Hub Server", "target": "Aegis Vault (docs/.aegis_vault)", "relation": "HOSTS_SOVEREIGN_VAULT"},
        {"source": "Enterprise_Hub Server", "target": "Homelab Technical Wiki (docs/wiki)", "relation": "INDEXES_SERVER_CORPUS"},
        {"source": "Enterprise_Hub Server", "target": "Agent Skills (.agents/skills)", "relation": "ORCHESTRATES_SKILLS"},
        {"source": "Enterprise_Hub Server", "target": "Huawei 26.1.0 Corpus (docs/Hua_Docs)", "relation": "STREAMS_O_RDONLY"},
        {"source": "Enterprise_Hub Server", "target": "Traefik v3 (192.168.0.48:443)", "relation": "INGRESS_ROUTING"},
        {"source": "Homelab Technical Wiki (docs/wiki)", "target": "ADR-40", "relation": "DEFINES_ARCHITECTURE"},
        {"source": "Homelab Technical Wiki (docs/wiki)", "target": "ADR-30", "relation": "DEFINES_ARCHITECTURE"},
        {"source": "Homelab Technical Wiki (docs/wiki)", "target": "Traefik v3 (192.168.0.48:443)", "relation": "DOCUMENTS_INVARIANT"},
        {"source": "Agent Skills (.agents/skills)", "target": "SKILL-SOVEREIGN-VAULT", "relation": "PROVIDES_MCP_SKILL"},
        {"source": "SKILL-SOVEREIGN-VAULT", "target": "Aegis Vault (docs/.aegis_vault)", "relation": "QUERIES_7_TOOLS"},
        {"source": "SKILL-SOVEREIGN-VAULT", "target": "ADR-40", "relation": "ENFORCES_ROUTER"},
        {"source": "Aegis Vault (docs/.aegis_vault)", "target": "ADR-40", "relation": "INDEXED_IN_BTREE"},
        {"source": "Aegis Vault (docs/.aegis_vault)", "target": "ALM-20104", "relation": "INDEXED_IN_BTREE"},
        {"source": "Aegis Vault (docs/.aegis_vault)", "target": "DSP OPTMODULE", "relation": "INDEXED_IN_BTREE"},
        {"source": "Aegis Vault (docs/.aegis_vault)", "target": "LOTE-202609B", "relation": "INDEXED_IN_BTREE"},
        {"source": "Huawei 26.1.0 Corpus (docs/Hua_Docs)", "target": "USC", "relation": "CONTAINS_NE_MANUAL"},
        {"source": "Huawei 26.1.0 Corpus (docs/Hua_Docs)", "target": "UPCF", "relation": "CONTAINS_NE_MANUAL"},
        {"source": "USC", "target": "ALM-20104", "relation": "TRIGGERS_ALARM"},
        {"source": "USC", "target": "ALM-20333", "relation": "TRIGGERS_ALARM"},
        {"source": "USC", "target": "ALM-1003", "relation": "TRIGGERS_ALARM"},
        {"source": "ALM-20104", "target": "NGPING", "relation": "DIAGNOSED_BY_MML"},
        {"source": "ALM-20104", "target": "MOD SCTPPP", "relation": "REMEDIATED_BY_MML"},
        {"source": "ALM-20104", "target": "VS.SCTP.RTX.Pkts", "relation": "MEASURED_BY_COUNTER"},
        {"source": "ALM-20333", "target": "NGPING", "relation": "DIAGNOSED_BY_MML"},
        {"source": "ALM-1003", "target": "DSP OPTMODULE", "relation": "DIAGNOSED_BY_MML"},
    ]

    nodes_by_id = {n["id"]: dict(n) for n in base_nodes}
    edge_set = {(e["source"], e["target"], e["relation"]) for e in base_edges}
    edges_list = list(base_edges)

    if graph_store is not None:
        try:
            with graph_store._get_connection() as gconn:
                gcur = gconn.cursor()
                gcur.execute(
                    """
                    SELECT s.name AS src_name, s.entity_type AS src_type,
                           t.name AS tgt_name, t.entity_type AS tgt_type,
                           r.relation_type AS rel
                    FROM entity_relations r
                    JOIN entities s ON r.source_entity_id = s.id
                    JOIN entities t ON r.target_entity_id = t.id
                    WHERE s.name IN ('ALM-20104', 'ALM-20333', 'ALM-1003', 'ADR-40', 'SKILL-SOVEREIGN-VAULT')
                    LIMIT 18
                    """
                )
                for row in gcur.fetchall():
                    sname = row[0]
                    tname = row[2]
                    ttype = (row[3] or "").lower()
                    rel = row[4] or "RELATED_TO"
                    if len(tname) > 36:
                        continue
                    if tname not in nodes_by_id:
                        cat = "mml_command" if ("MML" in rel or "COUNTER" in rel or "mml" in ttype) else "telecom_alarm"
                        nodes_by_id[tname] = {
                            "id": tname,
                            "label": tname,
                            "category": cat,
                            "color": category_palette[cat]["color"],
                            "ring": 3,
                            "query_preset": tname.split("(")[0].strip(),
                            "description": f"Live GraphStore entity ({rel}) linked to {sname}.",
                        }
                    ek = (sname, tname, rel)
                    if sname in nodes_by_id and ek not in edge_set:
                        edge_set.add(ek)
                        edges_list.append({"source": sname, "target": tname, "relation": rel})
        except Exception:
            pass

    ft = (filter_term or "").strip().lower()
    if ft:
        matched_ids = {
            nid
            for nid, n in nodes_by_id.items()
            if ft in nid.lower()
            or ft in n.get("label", "").lower()
            or ft in n.get("category", "").lower()
            or ft in n.get("description", "").lower()
        }
        connected_ids = set(matched_ids)
        for e in edges_list:
            if e["source"] in matched_ids or e["target"] in matched_ids:
                connected_ids.add(e["source"])
                connected_ids.add(e["target"])
        filtered_nodes = [n for nid, n in nodes_by_id.items() if nid in connected_ids]
        filtered_edges = [
            e for e in edges_list if e["source"] in connected_ids and e["target"] in connected_ids
        ]
    else:
        filtered_nodes = list(nodes_by_id.values())
        filtered_edges = edges_list

    graph_stats = graph_store.get_entity_statistics() if graph_store else {}
    return {
        "status": "ok",
        "filter_applied": filter_term or None,
        "total_nodes": len(filtered_nodes),
        "total_edges": len(filtered_edges),
        "categories": category_palette,
        "nodes": filtered_nodes,
        "edges": filtered_edges,
        "domain_summary": {
            "server_host": "Dell Latitude 7390 (homelab / 192.168.0.48)",
            "vault_total_entities": graph_stats.get("total_entities", len(filtered_nodes)),
            "vault_total_relations": graph_stats.get("total_relations", len(filtered_edges)),
            "corpora_connected": 4,
        },
    }
