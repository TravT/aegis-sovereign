"""Step 12.6: batch work and test runs on the Dell stay inside a memory and CPU cap and out of the nightly window.

`sovereign-server` jumps from ~143 MiB idle to 750-1,483 MiB when the Gemma encoder loads on the first plain-language
query; the Dell has about 2 GB free. An uncapped batch job or test run at that moment invites the OOM killer, and
the nightly backup, restore test and checks run 03:30-05:30.
"""

import datetime as dt

import pytest

from tools.bounded_run import check

GIB = 1024 ** 3


def _cgroups(tmp_path, chain):
    """A fake cgroup tree: `chain` lists (memory.max, cpu.max) from the root down to the process's own group."""
    root = tmp_path / "cg"
    path = root
    rel = ""
    for i, (mem, cpu) in enumerate(chain):
        if i:
            rel += f"/g{i}"
            path = root / rel.lstrip("/")
        path.mkdir(parents=True, exist_ok=True)
        if mem is not None:
            (path / "memory.max").write_text(f"{mem}\n")
        if cpu is not None:
            (path / "cpu.max").write_text(f"{cpu}\n")
    proc = tmp_path / "proc_cgroup"
    proc.write_text(f"0::{rel or '/'}\n")
    return root, proc


def _check(tmp_path, chain, when="14:00", host="homelab", **kw):
    root, proc = _cgroups(tmp_path, chain)
    now = dt.datetime.combine(dt.date(2026, 10, 15), dt.time.fromisoformat(when))
    return check("test run", now=now, hostname=host, cgroup_root=root, proc_cgroup=proc, in_container=False, env={}, **kw)


def test_capped_scope_in_the_day_is_allowed(tmp_path):
    assert _check(tmp_path, [(None, None), ("max", "max"), (int(2.5 * GIB), "150000 100000")]) is None


def test_uncapped_run_is_refused_with_the_command_to_use(tmp_path):
    reason = _check(tmp_path, [(None, None), ("max", "max")])
    assert reason and "memory" in reason
    assert "systemd-run --user --scope -p MemoryMax=2.5G -p CPUQuota=150%" in reason


def test_a_cap_on_a_parent_group_counts(tmp_path):
    assert _check(tmp_path, [(None, None), (2 * GIB, "100000 100000"), ("max", "max")]) is None


@pytest.mark.parametrize("mem,cpu,what", [(4 * GIB, "150000 100000", "memory"), (2 * GIB, "max", "CPU"),
                                          (2 * GIB, "400000 100000", "CPU")])
def test_too_loose_a_cap_is_refused(tmp_path, mem, cpu, what):
    reason = _check(tmp_path, [(None, None), (mem, cpu)])
    assert reason and what in reason


@pytest.mark.parametrize("when,blocked", [("03:29", False), ("03:30", True), ("04:45", True), ("05:29", True), ("05:30", False)])
def test_nightly_window_is_refused(tmp_path, when, blocked):
    reason = _check(tmp_path, [(None, None), (2 * GIB, "150000 100000")], when=when)
    assert (reason is not None and "03:30" in reason) == blocked


def test_other_hosts_containers_and_explicit_override_are_not_checked(tmp_path):
    chain = [(None, None), ("max", "max")]
    assert _check(tmp_path, chain, host="ci-runner") is None
    root, proc = _cgroups(tmp_path, chain)
    now = dt.datetime(2026, 10, 15, 4, 0)
    assert check("x", now=now, hostname="homelab", cgroup_root=root, proc_cgroup=proc, in_container=True, env={}) is None
    assert check("x", now=now, hostname="homelab", cgroup_root=root, proc_cgroup=proc, in_container=False,
                 env={"AEGIS_UNBOUNDED_OK": "1"}) is None
