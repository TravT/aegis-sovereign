"""Batch work and test runs on the Dell stay inside a memory and CPU cap and out of the nightly window (PRJ-06 step 12.6).

`sovereign-server` jumps from ~143 MiB idle to 750-1,483 MiB when the Gemma encoder loads on its first plain-language
query, and the Dell has about 2 GB free: an uncapped batch job or test run at that moment invites the OOM killer.
The nightly backup, restore test and checks run 03:30-05:30.

Only enforced on the Dell itself (hostname `homelab`, outside containers: Nomad already caps those). Set
AEGIS_UNBOUNDED_OK=1 to run anyway, deliberately.

    from tools.bounded_run import require
    require("vault ingestion")      # exits with the command to use when the run is not allowed
"""

import datetime as dt
import os
import socket
import sys
from pathlib import Path
from typing import Mapping, Optional, Tuple

MEMORY_MAX = int(2.5 * 1024 ** 3)   # bytes
CPU_MAX = 1.5                       # cores (CPUQuota=150%)
NIGHT = (dt.time(3, 30), dt.time(5, 30))
GUARDED_HOST = "homelab"
COMMAND = "systemd-run --user --scope -p MemoryMax=2.5G -p CPUQuota=150%"


def _effective_limits(cgroup_root: Path, proc_cgroup: Path) -> Tuple[float, float]:
    """The tightest memory.max (bytes) and cpu.max (cores) on the path from the process's cgroup to the root."""
    rel = ""
    for line in proc_cgroup.read_text().splitlines():
        if line.startswith("0::"):
            rel = line[3:].strip()
    mem, cpu = float("inf"), float("inf")
    path = cgroup_root / rel.lstrip("/")
    while True:
        m = path / "memory.max"
        if m.is_file():
            v = m.read_text().strip()
            if v != "max":
                mem = min(mem, int(v))
        c = path / "cpu.max"
        if c.is_file():
            quota, _, period = c.read_text().strip().partition(" ")
            if quota != "max":
                cpu = min(cpu, int(quota) / int(period or 100000))
        if path == cgroup_root or path.parent == path:
            break
        path = path.parent
    return mem, cpu


def check(
    purpose: str,
    *,
    now: Optional[dt.datetime] = None,
    hostname: Optional[str] = None,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    proc_cgroup: Path = Path("/proc/self/cgroup"),
    in_container: Optional[bool] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """None when `purpose` may run here and now, else the reason (with the command to use)."""
    env = os.environ if env is None else env
    hostname = socket.gethostname() if hostname is None else hostname
    in_container = Path("/.dockerenv").exists() if in_container is None else in_container
    if hostname != GUARDED_HOST or in_container or env.get("AEGIS_UNBOUNDED_OK") == "1":
        return None
    now = now or dt.datetime.now()
    if NIGHT[0] <= now.time() < NIGHT[1]:
        return (f"{purpose} refused: 03:30-05:30 is the nightly backup, restore test and checks window. "
                "Run it after 05:30 (AEGIS_UNBOUNDED_OK=1 overrides, deliberately).")
    try:
        mem, cpu = _effective_limits(cgroup_root, proc_cgroup)
    except OSError as exc:
        return f"{purpose} refused: cannot read this process's cgroup limits ({exc}). Run it as: {COMMAND} <command>"
    problems = []
    if mem > MEMORY_MAX:
        problems.append("no memory cap" if mem == float("inf") else f"memory cap {mem / 1024 ** 3:.1f} GiB > 2.5 GiB")
    if cpu > CPU_MAX:
        problems.append("no CPU cap" if cpu == float("inf") else f"CPU cap {cpu:.1f} cores > 1.5")
    if problems:
        return (f"{purpose} refused on the Dell: {', '.join(problems)}. The Gemma encoder in sovereign-server can take "
                f"~1.5 GB at any moment. Run it as: {COMMAND} <command>")
    return None


def require(purpose: str) -> None:
    reason = check(purpose)
    if reason:
        sys.exit(reason)
