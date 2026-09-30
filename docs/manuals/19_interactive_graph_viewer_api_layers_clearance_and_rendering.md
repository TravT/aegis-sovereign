---
title: "Manual 19: The Interactive Graph Viewer, API, Layers, Clearance & Rendering"
category: operations
type: documentation
node: homelab
domain: ai-data
tags:
  - homelab/appliance
  - product/appliance
  - ux/graph
  - security/clearance
  - operations/runbook
status: active
last_reviewed: 2026-09-30
aliases:
  - Manual 19 Graph Viewer
  - Graph API
  - Graph Explorer
---

# Manual 19: The Interactive Graph Viewer, API, Layers, Clearance & Rendering

Rationale and measurements: [ADR-14](../adrs/ADR-14-Interactive-Graph-Viewer-Clearance-Aware-Layers-Server-Layout-and-Dependency-Free-Renderer.md). The tree it draws: [Manual 16](16_structure_extraction_tier_profiles_and_adding_a_format.md). Operating quirks and the safe-change recipe: [Manual 18](18_project_memory_operating_quirks_and_session_handoff.md). This manual is the user, operator and developer how-to.

## 1. What you see

The portal's graph tab is an explorer with three layers:

| Layer | Nodes | Edges | Colour by |
| :--- | :--- | :--- | :--- |
| **Manual trees** | every chapter and page of the indexed manuals (about 45k), one root per package | `CHILD_OF`, `SECOND_PARENT` (23 topics have two parents) | package (USC / UPCF / REL), console family, or depth |
| **Alarms · MML · KPIs** | alarms, MML commands, KPIs, features, releases (3.6k) | `DIAGNOSED_BY_MML`, `REMEDIATED_BY_MML`, `CONFIGURED_BY_MML`, `MEASURED_BY_COUNTER`, `CANONICAL_ALARM_SPEC`, `DEFINES_ALARM`, `IMPLEMENTS_FEATURE` | entity type |
| **Homelab wiki** | every note of `docs/wiki` (about 124) | `LINKS_TO`, `GOVERNED_BY` (a link from a note to an ADR) | note type, or domain |

Reserved and not yet extracted: `CAUSED_BY` (alarm to alarm) and `NEXT_STEP` (MML to MML in a runbook), Task 14.3.

## 2. Using it

- **Open**: the tree starts *clustered* (package roots plus two levels, about 2,000 nodes). Double-click a node whose inspector offers "Expand" to load one more level; tick **show all nodes** to load everything (about 1.3 MB on the wire).
- **Move**: 2D pans with a drag and zooms with the wheel (about the cursor); 3D orbits with a drag, pans with Shift-drag or a right drag, zooms with the wheel; touch uses one finger and pinch.
- **Find**: the search box calls `/graph/v2/find`; picking a result loads the ancestors along its path and selects the node. An alarm's inspector lists the manual topics that describe it; clicking one jumps to the tree.
- **Filter**: legend chips isolate a category (click again to restore, Shift-click adds or removes one). The "clearance" selector re-requests the graph at that level.
- **Inspect**: selecting a node highlights its neighbours and edges and lists its connections by kind; "Run Prong 1/2 search on node" hands its name to the search tab.

## 3. The API

All routes are `GET`, return JSON, and take `user_clearance` (`public | internal | confidential | restricted`, default `restricted`, like every other endpoint).

| Route | Parameters | Returns |
| :--- | :--- | :--- |
| `/graph/v2/meta` | | layers with node and edge counts *at that clearance*, edge kinds present, theme legend, `reserved_edge_kinds`, `content_version` |
| `/graph/v2/slice` | `layer` (`tree`, `entity`, `wiki`), `mode` (`clustered` default or `all`, tree only), `focus` (a node id), `levels` (default 2) | columnar `nodes` (`id label kind group depth theme n_desc expandable`, tree positions `x y x3 y3 z3`, flat `degree`, entity `see_also`) and `edges` (`s`, `t` index arrays and `k` kinds) |
| `/graph/v2/find` | `q` (text) or `id` (one node), `layer`, `limit` (at most 200) | matches with `id label layer kind path` (ancestors from the package root) |

Node ids are `pkg:<package>`, `t:<topic_id>`, `e:<entity_type>:<name>` and `w:<relative path>`. Errors: 400 for a bad layer, mode, clearance or number, 404 for an unknown or hidden `focus` (a hidden node looks exactly like a missing one), 503 without on-disk databases. Responses are compact JSON, gzipped when the client sends `Accept-Encoding: gzip`, with a weak `ETag` equal to the vault content version (`If-None-Match` gets a 304).

## 4. Clearance rules

1. A node above the caller's level is **never sent**, nor are its edges, nor is it counted (`n_desc`, `meta`).
2. A tree node's level is the minimum over its records; a container without records takes the minimum of its **primary** children; a structure-only leaf inherits its parent's; a root with no information fails closed (restricted).
3. A hidden parent hides its whole subtree (no orphans).
4. Entities and relations use their own `clearance_level`; wiki notes use a `clearance_level` (or `clearance`) key in the frontmatter and default to public, an unreadable value fails closed.
5. This is a request filter, not authentication: the server has no login, the tailnet is the boundary.

## 5. What may appear (allow-lists)

`core/graphview/policy.py` holds `ENTITY_TYPES` and `ENTITY_RELATIONS`. To show a new entity type or relation kind, add it there and add a case to `tests/graph_fixtures.py`. Personal Paperless data (`monetary`, `cnpj`, `cpf`, `date`, `document`), diagram plates and noise relations (for example `AFFECTS_NE` from an ADR to an alarm) are excluded on purpose; `test_entity_layer_never_contains_personal_or_unlisted_entities_at_any_clearance` and the real-vault smoke test guard it.

## 6. Layout and performance

- **Tree**: positions are computed on the server (radial, deterministic, per clearance level) on the first slice after a vault change, about 2 s, then cached in memory keyed by the content version (size and mtime of both databases and their WAL, and the wiki notes). `meta` and `find` never trigger it.
- **Entity and wiki**: laid out in the browser (`graph_force.js`), a few seconds for 3.6k nodes on a GPU machine.
- **Rendering**: `graph_gl.js` uses WebGL2 points and lines. Without a GPU (software rendering) the clustered view runs at about 45 to 55 fps and "show all" at about 4 to 5 fps; while you drag or zoom and frames run slower than 45 ms, edges over 8,000 are hidden and redrawn on release.
- **Budgets** (checked by `tests/test_graph_real_vault.py`): first build under 15 s, the "show all" payload under 3 MB gzipped, the default view under 5,000 nodes.

## 7. Colour

At most three categories get a colour (the first three palette slots, the only ones that pass the all-pairs colour-blind gate on the portal's dark surface); everything else is neutral grey "other". The fixed assignments are in `KNOWN` at the top of `graph_view.js`; unknown categories take the free slots by count. Do not add a fourth hue without re-running the palette validator with `pairs: "all"`.

## 8. Tests and how to run them

```bash
cd dev/aegis-sovereign-appliance
/home/tlima/Enterprise_Hub/.venv/bin/python -m pytest tests/test_graph_service.py tests/test_graph_routes.py \
  tests/test_graph_real_vault.py tests/test_graph_portal_assets.py -q
```

Three seams: the `GraphService` interface (hand-drawn fixture vault, expected values derived by hand), the HTTP routes, and the real vault (independent SQL counts). `tests/test_graph_viewer_browser.py` drives the real portal in Chromium and **skips itself** when Playwright or Chromium is missing. The Dell has no browser: install Playwright and Chromium into a scratch directory (`pip install --target DIR playwright`, then `PYTHONPATH=DIR PLAYWRIGHT_BROWSERS_PATH=DIR/browsers python -m playwright install chromium`) and run pytest with those two variables set. Headless Chromium here renders with SwiftShader, so its frame times are a worst case.

## 9. Troubleshooting

| Symptom | Cause and fix |
| :--- | :--- |
| Graph tab says it needs WebGL2 | the browser or its GPU driver has no WebGL2; use a current Chrome, Edge or Firefox |
| Counts look stale after re-indexing | the content version changes with the vault files; hit "Fit" or reload, and check that the watcher finished writing |
| A node you expect is missing | it is above the selected clearance, or its parent is (a hidden parent hides the subtree); raise the level to check |
| 404 on `focus` | the node is hidden or was never there; the two are deliberately identical |
| First "show all" takes several seconds | the server is building the layout for that clearance; later requests are cached |
| Entity layer empty | the entity graph database is missing or empty; `/graph/v2/meta` shows the counts |

## 10. Extending

New edge kinds (Task 14.3) are added to the layer that owns them and to `RESERVED_EDGE_KINDS` until populated; a new layer is a module that returns a `FlatView` (or a tree view), registered in `GraphService`, plus its label in `LAYER_LABELS`. Keep the interface at three calls.
