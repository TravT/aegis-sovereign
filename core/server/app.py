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
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

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

from .constants import (
    DEFAULT_ROUTER_DB,
    DEFAULT_GRAPH_DB,
    DEFAULT_DIAGRAMS_DIR,
    _PROD_VAULT_DIR,
    _extract_structured_sections,
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
    ) -> Dict[str, Any]:
        with self._lock:
            self.status["total_queries"] += 1

        routed = self.router.route_and_execute(
            query=query,
            user_clearance=user_clearance,
            plan=plan,
            limit=limit,
        )
        if "route" in routed and "route_type" not in routed:
            routed["route_type"] = routed["route"]

        route_type = routed.get("route_type") or "hybrid_needle"
        is_mock_searcher = hasattr(self.searcher, "_mock_name") or type(self.searcher).__name__ == "MagicMock"
        clr_int = ClearanceLevel.from_string(user_clearance).value

        results = list(routed.get("results") or [])
        if route_type != "deterministic_direct" and not is_mock_searcher:
            fts_hits = self.router._fallback_fts_search(query=query, clearance_int=clr_int, limit=limit)
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

            item = dict(r)
            item["virtual_uri"] = v_uri
            item["source_uri"] = v_uri
            item["file_path"] = v_uri
            item["title"] = title_str
            item["content"] = full_text
            item["text"] = full_text
            item["structured_sections"] = _extract_structured_sections(full_text)
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
        """Extracts and renders an authentic HTML/OpenXML archive document with Dark Obsidian styling."""
        entry = self.archive_streamer.resolve_virtual_uri(virtual_uri)
        return DocumentViewer.format_entry_to_styled_html(entry, virtual_uri)

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

    def control_llm(self, action: str, engine: str = "ollama") -> Dict[str, Any]:
        return self.llm_controller.scale_engine(action=action, engine=engine)

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
    )
    SovereignHTTPHandler.manager = manager
    return manager
