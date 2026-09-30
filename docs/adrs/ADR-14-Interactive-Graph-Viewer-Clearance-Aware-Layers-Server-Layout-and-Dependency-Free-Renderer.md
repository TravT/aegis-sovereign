---
title: "ADR-14: Interactive Graph Viewer, Clearance-Aware Layers, Server-Side Layout & a Dependency-Free Renderer"
type: "adr"
category: "architecture"
status: "accepted"
date: "2026-09-30"
last_reviewed: "2026-09-30"
node: "homelab"
domain: "product-ux"
tags:
  - aegis/adrs
  - architecture/decisions
  - product/appliance
  - ux/graph
  - security/clearance
  - tiering/footprint
aliases:
  - "ADR-14"
  - "Graph Viewer"
  - "Interactive Graph"
---

# ADR-14: Interactive Graph Viewer, Clearance-Aware Layers, Server-Side Layout & a Dependency-Free Renderer

## Status
Accepted. Implemented on branch `feat/graph-viewer` (`core/graphview`, `web/portal/js/graph_*.js`). Builds on [ADR-12](ADR-12-Pluggable-Structure-Extraction-Tier-Size-Policy-and-Search-Time-Deduplication.md) (the topic tree it draws) and [ADR-13](ADR-13-File-Type-Handlers-Conformance-Gate-and-Tiered-Fidelity-Ingestion.md). Operator guide: [Manual 19](../manuals/19_interactive_graph_viewer_api_layers_clearance_and_rendering.md).

## Date
2026-09-30

## Context

The portal graph was a static SVG of concentric rings that **sampled** a few dozen nodes. The vault holds 45,425 tree nodes (manual chapters, 12 levels deep), 3,622 alarm / MML / KPI / feature entities with 5,739 relations, and 124 wiki notes with 686 links. The owner wants an Obsidian-style explorer: all nodes reachable, 3D and 2D with zoom, pan and orbit, real relationships, the wiki as a second corpus, **air-gapped** (no CDN), clearance respected, and usable on an office laptop (Tier 1).

Facts that shaped the design (measured on the live vault):

- The tree and the entity graph are **two separate worlds** with no join key (37 name matches); only alarm ids in manual titles link them (853 of 995 canonical `ALM-<n>` have a topic).
- Most entities have **no document link** (1,442 of 1,865 alarms), the entity graph also holds personal Paperless data (amounts, CNPJ/CPF, dates) and noise relations (ADR to alarm), so corpus cannot be the filter.
- Tree nodes have **no clearance** of their own; entities and relations do (most alarms, MML commands and KPIs are level 1).
- With no GPU (software rendering, the worst case) a full 45k-node frame costs 194 ms in 2D and 277 ms in 3D, 80% of it the edges; the default clustered view (2,057 nodes) costs 23 / 17 ms.

## Decision

### 1. One deep module, three calls: `GraphService.meta / slice / find`
`core/graphview` hides layers, clearance, level of detail, layout and caching behind three calls, exposed as `/graph/v2/meta`, `/slice`, `/find` (compact JSON, gzip, ETag / 304). Results use a columnar wire format (arrays per attribute, edges as index pairs): the full tree is 7.7 MB raw and 1.3 MB gzipped.

### 2. Three layers, cross-links only on deterministic keys
`tree` (the manual trees, one synthetic root per package), `entity` (alarms, MML commands, KPIs, features, releases) and `wiki` (notes and their links). An alarm entity lists the manual topics whose title starts with its id (`see_also`); MML commands have no such key and are left to Task 14.3. The edge kinds `CAUSED_BY` and `NEXT_STEP` (ALM to MML to MML chains) are **reserved in the contract** (`meta.reserved_edge_kinds`) and arrive with Task 14.3; alarm to MML edges already exist in the entity graph.

### 3. Clearance: dropped, never redacted, derived for tree nodes
A node above the caller's level is not sent, nor are its edges or its counts (a redacted placeholder would leak the shape of restricted structure). A tree node's level is the minimum over its records; a record-less container takes the minimum of its **primary** children (a second-parent link is a cross-reference, not containment); a structure-only leaf inherits its parent's level; a root with nothing at all fails closed. A **hidden parent hides its whole subtree**, and a hidden node is indistinguishable from a missing one (404). The level is a request parameter (`user_clearance`, default `restricted`, exactly like every other endpoint): the server has no login, so this is a filter, not authentication; the trust boundary is the tailnet.

### 4. Allow-lists, not deny-lists
`core/graphview/policy.py` names the entity types and relation kinds that may appear; anything else, including any type added later, stays out. Tests fail if a personal type ever shows.

### 5. The tree layout is computed on the server
A deterministic radial layout (2D and 3D), per clearance level so hidden nodes cannot move visible ones, lazily on first slice. Shallow leaves get a tiny angular slice, so each ring is spread by pool-adjacent-violators with the seam at the ring's largest gap, blending toward even spacing when a run would wrap; sphere radii keep the lattice spacing at or above the node spacing. On the real vault every one of the 45,425 nodes has a distinct position (closest pair 2.9 units in 2D, 1.7 in 3D). The default view is **clustered** (packages plus two levels, 2,057 nodes); double-click expands one level, "show all" loads everything.

### 6. A dependency-free WebGL renderer instead of a vendored graph library
The plan was to vendor `3d-force-graph` and `force-graph`. On inspection: `3d-force-graph` draws one mesh per node (unusable at 45k), current `three` ships only unminified builds (two files of about 1.3 MB), and `d3-force-3d` needs five more packages. Since the server already lays the tree out, the browser only needs points, lines and a camera, so `graph_gl.js` (WebGL2, about 400 lines) draws nodes as points and edges as lines sharing the node buffers, with an orthographic camera in 2D and an orbit camera in 3D, and `graph_force.js` lays out the small layers (Fruchterman-Reingold with far cells approximated by their centre of mass). **No third-party code is loaded or vendored**, which fits the air-gap and Tier 1 goals and removes a supply-chain item. A test fails if any portal file references an external origin.

### 7. Colour policy from the data-viz method
A node graph is scatter-like: any two categories can touch, so the all-pairs gate applies. Searching the eight-hue dark palette on the portal surface, at most **three** hues pass cleanly (four only for two specific sets and only with secondary encoding; five or more never). The viewer therefore colours at most three categories (USC / UPCF / REL; the top three console families; alarm / MML / KPI; decision / documentation / chapter) and folds the rest into a neutral "other"; legend chips **isolate** a category. Depth uses a one-hue sequential ramp. Direct labels on the largest nodes, tooltips and the inspector's text lists are the secondary encoding.

### 8. Slow devices degrade gracefully
While the user drags or zooms and frames measurably run slower than 45 ms, a dense edge set (over 8,000) is hidden and redrawn when the input stops.

## Consequences

- One request opens the explorer (about 160 ms for the clustered tree); "show all" costs 1.3 MB on the wire and about 1.6 s including layout the first time.
- Adding a layer or an edge kind is a change in one place (`policy.py` and the layer module); the interface stays three calls.
- Clearance is enforced per request but is not authentication. If the appliance ever gets logins, the parameter becomes derived from the session and nothing else changes.
- The renderer is ours to maintain (about 900 lines of JavaScript in total); in exchange there is nothing to update, audit or pin.
- Colour carries at most three categories; the fourth and later are reachable through the legend filter, labels and the inspector.

## Measurements (live vault, 2026-09-30)

| What | Value |
| :--- | :--- |
| Tree, all nodes | 45,425 nodes, 45,473 edges; 7.7 MB raw, 1.3 MB gzipped; first build 2.2 s, cached 0.2 s |
| Tree, default view | 2,057 nodes, 2,059 edges; 23 ms (2D) / 17 ms (3D) per frame in software GL |
| Tree, all nodes, software GL | 194 ms (2D) / 277 ms (3D) per frame; points alone 30 ms, edges 180 to 230 ms |
| Entity layer | 3,622 nodes, 5,739 edges, 73 KB gzipped (public sees 668 / 661) |
| Wiki layer | 124 notes, 686 links (192 `GOVERNED_BY`, 494 `LINKS_TO`), 7 KB gzipped |
| Layout quality | 45,425 distinct positions in 2D and 3D; closest pair 2.9 (2D) and 1.7 (3D) |

## Known limits and next steps

- Frame rates were measured with software rendering only (no GPU on the Dell, and the S20 FE needs its PIN); on any GPU the full view is expected to be far faster. Measure on the real laptop tier when one is available.
- No keyboard navigation of the canvas yet; the search box, the inspector lists and the legend are the accessible route.
- `CAUSED_BY` and MML chains (Task 14.3); the old `/graph/topology` route and `topology.js` stay until the new viewer is verified in production, then are removed.
