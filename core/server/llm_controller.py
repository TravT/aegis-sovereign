"""
Local LLM On-Demand Runtime Controller.
Manages ephemeral lifecycle (scale up/down, health probing, auto-stop on idle)
for local CPU engines (Ollama and llama.cpp) via Nomad REST API.
"""

import json
import logging
import os
import threading
import time
import urllib.request
from typing import Dict, Any, Optional, List

logger = logging.getLogger("sovereign_server.llm")


class LLMController:
    """Manages ephemeral on-demand lifecycle of local LLMs (Ollama / llama-cpp) via Nomad API."""

    def __init__(
        self,
        nomad_url: Optional[str] = None,
        ollama_url: Optional[str] = None,
        llama_cpp_url: Optional[str] = None,
        idle_timeout_seconds: float = 600.0,
    ):
        self.nomad_url = (nomad_url or os.getenv("NOMAD_ADDR", "http://127.0.0.1:4646")).rstrip("/")
        # ACL token for scaling the LLM jobs (Nomad policy "llm-scaler"); unset when ACLs are off.
        self.nomad_token = os.getenv("NOMAD_TOKEN", "")
        self.ollama_url = (ollama_url or os.getenv("SOVEREIGN_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.llama_cpp_url = (llama_cpp_url or os.getenv("SOVEREIGN_LLAMA_CPP_URL", "http://127.0.0.1:8085")).rstrip("/")
        self.idle_timeout_seconds = idle_timeout_seconds
        self.last_activity = time.time()
        self._lock = threading.Lock()
        self._daemon_started = False
        self._active_engine = "ollama"
        self._start_idle_daemon()

    def record_activity(self):
        with self._lock:
            self.last_activity = time.time()

    def _start_idle_daemon(self):
        if self._daemon_started:
            return
        self._daemon_started = True

        def _watcher():
            while True:
                time.sleep(30.0)
                try:
                    status = self.get_status()
                    if status.get("running"):
                        idle_sec = time.time() - self.last_activity
                        if idle_sec > self.idle_timeout_seconds:
                            logger.info(
                                "Auto-scaling LLM (%s) to standby after %.0fs idle",
                                status.get("engine", "ollama"),
                                idle_sec,
                            )
                            self.scale_engine("stop", engine=status.get("engine", "ollama"))
                except Exception as e:
                    logger.debug("LLM idle watcher exception: %s", e)

        t = threading.Thread(target=_watcher, daemon=True, name="llm_idle_watcher")
        t.start()

    def get_status(self, engine: Optional[str] = None) -> Dict[str, Any]:
        """Probes local Ollama or llama-cpp and Nomad job scale status."""
        target_engine = (engine or self._active_engine).lower()
        if "llama-cpp" in target_engine or target_engine.startswith("llama"):
            return self._get_llama_cpp_status()
        return self._get_ollama_status()

    def _get_ollama_status(self) -> Dict[str, Any]:
        is_responding = False
        model_name = "qwen2.5:1.5b"
        available_models: List[str] = []

        try:
            req = urllib.request.Request(f"{self.ollama_url}/api/tags")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    is_responding = True
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                    if models:
                        available_models = models
                        model_name = models[0]
        except Exception:
            is_responding = False

        nomad_running = False
        desired_count = 0
        try:
            req = urllib.request.Request(f"{self.nomad_url}/v1/job/ollama/scale", headers=self._nomad_headers())
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tg = data.get("TaskGroups", {}).get("ai-stack", {})
                desired_count = tg.get("Desired", 0)
                running_count = tg.get("Running", 0)
                nomad_running = desired_count > 0 or running_count > 0
        except Exception:
            nomad_running = is_responding

        idle_seconds = int(time.time() - self.last_activity)
        status_str = (
            "online"
            if is_responding
            else ("starting" if (nomad_running and desired_count > 0) else "standby")
        )

        return {
            "status": status_str,
            "running": is_responding or nomad_running,
            "engine": "ollama",
            "service": "ollama",
            "model": model_name,
            "available_models": available_models,
            "target_url": self.ollama_url,
            "idle_seconds": idle_seconds,
            "auto_stop_minutes": int(self.idle_timeout_seconds // 60),
            "desired_count": desired_count,
        }

    def _get_llama_cpp_status(self) -> Dict[str, Any]:
        is_responding = False
        model_name = "Phi-3-mini-4k-instruct-q4"

        try:
            req = urllib.request.Request(f"{self.llama_cpp_url}/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    is_responding = True
        except Exception:
            is_responding = False

        nomad_running = False
        desired_count = 0
        try:
            req = urllib.request.Request(f"{self.nomad_url}/v1/job/llama-cpp/scale", headers=self._nomad_headers())
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                tg = data.get("TaskGroups", {}).get("ai-stack", {})
                desired_count = tg.get("Desired", 0)
                running_count = tg.get("Running", 0)
                nomad_running = desired_count > 0 or running_count > 0
        except Exception:
            nomad_running = is_responding

        idle_seconds = int(time.time() - self.last_activity)
        status_str = (
            "online"
            if is_responding
            else ("starting" if (nomad_running and desired_count > 0) else "standby")
        )

        return {
            "status": status_str,
            "running": is_responding or nomad_running,
            "engine": "llama-cpp",
            "service": "llama-cpp",
            "model": model_name,
            "available_models": ["Phi-3-mini-4k-instruct-q4.gguf", "qwen2.5-1.5b-instruct.gguf"],
            "target_url": self.llama_cpp_url,
            "idle_seconds": idle_seconds,
            "auto_stop_minutes": int(self.idle_timeout_seconds // 60),
            "desired_count": desired_count,
        }

    def _nomad_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = dict(extra or {})
        if self.nomad_token:
            headers["X-Nomad-Token"] = self.nomad_token
        return headers

    def scale_engine(
        self,
        action: str,
        engine: str = "ollama",
        timeout_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        """Scales Nomad LLM job up (count=1) or down (count=0)."""
        action = action.lower()
        if action == "status":
            return self.get_status(engine=engine)
        if action not in ("start", "stop"):
            raise ValueError(f"Invalid action {action!r}, must be 'start', 'stop', or 'status'")

        target_count = 1 if action == "start" else 0
        job_id = "llama-cpp" if ("llama-cpp" in engine.lower() or engine.lower().startswith("llama")) else "ollama"
        group_name = "ai-stack"

        payload = {
            "Count": target_count,
            "Target": {"Group": group_name},
            "Message": f"Scaling {action} from Sovereign Web Portal ({job_id})",
        }

        try:
            req = urllib.request.Request(
                f"{self.nomad_url}/v1/job/{job_id}/scale",
                data=json.dumps(payload).encode("utf-8"),
                headers=self._nomad_headers({"Content-Type": "application/json"}),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                pass
        except Exception:
            if action == "stop":
                try:
                    req_stop = urllib.request.Request(
                        f"{self.nomad_url}/v1/job/{job_id}", method="DELETE", headers=self._nomad_headers()
                    )
                    urllib.request.urlopen(req_stop, timeout=5.0)
                except Exception:
                    pass

        self._active_engine = "llama-cpp" if ("llama-cpp" in engine.lower() or engine.lower().startswith("llama")) else "ollama"
        self.record_activity()

        if action == "start":
            start_t = time.time()
            check_url = (
                f"{self.llama_cpp_url}/health"
                if ("llama-cpp" in engine.lower() or engine.lower().startswith("llama"))
                else f"{self.ollama_url}/api/tags"
            )
            while time.time() - start_t < timeout_seconds:
                try:
                    req = urllib.request.Request(check_url)
                    with urllib.request.urlopen(req, timeout=1.0) as resp:
                        if resp.status == 200:
                            return {
                                "success": True,
                                "status": "online",
                                "engine": self._active_engine,
                                "elapsed_s": round(time.time() - start_t, 2),
                            }
                except Exception:
                    time.sleep(1.0)
            return {
                "success": False,
                "status": "starting",
                "engine": self._active_engine,
                "message": "Scale command sent, warming up",
            }
        else:
            return {"success": True, "status": "standby", "engine": self._active_engine}
