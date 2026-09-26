#!/usr/bin/env python3
"""
Aegis Sovereign Desktop Edition — Production Workstation Daemon (ADR-37).
Zero-Copy In-Place Indexer and Serverless Desktop Engine (sovereign-desktopd).

Invariants:
1. Zero-Copy In-Place Traversal: Files opened read-only (O_RDONLY). Never duplicated.
2. Dedicated User Cache Storage: Linux/macOS (~/.cache/sovereign/), Windows (%LOCALAPPDATA%\\Sovereign\\).
3. Kernel Event Observers: Native OS filesystem events debounced with 40ms sliding window.
4. Cognitive Spotlight HUD Loopback Server: Strictly binds to 127.0.0.1:9876 (Zero Egress / DLP Safe).
5. Native 1-Click Jump Action: Safe native OS file opening preventing path traversal.
6. Zero Plaintext Secrets.
"""

import argparse
import datetime
import json
import logging
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

# Add repository root to path for core imports
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.chunker import parse_and_chunk_markdown
from core.indexer.dual_encoder import SovereignIndexer
from core.search.searcher import SovereignSearcher
from core.proxy.context_condenser import ContextCondenser
from core.graph.store import GraphStore
from core.graph.indexer import GraphIndexer
from desktop.daemon.nano_runner import NanoRunner, NanoSynthesisResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [AegisDesktop] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("aegis_desktop")


def get_default_cache_dir() -> Path:
    """
    Returns the OS-compliant dedicated user cache directory (ADR-37):
    - Linux / macOS: ~/.cache/sovereign/
    - Windows: %LOCALAPPDATA%\\Sovereign\\
    Can be overridden via AEGIS_STORAGE_DIR or AEGIS_DESKTOP_HOME.
    """
    env_storage = os.getenv("AEGIS_STORAGE_DIR") or os.getenv("AEGIS_DESKTOP_HOME")
    if env_storage:
        return Path(os.path.expanduser(env_storage)).resolve()

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Sovereign"
        return Path.home() / "AppData" / "Local" / "Sovereign"
    else:
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache:
            return Path(xdg_cache) / "sovereign"
        return Path.home() / ".cache" / "sovereign"


def read_file_readonly(path: Path) -> str:
    """
    Opens a file strictly with O_RDONLY at the OS kernel level, ensuring zero mutation
    and absolute compliance with corporate DLP and zero-copy invariants.
    """
    fd = os.open(str(path), os.O_RDONLY)
    try:
        with open(fd, "r", encoding="utf-8", errors="replace", closefd=True) as f:
            return f.read()
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


class SlidingDebouncer:
    """
    Sliding-window debouncer with 40ms window per ADR-37.
    Coalesces rapid file events and triggers micro-reindexing once the filesystem settles.
    """
    def __init__(self, delay: float = 0.040, callback=None):
        self.delay = delay
        self.callback = callback
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._pending_events: Dict[str, str] = {}  # path -> event_type

    def push(self, path: str, event_type: str):
        with self._lock:
            # If deleted, delete event takes precedence
            if event_type == "delete":
                self._pending_events[path] = "delete"
            else:
                if self._pending_events.get(path) != "delete":
                    self._pending_events[path] = event_type

            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self):
        with self._lock:
            events = dict(self._pending_events)
            self._pending_events.clear()
            self._timer = None

        if self.callback and events:
            self.callback(events)


class WorkstationWatcherHandler(FileSystemEventHandler):
    """Watches local user folders in-place without copying files."""
    def __init__(self, daemon: 'WorkstationDaemon'):
        super().__init__()
        self.daemon = daemon

    def _is_supported(self, path: str) -> bool:
        norm = path.replace("\\", "/")
        ignored = [
            "/.git/", "/.obsidian/", "/node_modules/", "/.trash/",
            "/venv/", "/.venv/", "/__pycache__/", "/.pytest_cache/",
            "/AppData/", "/.cache/sovereign/"
        ]
        for ig in ignored:
            if ig in norm:
                return False
        return norm.endswith((".md", ".txt", ".pdf", ".rst", ".json", ".csv"))

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and self._is_supported(event.src_path):
            self.daemon.debouncer.push(event.src_path, "modify")

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and self._is_supported(event.src_path):
            self.daemon.debouncer.push(event.src_path, "create")

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory and self._is_supported(event.src_path):
            self.daemon.debouncer.push(event.src_path, "delete")

    def on_moved(self, event: FileSystemEvent):
        if not event.is_directory:
            if self._is_supported(event.src_path):
                self.daemon.debouncer.push(event.src_path, "delete")
            dest_path = getattr(event, "dest_path", None)
            if dest_path and self._is_supported(dest_path):
                self.daemon.debouncer.push(dest_path, "create")


class WorkstationDaemon:
    """
    Full production sovereign-desktopd engine.
    Manages in-place watchers, embedded Qdrant vectors, SQLite WAL graph store,
    nano inference runner, and loopback HTTP server.
    """
    def __init__(
        self,
        watch_paths: Optional[List[str]] = None,
        storage_dir: Optional[Path] = None,
        port: int = 9876,
    ):
        self.storage_dir = (storage_dir or get_default_cache_dir()).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.qdrant_path = os.getenv("QDRANT_URL") or str(self.storage_dir / "qdrant")
        self.graph_path = os.getenv("GRAPH_DB_PATH") or str(self.storage_dir / "graph_store.db")
        self.collection_name = os.getenv("QDRANT_COLLECTION", "workstation_chunks")
        self.models_dir = self.storage_dir / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.port = port

        # Resolve watch paths
        if watch_paths is not None:
            self.watch_paths = [Path(os.path.expanduser(p)).resolve() for p in watch_paths if p]
        else:
            home = Path.home()
            candidates = [home / "Documents", home / "Projects", home / "Notes", home / "Work"]
            self.watch_paths = [p for p in candidates if p.exists()]

        # Initialize Qdrant storage (embedded or HTTP)
        self.indexer = SovereignIndexer(
            qdrant_target=self.qdrant_path,
            collection_name=self.collection_name
        )
        self.indexer.init_collection()

        self.searcher = SovereignSearcher(
            qdrant_target=self.qdrant_path,
            collection_name=self.collection_name,
            client=self.indexer.client,
        )
        self.graph_store = GraphStore(db_path=self.graph_path)
        self.graph_indexer = GraphIndexer(store=self.graph_store)
        self.condenser = ContextCondenser(searcher=self.searcher, graph_store=self.graph_store)

        # On-device Nano-Model inference runner
        self.nano_runner = NanoRunner(cache_dir=self.storage_dir)

        # File system observer & 40ms debouncer
        self.debouncer = SlidingDebouncer(delay=0.040, callback=self._handle_debounced_events)
        self.observer = Observer()

        self._stats = {
            "indexed_files": 0,
            "purged_files": 0,
            "queries_processed": 0,
            "optimizations_processed": 0,
            "start_time": time.time(),
        }

    def start_filesystem_watchers(self):
        """Starts background kernel event observers on all watched directories."""
        handler = WorkstationWatcherHandler(self)
        active_watches = 0
        for path in self.watch_paths:
            if path.exists():
                logger.info(f"Watching directory in-place: {path}")
                self.observer.schedule(handler, str(path), recursive=True)
                active_watches += 1
        if active_watches > 0:
            self.observer.start()
        else:
            logger.warning("No valid watch paths found to monitor.")

    def stop_filesystem_watchers(self):
        """Stops filesystem observer."""
        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join()

    def _handle_debounced_events(self, events: Dict[str, str]):
        """Processes coalesced filesystem events after the 40ms sliding window."""
        for file_path, event_type in events.items():
            if event_type == "delete":
                self.handle_deletion(file_path)
            elif event_type in ("create", "modify"):
                self.index_file_inplace(file_path)

    def handle_deletion(self, file_path: str):
        """Purges file records from embedded Qdrant and SQLite WAL graph store."""
        logger.info(f"Purging deleted file from local indexes: {file_path}")
        p = Path(file_path)
        # Purge from Qdrant vector collection
        self.indexer.delete_file_points(str(p))
        # Purge from SQLite WAL graph store
        self.graph_store.delete_document_by_identifier(str(p))
        self.graph_store.delete_document(corpus="workstation", doc_identifier=str(p))
        self._stats["purged_files"] += 1

    def index_file_inplace(self, file_path: str):
        """Indexes a document in-place strictly using O_RDONLY without copying."""
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return

        try:
            content = read_file_readonly(p)
        except Exception as e:
            logger.warning(f"Failed to read file {p}: {e}")
            return

        try:
            # Index chunks in Qdrant
            counts = self.indexer.index_files([str(p)], p.parent)
            chunk_count = counts.get(str(p), 0)

            # If Markdown or structured text, extract entities into SQLite GraphStore
            if p.suffix.lower() in (".md", ".txt", ".rst"):
                doc_title = p.stem
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        import yaml
                        try:
                            fm = yaml.safe_load(parts[1]) or {}
                            if "title" in fm:
                                doc_title = fm["title"]
                        except Exception:
                            pass

                from core.graph.extractor import extract_paperless_entities
                doc_hash = abs(hash(str(p))) % 10000000
                extraction = extract_paperless_entities(
                    doc_id=doc_hash,
                    title=doc_title,
                    correspondent="Local Workstation",
                    doc_type="Document",
                    tags=["workstation", "local", p.suffix.lstrip(".")],
                    content=content
                )
                self.graph_store.index_document(
                    corpus="workstation",
                    doc_identifier=str(p),
                    title=doc_title,
                    created_date=datetime.date.today().isoformat(),
                    url=f"file://{p.resolve()}",
                    entities=extraction.entities,
                    relations=extraction.relations
                )

            self._stats["indexed_files"] += 1
            logger.info(f"Successfully indexed in-place: {p} ({chunk_count} chunks)")
        except Exception as e:
            logger.warning(f"Error indexing {p}: {e}")

    def query(
        self,
        query_str: str,
        limit: int = 5,
        retrieval_mode: str = "high_precision",
        confidence_floor: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Performs hybrid dense+sparse vector search against embedded Qdrant."""
        self._stats["queries_processed"] += 1
        raw_hits = self.searcher.search(
            query=query_str,
            limit=limit,
            retrieval_mode=retrieval_mode,
            confidence_floor=confidence_floor,
        )
        flattened = []
        for h in raw_hits:
            payload = h.get("payload", {})
            flattened.append({
                "id": h.get("id"),
                "score": h.get("rrf_score", 0.0),
                "rrf_score": h.get("rrf_score", 0.0),
                "doc_title": payload.get("doc_title", ""),
                "file_path": payload.get("file_path", ""),
                "heading": payload.get("heading", ""),
                "text": payload.get("text", ""),
                "tags": payload.get("tags", []),
                "payload": payload,
                "meta": h.get("meta", {}),
            })
        return flattened

    def optimize(
        self,
        query_str: str,
        max_chunks: int = 3,
        retrieval_mode: str = "high_precision",
        confidence_floor: float = 0.0,
        include_graph_dossier: bool = True,
        use_nano: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes ContextCondenser hybrid optimization and synthesizes grounded answer
        via the on-device NanoRunner engine with citation pills.
        """
        self._stats["optimizations_processed"] += 1
        res = self.condenser.optimize(
            query=query_str,
            max_chunks=max_chunks,
            retrieval_mode=retrieval_mode,
            confidence_floor=confidence_floor,
            include_graph_dossier=include_graph_dossier,
        )
        res_dict = res.to_dict()

        # Build chunks for nano_runner from hits
        raw_hits = self.searcher.search(
            query=query_str,
            limit=max_chunks,
            retrieval_mode=retrieval_mode,
            confidence_floor=confidence_floor,
        )
        nano_chunks = []
        for h in raw_hits:
            payload = h.get("payload", {})
            nano_chunks.append({
                "doc_title": payload.get("doc_title", ""),
                "file_path": payload.get("file_path", ""),
                "heading": payload.get("heading", ""),
                "text": payload.get("text", ""),
                "score": h.get("rrf_score", 0.0),
                "chunk_index": payload.get("chunk_index", 0),
            })
        res_dict["condensed_chunks"] = nano_chunks

        # Generate on-device Nano synthesis
        if use_nano:
            synthesis = self.nano_runner.synthesize(
                query=query_str,
                chunks=nano_chunks,
                graph_dossier=res_dict.get("graph_dossier"),
                confidence_floor=confidence_floor or 0.35,
            )
            res_dict["synthesis"] = synthesis.to_dict()

        return res_dict

    def is_safe_path(self, target_path: Path) -> Tuple[bool, str]:
        """
        Validates target path against path traversal attacks.
        Ensures file exists, is regular file or directory, and is within permissible roots.
        """
        try:
            resolved = target_path.expanduser().resolve()
        except Exception as e:
            return False, f"Invalid path resolution: {e}"

        # Prevent null bytes
        if "\0" in str(target_path):
            return False, "Null byte in path detected"

        if not resolved.exists():
            return False, f"Path does not exist: {resolved}"

        # Block dangerous executable extensions that might attempt arbitrary code execution
        dangerous_exts = {".exe", ".bat", ".cmd", ".vbs", ".bin", ".com", ".scr", ".msi"}
        if resolved.suffix.lower() in dangerous_exts and resolved.is_file():
            return False, f"Access denied: opening executable binaries is prohibited for security ({resolved.name})"

        # Check that path is within allowed user roots (home, temp, or watched directories)
        allowed_roots = [Path.home().resolve(), self.storage_dir.resolve(), Path("/tmp").resolve()]
        for wp in self.watch_paths:
            allowed_roots.append(wp.resolve())

        is_allowed = any(
            resolved == root or root in resolved.parents
            for root in allowed_roots
        )
        if not is_allowed:
            return False, f"Access denied: path outside permissible user boundaries ({resolved})"

        return True, str(resolved)

    def open_path(self, target_path_str: str) -> Tuple[bool, str]:
        """
        1-Click native OS file opening.
        Uses native OS launchers (xdg-open, open, start) without shell=True.
        """
        p = Path(target_path_str)
        safe, msg = self.is_safe_path(p)
        if not safe:
            return False, msg

        resolved_str = msg
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", resolved_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "win32":
                os.startfile(resolved_str)
            else:
                # Linux / BSD
                subprocess.Popen(["xdg-open", resolved_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, resolved_str
        except Exception as e:
            return False, f"Failed to open via OS launcher: {e}"

    def reveal_path(self, target_path_str: str) -> Tuple[bool, str]:
        """Reveals file in the native OS desktop file manager."""
        p = Path(target_path_str)
        safe, msg = self.is_safe_path(p)
        if not safe:
            return False, msg

        resolved = Path(msg)
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(resolved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "win32":
                subprocess.Popen(["explorer.exe", f"/select,{resolved}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # Linux: open containing folder
                folder = resolved if resolved.is_dir() else resolved.parent
                subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, str(resolved)
        except Exception as e:
            return False, f"Failed to reveal via file manager: {e}"


class DesktopHUDHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for Cognitive Spotlight HUD (loopback only)."""
    daemon: WorkstationDaemon

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/ipc/"):
            path = path[4:]
        elif path == "/ipc":
            path = "/status"
        if path == "/health":
            self._send_json(200, {
                "status": "online",
                "edition": "Aegis Sovereign Desktop",
                "version": "1.0.0",
                "zero_copy": True,
                "dlp_compliant": True,
                "port": self.daemon.port,
            })
        elif path == "/status":
            graph_stats = self.daemon.graph_store.get_entity_statistics()
            self._send_json(200, {
                "status": "online",
                "edition": "Aegis Sovereign Desktop",
                "version": "1.0.0",
                "storage_dir": str(self.daemon.storage_dir),
                "watched_paths": [str(p) for p in self.daemon.watch_paths],
                "stats": {
                    **self.daemon._stats,
                    "uptime_seconds": round(time.time() - self.daemon._stats["start_time"], 1),
                },
                "nano_runner": {
                    "model": self.daemon.nano_runner.model_name,
                    "is_fallback": self.daemon.nano_runner.is_fallback,
                    "execution_mode": self.daemon.nano_runner.execution_mode,
                    "ollama_url": self.daemon.nano_runner.ollama_url,
                    "ollama_model": self.daemon.nano_runner.ollama_model,
                },
                "graph_statistics": graph_stats,
            })
        elif path in ("/", "/hud", "/index.html"):
            hud_path = REPO_ROOT / "desktop" / "hud" / "index.html"
            if hud_path.exists():
                content = hud_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
            else:
                self._send_json(404, {"error": "HUD index.html not found"})
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path.startswith("/ipc/"):
            path = path[4:]
        content_length = int(self.headers.get("Content-Length", 0))
        payload = {}
        if content_length > 0:
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except Exception as e:
                self._send_json(400, {"error": f"Malformed JSON: {e}"})
                return

        if path == "/query":
            query_str = payload.get("query", "").strip()
            if not query_str:
                self._send_json(400, {"error": "Missing 'query' parameter"})
                return

            limit = int(payload.get("limit") or payload.get("max_chunks") or 5)
            mode = payload.get("retrieval_mode", "high_precision")
            floor = float(payload.get("confidence_floor", 0.0))

            results = self.daemon.query(
                query_str=query_str,
                limit=limit,
                retrieval_mode=mode,
                confidence_floor=floor
            )
            self._send_json(200, {"query": query_str, "results": results})

        elif path == "/optimize":
            query_str = payload.get("query", "").strip()
            if not query_str:
                self._send_json(400, {"error": "Missing 'query' parameter"})
                return

            max_chunks = int(payload.get("max_chunks", 3))
            mode = payload.get("retrieval_mode", "high_precision")
            floor = float(payload.get("confidence_floor", 0.0))
            include_dossier = bool(payload.get("include_graph_dossier", True))
            use_nano = bool(payload.get("use_nano", True))

            result = self.daemon.optimize(
                query_str=query_str,
                max_chunks=max_chunks,
                retrieval_mode=mode,
                confidence_floor=floor,
                include_graph_dossier=include_dossier,
                use_nano=use_nano,
            )
            self._send_json(200, result)

        elif path == "/open":
            file_path = payload.get("path", "").strip()
            if not file_path:
                self._send_json(400, {"error": "Missing 'path' parameter"})
                return

            success, message = self.daemon.open_path(file_path)
            if success:
                self._send_json(200, {"status": "ok", "opened": message})
            else:
                self._send_json(403 if "Access denied" in message else 400, {"error": message})

        elif path == "/reveal":
            file_path = payload.get("path", "").strip()
            if not file_path:
                self._send_json(400, {"error": "Missing 'path' parameter"})
                return

            success, message = self.daemon.reveal_path(file_path)
            if success:
                self._send_json(200, {"status": "ok", "revealed": message})
            else:
                self._send_json(403 if "Access denied" in message else 400, {"error": message})

        else:
            self._send_json(404, {"error": "Not Found"})

    def log_message(self, format, *args):
        # Mute standard noisy HTTP access logs
        pass


def run_daemon(watch_paths: Optional[List[str]] = None, host: str = "127.0.0.1", port: int = 9876):
    """CLI launcher for sovereign-desktopd."""
    daemon = WorkstationDaemon(watch_paths=watch_paths, port=port)
    daemon.start_filesystem_watchers()

    DesktopHUDHandler.daemon = daemon
    server = HTTPServer((host, port), DesktopHUDHandler)
    logger.info(f"Aegis Sovereign Desktop Daemon running at http://{host}:{port}")
    logger.info(f"User Cache Storage: {daemon.storage_dir}")
    logger.info(f"Watched Folders: {[str(p) for p in daemon.watch_paths]}")

    def shutdown(signum, frame):
        logger.info("Initiating graceful shutdown...")
        daemon.stop_filesystem_watchers()
        threading.Thread(target=server.shutdown).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        daemon.stop_filesystem_watchers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aegis Sovereign Desktop Workstation Daemon (ADR-37)")
    parser.add_argument("--watch", nargs="*", help="Directories to watch and index in-place")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind host for HUD (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9876, help="Loopback port for HUD (default: 9876)")
    args = parser.parse_args()
    run_daemon(watch_paths=args.watch, host=args.host, port=args.port)
