"""
HTTP Request Handler for Sovereign Server.
Processes REST requests, streams Dark Obsidian HTML document views,
and executes Two-Pronged routing with zero cloud tokens.
"""

import json
import logging
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import Dict, Any

from ..containers.archive_streamer import ArchiveSecurityError
from ..license import LicenseError
from ..security import (
    PlanLimitExceededError,
    FeatureNotAllowedError,
)
from .constants import WEB_PORTAL_INDEX, _PROD_VAULT_DIR, _LEGACY_DATA_DIR

logger = logging.getLogger("sovereign_server.handler")


class SovereignHTTPHandler(BaseHTTPRequestHandler):
    """Zero-cloud REST request handler for the Aegis Sovereign Knowledge Appliance."""

    manager: Any

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _send_bytes(self, status_code: int, content_type: str, body: bytes):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/portal", "/portal/", "/index.html"):
            if WEB_PORTAL_INDEX.exists():
                html_bytes = WEB_PORTAL_INDEX.read_bytes()
                self._send_bytes(200, "text/html; charset=utf-8", html_bytes)
            else:
                self._send_json(404, {"error": "Web portal index.html not found", "path": str(WEB_PORTAL_INDEX)})
        elif parsed.path.startswith("/portal/css/") or parsed.path.startswith("/portal/js/"):
            rel_subpath = parsed.path[len("/portal/"):].lstrip("/")
            if ".." in rel_subpath or "\\" in rel_subpath:
                self._send_json(403, {"error": "Path traversal blocked"})
                return
            target_file = (WEB_PORTAL_INDEX.parent / rel_subpath).resolve()
            if not str(target_file).startswith(str(WEB_PORTAL_INDEX.parent.resolve())):
                self._send_json(403, {"error": "Access forbidden outside portal directory"})
                return
            if target_file.exists() and target_file.is_file():
                ctype = "text/plain"
                if target_file.suffix == ".css":
                    ctype = "text/css; charset=utf-8"
                elif target_file.suffix == ".js":
                    ctype = "application/javascript; charset=utf-8"
                self._send_bytes(200, ctype, target_file.read_bytes())
                return
            self._send_json(404, {"error": f"Portal asset '{rel_subpath}' not found"})
            return
        elif parsed.path.startswith("/diagrams/"):
            rel_name = urllib.parse.unquote(parsed.path[len("/diagrams/"):]).strip()
            if not rel_name or ".." in rel_name or "/" in rel_name or "\\" in rel_name:
                self._send_json(403, {"error": "Invalid diagram filename (path traversal blocked)"})
                return
            candidate_paths = [
                _PROD_VAULT_DIR / "extracted_diagrams" / rel_name,
                _LEGACY_DATA_DIR / "extracted_diagrams" / rel_name,
            ]
            for cp in candidate_paths:
                if cp.exists() and cp.is_file():
                    ctype = "image/png"
                    if rel_name.lower().endswith((".jpg", ".jpeg")):
                        ctype = "image/jpeg"
                    elif rel_name.lower().endswith(".gif"):
                        ctype = "image/gif"
                    self._send_bytes(200, ctype, cp.read_bytes())
                    return
            self._send_json(404, {"error": f"Diagram '{rel_name}' not found"})
        elif parsed.path in ("/health", "/status"):
            self._send_json(200, self.manager.get_status())
        elif parsed.path == "/llm/status":
            self._send_json(200, self.manager.llm_controller.get_status())
        elif parsed.path == "/archive/view":
            query_params = urllib.parse.parse_qs(parsed.query)
            virtual_uri = query_params.get("uri", [""])[0]
            if not virtual_uri:
                self._send_json(400, {"error": "Missing 'uri' query parameter (e.g. ?uri=archive://...)"})
                return
            try:
                html_out = self.manager.render_archive_document_html(virtual_uri)
                self._send_bytes(200, "text/html; charset=utf-8", html_out.encode("utf-8", errors="replace"))
            except KeyError as ke:
                self._send_json(404, {"error": str(ke)})
            except Exception as e:
                self._send_json(500, {"error": f"Failed to render document: {e}"})
        elif parsed.path == "/graph/topology":
            query_params = urllib.parse.parse_qs(parsed.query)
            filter_term = query_params.get("filter", [""])[0]
            try:
                self._send_json(200, self.manager.get_graph_topology(filter_term=filter_term))
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        elif parsed.path == "/sources":
            try:
                self._send_json(200, self.manager.get_monitored_sources())
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        elif parsed.path == "/license":
            try:
                self._send_json(200, self.manager.get_license_status())
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        elif parsed.path == "/dossier":
            query_params = urllib.parse.parse_qs(parsed.query)
            entity = query_params.get("entity", [""])[0]
            user_clearance = query_params.get("user_clearance", ["restricted"])[0]
            if not entity:
                self._send_json(400, {"error": "Missing 'entity' parameter"})
                return
            try:
                res = self.manager.compile_dossier(entity, user_clearance=user_clearance)
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "Not Found", "path": parsed.path})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        payload = {}
        if content_length > 0:
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except Exception:
                payload = {}

        if parsed.path in ("/sources/add", "/sources/sync"):
            path_str = payload.get("path", "")
            domain = payload.get("domain", "Custom Server Corpus")
            ingest_now = bool(payload.get("ingest_now", True))
            try:
                res = self.manager.add_or_sync_source(
                    path_str=path_str,
                    domain=domain,
                    ingest_now=ingest_now,
                )
                self._send_json(200, res)
            except PermissionError as pe:
                self._send_json(403, {"error": str(pe), "code": "ANTI_LOOP_NO_INDEX_BLOCKED"})
            except FileNotFoundError as fnf:
                self._send_json(404, {"error": str(fnf)})
            except ValueError as ve:
                self._send_json(400, {"error": str(ve)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path in ("/sources/remove", "/vault/purge"):
            path_str = payload.get("path", "")
            prefix_str = payload.get("prefix", "")
            keep_entry = bool(payload.get("keep_in_monitored_list", False))
            try:
                res = self.manager.remove_and_purge_source(
                    path_str=path_str,
                    prefix_str=prefix_str,
                    keep_in_monitored_list=keep_entry,
                )
                self._send_json(200, res)
            except ValueError as ve:
                self._send_json(400, {"error": str(ve)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path == "/license/attach":
            try:
                res = self.manager.attach_license(payload)
                self._send_json(200, res)
            except LicenseError as le:
                self._send_json(400, {"error": str(le), "code": "INVALID_LICENSE_SIGNATURE"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path == "/optimize":
            query = payload.get("query", "")
            if not query:
                self._send_json(400, {"error": "Missing 'query' in JSON payload"})
                return

            analytical_depth = payload.get("analytical_depth", "flash_needle")
            evidence_grounding = payload.get("evidence_grounding", "verbatim_footnotes")
            include_visual_plates = bool(payload.get("include_visual_plates", False))
            user_clearance = payload.get("user_clearance", "restricted")
            critical_posture = payload.get("critical_posture", "neutral")
            plan = payload.get("plan")

            try:
                res = self.manager.optimize_context(
                    query=query,
                    max_chunks=int(payload.get("max_chunks", 3)),
                    retrieval_mode=payload.get("retrieval_mode", "high_precision"),
                    confidence_floor=float(payload.get("confidence_floor", 0.0)),
                    include_graph_dossier=bool(payload.get("include_graph_dossier", False)),
                    analytical_depth=analytical_depth,
                    evidence_grounding=evidence_grounding,
                    include_visual_plates=include_visual_plates,
                    user_clearance=user_clearance,
                    critical_posture=critical_posture,
                    plan=plan,
                )
                self._send_json(200, res)
            except (PlanLimitExceededError, FeatureNotAllowedError, PermissionError) as pe:
                self._send_json(403, {"error": str(pe), "code": "PLAN_RESTRICTION"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path == "/router/analyze":
            query = payload.get("query", "")
            if not query:
                self._send_json(400, {"error": "Missing 'query' in JSON payload"})
                return
            try:
                res = self.manager.analyze_route(query)
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path == "/router/query":
            query = payload.get("query", "")
            if not query:
                self._send_json(400, {"error": "Missing 'query' in JSON payload"})
                return
            user_clearance = payload.get("user_clearance", "restricted")
            plan = payload.get("plan")
            limit = int(payload.get("limit", 5))
            force_synthesize = payload.get("synthesize")
            if force_synthesize is not None:
                force_synthesize = bool(force_synthesize)
            prefer_neural = payload.get("prefer_neural")
            if prefer_neural is not None:
                prefer_neural = bool(prefer_neural)
            domain_filter = payload.get("domain_filter") or payload.get("domain") or "all"
            try:
                res = self.manager.route_and_execute(
                    query=query,
                    user_clearance=user_clearance,
                    plan=plan,
                    limit=limit,
                    force_synthesize=force_synthesize,
                    prefer_neural=prefer_neural,
                    domain_filter=domain_filter,
                )
                self._send_json(200, res)
            except (PlanLimitExceededError, FeatureNotAllowedError, PermissionError) as pe:
                self._send_json(403, {"error": str(pe), "code": "PLAN_RESTRICTION"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path == "/llm/control":
            action = payload.get("action", "start")
            engine = payload.get("engine", "ollama")
            try:
                res = self.manager.control_llm(action=action, engine=engine)
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path == "/archive/inspect":
            archive_path = payload.get("archive_path", "")
            virtual_uri = payload.get("virtual_uri", "")
            query = payload.get("query", "")
            ingest = bool(payload.get("ingest", False))
            section_filter = str(payload.get("section_filter") or "")
            extract_diagram = bool(payload.get("extract_diagram_to_artifact", False))
            char_offset = int(payload.get("char_offset", 0))
            max_chars = int(payload.get("max_chars", 8000))
            if not archive_path and not virtual_uri:
                self._send_json(400, {"error": "Missing 'archive_path' or 'virtual_uri' in JSON payload"})
                return
            try:
                res = self.manager.inspect_archive(
                    archive_path=archive_path,
                    virtual_uri=virtual_uri,
                    query=query,
                    ingest=ingest,
                    section_filter=section_filter,
                    extract_diagram_to_artifact=extract_diagram,
                    char_offset=char_offset,
                    max_chars=max_chars,
                )
                self._send_json(200, res)
            except ArchiveSecurityError as ase:
                self._send_json(403, {"error": str(ase), "code": "ARCHIVE_SECURITY_VIOLATION"})
            except (FileNotFoundError, KeyError) as fnf:
                self._send_json(404, {"error": str(fnf)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path == "/onboarding/scan":
            root_paths = payload.get("root_paths") or payload.get("root_path") or []
            if isinstance(root_paths, str):
                root_paths = [root_paths]
            max_scan_seconds = float(payload.get("max_scan_seconds", 15.0))
            if not root_paths:
                self._send_json(400, {"error": "Missing 'root_paths' in JSON payload"})
                return
            try:
                res = self.manager.scan_onboarding_radar(
                    root_paths=root_paths,
                    max_scan_seconds=max_scan_seconds,
                )
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path == "/query":
            query = payload.get("query", "")
            if not query:
                self._send_json(400, {"error": "Missing 'query' in JSON payload"})
                return

            user_clearance = payload.get("user_clearance", "restricted")
            analytical_depth = payload.get("analytical_depth", "flash_needle")
            retrieval_mode = payload.get("retrieval_mode", "high_precision")
            confidence_floor = float(payload.get("confidence_floor", 0.0))
            limit = int(payload.get("limit", 5))

            try:
                route_info = self.manager.analyze_route(query)
                hits = self.manager.search(
                    query=query,
                    limit=limit,
                    retrieval_mode=retrieval_mode,
                    confidence_floor=confidence_floor,
                    user_clearance=user_clearance,
                    analytical_depth=analytical_depth,
                )
                self._send_json(200, {
                    "query": query,
                    "total": len(hits),
                    "results": hits,
                    "user_clearance": user_clearance,
                    "analytical_depth": analytical_depth,
                    "route_decision": route_info,
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        elif parsed.path == "/webhook/paperless":
            try:
                res = self.manager.handle_ingestion(payload)
                self._send_json(200, res)
            except (PlanLimitExceededError, FeatureNotAllowedError, PermissionError) as pe:
                self._send_json(403, {"error": str(pe), "code": "PLAN_LIMIT_EXCEEDED"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        else:
            self._send_json(404, {"error": "Not Found", "path": parsed.path})
