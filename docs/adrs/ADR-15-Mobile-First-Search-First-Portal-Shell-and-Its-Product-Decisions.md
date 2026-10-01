---
title: "ADR-15: Mobile-First, Search-First Portal Shell and Its Product Decisions"
type: "adr"
category: "architecture"
status: "accepted"
date: "2026-10-01"
last_reviewed: "2026-10-01"
node: "homelab"
domain: "product-ux"
tags:
  - aegis/adrs
  - architecture/decisions
  - product/appliance
  - ux/portal
  - security/clearance
aliases:
  - "ADR-15"
  - "Portal Redesign"
  - "Variant A"
---

# ADR-15: Mobile-First, Search-First Portal Shell and Its Product Decisions

## Status
Accepted as a design on 2026-10-01; implementation not started. Two product questions are still open (see "Still open"). Builds on [ADR-14](ADR-14-Interactive-Graph-Viewer-Clearance-Aware-Layers-Server-Layout-and-Dependency-Free-Renderer.md) (the graph explorer it hosts) and is paired with [ADR-16](ADR-16-Archive-Streaming-Checkpoint-Index-Lazy-Preview-and-Memory-Budget.md) (the memory fix that its first phase enables). Evidence and the build plan: the recommendation (wiki note `projects/aegis/studies/portal-redesign-recommendation.md` in Enterprise_Hub), the audit (wiki note `projects/aegis/studies/portal-redesign-audit.md` in Enterprise_Hub), the design principles (wiki note `projects/aegis/studies/portal-redesign-design.md` in Enterprise_Hub) and the implementation plan (wiki note `projects/aegis/studies/portal-redesign-implementation-plan.md` in Enterprise_Hub).

## Date
2026-10-01

## Context

The owner's complaint was "too many buttons, and far from mobile first". The audit measured it on the live portal at 390x844:

- 50 controls on the landing screen of the search tab; 63 of 87 controls in the whole portal (72%) are smaller than 44 px.
- The title, status pills and four stacked tabs take 653 of 844 px before any content. The search box is 124 px wide and the "Route & Execute" button is clipped off the screen; "Re-Sync" and "Purge" cannot be reached on a phone.
- Five destructive actions have no confirmation: "Purge Data from DB" deletes on the first tap.
- Opening the portal fires a query and then an automatic archive preview of the first result. That preview is what out-of-memory-killed the server on every page load (runbook section 21, [ADR-16](ADR-16-Archive-Streaming-Checkpoint-Index-Lazy-Preview-and-Memory-Budget.md)).

Three structurally different prototypes were built and compared with scripted task flows: **A** a search-first app shell, **B** one command bar with an answer log, **C** the graph always on screen with results in a bottom sheet.

## Decision

### 1. The shell: variant A
Three destinations, **Search, Graph, Settings**. On a phone they are a bottom tab bar; from 768 px wide they become a left rail and Search splits into results on the left and the source on the right. The graph explorer of ADR-14 is the Graph destination. B was rejected because it hides admin and the graph behind `/` commands; C because it would run WebGL on every visit and its draggable sheet is the hardest piece to make accessible.

| | Today | Variant A |
| :--- | :--- | :--- |
| Controls on the landing screen | 50 | 11 |
| Controls under 44 px, whole portal | 63 of 87 | 0 |
| Destructive actions without a confirmation | 5 | 0 |
| Show an entity in the graph (phone) | 3 taps plus about 7.5 screens of scrolling | 1 tap |
| Re-sync a folder (phone) | not possible | 4 taps |

### 2. Product decisions (settled with the owner on 2026-10-01)
1. **Open idle.** The portal opens with only a status call. A search, and the preview of a result, happen only when the user taps. This removes the crash trigger from page load and is phase 1 of the plan, shippable on its own.
2. **Demo tools are hidden.** The plan quick-switch (Activate ENTERPRISE / PRO / Switch to FREE) appears only with `?demo=1`, under Settings, and a downgrade asks for confirmation. It mints licenses with the appliance's own key, so it protects nothing and is kept for demos.
3. **Local LLM switch.** Turning it on asks for confirmation and states the cost (RAM on the host, time to be ready); turning it off is immediate with an undo toast.
4. **Remove from index is allowed on phones**, always behind a confirmation sheet that names the folder and shows how many records will go, with a type-the-folder-name step above 1,000 records. No destructive action sits next to a primary action.
5. **One global Clearance setting** applies to search, preview and graph, is remembered per browser and shown as a chip in the header. The default stays `restricted`; `?demo=1` starts at `public`. Clearance remains a filter the server applies to the level requested, not a login.
6. **Recent searches** are kept in the browser (query text only), on by default, capped at 8, with a Clear action in Settings.
7. **Name.** "Aegis" in the header and the tab title; the full name once, in Settings, About.
8. **Dark theme only for now.** The colour tokens stay theme-ready; a light theme is revisited after phase 4.
9. **The Cmd+K palette is later** (after the shell and the graph screen). **Installing as an app (PWA) is deferred**; if wanted, a manifest and an icon only, with no service worker.
10. **Vocabulary** is fixed in `CONTEXT.md` of the appliance repository: **Plan** (FREE / PRO / ENTERPRISE) and **Deployment profile** (desktop / edge / datacenter) replace the overloaded "tier"; **Source folder**, **Citation** and **Document** separate the three meanings of "source"; the one destructive verb is **Remove from index**.

### 3. Constraints that carry over
Air-gapped (system fonts and inline SVG, no external origin: a test enforces it, so the inline SVG must not carry the `xmlns` URL); vanilla HTML, CSS and JavaScript with no build step; the existing API contracts; every element id that the existing tests assert is kept, and `test_06` of `test_web_portal.py` is updated because it asserts the old tab labels.

## Still open
- **Presets**: keep all 12 examples inside the collapsed "Examples" (their strings are asserted by a test) or cut to 4 to 6.
- **Deep synthesis**: whether to show it while the Local LLM is off (the prototype shows it disabled, with "turn it on in Settings").

## Consequences
- The first release of the new design is one day of work (phase 1: idle open, preview on tap) and fixes the page-load crash independently of the larger rebuild.
- The full rebuild is seven phases, about 13 days (about 15 to 17 with buffer); the plan lists the files, the tests and a real-browser phone-size check that does not exist today.
- Settings becomes the home of anything rare or consequential (Plan, Local LLM, Sources, Clearance, Demo tools), so the Search screen stays at 11 controls.
- A single global clearance means the portal can show at most one level at a time; per-panel levels are not supported.

## Where the prototypes are
Static, mock-data prototypes (A, B, C) are in `docs/design/portal-redesign/prototype/` of the appliance repository (`?variant=A|B|C`); screenshots and capture scripts are kept out of git in `studies/2026-10-01/portal-redesign/`.
