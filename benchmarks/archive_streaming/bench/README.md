# Archive-streaming benchmark harness

Reproducible benchmark of the Aegis archive-loading path (`/archive/inspect`, `/archive/view`,
ingest dry-run) for the current code (D0) and the prototype designs in `../proto/` (D1, D2, D2i, D3, D4).
It only reads: the zips in `docs/Hua_Docs` (O_RDONLY) and, for the portal scenarios, the live router DB
opened with sqlite `mode=ro`. It writes only under this directory (`results.json`, `work/`).
It never starts the server, never talks to port 8765 and never edits the repo.

## Rerun

```bash
cd /home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/benchmarks/archive_streaming/bench
PY=/home/tlima/Enterprise_Hub/.venv/bin/python

# full matrix (about 50 min on the Dell; D2 is slow by design): every design x scenario, 5 fresh processes each
$PY bench_archive_streaming.py --runs 5 --out results.json

# a subset, merged into an existing results file
$PY bench_archive_streaming.py --designs D0,D3 --scenarios S1,S6 --runs 5 --append --out results.json

# markdown tables from a results file
$PY make_tables.py results.json > tables.md

# flags: --no-db (never open the router DB), --full-imports (execute core/__init__.py and
# core/server/__init__.py like the real server, +~100 MB baseline), --mem-max 2G (scope cap), --no-warm
```

Each run is `systemd-run --user --scope -q -p MemoryMax=2G -p MemorySwapMax=0 -- python bench_archive_streaming.py --child ...`,
so every measurement is a fresh interpreter in its own cgroup. The child reads its own cgroup files
before exiting. A child killed by the cap is recorded as `oom_killed_likely` (exit 137).

The prototype tests (behaviour equivalence + security) run separately:

```bash
cd ../proto
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance:. \
  systemd-run --user --scope -q -p MemoryMax=2G -p MemorySwapMax=0 -- \
  /home/tlima/Enterprise_Hub/.venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=$PWD/.pytest_tmp test_proto_equivalence.py
```

`PYTHONDONTWRITEBYTECODE=1` matters: without it, importing the repo modules would drop `__pycache__`
directories into the repo working tree.

## Metrics (per run; aggregated as min / median / max)

| field | meaning |
|---|---|
| `wall_s` | wall time of the scenario body (all its calls), measured in the child |
| `calls[].seconds`, `calls[].resolve_s` | per request wall time, and the part spent inside `resolve_virtual_uri` (the archive read) |
| `cg_memory_peak` | cgroup v2 `memory.peak` of the scope: whole-lifetime peak, includes interpreter + imports and any page cache first touched inside the scope. The zips are read once before the matrix (`_warm_page_cache`) so their pages are charged to the parent, not the scopes |
| `cg_peak_minus_baseline` | `memory.peak` minus `memory.current` right before the first call |
| `maxrss` | `ru_maxrss` of the child (exact peak RSS) |
| `sampled_max_anon` | peak of `anon` in the scope's `memory.stat`, sampled every 5 ms (approximate) |
| `retained_*` | RSS / anon after the calls returned and their results were dropped (`gc.collect()`), minus the baseline |
| `digest` | SHA-256 of the full output (inspect_archive dict, ArchiveEntry incl. raw bytes, HTML, ingest report). `equivalence_vs_D0` in results.json compares every call's digest with D0's |
| `loadavg_before` | 1/5/15-min load average before the run (noise indicator) |

Import stubs: by default the child imports `core.containers.*`, `core.server.archive_inspector`,
`core.server.constants`, `core.server.viewer` and `core.ingest.*` straight from the repo tree without
executing `core/__init__.py` / `core/server/__init__.py` (which pull the searcher, Qdrant client and the
HTTP server: about +100 MB RSS and 3 s of imports that the archive path does not use). The code under
test is unmodified. Use `--full-imports` to measure with the production import footprint.

## Scenarios

| id | what | router DB lookup |
|---|---|---|
| S1 | portal startup preview: `POST /archive/inspect {"virtual_uri": <ALM-20104 top hit>, "section_filter": "", "extract_diagram_to_artifact": false, "max_chars": 8000}` (portal.js:448-456) | on (mode=ro) |
| S2 | same URI with `section_filter` "Procedure", then "Possible Causes" | on |
| S3 | `char_offset` paging: 5 pages x 8000 chars of a 550 KB member at 97 % of the .hwics stream | off |
| S4 | nested: zip-in-zip with a STORED inner zip (ReleaseDoc) + a .hwics member at 94 % | off |
| S5 | xlsx + docx members of the 142 MB ReleaseDoc zip + an xlsx inside the .hwics | off |
| S6 | three concurrent previews (threads, as under ThreadingHTTPServer): USC ALM-20104, a UPCF member, a deep USC member | on |
| S7 | `/archive/view` render: `resolve_virtual_uri` + `DocumentViewer.format_entry_to_styled_html` (html + docx) | n/a |
| S8 / S8b | `core.ingest.pipeline.ingest_source(..., dry_run=True)` (what `tools/ingest_files.py --dry-run` calls) against an empty scratch DB, on the 142 MB ReleaseDoc zip / the 330 MB product zip. D0 only: ingest does not use the streamer | n/a |
| S9 | cache effect: 5 sequential requests in one process (repeat, section jump, two other members of the same archive) | off |
| S10 | `archive_path` listing (`stream_archive`) of the 19 MB ReleaseDoc zip | n/a |

The router DB lookup (`SELECT ... WHERE doc_identifier = ? OR doc_identifier = ? OR metadata LIKE ?`)
is a full table scan; it is enabled only for the portal-facing scenarios so the archive cost stays visible elsewhere.
