---
title: "ADR-08: Zero-Friction Onboarding, Ambient Connectors & Data Portability"
type: adr
category: decision
status: accepted
date: 2026-09-22
last_reviewed: 2026-09-22
node: homelab
domain: product-ux
tags:
  - homelab/adrs
  - architecture/decisions
  - product/onboarding
  - connectors/outlook
  - portability/capsule
  - product/appliance
  - ux/frictionless
aliases:
  - ADR-08
  - Zero-Friction Onboarding
  - Ambient Connectors
  - Sovereign Capsule Portability
---

# ADR-08: Zero-Friction Onboarding, Ambient Connectors & Data Portability

## Status
Accepted

## Context & Motivation

Enterprise software adoption fails most frequently not during procurement, but during the first 60 seconds of user interaction. An agent that demands connection strings, database parameters, or manual file selection before providing any value will be abandoned in favor of familiar (though inferior) tools.

Three specific friction points block enterprise adoption of local workstation RAG:

1. **Discovery Paralysis**: Users cannot enumerate which of their local files and applications are indexable without prior technical knowledge.
2. **Outlook Lock Wall**: Windows places an exclusive `ERROR_SHARING_VIOLATION (0x20)` file lock on active `.ost` mailbox files, causing standard file-reading libraries to fail silently.
3. **Machine Transfer Penalty**: Re-indexing all files on a new workstation requires hours of CPU compute and is a major adoption barrier when upgrading hardware.

## Decision

### 1. 60-Second Auto-Discovery Radar

Upon first binary execution, the engine performs a non-blocking inspection of standard OS application configurations in **under 15 ms** to automatically discover indexable vaults — without prompting for paths or credentials:

**Auto-Discovery Targets:**
- Outlook 365 profile detection via Windows Registry `HKCU\Software\Microsoft\Office\...\Profiles`
- OneDrive Business sync root (`C:\Users\<user>\OneDrive - <tenant>\`)
- Obsidian vault paths from `%APPDATA%\obsidian\obsidian.json`
- Local Documents, Desktop, and Downloads directories

**First-Run Welcome UI Flow:**
```
We discovered these local vaults. Select which to awaken:

[✔] Corporate Outlook Mailbox          ~8,400 messages
[✔] OneDrive Business Sync             ~1,240 documents
[✔] Obsidian / Markdown Notes          ~420 notes

                [ ⚡ AWAKEN VAULT (3 min) ]
```

### 2. Outlook MAPI COM Lock Breaker

**The Problem**: Active Outlook holds exclusive locks on `.ost` files. Direct file reads fail with `ERROR_SHARING_VIOLATION / 0x20`.

**The Solution**: Connect via **unprivileged Windows COM automation** (`Outlook.Application`) running inside a background Single-Threaded Apartment (STA) thread. The engine reads mail items directly from MAPI memory — bypassing the locked `.ost` file on disk entirely — without requiring administrative privileges.

**VIP Noise Reduction Filter**: Emails with `> 30 CC recipients` and zero user replies are indexed exclusively into the lexical FTS5 store, saving 60% of CPU cycles and vector memory on mass-distribution corporate mailing lists.

### 3. Atomic Portability Capsule (`.sovereign-capsule`)

The `.sovereign-capsule` format provides a single-file encrypted portable export of the entire indexed knowledge vault:

| Component | Implementation |
| :--- | :--- |
| **Encryption** | AES-256-GCM using user passphrase (PBKDF2-HMAC-SHA256, 310,000 iterations) |
| **Contents** | `manifest.json` + Qdrant binary snapshot + SQLite WAL database |
| **Compression** | Zstandard level 19 (dictionary-assisted) |
| **Restoration** | Full vector graph restoration on a clean PC in **< 4 seconds** without re-indexing |

### 4. Habit-Forming Enterprise Features

| Feature | Implementation |
| :--- | :--- |
| **1-Click Meeting Briefing Card** | Generates contextual dossiers for upcoming calendar events directly inside the Spotlight HUD, pulling relevant emails, tickets, and documents |
| **Ghost Vault Auto-Pruning** | Automatically pages dormant vector caches out of RAM when monitored project directories remain untouched for 90 days |
| **Fleet Enterprise Lead Hook** | Subtle `[ Request Fleet / Managed Edge Trial ]` button in HUD settings routes to a fleet-size qualification form |

## Consequences

**Positive:**
- Zero-friction onboarding drives immediate first-run value (sub-5-minute time-to-search)
- COM/MAPI Outlook bridge covers a business-critical data silo that is completely inaccessible to naive file indexers
- Capsule portability eliminates machine-transfer re-indexing overhead — a major enterprise adoption accelerator
- Ghost vault pruning keeps RAM consumption flat over long-running deployments

**Negative:**
- COM/MAPI STA thread requires Windows OS; Linux/macOS Outlook access requires alternative connectors (EWS or Graph API)
- Capsule import/export adds implementation complexity for key-derivation and format versioning

## Supersedes / Complements
- Complements [ADR-37: Zero-Copy Workstation Indexing](ADR-37-Zero-Copy-Workstation-Indexing-and-Serverless-Desktop-Engine.md)
- Complements [ADR-40: Two-Pronged Hybrid Retrieval](ADR-40-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md)
- Complements [ADR-44: Zero-Knowledge Telemetry & Privacy Architecture](ADR-44-Zero-Knowledge-Telemetry-Zstandard-Compression-and-Privacy-Architecture.md)

## Related
- [Manual 08: Desktop Workstation & Corporate DLP](../appliance/08_desktop_workstation_and_corporate_dlp.md)
- [Chapter 23: Sovereign Knowledge Appliance & Commercial Stack Architecture](../23_sovereign_knowledge_appliance_and_commercial_stack.md)
