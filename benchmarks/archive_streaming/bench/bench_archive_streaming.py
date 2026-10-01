#!/usr/bin/env python3
"""Reproducible benchmark: Aegis archive-loading path, baseline (D0) vs prototype designs.

Parent mode (default) runs every (design, scenario) N times, each run in a FRESH Python process
inside its own capped systemd user scope:

    systemd-run --user --scope -q -p MemoryMax=2G -p MemorySwapMax=0 -- python this.py --child ...

The child reads its own cgroup (/proc/self/cgroup -> /sys/fs/cgroup/<scope>/) and reports:
  * cgroup memory.peak (whole scope lifetime; includes page cache first touched in the scope)
  * sampled peak of cgroup `anon` (memory.stat, every 5 ms; approximate, misses sub-5 ms spikes)
  * ru_maxrss (exact peak RSS of the process) and the RSS/anon baseline before the first call
  * RSS/anon retained after the calls return and their results are dropped (gc.collect())
  * wall time per call and per scenario, phase timers, and a SHA-256 digest of every output
    (full inspect_archive dict / ArchiveEntry incl. raw bytes / rendered HTML / ingest report)
The parent records loadavg, detects OOM kills (exit 137 / SIGKILL), aggregates min/median/max
and checks that every design's outputs are byte-identical to D0's.

Only reads: the four zips in docs/Hua_Docs (O_RDONLY) and, for the portal scenarios, the live
router DB opened with sqlite `mode=ro`. Writes only under this benchmark's directory.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import gc
import hashlib
import json
import os
import resource
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any, Callable, Dict, List

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROTO = ROOT / "proto"
APPLIANCE = Path("/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance")
PYTHON = "/home/tlima/Enterprise_Hub/.venv/bin/python"
VAULT_ROUTER_DB = Path("/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db")
HUA = "/home/tlima/Enterprise_Hub/docs/Hua_Docs"
WORK = HERE / "work"

USC_ZIP = f"{HUA}/HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip"
USC_HW = "HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics"
UPCF_ZIP = f"{HUA}/UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).zip"
UPCF_HW = "UPCF 26.1.0 Product Documentation (Virtual Machine Container) 02 (Online Information Center).hwics"
REL_USC = f"{HUA}/USC 26.1.0_ReleaseDoc_EN (VM).zip"
REL_UPCF = f"{HUA}/UPCF 26.1.0.5_ReleaseDoc_EN (Virtual Machine Container).zip"


def hw(zip_path: str, inner: str, member: str) -> str:
    return f"archive://{zip_path}!{inner}#{member}"


U_20104 = hw(USC_ZIP, USC_HW, "resources/alarms/20104.html")  # what ALM-20104 routes to (router DB record)
U_LONG = hw(USC_ZIP, USC_HW, "resources/toctopics/en-us_topic_0000001231298590.html")  # 550 KB, at 97% of the inner stream
U_DEEP = hw(USC_ZIP, USC_HW, "resources/sps/maintenance/redundancy_mgt/cn_21_33_300027.html")  # 30 KB, at 94%
U_UPCF = hw(UPCF_ZIP, UPCF_HW, "resources/upcc/maintenance/redundancy_mgt/cn_90_33_201040.html")
U_ZIPZIP = f"archive://{REL_USC}!12. Other Documents/SOAP Interface for NP Subscriber Definition and Deletion/mnp.zip#mnp/mnp.wsdl"
U_XLSX = f"archive://{REL_USC}#04. NorthBound/USC 26.1.0 Alarm List.xlsx"
U_DOCX = f"archive://{REL_USC}#01. Release Notes/USC 26.1.0 Release Notes.docx"
U_HW_XLSX = hw(USC_ZIP, USC_HW, "resources/be/description/security_desc/resource/uscdb_communication_matrix_en.xlsx")

DESIGNS = ["D0", "D1", "D2", "D2i", "D3", "D4"]


# =============================================================================== child side
def _cgroup_dir() -> Path:
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            return Path("/sys/fs/cgroup" + line[3:].strip())
    raise RuntimeError("cgroup v2 not found")


def _memstat(cg: Path) -> Dict[str, int]:
    out = {}
    for line in (cg / "memory.stat").read_text().splitlines():
        k, _, v = line.partition(" ")
        if k in ("anon", "file", "kernel", "sock", "shmem"):
            out[k] = int(v)
    return out


def _rss() -> int:
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


class Sampler(threading.Thread):
    def __init__(self, cg: Path, interval: float = 0.005):
        super().__init__(daemon=True)
        self.cg, self.interval = cg, interval
        self.max_anon = 0
        self.max_rss = 0
        self._halt = threading.Event()
        self._path = cg / "memory.stat"

    def run(self):
        while not self._halt.is_set():
            try:
                with open(self._path, "rb") as f:
                    head = f.read(64)
                if head.startswith(b"anon "):
                    self.max_anon = max(self.max_anon, int(head.split(b"\n", 1)[0].split()[1]))
                self.max_rss = max(self.max_rss, _rss())
            except Exception:
                pass
            self._halt.wait(self.interval)

    def stop(self):
        self._halt.set()
        self.join()


def _install_import_stubs() -> None:
    """Import core.* submodules without executing core/__init__.py and core/server/__init__.py.

    Those package initialisers import the searcher, Qdrant client, graph store, HTTP server... (+100 MB
    RSS, ~3 s) which are irrelevant to the archive path and would drown the signal. The modules under
    test (core.containers.*, core.server.archive_inspector/constants/viewer, core.ingest.*) are loaded
    unmodified from the repo working tree. `--full-imports` disables this.
    """
    for name, sub in (("core", "core"), ("core.server", "core/server")):
        if name not in sys.modules:
            m = types.ModuleType(name)
            m.__path__ = [str(APPLIANCE / sub)]
            sys.modules[name] = m


class _NoDB:
    def cursor(self):
        raise RuntimeError("router DB disabled for this scenario")


class RouterStub:
    """What ArchiveInspector needs from the router: `_conn` (read-only connection to the live vault)."""

    def __init__(self, use_db: bool):
        if use_db:
            self._conn = sqlite3.connect(f"file:{VAULT_ROUTER_DB}?mode=ro", uri=True, check_same_thread=False)
        else:
            self._conn = _NoDB()


def _digest(obj: Any) -> str:
    def enc(o):
        if isinstance(o, bytes):
            return {"__bytes_sha256__": hashlib.sha256(o).hexdigest(), "len": len(o)}
        if dataclasses.is_dataclass(o):
            return {k: enc(v) for k, v in dataclasses.asdict(o).items()} if not isinstance(o, type) else str(o)
        if isinstance(o, dict):
            return {str(k): enc(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [enc(v) for v in o]
        return o
    if dataclasses.is_dataclass(obj):
        obj = {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}
    return hashlib.sha256(json.dumps(enc(obj), sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class Ctx:
    def __init__(self, design: str, use_db: bool):
        sys.path.insert(0, str(PROTO))
        from streamers import ArchiveCache, make_streamer  # noqa: E402
        from core.server.archive_inspector import ArchiveInspector  # noqa: E402
        from core.server.viewer import DocumentViewer  # noqa: E402
        self.design = design
        self.cache = ArchiveCache() if design in ("D3", "D4") else None
        self.streamer = make_streamer(design, self.cache)
        if design == "D4":
            from inspector_d4 import InspectorD4
            cls = InspectorD4
        else:
            cls = ArchiveInspector
        self.inspector = cls(archive_streamer=self.streamer, router=RouterStub(use_db))
        self.viewer = DocumentViewer
        self.calls: List[Dict[str, Any]] = []
        # phase timer: time spent inside streamer.resolve_virtual_uri (the archive read), per thread
        self._tl = threading.local()
        orig = self.streamer.resolve_virtual_uri

        def timed(uri):
            t = time.perf_counter()
            try:
                return orig(uri)
            finally:
                self._tl.resolve_s = getattr(self._tl, "resolve_s", 0.0) + time.perf_counter() - t
        self.streamer.resolve_virtual_uri = timed

    def call(self, label: str, fn: Callable[[], Any]) -> Any:
        self._tl.resolve_s = 0.0
        t0 = time.perf_counter()
        err = None
        try:
            res = fn()
        except Exception as exc:  # recorded, compared across designs like any output
            res = {"__error__": type(exc).__name__, "msg": str(exc)[:300]}
            err = type(exc).__name__
        dt = time.perf_counter() - t0
        self.calls.append({"label": label, "seconds": round(dt, 4), "resolve_s": round(self._tl.resolve_s, 4),
                           "digest": _digest(res), "error": err, "rss_after_call": _rss()})
        return res

    def inspect(self, label: str, uri: str, **kw) -> Any:
        body = {"virtual_uri": uri, "section_filter": "", "extract_diagram_to_artifact": False, "max_chars": 8000}
        body.update(kw)
        # exactly what core/server/handler.py:363-384 passes for this JSON body
        return self.call(label, lambda: self.inspector.inspect_archive(
            archive_path=body.get("archive_path", ""), virtual_uri=body.get("virtual_uri", ""),
            query=body.get("query", ""), ingest=bool(body.get("ingest", False)),
            section_filter=str(body.get("section_filter") or ""),
            extract_diagram_to_artifact=bool(body.get("extract_diagram_to_artifact", False)),
            char_offset=int(body.get("char_offset", 0)), max_chars=int(body.get("max_chars", 8000))))


def s1(c: Ctx):  # portal startup preview (portal.js:448-456 body), DB lookup on
    c.inspect("S1 preview ALM-20104", U_20104)


def s2(c: Ctx):
    c.inspect("S2 section=Procedure", U_20104, section_filter="Procedure")
    c.inspect("S2 section=Possible Causes", U_20104, section_filter="Possible Causes")


def s3(c: Ctx):
    for page in range(5):
        c.inspect(f"S3 page {page} (char_offset={page * 8000})", U_LONG, char_offset=page * 8000)


def s4(c: Ctx):
    c.inspect("S4a zip-in-zip (STORED inner) wsdl", U_ZIPZIP)
    c.inspect("S4b .hwics member at 94% of inner stream", U_DEEP)


def s5(c: Ctx):
    c.inspect("S5a xlsx in ReleaseDoc zip", U_XLSX)
    c.inspect("S5b docx in ReleaseDoc zip", U_DOCX)
    c.inspect("S5c xlsx inside .hwics", U_HW_XLSX)


def s6(c: Ctx):
    uris = [U_20104, U_UPCF, U_DEEP]
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(3) as ex:
        futs = [ex.submit(c.inspect, f"S6 concurrent #{i} {u.rsplit('/', 1)[-1]}", u) for i, u in enumerate(uris)]
        for f in futs:
            f.result()
    c.calls.append({"label": "S6 all three (wall)", "seconds": round(time.perf_counter() - t0, 4), "digest": "", "error": None})


def s7(c: Ctx):
    def view(uri):
        entry = c.streamer.resolve_virtual_uri(uri)  # app.py:555-558
        return c.viewer.format_entry_to_styled_html(entry, uri)
    c.call("S7a /archive/view ALM-20104 html", lambda: view(U_20104))
    c.call("S7b /archive/view docx", lambda: view(U_DOCX))


def _ingest(c: Ctx, source: str, label: str):
    from core.ingest.pipeline import IngestOptions, ingest_source
    from core.structure import get_profile
    db = WORK / "ingest_scratch.db"  # empty document_records table; dry_run never writes
    def run():
        rep = ingest_source(db, Path(source), IngestOptions("BENCH", get_profile("edge"), "missing", 0, None, dry_run=True))
        rep.pop("seconds", None)
        return rep
    c.call(label, run)


def s8(c: Ctx):
    _ingest(c, REL_USC, "S8a ingest --dry-run USC ReleaseDoc (142 MB)")


def s8b(c: Ctx):
    _ingest(c, USC_ZIP, "S8b ingest --dry-run USC product doc (330 MB; .hwics skipped)")


def s9(c: Ctx):  # cache effect: repeated and neighbouring requests in one server process
    c.inspect("S9 #1 ALM-20104 (cold)", U_20104)
    c.inspect("S9 #2 ALM-20104 (repeat)", U_20104)
    c.inspect("S9 #3 ALM-20104 section=Procedure", U_20104, section_filter="Procedure")
    c.inspect("S9 #4 other member, same archive (94%)", U_DEEP)
    c.inspect("S9 #5 other member, same archive (97%, 550 KB)", U_LONG)


def s10(c: Ctx):  # archive_path listing mode (stream_archive) on the smallest zip
    c.call("S10 stream_archive listing UPCF ReleaseDoc (19 MB)",
           lambda: c.inspector.inspect_archive(archive_path=REL_UPCF))


SCENARIOS: Dict[str, Dict[str, Any]] = {
    "S1": {"fn": s1, "db": True, "desc": "portal startup preview: POST /archive/inspect for the ALM-20104 top hit"},
    "S2": {"fn": s2, "db": True, "desc": "inspect with section_filter Procedure, then Possible Causes"},
    "S3": {"fn": s3, "db": False, "desc": "char_offset paging, 5 pages x 8000 chars of a 550 KB member at 97% of the .hwics"},
    "S4": {"fn": s4, "db": False, "desc": "nested: zip-in-zip (STORED inner) + .hwics member at 94%"},
    "S5": {"fn": s5, "db": False, "desc": "xlsx + docx members (ReleaseDoc zip) + xlsx inside .hwics"},
    "S6": {"fn": s6, "db": True, "desc": "three concurrent previews (threads, like ThreadingHTTPServer)"},
    "S7": {"fn": s7, "db": False, "desc": "/archive/view HTML render (resolve_virtual_uri + DocumentViewer)"},
    "S8": {"fn": s8, "db": False, "desc": "ingest pipeline --dry-run on the 142 MB ReleaseDoc zip", "designs": ["D0"]},
    "S8b": {"fn": s8b, "db": False, "desc": "ingest pipeline --dry-run on the 330 MB product zip", "designs": ["D0"]},
    "S9": {"fn": s9, "db": False, "desc": "cache effect: 5 sequential requests in one process"},
    "S10": {"fn": s10, "db": False, "desc": "archive_path listing (stream_archive) of the 19 MB ReleaseDoc zip"},
}


def child(args) -> int:
    cg = _cgroup_dir()
    if not args.full_imports:
        _install_import_stubs()
    sc = SCENARIOS[args.scenario]
    t_imp = time.perf_counter()
    ctx = Ctx(args.design, use_db=sc["db"] and not args.no_db)
    if args.scenario in ("S8", "S8b"):
        import core.ingest.pipeline  # noqa: F401  (import cost outside the measured region)
        import core.structure  # noqa: F401
    import_s = time.perf_counter() - t_imp
    gc.collect()
    base = {"rss": _rss(), "maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "cg_current": int((cg / "memory.current").read_text()), **{f"cg_{k}": v for k, v in _memstat(cg).items()}}
    sampler = Sampler(cg)
    sampler.start()
    t0 = time.perf_counter()
    sc["fn"](ctx)
    wall = time.perf_counter() - t0
    sampler.stop()
    after_keep = {"rss": _rss(), **{f"cg_{k}": v for k, v in _memstat(cg).items()}}
    gc.collect()
    after = {"rss": _rss(), "cg_current": int((cg / "memory.current").read_text()),
             **{f"cg_{k}": v for k, v in _memstat(cg).items()}}
    events = dict(l.split() for l in (cg / "memory.events").read_text().splitlines())
    out = {
        "design": args.design, "scenario": args.scenario, "wall_s": round(wall, 4), "import_s": round(import_s, 3),
        "calls": ctx.calls,
        "baseline": base, "after": after, "after_before_gc": after_keep,
        "cg_memory_peak": int((cg / "memory.peak").read_text()),
        "cg_swap_peak": int((cg / "memory.swap.peak").read_text()) if (cg / "memory.swap.peak").exists() else None,
        "maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "sampled_max_anon": sampler.max_anon, "sampled_max_rss": sampler.max_rss,
        "memory_events": events,
        "streamer_stats": dict(getattr(ctx.streamer, "stats", {}) or {}),
        "cache_stats": dict(ctx.cache.stats) if ctx.cache else None,
        "cache_index_bytes": ctx.cache.index_bytes() if ctx.cache else None,
        "cgroup": str(cg),
    }
    Path(args.result_file).write_text(json.dumps(out))
    return 0


# =============================================================================== parent side
def _prepare_work() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    db = WORK / "ingest_scratch.db"
    if not db.exists():
        src = sqlite3.connect(f"file:{VAULT_ROUTER_DB}?mode=ro", uri=True)
        ddl = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='document_records'").fetchone()[0]
        src.close()
        dst = sqlite3.connect(str(db))
        dst.execute(ddl)
        dst.commit()
        dst.close()


def _warm_page_cache() -> None:
    """Read each zip once OUTSIDE the scopes so its pages are not charged to (and do not inflate) a scope's memory.peak."""
    for p in (USC_ZIP, UPCF_ZIP, REL_USC, REL_UPCF):
        with open(p, "rb", buffering=0) as f:
            while f.read(8 << 20):
                pass


def run_one(design: str, scenario: str, run_idx: int, mem_max: str, extra: List[str]) -> Dict[str, Any]:
    rf = WORK / f"res_{design}_{scenario}_{run_idx}.json"
    if rf.exists():
        rf.unlink()
    cmd = ["systemd-run", "--user", "--scope", "-q", "-p", f"MemoryMax={mem_max}", "-p", "MemorySwapMax=0", "--",
           PYTHON, str(Path(__file__).resolve()), "--child", "--design", design, "--scenario", scenario,
           "--result-file", str(rf)] + extra
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=f"{APPLIANCE}:{PROTO}")
    load_before = os.getloadavg()
    t0 = time.perf_counter()
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=900)
    proc_wall = time.perf_counter() - t0
    rec: Dict[str, Any] = {"design": design, "scenario": scenario, "run": run_idx, "returncode": p.returncode,
                           "process_wall_s": round(proc_wall, 3), "loadavg_before": load_before,
                           "loadavg_after": os.getloadavg()}
    if p.returncode == 0 and rf.exists():
        rec.update(json.loads(rf.read_text()))
        rf.unlink()
    else:
        rec["failed"] = True
        rec["oom_killed_likely"] = p.returncode in (137, -9)
        rec["stderr_tail"] = p.stderr[-1500:]
    return rec


def _mb(x) -> float:
    return round(x / 1048576, 1)


def aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        groups.setdefault(f"{r['design']}|{r['scenario']}", []).append(r)
    agg = {}
    for key, rs in groups.items():
        ok = [r for r in rs if not r.get("failed")]
        d: Dict[str, Any] = {"runs": len(rs), "ok": len(ok), "failed": len(rs) - len(ok),
                             "oom_killed": sum(1 for r in rs if r.get("oom_killed_likely"))}
        if ok:
            def s(vals):
                return {"min": min(vals), "median": statistics.median(vals), "max": max(vals)}
            d["wall_s"] = s([r["wall_s"] for r in ok])
            d["cg_memory_peak_mb"] = s([_mb(r["cg_memory_peak"]) for r in ok])
            d["cg_peak_minus_baseline_mb"] = s([_mb(r["cg_memory_peak"] - r["baseline"]["cg_current"]) for r in ok])
            d["maxrss_mb"] = s([_mb(r["maxrss"]) for r in ok])
            d["maxrss_minus_baseline_rss_mb"] = s([_mb(r["maxrss"] - r["baseline"]["rss"]) for r in ok])
            d["sampled_anon_peak_minus_baseline_mb"] = s([_mb(r["sampled_max_anon"] - r["baseline"].get("cg_anon", 0)) for r in ok])
            d["retained_rss_mb"] = s([_mb(r["after"]["rss"] - r["baseline"]["rss"]) for r in ok])
            d["retained_anon_mb"] = s([_mb(r["after"].get("cg_anon", 0) - r["baseline"].get("cg_anon", 0)) for r in ok])
            d["baseline_rss_mb"] = s([_mb(r["baseline"]["rss"]) for r in ok])
            d["file_charged_after_mb"] = s([_mb(r["after"].get("cg_file", 0)) for r in ok])
            labels = [c["label"] for c in ok[0]["calls"]]
            d["calls"] = {}
            for i, lab in enumerate(labels):
                vals = [r["calls"][i]["seconds"] for r in ok if i < len(r["calls"])]
                rvals = [r["calls"][i].get("resolve_s", 0.0) for r in ok if i < len(r["calls"])]
                d["calls"][lab] = {"seconds": s(vals), "resolve_s": s(rvals), "digest": ok[0]["calls"][i]["digest"],
                                   "error": ok[0]["calls"][i]["error"],
                                   "digest_stable_across_runs": len({r["calls"][i]["digest"] for r in ok}) == 1}
            d["streamer_stats"] = ok[0].get("streamer_stats")
            d["cache_stats"] = ok[0].get("cache_stats")
            d["cache_index_bytes"] = ok[0].get("cache_index_bytes")
            d["loadavg_1m"] = s([r["loadavg_before"][0] for r in rs])
        agg[key] = d
    return agg


def equivalence(agg: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for key, d in agg.items():
        design, scen = key.split("|")
        if design == "D0" or "calls" not in d:
            continue
        ref = agg.get(f"D0|{scen}")
        if not ref or "calls" not in ref:
            out[key] = "no D0 reference (D0 failed or not run)"
            continue
        diffs = [lab for lab, c in d["calls"].items() if c["digest"] and ref["calls"].get(lab, {}).get("digest") != c["digest"]]
        out[key] = "IDENTICAL" if not diffs else {"differs": diffs}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--design", default="D0")
    ap.add_argument("--scenario", default="S1")
    ap.add_argument("--result-file")
    ap.add_argument("--designs", default=",".join(DESIGNS))
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--mem-max", default="2G")
    ap.add_argument("--out", default=str(HERE / "results.json"))
    ap.add_argument("--append", action="store_true", help="merge into an existing --out (re-run a subset)")
    ap.add_argument("--no-db", action="store_true", help="never open the live router DB (skip the inspector's LIKE lookup)")
    ap.add_argument("--full-imports", action="store_true", help="execute core/__init__ and core/server/__init__ (production import footprint)")
    ap.add_argument("--no-warm", action="store_true")
    args = ap.parse_args()
    if args.child:
        return child(args)

    _prepare_work()
    if not args.no_warm:
        _warm_page_cache()
    extra = (["--no-db"] if args.no_db else []) + (["--full-imports"] if args.full_imports else [])
    records: List[Dict[str, Any]] = []
    outp = Path(args.out)
    if args.append and outp.exists():
        records = json.loads(outp.read_text())["records"]
    todo = [(d, s) for s in args.scenarios.split(",") for d in args.designs.split(",")
            if d in SCENARIOS[s].get("designs", DESIGNS)]
    for d, s in todo:
        records = [r for r in records if not (r["design"] == d and r["scenario"] == s)]
        for i in range(args.runs):
            rec = run_one(d, s, i, args.mem_max, extra)
            records.append(rec)
            status = "OOM-KILLED" if rec.get("oom_killed_likely") else ("FAILED rc=%s" % rec["returncode"] if rec.get("failed") else "ok")
            peak = _mb(rec["cg_memory_peak"]) if "cg_memory_peak" in rec else "-"
            print(f"{d:4} {s:4} run {i} {status:10} wall={rec.get('wall_s', '-')}s cg.peak={peak}MB "
                  f"maxrss={_mb(rec['maxrss']) if 'maxrss' in rec else '-'}MB load={rec['loadavg_before'][0]:.2f}", flush=True)
    agg = aggregate(records)
    res = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": {"kernel": os.uname().release, "cpu_count": os.cpu_count(), "python": sys.version.split()[0]},
        "config": {"mem_max": args.mem_max, "runs": args.runs, "no_db": args.no_db, "full_imports": args.full_imports},
        "scenarios": {k: v["desc"] for k, v in SCENARIOS.items()},
        "aggregate": agg,
        "equivalence_vs_D0": equivalence(agg),
        "records": records,
    }
    outp.write_text(json.dumps(res, indent=1))
    print(json.dumps(res["equivalence_vs_D0"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
