---
title: "ADR-16: Archive Streaming with a Checkpoint Index, Lazy Preview & a Memory Budget"
type: "adr"
category: "architecture"
status: "accepted"
date: "2026-10-01"
last_reviewed: "2026-10-01"
node: "homelab"
domain: "ai-data"
tags:
  - aegis/adrs
  - architecture/decisions
  - product/appliance
  - performance/memory
  - ingestion/containers
aliases:
  - "ADR-16"
  - "Archive Streaming"
  - "Checkpoint Index"
---

# ADR-16: Archive Streaming with a Checkpoint Index, Lazy Preview & a Memory Budget

## Status
Accepted as a design on 2026-10-01; the interim mitigation (a higher memory limit) is deployed, and phase 0 (the portal opens idle and previews on tap) was implemented on 2026-10-01. Phase 1 (the streaming core with a shared cache, and the database race fix) was implemented on 2026-10-07; phases 2 to 4 are not. Builds on [ADR-07](ADR-07-Virtual-Container-Streaming-and-Cognitive-Graph-Intelligence.md) (virtual container streaming: read-only, in memory, bounded) and pairs with [ADR-15](ADR-15-Mobile-First-Search-First-Portal-Shell-and-Its-Product-Decisions.md) (the portal opens idle, the preview happens on tap). Evidence and plan: the baseline (wiki note `projects/aegis/studies/archive-streaming-baseline.md` in Enterprise_Hub) and the plan (wiki note `projects/aegis/studies/archive-streaming-plan.md` in Enterprise_Hub); the benchmark harness and prototypes are in `benchmarks/archive_streaming/` of the appliance repository.

## Date
2026-10-01

## Context

Opening the portal fired a startup query and then an automatic preview of the first result. The preview reads the whole ReleaseDoc zip (330 MB) into memory with `f.read()` in `archive_streamer._read_file_readonly_bytes`, decompresses a member, and reads nested archives whole again: about **1.06 GB of heap** for one preview, against a 768 MB task limit. The server was out-of-memory-killed on every page load (runbook section 21). The code from before the graph viewer reproduces it, so it was a latent bug that only a real browser page load exposes.

Interim mitigation (deployed 2026-09-30): `memory = 768` stays as the scheduler reservation and `memory_max = 2048` is the hard limit (the node has 15 of 16 GiB reserved, so a plain 2048 cannot be placed; oversubscription is on). It is not enough on its own: two concurrent previews need about 2.1 GB.

## Decision

### 1. Stop reading whole archives
Use random access on the outer zip, and open nested archives without materialising them, through an **indexed inflate adapter**: the inner `.hwics` is DEFLATED with its central directory at the end of the stream, so an in-memory checkpoint index (about 3.3 MB per archive) lets each member be reached with one decompression pass. A per-process cache keeps the parsed directories and the checkpoint indexes keyed by path, modification time and size, plus a small LRU of decoded member text with a byte budget (design **D3**; **D4** adds chunked reads so `char_offset` paging does not decode from zero).

### 2. Keep every ADR-07 invariant
Read-only access, no extraction to disk, path-traversal and zip-bomb protections, bounded reads, the `archive://` URI scheme, and the `section_filter` / `char_offset` / `max_chars` semantics. The prototypes returned output identical to the current code (SHA-256 of the whole `inspect_archive` result, entry bytes and rendered HTML) on all 25 benchmarked requests, and 56 prototype tests reproduce the ADR-07 security tests and add nested, zip64, corrupt-stream, concurrency, no-disk-write and memory-budget cases.

### 3. Lazy preview
The portal previews only on a tap ([ADR-15](ADR-15-Mobile-First-Search-First-Portal-Shell-and-Its-Product-Decisions.md)); this is the first, one-day, independent change and also gives a stop-gap lock on concurrent previews.

### 4. Memory policy
`memory_max` stays at 2048 MB until the streaming change is proven; after a soak period it is lowered back to 768 MB. Memory budgets become tests: peak anonymous memory while previewing a 330 MB zip must stay under an agreed bound.

### 5. Fix the database race in the same change
Concurrent requests share one SQLite connection and `archive_inspector.py:80-95` swallows the error, so a preview sometimes comes back without its title and content (2 of 10 concurrent runs). Each request gets its own connection and failures are reported.

## Alternatives considered (portal startup preview, median, 5 fresh processes each)

| Design | Latency | Peak above baseline | Verdict |
| :--- | :--- | :--- | :--- |
| D0 current: read everything | 1.81 s | 1,006 MB | out-of-memory with three previews |
| D1 `ZipFile` on the file object | 1.39 s | 361 MB | nested archives still read whole |
| D2 stdlib seekable member | 5.08 s | 66 MB | memory fixed, 3 to 4 times slower |
| D2i indexed inflate adapter | 1.06 s | 28 MB | fast, no cache |
| **D3** D2i plus cache | **1.05 s** | **28 MB** | **chosen**: repeats and section jumps take about 1 ms |
| D4 D3 plus chunked paging | 1.09 s | 28 MB | adds `char_offset` pages in 6 ms each |

Three concurrent previews: D0 is killed 5 of 5 times even at 2 GB; D3 finishes in 3.5 s using 72 MB. Paging four `char_offset` pages: 1.55 s each today, 6 ms each with D3. Ingest is not affected (it skips `.hwics` members and peaks at 82 MB).

## Implementation (2026-10-07, phase 1)
The streaming core is in `core/containers/archive_io.py` (`PreadFile`, `IndexedInflateFile`, `InflateIndex`, `member_data_start`), `core/containers/archive_cache.py` (`ArchiveCache`, shared by every streamer instance) and `archive_streamer.py` (`_stream_zipfile`, `_open_nested`, `_dispatch_archive`). `archive_inspector.py` reads the database through its own short read-only connection per request (an in-memory router database uses the shared connection under a lock) and logs a failed lookup instead of swallowing it. Measured on the real 330 MB package: cold preview **1.29 s at +26 MB resident (was about 1,006 MB)**, a repeat **0.2 ms**, another member of the same package 1 ms, three concurrent previews 0.17 s, checkpoint index 3.1 MB.

Differences from the prototype, found while porting: an archive evicted or replaced while a request is still reading it is closed only when the last reader leaves (reference counting); a cached entry's key includes the streamer's limits and the exact path spelling, so a stricter streamer is never served an entry read under looser limits; an empty inflate block no longer ends a read early; cached entries are copies. Tuning: `AEGIS_ARCHIVE_CACHE=0` disables the cache, `AEGIS_ARCHIVE_CACHE_ARCHIVES` (8) and `AEGIS_ARCHIVE_ENTRY_CACHE_MB` (64) bound it. Tests: `tests/test_archive_streaming_memory.py` (36: equivalence with a frozen copy of the old streamer in `tests/_legacy_streamer.py`, ADR-07 security cases, cache invalidation and budget, zero disk writes, a 12 MB heap budget, and a real-corpus budget of 64 MB and 1.5 s cold) and `tests/test_archive_inspector_db_race.py`.

Still open: the diagram path (phase 2) reads the whole inner package, so `POST /archive/inspect` with `extract_diagram_to_artifact` (or an image entry) keeps a one-at-a-time lock in `core/server/handler.py`; the listing budget and the secondary readers (`hdx_parser`, `openxml_parser`) are phases 3 and 4; `memory_max` goes back to 768 MB only after a soak.

## Consequences
- The page-load crash is fixed twice over: the preview no longer fires on load, and when it does it needs tens of megabytes, not a gigabyte.
- A module-level cache adds state to the server; it is bounded (about 3.3 MB per archive plus the LRU budget) and invalidated by modification time and size.
- The diagram path still reads a 353 MB inner archive and writes PNGs to disk; that is phase 2 and an exception to the no-disk rule to be removed.
- About 6 to 7 engineer-days in four phases (stop-gap, streaming core with the race fix, diagram path, listing budget and secondary readers); the out-of-memory fix itself is about 3.5 days.
