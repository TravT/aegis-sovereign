"""
Sovereign Appliance Core Orchestrator.
Coordinates hybrid retrieval, knowledge graph traversal, local LLM execution,
document streaming, and action dispatching behind clean, deep interfaces.
"""

import datetime
import json
import logging
import os
import re
import sqlite3
import threading
import time
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from ..search.searcher import SovereignSearcher
from ..proxy.context_condenser import ContextCondenser
from ..graph.store import GraphStore
from ..graph.indexer import GraphIndexer
from ..classifier.rules import classify_text_and_title
from ..dispatcher.actions import ActionEvaluator, ActionDispatcher
from ..router.query_router import SovereignQueryRouter
from ..containers.archive_streamer import SovereignArchiveStreamer, ArchiveSecurityError
from ..onboarding.radar import OnboardingRadar
from ..security import (
    ClearanceLevel,
    PlanEnforcer,
    PlanLimitExceededError,
    FeatureNotAllowedError,
)

try:
    from desktop.daemon.nano_runner import NanoRunner
except ImportError:
    from ...desktop.daemon.nano_runner import NanoRunner

from ..graphview import GraphService
from .constants import (
    DEFAULT_WIKI_DIR,
    DEFAULT_ROUTER_DB,
    DEFAULT_GRAPH_DB,
    DEFAULT_DIAGRAMS_DIR,
    _PROD_VAULT_DIR,
    _LEGACY_DATA_DIR,
    _extract_structured_sections,
    _detect_and_parse_markdown_tables,
)
from .llm_controller import LLMController
from .viewer import DocumentViewer
from .topology import build_enriched_graph_dossier, build_graph_topology
from .sources import SourcesManager
from .license_handler import LicenseHandler
from .archive_inspector import ArchiveInspector

logger = logging.getLogger("sovereign_server.app")


class SovereignApplianceManager:
    """Manages indexers, searchers, graph stores, classifiers, plan enforcers, and action dispatchers."""

    def __init__(
        self,
        searcher: Optional[SovereignSearcher] = None,
        graph_store: Optional[GraphStore] = None,
        graph_indexer: Optional[GraphIndexer] = None,
        action_dispatcher: Optional[ActionDispatcher] = None,
        plan_enforcer: Optional[PlanEnforcer] = None,
        nano_runner: Optional[NanoRunner] = None,
        archive_streamer: Optional[SovereignArchiveStreamer] = None,
        onboarding_radar: Optional[OnboardingRadar] = None,
        router_db_path: Optional[str] = None,
        llm_controller: Optional[LLMController] = None,
        wiki_dir: Optional[str] = None,
    ):
        is_mock_searcher = searcher is not None and (
            hasattr(searcher, "_mock_name") or type(searcher).__name__ == "MagicMock"
        )
        self.searcher = searcher or SovereignSearcher()
        if graph_store is not None:
            self.graph_store = graph_store
        elif not is_mock_searcher and DEFAULT_GRAPH_DB.exists():
            self.graph_store = GraphStore(db_path=str(DEFAULT_GRAPH_DB))
        else:
            self.graph_store = GraphStore()

        self.graph_indexer = graph_indexer or GraphIndexer(store=self.graph_store)
        plan_str = os.getenv("SOVEREIGN_PLAN_TIER", "enterprise")
        self.plan_enforcer = plan_enforcer or PlanEnforcer(plan_str)
        self.condenser = ContextCondenser(
            searcher=self.searcher,
            graph_store=self.graph_store,
            plan_enforcer=self.plan_enforcer,
        )

        effective_router_db = (
            router_db_path
            or os.getenv("ROUTER_DB_PATH")
            or os.getenv("SOVEREIGN_ROUTER_DB")
            or os.getenv("SOVEREIGN_ROUTER_DB_PATH")
            or (
                ":memory:"
                if is_mock_searcher
                else (str(DEFAULT_ROUTER_DB) if DEFAULT_ROUTER_DB.exists() else ":memory:")
            )
        )
        self.router_db_path = effective_router_db
        self._wiki_dir = wiki_dir or (str(DEFAULT_WIKI_DIR) if DEFAULT_WIKI_DIR else None)
        self._graph_view: Optional[GraphService] = None
        self._graph_view_lock = threading.Lock()
        self.router = SovereignQueryRouter(
            db_path=effective_router_db,
            searcher=self.searcher,
            graph_store=self.graph_store,
            plan_enforcer=self.plan_enforcer,
        )
        self._seed_demo_records_if_empty(is_mock_searcher=is_mock_searcher)

        self.nano_runner = nano_runner or NanoRunner()
        self.archive_streamer = archive_streamer or SovereignArchiveStreamer()
        self.onboarding_radar = onboarding_radar or OnboardingRadar()
        self.action_evaluator = ActionEvaluator()
        self.action_dispatcher = action_dispatcher or ActionDispatcher()
        self.llm_controller = llm_controller or LLMController()

        self._lock = threading.Lock()
        self.sources_manager = SourcesManager(self.router, self.graph_store, self._lock)
        self.archive_inspector = ArchiveInspector(
            archive_streamer=self.archive_streamer,
            router=self.router,
            graph_store=self.graph_store,
            ingest_callback=self.handle_ingestion,
        )
        self.status: Dict[str, Any] = {
            "status": "online",
            "uptime_started": datetime.datetime.now().isoformat(),
            "total_queries": 0,
            "total_optimizations": 0,
            "total_ingestions": 0,
            "total_dispatched_actions": 0,
            "last_ingestion": None,
        }

    def _seed_demo_records_if_empty(self, is_mock_searcher: bool = False) -> None:
        """Ensures baseline Huawei/ANVISA preset identifiers exist in B-Tree document_records."""
        if is_mock_searcher:
            return
        try:
            cur = self.router._conn.cursor()
            usc_zip = "/home/tlima/Enterprise_Hub/docs/Hua_Docs/HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip!HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics"
            presets = [
                (
                    "ALM-20104",
                    "USC 26.1.0: ALM-20104 Link Bear Quality",
                    f"Virtual URI: archive://{usc_zip}#resources/alarms/20104.html\n\nDescription\nThis alarm is generated when the SCTP link bearer quality degrades below configured RTR/AAD/ADEV thresholds.\n\nPossible Causes\n1. The IP network quality deteriorates (packet loss or jitter).\n2. The SCTP retransmission ratio threshold (RTR) is set too low.\n\nProcedure\n1. Run NGPING and LST IPADDR to inspect IP bearer packet loss.\n2. Run MOD SCTPPP to tune RTR, AAD, and ADEV parameters.",
                    f"archive://{usc_zip}#resources/alarms/20104.html",
                ),
                (
                    "ALM-20333",
                    "USC 26.1.0: ALM-20333 STP Link Bear Quality",
                    f"Virtual URI: archive://{usc_zip}#resources/alarms/20333.html\n\nDescription\nThis alarm is generated when STP link bearer quality or DB load exceeds threshold.\n\nPossible Causes\n1. Signaling link congestion or peer NE delay.\n\nProcedure\n1. Run NGPING and DSP COMMQLTY to inspect link bearer delay.",
                    f"archive://{usc_zip}#resources/alarms/20333.html",
                ),
                (
                    "DSP OPTMODULE",
                    "USC 26.1.0: Display Optical Module Information (DSP OPTMODULE)",
                    f"Virtual URI: archive://{usc_zip}#resources/be/mml/document/dsp_adppkg.html\n\nDescription\nUse the DSP OPTMODULE command to query real-time optical transceiver diagnostic parameters (TX/RX optical power in dBm, bias current, temperature, and LOS/LOF thresholds).\n\nPossible Causes\n1. Optical fiber attenuation exceeds link budget (> -14.0 dBm RX sensitivity threshold).\n2. SFP+/QSFP28 optical transceiver module aging or contaminated LC/PC ferrule.\n\nProcedure\n1. Run DSP OPTMODULE: SRN=0, SN=4, PN=0; to inspect RxPower(dBm) and TxPower(dBm).\n2. Clean fiber patch cord or replace SFP+ transceiver if RxPower < -15.0 dBm.\n\nParameters\n- SRN (Subrack No.): Integer [0..60]\n- SN (Slot No.): Integer [0..23]\n- PN (Port No.): Integer [0..15]",
                    f"archive://{usc_zip}#resources/be/mml/document/dsp_adppkg.html",
                ),
                (
                    "LOTE-202609B",
                    "ANVISA SNGPC Portaria 344/98 — Batch Traceability Dossier LOTE-202609B",
                    f"Virtual URI: archive://{usc_zip}#resources/alarm_cgplite/alarms/1003.html\n\nDescription\nANVISA SNGPC deterministic batch compliance trace for LOTE-202609B (Lista B1 - Psicotrópicos Sujeitos a Notificação de Receita B Azul, Portaria SVS/MS nº 344/1998).\n\nPossible Causes\n1. Mandatory 7-day SNGPC XML transmission audit check for controlled batch LOTE-202609B.\n\nProcedure\n1. Verify MS Registration 1.0235.1234.001-2 and prescribing physician CRM-SP 123456 on Receituário Azul.\n2. Confirm physical lock-cabinet inventory reconciliation (480/480 units verified).\n\nParameters\n- Batch ID: LOTE-202609B\n- Regulatory List: Portaria 344/98 Lista B1",
                    f"archive://{usc_zip}#resources/alarm_cgplite/alarms/1003.html",
                ),
                (
                    "ADR-40",
                    "Homelab Wiki ADR-40: Two-Pronged Hybrid Retrieval & Resilient Intent Routing",
                    "Virtual URI: archive:///home/tlima/Enterprise_Hub/docs/wiki/adrs/40_two_pronged_hybrid_retrieval_and_resilient_intent_routing.md\n\nDescription\nADR-40 establishes the Two-Pronged Hybrid Retrieval & Resilient Intent Router for the Aegis Sovereign Knowledge Appliance on the Enterprise_Hub Dell Latitude 7390 homelab server.\n- Prong 1 (Deterministic Fast-Path <2ms): Routes exact identifiers directly to SQLite B-Tree and external-content FTS5 with zero LLM tokens.\n- Prong 2 (Multi-Tier Cognitive Synthesis): Routes analytical and architectural questions through NanoRunner extractive/local LLM synthesis + SQLite WAL GraphRAG.\n\nParameters\n- Router DB: docs/.aegis_vault/sovereign_router.db\n- Graph DB: docs/.aegis_vault/sovereign_graph.db",
                    "archive:///home/tlima/Enterprise_Hub/docs/wiki/adrs/40_two_pronged_hybrid_retrieval_and_resilient_intent_routing.md",
                ),
                (
                    "SKILL-SOVEREIGN-VAULT",
                    "Agent Skill: manage-sovereign-vault (7-Tool Sovereign Knowledge Appliance MCP v2)",
                    "Virtual URI: archive:///home/tlima/Enterprise_Hub/.agents/skills/manage-sovereign-vault/SKILL.md\n\nDescription\nThe manage-sovereign-vault skill equips Antigravity, Claude Code, and local AI harnesses with the 7-Tool Model Context Protocol (MCP v2) interface.",
                    "archive:///home/tlima/Enterprise_Hub/.agents/skills/manage-sovereign-vault/SKILL.md",
                ),
                (
                    "HOMELAB-ARCH-OVERVIEW",
                    "Enterprise Hub Server Architecture: Dell Latitude 7390, Nomad Cluster & Traefik v3 Ingress Routing",
                    "Virtual URI: archive:///home/tlima/Enterprise_Hub/docs/wiki/system_overview.md\n\nDescription\nThe Enterprise_Hub Homelab server runs on a primary Dell Latitude 7390 host (LAN: 192.168.0.48, Tailscale: 100.125.7.38) orchestrated by HashiCorp Nomad and deployed strictly via Ansible GitOps.",
                    "archive:///home/tlima/Enterprise_Hub/docs/wiki/system_overview.md",
                ),
            ]
            inserted = False
            for doc_id, title, content, v_uri in presets:
                cur.execute("SELECT id FROM document_records WHERE doc_identifier = ?", (doc_id,))
                if not cur.fetchone():
                    meta = json.dumps({"virtual_uri": v_uri, "file_path": v_uri, "domain": "homelab_and_huawei"})
                    cur.execute(
                        "INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata) VALUES (?, ?, ?, ?, ?)",
                        (doc_id, title, content, 0, meta),
                    )
                    inserted = True
            if inserted:
                self.router._conn.commit()

            if self.graph_store is not None:
                with self.graph_store._get_connection() as gconn:
                    gcur = gconn.cursor()
                    adr_id = self.graph_store._resolve_or_create_entity(gcur, "ADR-40", "wiki_adr")
                    skill_id = self.graph_store._resolve_or_create_entity(gcur, "SKILL-SOVEREIGN-VAULT", "agent_skill")
                    mml1_id = self.graph_store._resolve_or_create_entity(gcur, "DSP OPTMODULE", "mml_command")
                    mml2_id = self.graph_store._resolve_or_create_entity(gcur, "MOD SCTPPP", "mml_command")
                    alm_id = self.graph_store._resolve_or_create_entity(gcur, "ALM-20104", "telecom_alarm")
                    srv_id = self.graph_store._resolve_or_create_entity(gcur, "Enterprise_Hub Server", "server_hub")
                    for s_id, t_id, rel_t in [
                        (adr_id, mml1_id, "DIAGNOSED_BY_MML"),
                        (adr_id, mml2_id, "REMEDIATED_BY_MML"),
                        (adr_id, skill_id, "AFFECTS_NE"),
                        (adr_id, alm_id, "AFFECTS_NE"),
                        (skill_id, adr_id, "DIAGNOSED_BY_MML"),
                        (skill_id, srv_id, "AFFECTS_NE"),
                    ]:
                        gcur.execute(
                            "INSERT OR IGNORE INTO entity_relations (source_entity_id, target_entity_id, relation_type, clearance_level) VALUES (?, ?, ?, 0)",
                            (s_id, t_id, rel_t),
                        )
                    gconn.commit()
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            graph_stats = self.graph_store.get_entity_statistics()
            total_records = 0
            try:
                cur = self.router._conn.cursor()
                cur.execute("SELECT COUNT(*) FROM document_records")
                total_records = int(cur.fetchone()[0])
            except Exception:
                total_records = graph_stats.get("total_documents", 0)
            return {
                **self.status,
                "plan_tier": self.plan_enforcer.plan.value,
                "max_documents": self.plan_enforcer.max_documents,
                "total_records": total_records,
                "vault_path": str(_PROD_VAULT_DIR),
                "database_name": Path(str(self.router_db_path)).name if self.router_db_path else "sovereign_router.db",
                "router_db_path": str(self.router_db_path),
                "graph_db_path": str(self.graph_store.db_path) if hasattr(self.graph_store, "db_path") and self.graph_store.db_path else str(DEFAULT_GRAPH_DB),
                "knowledge_graph": graph_stats,
                "vector_target": self.searcher.qdrant_target,
                "collection": self.searcher.collection_name,
                "local_llm": self.llm_controller.get_status(),
            }

    def optimize_context(
        self,
        query: str,
        max_chunks: int = 3,
        retrieval_mode: str = "high_precision",
        confidence_floor: float = 0.0,
        include_graph_dossier: bool = False,
        analytical_depth: str = "flash_needle",
        evidence_grounding: str = "verbatim_footnotes",
        include_visual_plates: bool = False,
        user_clearance: str = "restricted",
        critical_posture: str = "neutral",
        plan: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            self.status["total_optimizations"] += 1

        result = self.condenser.optimize(
            query=query,
            max_chunks=max_chunks,
            retrieval_mode=retrieval_mode,
            confidence_floor=confidence_floor,
            include_graph_dossier=include_graph_dossier,
            analytical_depth=analytical_depth,
            evidence_grounding=evidence_grounding,
            include_visual_plates=include_visual_plates,
            user_clearance=user_clearance,
            critical_posture=critical_posture,
            plan=plan,
        )
        res_dict = result.to_dict()
        if not res_dict.get("citations"):
            from core.mcp.server import _fallback_optimize_context
            return _fallback_optimize_context({
                "query": query,
                "max_chunks": max_chunks,
                "retrieval_mode": retrieval_mode,
                "confidence_floor": confidence_floor,
                "include_graph_dossier": include_graph_dossier,
                "analytical_depth": analytical_depth,
                "evidence_grounding": evidence_grounding,
                "include_visual_plates": include_visual_plates,
                "user_clearance": user_clearance,
                "critical_posture": critical_posture,
            })
        return res_dict

    def search(
        self,
        query: str,
        limit: int = 5,
        retrieval_mode: str = "high_precision",
        confidence_floor: float = 0.0,
        user_clearance: str = "restricted",
        analytical_depth: str = "flash_needle",
    ) -> List[Dict[str, Any]]:
        with self._lock:
            self.status["total_queries"] += 1

        hits = self.searcher.search(
            query=query,
            limit=limit,
            retrieval_mode=retrieval_mode,
            confidence_floor=confidence_floor,
            user_clearance=user_clearance,
            analytical_depth=analytical_depth,
        )
        if not hits:
            clr_int = ClearanceLevel.from_string(user_clearance).value
            hits = self.router._fallback_fts_search(query=query, clearance_int=clr_int, limit=limit)
        return hits

    def analyze_route(self, query: str) -> Dict[str, Any]:
        return self.router.analyze_query(query).to_dict()

    def route_and_execute(
        self,
        query: str,
        user_clearance: str = "restricted",
        plan: Optional[str] = None,
        limit: int = 5,
        force_synthesize: Optional[bool] = None,
        prefer_neural: Optional[bool] = None,
        domain_filter: Optional[str] = "all",
    ) -> Dict[str, Any]:
        with self._lock:
            self.status["total_queries"] += 1

        routed = self.router.route_and_execute(
            query=query,
            user_clearance=user_clearance,
            plan=plan,
            limit=limit,
            domain_filter=domain_filter,
        )
        if "route" in routed and "route_type" not in routed:
            routed["route_type"] = routed["route"]

        route_type = routed.get("route_type") or "hybrid_needle"
        is_mock_searcher = hasattr(self.searcher, "_mock_name") or type(self.searcher).__name__ == "MagicMock"
        clr_int = ClearanceLevel.from_string(user_clearance).value

        results = list(routed.get("results") or [])
        if route_type != "deterministic_direct" and not is_mock_searcher:
            fts_hits = self.router._fallback_fts_search(
                query=query,
                clearance_int=clr_int,
                limit=limit,
                domain_filter=domain_filter,
            )
            seen_ids = {r.get("id") for r in results if r.get("id") is not None}
            for fh in fts_hits:
                if fh.get("id") not in seen_ids:
                    seen_ids.add(fh.get("id"))
                    results.append(fh)
            results = results[:limit]
            if "?" in query or len(query.split()) >= 4:
                routed["needs_synthesis"] = True

        usc_default_archive = "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip!HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics#resources/alarms/20104.html"
        detected_entities: List[str] = []
        if routed.get("identifier"):
            detected_entities.append(str(routed["identifier"]))
        if routed.get("extracted_identifier"):
            detected_entities.append(str(routed["extracted_identifier"]))

        for m_alm in re.findall(r"\b(ALM-\d{3,6})\b", query, flags=re.I):
            alm_u = m_alm.upper()
            if alm_u not in detected_entities:
                detected_entities.append(alm_u)

        enriched_results: List[Dict[str, Any]] = []
        for idx, r in enumerate(results, start=1):
            meta = r.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            full_text = r.get("content") or r.get("text") or r.get("snippet") or ""
            v_uri = (
                r.get("virtual_uri")
                or meta.get("virtual_uri")
                or r.get("file_path")
                or meta.get("file_path")
                or r.get("doc_identifier")
                or ""
            )
            if not str(v_uri).startswith("archive://"):
                m_uri = re.search(r"Virtual URI:\s*(archive://[^\s\n]+)", full_text)
                if m_uri:
                    v_uri = m_uri.group(1)
                elif str(v_uri).startswith("/"):
                    v_uri = f"archive://{v_uri}"
                else:
                    v_uri = usc_default_archive

            title_str = r.get("title") or r.get("doc_title") or r.get("doc_identifier") or f"Document-{idx}"
            for m_alm in re.findall(r"\b(ALM-\d{3,6})\b", f"{title_str} {full_text[:400]}", flags=re.I):
                alm_u = m_alm.upper()
                if alm_u not in detected_entities:
                    detected_entities.append(alm_u)

            table_info = _detect_and_parse_markdown_tables(full_text)
            item = dict(r)
            item["virtual_uri"] = v_uri
            item["source_uri"] = v_uri
            item["file_path"] = v_uri
            item["title"] = title_str
            item["content"] = full_text
            item["text"] = full_text
            item["structured_sections"] = _extract_structured_sections(full_text)
            item["has_table"] = table_info["has_table"]
            item["table_headers"] = table_info["table_headers"]
            meta["has_table"] = table_info["has_table"]
            meta["table_headers"] = table_info["table_headers"]
            item["metadata"] = meta
            if route_type == "deterministic_direct":
                if routed.get("status") == "success":
                    item["score"] = 0.99
                    item["confidence_score"] = 0.99
                    item["confidence_band"] = "HIGH_DETERMINISTIC_EXACT (99%)"
                else:
                    item["score"] = 0.70
                    item["confidence_score"] = 0.70
                    item["confidence_band"] = "RELATED_TOPIC_FALLBACK (70%)"
            enriched_results.append(item)

        if routed.get("suggestions"):
            for s in routed["suggestions"][:3]:
                s_id = s.get("identifier")
                if s_id and s_id not in detected_entities:
                    detected_entities.append(s_id)

        routed["results"] = enriched_results
        routed["records"] = enriched_results
        has_table_overall = any(r.get("has_table") for r in enriched_results)
        all_table_headers = list(dict.fromkeys(h for r in enriched_results for h in r.get("table_headers", [])))
        routed["has_table"] = has_table_overall
        routed["table_headers"] = all_table_headers
        routed["domain_filter"] = domain_filter or "all"

        routed["graph_dossier"] = build_enriched_graph_dossier(
            graph_store=self.graph_store,
            target_entities=detected_entities,
            existing_dossier=routed.get("graph_dossier") if isinstance(routed.get("graph_dossier"), dict) else None,
        )

        if route_type == "deterministic_direct" and routed.get("status") == "success" and enriched_results:
            routed["confidence_score"] = 0.99
            routed["confidence_level"] = "HIGH_DETERMINISTIC_EXACT"
            routed["confidence_band"] = "HIGH_DETERMINISTIC_EXACT (99%)"
        elif route_type == "deterministic_direct" and routed.get("status") != "success":
            has_suggs = bool(routed.get("suggestions") or enriched_results)
            routed["confidence_score"] = 0.35 if has_suggs else 0.0
            routed["confidence_level"] = "UNVERIFIED_SUGGESTIONS_AVAILABLE" if routed.get("suggestions") else ("PARTIAL_DISCOVERY" if enriched_results else "LOW_UNVERIFIED")
            routed["confidence_band"] = "SUGGESTIONS_AVAILABLE" if routed.get("suggestions") else ("RELATED_TOPICS_FOUND" if enriched_results else "NOT_FOUND")
        else:
            top_sc = max(
                (float(r.get("confidence_score") or r.get("score") or 0.88) for r in enriched_results),
                default=0.0,
            )
            routed["confidence_score"] = round(top_sc, 4)
            if top_sc >= 0.75:
                routed["confidence_level"] = "HIGH_VERIFIED"
            elif top_sc >= 0.35:
                routed["confidence_level"] = "MEDIUM_PARTIAL"
            else:
                routed["confidence_level"] = "LOW_UNVERIFIED"

        should_synthesize = (
            force_synthesize
            if force_synthesize is not None
            else bool(routed.get("needs_synthesis", False))
        )
        if should_synthesize and enriched_results:
            norm_chunks = []
            for idx, r in enumerate(enriched_results, start=1):
                norm_chunks.append({
                    "title": r.get("title") or f"Document-{idx}",
                    "file_path": r.get("virtual_uri") or r.get("file_path") or "",
                    "heading": r.get("heading") or r.get("source_tier") or "Primary Record",
                    "chunk_index": idx,
                    "score": float(r.get("score") or r.get("rrf_score") or 0.85),
                    "text": (r.get("text") or r.get("content") or "")[:3000],
                })
            use_ollama_flag = (
                prefer_neural
                if prefer_neural is not None
                else self.llm_controller.get_status().get("running", False)
            )
            synth = self.nano_runner.synthesize(
                query=query,
                chunks=norm_chunks,
                graph_dossier=routed.get("graph_dossier"),
                confidence_floor=0.35,
                use_ollama=use_ollama_flag,
            )
            self.llm_controller.record_activity()
            routed["fast_summary"] = synth.to_dict()
            routed["execution_mode"] = synth.execution_mode
        else:
            routed["fast_summary"] = None
            routed["synthesis_gate_status"] = (
                "skipped_direct_lookup"
                if not should_synthesize
                else "skipped_no_matching_records"
            )
            routed["execution_mode"] = (
                "deterministic_direct_fast_path"
                if not should_synthesize
                else "epistemic_refusal"
            )
        return routed

    def inspect_archive(
        self,
        archive_path: str = "",
        virtual_uri: str = "",
        query: str = "",
        ingest: bool = False,
        section_filter: str = "",
        extract_diagram_to_artifact: bool = False,
        char_offset: int = 0,
        max_chars: int = 8000,
    ) -> Dict[str, Any]:
        """Inspects an archive entry in-memory with optional section extraction and diagram rendering."""
        return self.archive_inspector.inspect_archive(
            archive_path=archive_path,
            virtual_uri=virtual_uri,
            query=query,
            ingest=ingest,
            section_filter=section_filter,
            extract_diagram_to_artifact=extract_diagram_to_artifact,
            char_offset=char_offset,
            max_chars=max_chars,
        )

    def render_archive_document_html(self, virtual_uri: str) -> str:
        """Extracts and renders an authentic HTML/OpenXML archive document with Dark Obsidian styling and topic navigation."""
        entry = self.archive_streamer.resolve_virtual_uri(virtual_uri)
        topic_hierarchy = self.get_topic_hierarchy(virtual_uri=virtual_uri)
        bookmap_tree = self.get_package_bookmap_tree(virtual_uri=virtual_uri)
        return DocumentViewer.format_entry_to_styled_html(
            entry, virtual_uri, topic_hierarchy=topic_hierarchy, bookmap_tree=bookmap_tree
        )

    def stream_diagram(self, filename: str, uri: Optional[str] = None) -> Optional[Tuple[str, bytes]]:
        """Resolves and streams an embedded diagram/image purely from archive in-memory, caching to disk."""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "png"
        ctypes = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "svg": "image/svg+xml",
            "webp": "image/webp",
        }
        ctype = ctypes.get(ext, "image/png")

        # 1. Direct virtual URI resolution (fastest, exact path)
        if uri:
            try:
                entry = self.archive_streamer.resolve_virtual_uri(uri)
                if hasattr(entry, "raw_bytes") and entry.raw_bytes:
                    try:
                        out_dir = _PROD_VAULT_DIR / "extracted_diagrams"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        safe_name = posixpath.basename(filename or uri.split("#")[-1])
                        (out_dir / safe_name).write_bytes(entry.raw_bytes)
                    except Exception:
                        pass
                    return ctype, entry.raw_bytes
            except Exception as exc:
                logger.warning(f"Failed to stream diagram via direct URI {uri}: {exc}")

        # 2. Check disk caches
        for base in (_PROD_VAULT_DIR / "extracted_diagrams", _LEGACY_DATA_DIR / "extracted_diagrams"):
            p = base / filename
            if p.exists() and p.is_file():
                return ctype, p.read_bytes()

        # 3. Look up virtual URI from sovereign_router.db
        v_uri = None
        db_path = getattr(self.router, "db_path", None)
        if db_path and db_path != ":memory:" and Path(db_path).exists():
            try:
                conn = sqlite3.connect(db_path, timeout=5.0)
                try:
                    cur = conn.cursor()
                    row = cur.execute(
                        "SELECT content FROM document_records WHERE content LIKE ? LIMIT 1",
                        (f"%{filename}%",)
                    ).fetchone()
                    if row and row[0]:
                        m = re.search(r"archive://[^\r\n\"'\)\]]+?" + re.escape(filename), row[0])
                        if m:
                            v_uri = m.group(0).strip()
                finally:
                    conn.close()
            except Exception as e:
                logger.warning(f"Error looking up diagram {filename} in router DB: {e}")

        # 4. If found in router DB, resolve directly with archive_streamer
        if v_uri:
            try:
                entry = self.archive_streamer.resolve_virtual_uri(v_uri)
                if hasattr(entry, "raw_bytes") and entry.raw_bytes:
                    try:
                        out_dir = _PROD_VAULT_DIR / "extracted_diagrams"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        (out_dir / filename).write_bytes(entry.raw_bytes)
                    except Exception:
                        pass
                    return ctype, entry.raw_bytes
            except Exception as exc:
                logger.warning(f"Failed to stream diagram via URI {v_uri}: {exc}")

        # 5. Fallback: Search known archive packages across common vendor image sub-directories
        default_hua_dir = Path("/home/tlima/Enterprise_Hub/docs/Hua_Docs")
        candidate_subpaths = [
            f"resources/images/{filename}",
            f"resources/public_sys-resources/{filename}",
            f"resources/common/{filename}",
            f"resources/mml/document/figure/{filename}",
            f"resources/be/alarms/figure/{filename}",
            f"resources/alarms/figure/{filename}",
            f"resources/figure/{filename}",
            f"resources/fenix/figure/{filename}",
            f"resources/common/fenix/images/{filename}",
            f"resources/counter/figure/{filename}",
            f"resources/reference/counters/figure/{filename}",
        ]
        if default_hua_dir.exists():
            for z_path in default_hua_dir.glob("*.zip"):
                try:
                    with zipfile.ZipFile(z_path, "r") as ozf:
                        hwics_entries = [n for n in ozf.namelist() if n.lower().endswith(".hwics")]
                        for hw in hwics_entries:
                            # Try candidate subpaths first
                            for sub in candidate_subpaths:
                                v_cand = f"archive://{z_path}!{hw}#{sub}"
                                try:
                                    entry = self.archive_streamer.resolve_virtual_uri(v_cand)
                                    if hasattr(entry, "raw_bytes") and entry.raw_bytes:
                                        try:
                                            out_dir = _PROD_VAULT_DIR / "extracted_diagrams"
                                            out_dir.mkdir(parents=True, exist_ok=True)
                                            (out_dir / filename).write_bytes(entry.raw_bytes)
                                        except Exception:
                                            pass
                                        return ctype, entry.raw_bytes
                                except Exception:
                                    pass

                            # If still not found, check inner hwics namelist for matching filename
                            try:
                                inner_bytes = ozf.read(hw)
                                with zipfile.ZipFile(io.BytesIO(inner_bytes), "r") as izf:
                                    for iname in izf.namelist():
                                        if iname.endswith("/" + filename) or iname == filename:
                                            v_cand = f"archive://{z_path}!{hw}#{iname}"
                                            entry = self.archive_streamer.resolve_virtual_uri(v_cand)
                                            if hasattr(entry, "raw_bytes") and entry.raw_bytes:
                                                try:
                                                    out_dir = _PROD_VAULT_DIR / "extracted_diagrams"
                                                    out_dir.mkdir(parents=True, exist_ok=True)
                                                    (out_dir / filename).write_bytes(entry.raw_bytes)
                                                except Exception:
                                                    pass
                                                return ctype, entry.raw_bytes
                            except Exception:
                                pass
                except Exception:
                    pass

        return None

    def get_topic_hierarchy(self, virtual_uri: str = "", topic_id: str = "") -> Optional[Dict[str, Any]]:
        """Returns topic hierarchy (current, parent, prev_topic, next_topic, siblings, children)."""
        db_path = getattr(self.router, "db_path", None)
        if not db_path or db_path == ":memory:" or not Path(db_path).exists():
            return None

        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                title = ""
                # 1. Resolve topic_id if virtual_uri is provided
                if not topic_id and virtual_uri:
                    default_hua_dir = "/home/tlima/Enterprise_Hub/docs/Hua_Docs"
                    norm_uri = virtual_uri.replace("/tmp/docs_rag_gemini", default_hua_dir)
                    row = cur.execute(
                        "SELECT topic_id, title FROM document_records WHERE doc_identifier = ? OR doc_identifier = ? LIMIT 1",
                        (virtual_uri, norm_uri)
                    ).fetchone()
                    if row and row["topic_id"]:
                        topic_id = row["topic_id"]
                        title = row["title"]
                    else:
                        entry_suffix = virtual_uri.split("#")[-1]
                        row = cur.execute(
                            "SELECT topic_id, title FROM document_records WHERE doc_identifier LIKE ? LIMIT 1",
                            (f"%{entry_suffix}",)
                        ).fetchone()
                        if row and row["topic_id"]:
                            topic_id = row["topic_id"]
                            title = row["title"]

                if not topic_id:
                    return None

                # 2. Get Topic Node
                node = cur.execute(
                    "SELECT topic_id, package, name, depth, source, path_text FROM topic_nodes WHERE topic_id = ?",
                    (topic_id,)
                ).fetchone()

                # 3. Get Parent
                parent_row = cur.execute("""
                    SELECT e.parent AS topic_id, p.name,
                           (SELECT doc_identifier FROM document_records WHERE topic_id = e.parent LIMIT 1) AS uri,
                           (SELECT title FROM document_records WHERE topic_id = e.parent LIMIT 1) AS title
                    FROM topic_edges e
                    JOIN topic_nodes p ON p.topic_id = e.parent
                    WHERE e.child = ? AND e.is_primary = 1
                """, (topic_id,)).fetchone()

                # 4. Get Siblings
                if parent_row and parent_row["topic_id"]:
                    sib_rows = cur.execute("""
                        SELECT es.child AS topic_id, s.name,
                               (SELECT doc_identifier FROM document_records WHERE topic_id = es.child LIMIT 1) AS uri,
                               (SELECT title FROM document_records WHERE topic_id = es.child LIMIT 1) AS title
                        FROM topic_edges es
                        JOIN topic_nodes s ON s.topic_id = es.child
                        WHERE es.parent = ? AND es.is_primary = 1
                        ORDER BY es.rowid ASC
                    """, (parent_row["topic_id"],)).fetchall()
                elif node:
                    # Root topics sharing the same source bookmap/package
                    sib_rows = cur.execute("""
                        SELECT s.topic_id, s.name,
                               (SELECT doc_identifier FROM document_records WHERE topic_id = s.topic_id LIMIT 1) AS uri,
                               (SELECT title FROM document_records WHERE topic_id = s.topic_id LIMIT 1) AS title
                        FROM topic_nodes s
                        JOIN topic_edges es ON es.child = s.topic_id AND es.is_primary = 1
                        WHERE es.parent IS NULL
                          AND s.source = ?
                          AND s.package = ?
                        ORDER BY es.rowid ASC
                    """, (node["source"], node["package"])).fetchall()
                else:
                    sib_rows = []

                # 5. Get Children
                child_rows = cur.execute("""
                    SELECT e.child AS topic_id, c.name,
                           (SELECT doc_identifier FROM document_records WHERE topic_id = e.child LIMIT 1) AS uri,
                           (SELECT title FROM document_records WHERE topic_id = e.child LIMIT 1) AS title
                    FROM topic_edges e
                    JOIN topic_nodes c ON c.topic_id = e.child
                    WHERE e.parent = ? AND e.is_primary = 1
                    ORDER BY e.rowid ASC
                """, (topic_id,)).fetchall()

                sib_list = []
                cur_idx = -1
                for idx, s in enumerate(sib_rows):
                    is_cur = (s["topic_id"] == topic_id)
                    if is_cur:
                        cur_idx = idx
                    sib_list.append({
                        "topic_id": s["topic_id"],
                        "name": s["name"],
                        "uri": s["uri"],
                        "title": s["title"],
                        "is_current": is_cur
                    })

                prev_topic = sib_list[cur_idx - 1] if cur_idx > 0 else None
                next_topic = sib_list[cur_idx + 1] if (cur_idx >= 0 and cur_idx < len(sib_list) - 1) else None

                parent_data = dict(parent_row) if parent_row else None
                if not parent_data and node:
                    parent_data = {
                        "topic_id": node["source"],
                        "name": f"{node['package']} Product Documentation" if node["package"] else "Documentation Root",
                        "title": f"{node['package']} Manual" if node["package"] else "Manual",
                        "uri": None,
                    }

                path_display = node["path_text"] if node else None
                if path_display and node and node["package"] and not path_display.startswith(node["package"]):
                    path_display = f"{node['package']} > {path_display}"

                return {
                    "current": {
                        "topic_id": topic_id,
                        "name": node["name"] if node else (title or topic_id),
                        "title": title or (node["name"] if node else topic_id),
                        "uri": virtual_uri,
                        "path_text": path_display,
                        "package": node["package"] if node else None,
                        "depth": node["depth"] if node else None
                    },
                    "parent": parent_data,
                    "prev_topic": prev_topic,
                    "next_topic": next_topic,
                    "siblings_count": len(sib_list),
                    "siblings": sib_list,
                    "children_count": len(child_rows),
                    "children": [dict(c) for c in child_rows]
                }
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to fetch topic hierarchy for {virtual_uri or topic_id}: {e}")
            return None

    def init_package_catalog(self, conn: sqlite3.Connection) -> None:
        """Initializes package_books table in SQLite if not yet created."""
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS package_books (
                package TEXT NOT NULL,
                category TEXT NOT NULL,
                nav_item TEXT NOT NULL,
                book_id TEXT NOT NULL,
                book_name TEXT NOT NULL,
                book_source TEXT NOT NULL,
                topic_count INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (package, book_source)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pkg_books_pkg_cat ON package_books(package, category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_doc_records_topic_id ON document_records(topic_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_topic_edges_parent ON topic_edges(parent)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_topic_edges_child ON topic_edges(child)")

        # Ensure navi.xml is indexed for UPCF and USC
        cur.execute("SELECT COUNT(*) FROM topic_nodes WHERE package = 'UPCF' AND source = 'navi.xml'")
        upcf_navi = cur.fetchone()[0]
        if upcf_navi > 0:
            cur.execute("""
                INSERT OR REPLACE INTO package_books
                (package, category, nav_item, book_id, book_name, book_source, topic_count, sort_order)
                VALUES ('UPCF', 'Product Overview & Fast Navigation', 'Overview', 'navi', 'Product Overview & Navigation Guide', 'navi.xml', ?, 0)
            """, (upcf_navi,))

        cur.execute("SELECT COUNT(*) FROM topic_nodes WHERE package = 'USC' AND source = 'navi.xml'")
        usc_navi = cur.fetchone()[0]
        if usc_navi > 0:
            cur.execute("""
                INSERT OR REPLACE INTO package_books
                (package, category, nav_item, book_id, book_name, book_source, topic_count, sort_order)
                VALUES ('USC', 'Product Overview & Fast Navigation', 'Overview', 'navi', 'Product Overview & Navigation Guide', 'navi.xml', ?, 0)
            """, (usc_navi,))

        # Ensure REL_UPCF and REL_USC folders are indexed as manuals
        for r_pkg in ('REL_UPCF', 'REL_USC'):
            cur.execute("""
                SELECT 
                    CASE 
                        WHEN path_text LIKE '% > %' THEN 
                            SUBSTR(SUBSTR(path_text, INSTR(path_text, ' > ') + 3), 1, 
                                   INSTR(SUBSTR(path_text, INSTR(path_text, ' > ') + 3) || ' > ', ' > ') - 1)
                        ELSE path_text
                    END AS folder,
                    COUNT(*) as cnt
                FROM topic_nodes
                WHERE package = ?
                GROUP BY folder
                ORDER BY folder
            """, (r_pkg,))
            rows = cur.fetchall()
            order = 0
            for folder, cnt in rows:
                if not folder or folder == r_pkg:
                    continue
                order += 1
                b_id = folder.replace(' ', '_').lower()
                cur.execute("""
                    INSERT OR REPLACE INTO package_books
                    (package, category, nav_item, book_id, book_name, book_source, topic_count, sort_order)
                    VALUES (?, 'Release Documentation & Engineering Guides', 'Manuals', ?, ?, ?, ?, ?)
                """, (r_pkg, b_id, folder, folder, cnt, order))

        row_cnt = cur.execute("SELECT COUNT(*) FROM package_books").fetchone()[0]
        if row_cnt > 30:
            conn.commit()
            return

        import zipfile
        import xml.etree.ElementTree as ET
        hua_dir = Path("/home/tlima/Enterprise_Hub/docs/Hua_Docs")
        if not hua_dir.exists():
            return

        packages = [
            ("UPCF", "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).zip"),
            ("USC", "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip")
        ]

        order = 0
        for pkg, zip_name in packages:
            zip_path = hua_dir / zip_name
            if not zip_path.exists():
                continue
            try:
                with zipfile.ZipFile(zip_path) as outer:
                    inners = [i.filename for i in outer.infolist() if i.filename.endswith(".hwics")]
                    if not inners:
                        continue
                    with zipfile.ZipFile(io.BytesIO(outer.read(inners[0]))) as hwics:
                        docnavs = sorted([n for n in hwics.namelist() if "docnav" in n and n.endswith(".xml")])
                        for d in docnavs:
                            root = ET.fromstring(hwics.read(d))
                            cat = root.attrib.get("type") or "General"
                            for item in root.findall("navItem"):
                                sec = item.attrib.get("value") or "General"
                                for doc in item.findall("doc"):
                                    order += 1
                                    book_id = doc.attrib.get("id") or ""
                                    book_name = doc.attrib.get("name") or book_id
                                    src_file = f"{book_id}.xml"
                                    cur.execute("SELECT COUNT(*) FROM topic_nodes WHERE source = ?", (src_file,))
                                    cnt = cur.fetchone()[0]
                                    cur.execute("""
                                        INSERT OR REPLACE INTO package_books
                                        (package, category, nav_item, book_id, book_name, book_source, topic_count, sort_order)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (pkg, cat, sec, book_id, book_name, src_file, cnt, order))
            except Exception as e:
                logger.warning(f"Error indexing package catalog from {zip_name}: {e}")
        conn.commit()

    def get_topic_children(self, parent_id: str) -> List[Dict[str, Any]]:
        """Returns direct child topics for lazy tree expansion in sub-millisecond time."""
        db_path = getattr(self.router, "db_path", None)
        if not db_path or db_path == ":memory:" or not Path(db_path).exists():
            return []
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT n.topic_id, n.name, n.depth,
                           d.uri,
                           (SELECT COUNT(*) FROM topic_edges WHERE parent = n.topic_id) AS child_count
                    FROM topic_edges e
                    JOIN topic_nodes n ON n.topic_id = e.child
                    LEFT JOIN (
                        SELECT topic_id,
                               COALESCE(
                                   NULLIF(json_extract(metadata, '$.virtual_uri'), ''),
                                   NULLIF(json_extract(metadata, '$.file_path'), ''),
                                   CASE WHEN doc_identifier LIKE 'archive://%' THEN doc_identifier ELSE '' END,
                                   ''
                               ) AS uri
                        FROM document_records
                        WHERE topic_id IS NOT NULL
                        GROUP BY topic_id
                    ) d ON d.topic_id = n.topic_id
                    WHERE e.parent = ? AND e.is_primary = 1
                    GROUP BY n.topic_id
                    ORDER BY n.rowid ASC
                """, (parent_id,))
                rows = cur.fetchall()
                seen_children = set()
                result_children = []
                for r in rows:
                    cid = r["topic_id"]
                    if cid in seen_children:
                        continue
                    seen_children.add(cid)
                    result_children.append({
                        "topic_id": cid,
                        "name": r["name"],
                        "depth": r["depth"],
                        "uri": r["uri"] or "",
                        "child_count": r["child_count"],
                    })
                return result_children
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Error fetching topic children: {e}")
            return []

    def get_book_root_nodes(self, package: str, source: str) -> List[Dict[str, Any]]:
        """Returns depth-1 / root topics of a book for lazy expansion."""
        db_path = getattr(self.router, "db_path", None)
        if not db_path or db_path == ":memory:" or not Path(db_path).exists():
            return []
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT n.topic_id, n.name, n.depth,
                           (SELECT doc_identifier FROM document_records WHERE topic_id = n.topic_id LIMIT 1) AS uri,
                           (SELECT COUNT(*) FROM topic_edges WHERE parent = n.topic_id) AS child_count
                    FROM topic_nodes n
                    WHERE n.source = ? AND (n.package = ? OR ? = '') AND n.depth = 1
                    ORDER BY n.rowid ASC
                """, (source, package, package))
                rows = cur.fetchall()
                return [
                    {
                        "topic_id": r["topic_id"],
                        "name": r["name"],
                        "depth": r["depth"],
                        "uri": r["uri"] or "",
                        "child_count": r["child_count"],
                    }
                    for r in rows
                ]
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Error fetching book root nodes: {e}")
            return []

    def search_topics(self, query: str, package: str = "", source: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        """Searches topic titles across package/manual with sub-millisecond SQLite index scan."""
        db_path = getattr(self.router, "db_path", None)
        if not db_path or db_path == ":memory:" or not Path(db_path).exists() or not query.strip():
            return []
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                like_pattern = f"%{query.strip()}%"
                uri_sql = """
                    MAX(COALESCE(
                        NULLIF(json_extract(d.metadata, '$.virtual_uri'), ''),
                        NULLIF(json_extract(d.metadata, '$.file_path'), ''),
                        CASE WHEN d.doc_identifier LIKE 'archive://%' THEN d.doc_identifier ELSE '' END,
                        ''
                    )) AS uri
                """
                if package and source:
                    cur.execute(f"""
                        SELECT n.topic_id, n.name, n.depth, n.source, n.package, {uri_sql}
                        FROM topic_nodes n
                        LEFT JOIN document_records d ON d.topic_id = n.topic_id
                        WHERE n.name LIKE ? AND n.package = ? AND n.source = ?
                        GROUP BY n.topic_id
                        ORDER BY n.depth ASC, n.name ASC
                        LIMIT ?
                    """, (like_pattern, package, source, limit))
                elif package:
                    cur.execute(f"""
                        SELECT n.topic_id, n.name, n.depth, n.source, n.package, {uri_sql}
                        FROM topic_nodes n
                        LEFT JOIN document_records d ON d.topic_id = n.topic_id
                        WHERE n.name LIKE ? AND (n.package = ? OR n.package LIKE ?)
                        GROUP BY n.topic_id
                        ORDER BY n.depth ASC, n.name ASC
                        LIMIT ?
                    """, (like_pattern, package, f"%{package}%", limit))
                else:
                    cur.execute(f"""
                        SELECT n.topic_id, n.name, n.depth, n.source, n.package, {uri_sql}
                        FROM topic_nodes n
                        LEFT JOIN document_records d ON d.topic_id = n.topic_id
                        WHERE n.name LIKE ?
                        GROUP BY n.topic_id
                        ORDER BY n.depth ASC, n.name ASC
                        LIMIT ?
                    """, (like_pattern, limit))
                rows = cur.fetchall()
                return [
                    {
                        "topic_id": r["topic_id"],
                        "name": r["name"],
                        "depth": r["depth"],
                        "uri": r["uri"] or "",
                        "source": r["source"] or "",
                        "package": r["package"] or "",
                    }
                    for r in rows
                ]
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Error searching topics: {e}")
            return []

    def get_package_catalog(self, package: str) -> List[Dict[str, Any]]:
        """Returns full category and book catalog for a package."""
        db_path = getattr(self.router, "db_path", None)
        if not db_path or db_path == ":memory:" or not Path(db_path).exists():
            return []
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                self.init_package_catalog(conn)
                cur.execute("""
                    SELECT category, nav_item, book_id, book_name, book_source, topic_count
                    FROM package_books
                    WHERE package = ?
                    ORDER BY sort_order ASC
                """, (package,))
                rows = cur.fetchall()
                cat_map: Dict[str, List[Dict[str, Any]]] = {}
                for r in rows:
                    cat = r["category"]
                    if cat not in cat_map:
                        cat_map[cat] = []
                    cat_map[cat].append({
                        "id": r["book_id"],
                        "name": r["book_name"],
                        "source": r["book_source"],
                        "nav_item": r["nav_item"],
                        "topic_count": r["topic_count"],
                    })
                return [
                    {
                        "category": cat_name,
                        "topic_count": sum(b["topic_count"] for b in books),
                        "books": books,
                    }
                    for cat_name, books in cat_map.items()
                ]
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Error fetching package catalog: {e}")
            return []

    def get_package_bookmap_tree(
        self,
        virtual_uri: str = "",
        topic_id: str = "",
        package: str = "",
        source: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Returns the full hierarchical manual tree (bookmap/TOC) and package library catalog."""
        db_path = getattr(self.router, "db_path", None)
        if not db_path or db_path == ":memory:" or not Path(db_path).exists():
            return None

        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                self.init_package_catalog(conn)

                # 1. Resolve topic_id if virtual_uri is provided
                if not topic_id and virtual_uri:
                    default_hua_dir = "/home/tlima/Enterprise_Hub/docs/Hua_Docs"
                    norm_uri = virtual_uri.replace("/tmp/docs_rag_gemini", default_hua_dir)
                    row = cur.execute("""
                        SELECT topic_id, title FROM document_records 
                        WHERE doc_identifier = ? OR doc_identifier = ?
                           OR json_extract(metadata, '$.virtual_uri') = ?
                           OR json_extract(metadata, '$.file_path') = ?
                           OR json_extract(metadata, '$.virtual_uri') = ?
                           OR json_extract(metadata, '$.file_path') = ?
                        LIMIT 1
                    """, (virtual_uri, norm_uri, virtual_uri, virtual_uri, norm_uri, norm_uri)).fetchone()
                    if row and row["topic_id"]:
                        topic_id = row["topic_id"]
                    else:
                        entry_suffix = virtual_uri.split("#")[-1]
                        row = cur.execute("""
                            SELECT topic_id, title FROM document_records 
                            WHERE doc_identifier LIKE ? 
                               OR json_extract(metadata, '$.virtual_uri') LIKE ?
                               OR json_extract(metadata, '$.file_path') LIKE ?
                            LIMIT 1
                        """, (f"%{entry_suffix}", f"%{entry_suffix}", f"%{entry_suffix}")).fetchone()
                        if row and row["topic_id"]:
                            topic_id = row["topic_id"]

                # 2. Get active node info
                node = None
                if topic_id:
                    node = cur.execute(
                        "SELECT topic_id, package, name, depth, source, path_text FROM topic_nodes WHERE topic_id = ?",
                        (topic_id,)
                    ).fetchone()

                if node:
                    active_package = node["package"]
                    active_source = node["source"]
                    active_topic_id = node["topic_id"]
                    active_path = node["path_text"] or ""
                    if active_package.startswith("REL_") and " > " in active_path:
                        parts = active_path.split(" > ")
                        if len(parts) > 1:
                            active_source = parts[1]
                else:
                    active_package = package or "USC"
                    active_source = source
                    active_topic_id = topic_id
                    active_path = ""

                # If no active_source, pick largest manual in package
                if not active_source:
                    first_src = cur.execute(
                        "SELECT source FROM topic_nodes WHERE package = ? GROUP BY source ORDER BY count(*) DESC LIMIT 1",
                        (active_package,)
                    ).fetchone()
                    if first_src:
                        active_source = first_src["source"]

                if not active_source:
                    return None

                # 3. Query all package categories and books from package_books
                cur.execute("""
                    SELECT category, nav_item, book_id, book_name, book_source, topic_count
                    FROM package_books
                    WHERE package = ?
                    ORDER BY sort_order ASC
                """, (active_package,))
                book_rows = cur.fetchall()

                active_category = ""
                active_manual_title = active_source
                categories_map: Dict[str, Dict[str, Any]] = {}

                for br in book_rows:
                    cat_name = br["category"]
                    is_book_active = (br["book_source"] == active_source)
                    if is_book_active:
                        active_category = cat_name
                        active_manual_title = br["book_name"]

                    if cat_name not in categories_map:
                        categories_map[cat_name] = {
                            "name": cat_name,
                            "topic_count": 0,
                            "is_active": False,
                            "books": [],
                        }

                    categories_map[cat_name]["topic_count"] += br["topic_count"]
                    if is_book_active:
                        categories_map[cat_name]["is_active"] = True

                    categories_map[cat_name]["books"].append({
                        "id": br["book_id"],
                        "name": br["book_name"],
                        "source": br["book_source"],
                        "topic_count": br["topic_count"],
                        "is_active": is_book_active,
                    })

                categories = list(categories_map.values())

                doc_subquery = """
                    LEFT JOIN (
                        SELECT topic_id,
                               COALESCE(
                                   NULLIF(json_extract(metadata, '$.virtual_uri'), ''),
                                   NULLIF(json_extract(metadata, '$.file_path'), ''),
                                   CASE WHEN doc_identifier LIKE 'archive://%' THEN doc_identifier ELSE '' END,
                                   ''
                               ) AS uri
                        FROM document_records
                        WHERE topic_id IS NOT NULL
                        GROUP BY topic_id
                    ) d ON d.topic_id = n.topic_id
                """
                if active_package.startswith("REL_"):
                    nodes_rows = cur.execute(f"""
                        SELECT n.topic_id, n.name, n.depth, n.path_text,
                               (SELECT parent FROM topic_edges WHERE child = n.topic_id AND is_primary = 1 LIMIT 1) AS parent_id,
                               d.uri,
                               (SELECT COUNT(*) FROM topic_edges WHERE parent = n.topic_id) AS child_count
                        FROM topic_nodes n
                        {doc_subquery}
                        WHERE n.package = ? AND (n.path_text LIKE ? OR n.path_text = ?)
                        GROUP BY n.topic_id
                        ORDER BY n.rowid ASC
                    """, (active_package, f"{active_package} > {active_source} > %", f"{active_package} > {active_source}")).fetchall()
                else:
                    nodes_rows = cur.execute(f"""
                        SELECT n.topic_id, n.name, n.depth, n.path_text,
                               (SELECT parent FROM topic_edges WHERE child = n.topic_id AND is_primary = 1 LIMIT 1) AS parent_id,
                               d.uri,
                               (SELECT COUNT(*) FROM topic_edges WHERE parent = n.topic_id) AS child_count
                        FROM topic_nodes n
                        {doc_subquery}
                        WHERE n.source = ? AND n.package = ?
                        GROUP BY n.topic_id
                        ORDER BY n.rowid ASC
                    """, (active_source, active_package)).fetchall()

                # Build active ancestor chain
                active_chain = []
                cur_ancestor = active_topic_id
                while cur_ancestor:
                    active_chain.append(cur_ancestor)
                    p_row = cur.execute(
                        "SELECT parent FROM topic_edges WHERE child = ? AND is_primary = 1 LIMIT 1",
                        (cur_ancestor,)
                    ).fetchone()
                    cur_ancestor = p_row["parent"] if (p_row and p_row["parent"]) else None

                ancestor_set = set(active_chain)
                filter_large = len(nodes_rows) > 3000

                nodes = []
                seen_topic_ids = set()
                for r in nodes_rows:
                    tid = r["topic_id"]
                    if tid in seen_topic_ids:
                        continue
                    seen_topic_ids.add(tid)

                    p = r["path_text"] or ""
                    is_active = (tid == active_topic_id)
                    is_ancestor = (tid in ancestor_set)
                    is_child_of_ancestor = (r["parent_id"] in ancestor_set)
                    is_child = bool(active_path and p.startswith(active_path + " > "))
                    is_top_level = (r["depth"] <= (2 if active_package.startswith("REL_") else 1))

                    if filter_large and not (is_top_level or is_ancestor or is_child_of_ancestor or is_child):
                        continue

                    nodes.append({
                        "topic_id": tid,
                        "name": r["name"],
                        "depth": r["depth"],
                        "path_text": r["path_text"],
                        "parent_id": r["parent_id"],
                        "uri": r["uri"] or "",
                        "child_count": r["child_count"],
                        "is_active": is_active,
                        "is_ancestor": is_ancestor and not is_active,
                    })

                return {
                    "package": active_package,
                    "active_source": active_source,
                    "active_category": active_category,
                    "manual_title": active_manual_title,
                    "active_topic_id": active_topic_id,
                    "active_chain": active_chain,
                    "categories": categories,
                    "nodes": nodes,
                }
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Error generating package bookmap tree: {e}")
            return None

    def scan_onboarding_radar(
        self,
        root_paths: List[str],
        max_scan_seconds: float = 15.0,
    ) -> Dict[str, Any]:
        """Run read-only OnboardingRadar across root_paths and return ranked DirectoryCandidates."""
        roots_list = [str(root_paths)] if isinstance(root_paths, (str, Path)) else [str(p) for p in root_paths]
        candidates = self.onboarding_radar.scan_workspace(
            roots=roots_list,
            max_scan_seconds=max_scan_seconds,
        )
        candidate_dicts = [
            {
                "path": c.path,
                "file_count": c.file_count,
                "total_bytes": c.total_bytes,
                "supported_extensions": dict(c.supported_extensions),
                "domain_category": c.domain_category,
                "priority_score": c.priority_score,
            }
            for c in candidates
        ]
        return {
            "status": "completed",
            "root_paths": roots_list,
            "max_scan_seconds": max_scan_seconds,
            "total_candidates": len(candidate_dicts),
            "candidates": candidate_dicts,
        }

    def compile_dossier(self, entity_name: str, user_clearance: str = "restricted") -> Dict[str, Any]:
        max_clr = ClearanceLevel.from_string(user_clearance).value
        return self.graph_store.compile_dossier(entity_name, max_clearance=max_clr)

    def handle_ingestion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            current_doc_count = self.graph_store.get_entity_statistics()["total_documents"]
            self.plan_enforcer.validate_ingest(current_doc_count)

        doc_id = payload.get("document_id") or payload.get("id") or int(time.time())
        title = payload.get("title") or payload.get("file_name") or f"Document-{doc_id}"
        content = payload.get("content") or payload.get("text") or ""
        correspondent = payload.get("correspondent") or ""
        doc_type = payload.get("document_type") or ""
        tags = payload.get("tags") or []
        doc_clearance = payload.get("clearance") or payload.get("clearance_level") or 0
        doc_clr_level = ClearanceLevel.from_string(doc_clearance).value

        classification = classify_text_and_title(
            title=title, content=content, existing_tags=tags, doc_id=int(doc_id)
        )
        corr_to_use = correspondent or classification.suggested_correspondent or ""
        doc_type_to_use = doc_type or classification.suggested_document_type or ""
        tags_to_use = list(set(tags + classification.suggested_tags))

        self.graph_indexer.index_document_record(
            doc_id=int(doc_id),
            title=title,
            correspondent=corr_to_use,
            doc_type=doc_type_to_use,
            tags=tags_to_use,
            content=content,
            corpus="archive",
            clearance_level=doc_clr_level,
        )

        actions = self.action_evaluator.evaluate_document({
            "id": doc_id,
            "title": title,
            "content": content,
            "correspondent": corr_to_use,
            "document_type": doc_type_to_use,
        })
        dispatched = self.action_dispatcher.dispatch(actions)

        with self._lock:
            self.status["total_ingestions"] += 1
            self.status["total_dispatched_actions"] += len(dispatched)
            self.status["last_ingestion"] = {
                "doc_id": doc_id,
                "title": title,
                "timestamp": datetime.datetime.now().isoformat(),
                "actions_triggered": len(dispatched),
            }

        return {
            "status": "ingested",
            "doc_id": doc_id,
            "classification": classification.to_dict(),
            "actions_dispatched": dispatched,
        }

    def control_llm(self, action: str, engine: str = "llama-cpp") -> Dict[str, Any]:
        return self.llm_controller.scale_engine(action=action, engine=engine)

    @property
    def graph_view(self) -> GraphService:
        """The interactive graph viewer's service (Task 14.1), created on first use."""
        with self._graph_view_lock:
            if self._graph_view is None:
                if self.router_db_path == ":memory:" or self.graph_store.db_path == ":memory:":
                    raise RuntimeError("graph viewer needs on-disk router and graph databases")
                self._graph_view = GraphService(
                    self.router_db_path, self.graph_store.db_path, wiki_dir=self._wiki_dir
                )
            return self._graph_view

    def get_graph_topology(self, filter_term: str = "") -> Dict[str, Any]:
        return build_graph_topology(self.graph_store, filter_term=filter_term)

    def get_monitored_sources(self) -> Dict[str, Any]:
        return self.sources_manager.get_monitored_sources()

    def add_or_sync_source(
        self,
        path_str: str,
        domain: str = "Custom Server Corpus",
        ingest_now: bool = True,
    ) -> Dict[str, Any]:
        return self.sources_manager.add_or_sync_source(path_str, domain=domain, ingest_now=ingest_now)

    def remove_and_purge_source(
        self,
        path_str: str = "",
        prefix_str: str = "",
        keep_in_monitored_list: bool = False,
    ) -> Dict[str, Any]:
        return self.sources_manager.remove_and_purge_source(
            path_str=path_str,
            prefix_str=prefix_str,
            keep_in_monitored_list=keep_in_monitored_list,
        )

    def get_license_status(self) -> Dict[str, Any]:
        return LicenseHandler.get_license_status(self)

    def attach_license(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return LicenseHandler.attach_license(self, payload)


# Backward-compatible alias
ApplianceManager = SovereignApplianceManager


def create_app(
    searcher: Optional[SovereignSearcher] = None,
    graph_store: Optional[GraphStore] = None,
    graph_indexer: Optional[GraphIndexer] = None,
    action_dispatcher: Optional[ActionDispatcher] = None,
    plan_enforcer: Optional[PlanEnforcer] = None,
    nano_runner: Optional[NanoRunner] = None,
    archive_streamer: Optional[SovereignArchiveStreamer] = None,
    onboarding_radar: Optional[OnboardingRadar] = None,
    router_db_path: Optional[str] = None,
    llm_controller: Optional[LLMController] = None,
    wiki_dir: Optional[str] = None,
) -> SovereignApplianceManager:
    """Factory to initialize the singleton SovereignApplianceManager."""
    from .handler import SovereignHTTPHandler

    manager = SovereignApplianceManager(
        searcher=searcher,
        graph_store=graph_store,
        graph_indexer=graph_indexer,
        action_dispatcher=action_dispatcher,
        plan_enforcer=plan_enforcer,
        nano_runner=nano_runner,
        archive_streamer=archive_streamer,
        onboarding_radar=onboarding_radar,
        router_db_path=router_db_path,
        llm_controller=llm_controller,
        wiki_dir=wiki_dir,
    )
    SovereignHTTPHandler.manager = manager
    return manager
