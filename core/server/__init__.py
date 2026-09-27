"""
Aegis Sovereign Core Server Package.
Decomposed deep modules coordinating hybrid retrieval, knowledge graph traversal,
local LLM orchestration, and in-browser document streaming.
"""

import argparse
import logging
import signal
import threading
from http.server import ThreadingHTTPServer

from .constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    _APPLIANCE_ROOT,
    _CANONICAL_PROD_VAULT,
    _PROD_VAULT_DIR,
    _LEGACY_DATA_DIR,
    WEB_PORTAL_INDEX,
    DEFAULT_ROUTER_DB,
    DEFAULT_GRAPH_DB,
    DEFAULT_HUAWEI_ROUTER_DB,
    DEFAULT_HUAWEI_GRAPH_DB,
    DEFAULT_DIAGRAMS_DIR,
    MONITORED_SOURCES_FILE,
    ACTIVE_LICENSE_FILE,
    LICENSE_KEYS_FILE,
    _resolve_default_router_db,
    _resolve_default_graph_db,
    _extract_structured_sections,
)
from .llm_controller import LLMController
from .viewer import DocumentViewer
from .topology import build_graph_topology, build_enriched_graph_dossier
from .sources import SourcesManager
from .license_handler import LicenseHandler
from .app import SovereignApplianceManager, ApplianceManager, create_app
from .handler import SovereignHTTPHandler

logger = logging.getLogger("sovereign_server")


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    manager = create_app()
    SovereignHTTPHandler.manager = manager
    server = ThreadingHTTPServer((host, port), SovereignHTTPHandler)

    logger.info(f"Sovereign Core HTTP Server listening on http://{host}:{port}")

    def shutdown_handler(signum, frame):
        logger.info("Received shutdown signal. Stopping server...")
        threading.Thread(target=server.shutdown).start()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        logger.info("Server terminated cleanly.")


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "_APPLIANCE_ROOT",
    "_CANONICAL_PROD_VAULT",
    "_PROD_VAULT_DIR",
    "_LEGACY_DATA_DIR",
    "WEB_PORTAL_INDEX",
    "DEFAULT_ROUTER_DB",
    "DEFAULT_GRAPH_DB",
    "DEFAULT_HUAWEI_ROUTER_DB",
    "DEFAULT_HUAWEI_GRAPH_DB",
    "DEFAULT_DIAGRAMS_DIR",
    "MONITORED_SOURCES_FILE",
    "ACTIVE_LICENSE_FILE",
    "LICENSE_KEYS_FILE",
    "_resolve_default_router_db",
    "_resolve_default_graph_db",
    "_extract_structured_sections",
    "LLMController",
    "DocumentViewer",
    "build_graph_topology",
    "build_enriched_graph_dossier",
    "SourcesManager",
    "LicenseHandler",
    "SovereignApplianceManager",
    "ApplianceManager",
    "create_app",
    "SovereignHTTPHandler",
    "run_server",
]
