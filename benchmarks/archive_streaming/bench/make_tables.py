#!/usr/bin/env python3
"""Render markdown tables from results.json (used to build BASELINE.md / PLAN.md tables)."""

import json
import sys
from pathlib import Path

res = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("results.json")).read_text())
agg = res["aggregate"]
designs = ["D0", "D1", "D2", "D2i", "D3", "D4"]
scen = [s for s in res["scenarios"] if any(k.endswith("|" + s) for k in agg)]


def cell(d):
    if not d:
        return "-"
    if d.get("ok", 0) == 0:
        return f"OOM-killed {d['oom_killed']}/{d['runs']}" if d.get("oom_killed") else f"failed {d['failed']}/{d['runs']}"
    w = d["wall_s"]
    return f"{w['median']:.2f} s / {d['maxrss_minus_baseline_rss_mb']['median']:.0f} MB"


print("### Baseline detail (D0)\n")
print("| scenario | wall s (min / med / max) | memory.peak MB (min / med / max) | peak - baseline MB | ru_maxrss MB | maxrss - baseline RSS MB | sampled anon peak - base MB | retained RSS MB | load 1m (med) | runs ok |")
print("|---|---|---|---|---|---|---|---|---|---|")
for s in scen:
    d = agg.get(f"D0|{s}")
    if not d:
        continue
    if not d.get("ok"):
        print(f"| {s} | {cell(d)} | | | | | | | | 0/{d['runs']} |")
        continue
    f = lambda k: f"{d[k]['min']:.2f} / {d[k]['median']:.2f} / {d[k]['max']:.2f}" if k == "wall_s" else f"{d[k]['min']:.0f} / {d[k]['median']:.0f} / {d[k]['max']:.0f}"
    print(f"| {s} | {f('wall_s')} | {f('cg_memory_peak_mb')} | {d['cg_peak_minus_baseline_mb']['median']:.0f} | {d['maxrss_mb']['median']:.0f} | "
          f"{d['maxrss_minus_baseline_rss_mb']['median']:.0f} | {d['sampled_anon_peak_minus_baseline_mb']['median']:.0f} | {d['retained_rss_mb']['median']:.1f} | "
          f"{d['loadavg_1m']['median']:.2f} | {d['ok']}/{d['runs']} |")

print("\n### Comparison (median wall time / median peak RSS above the pre-call baseline)\n")
print("| scenario | " + " | ".join(designs) + " |")
print("|---|" + "---|" * len(designs))
for s in scen:
    print(f"| {s} | " + " | ".join(cell(agg.get(f"{d}|{s}")) for d in designs) + " |")

print("\n### cgroup memory.peak, median MB (includes interpreter + imports, ~25 MB)\n")
print("| scenario | " + " | ".join(designs) + " |")
print("|---|" + "---|" * len(designs))
for s in scen:
    row = []
    for dn in designs:
        d = agg.get(f"{dn}|{s}")
        row.append("-" if not d else (f"{d['cg_memory_peak_mb']['median']:.0f}" if d.get("ok") else cell(d)))
    print(f"| {s} | " + " | ".join(row) + " |")

print("\n### Per-call latency, median seconds (resolve_virtual_uri share in brackets)\n")
labels = []
for s in scen:
    d0 = agg.get(f"D0|{s}") or next((agg[k] for k in agg if k.endswith("|" + s) and agg[k].get("calls")), None)
    if d0 and d0.get("calls"):
        labels += [(s, l) for l in d0["calls"]]
print("| call | " + " | ".join(designs) + " |")
print("|---|" + "---|" * len(designs))
for s, lab in labels:
    row = []
    for dn in designs:
        d = agg.get(f"{dn}|{s}")
        c = (d or {}).get("calls", {}).get(lab)
        row.append("-" if not c else f"{c['seconds']['median']:.3f} ({c['resolve_s']['median']:.3f})")
    print(f"| {lab} | " + " | ".join(row) + " |")

print("\n### Equivalence vs D0\n")
for k, v in sorted(res["equivalence_vs_D0"].items()):
    print(f"- {k}: {v}")
