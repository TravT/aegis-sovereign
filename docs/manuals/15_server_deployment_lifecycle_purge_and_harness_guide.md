---
title: "Manual 15: Unified Server Vault Topology, Data Purge Lifecycle & Multi-Harness Integration Guide"
category: operations
type: documentation
node: homelab
domain: ai-data
tags:
  - homelab/appliance
  - product/appliance
  - ai/rag
  - ai/mcp
  - operations/lifecycle
status: active
last_reviewed: 2026-09-25
aliases:
  - Manual 15 Server Deployment and Purge Guide
  - Sovereign Vault Purge and Harness Guide
  - Unified Server Knowledge Vault
---

# 🏛️ Manual 15: Unified Server Vault Topology, Data Purge Lifecycle & Multi-Harness Integration Guide

> **Canonical Vault Location**: `/home/tlima/Enterprise_Hub/docs/.aegis_vault/`  
> **Unified Databases**: `sovereign_router.db` (49,000+ records) & `sovereign_graph.db` (9,100+ entities / 20,250+ relations)  
> **Companion Manuals**: [01. Deployment Guide](01_deployment_guide.md) | [04. MCP Harness Configuration](04_mcp_harness_and_agent_configuration.md) | [13. Deep .HDX Ingestion](13_hdx_telecom_and_deep_container_ingestion.md)

---

## 1. Single-Vault Server Storage Topology (Zero Split-Brain Architecture)

To eliminate scattered `.db` files across application folders (`data/rag/graph_store.db`, `dev/aegis-sovereign-appliance/data/`), **Aegis-Sovereign (`AS`)** consolidates 100% of server knowledge into a single, air-gapped production vault directory at `/home/tlima/Enterprise_Hub/docs/.aegis_vault/`:

| File / Directory | Role & Contents | Record Scale |
| :--- | :--- | :--- |
| **`sovereign_router.db`** | Canonical SQLite B-Tree (`document_records`) + external-content `FTS5` (`document_fts`) index for deterministic Prong 1 (`<1ms`) and lexical BM25 retrieval across **all** server domains. | **49,001 records** |
| **`sovereign_graph.db`** | Canonical SQLite WAL Relational Knowledge Graph (`documents`, `entities`, `document_entities`, `entity_relations`) powering 1-to-3 hop GraphRAG dossiers. | **1,265 docs / 9,117 entities / 20,297 edges** |
| **`monitored_sources.json`** | Live manifest tracking every monitored server directory (`docs/Hua_Docs`, `docs/wiki`, `.agents/skills`, `docs/manuals`, `docs/commercial`), record counts, and status. | **5 Server Domains** |
| **`extracted_diagrams/`** | Extracted high-resolution `.png` hardware topology diagrams from vendor `.hdx` packages (`E9000`, `S5720`, `USC`). | **17 Diagrams** |
| **`.aegis-no-index`** | Anti-loop sentinel file preventing recursive filesystem watchers (`rag_watcher.py`) from re-indexing database binary artifacts. | **Active Guard** |

### Unified Symlink Topology (100% Backward Compatibility)
- `data/rag/graph_store.db` $\to$ `/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_graph.db`
- `dev/aegis-sovereign-appliance/data/sovereign_router.db` $\to$ `/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db`
- `dev/aegis-sovereign-appliance/data/sovereign_graph.db` $\to$ `/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_graph.db`
- Legacy `sovereign_huawei_router.db` & `sovereign_huawei_graph.db` symlinks resolve transparently to `sovereign_router.db` and `sovereign_graph.db`.

---

## 2. How to Deploy, Operate & Maintain the Appliance

### 2.1 Turn-Key Deployment (`./install.sh`)
```bash
cd /home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance
./install.sh
```
The installer verifies Python dependencies, checks the unified `sovereign_router.db` and `sovereign_graph.db` integrity inside `docs/.aegis_vault/`, generates MCP harness manifests, and starts the local Web Management Portal (`http://127.0.0.1:8765`).

### 2.2 Starting the Local Server & Web Management Console
```bash
python3 -m core.server --host 0.0.0.0 --port 8765
```
Open `http://127.0.0.1:8765/` in any browser to access the **Aegis Sovereign Executive & NOC Portal** (Dark/Light HUD, Corpus Directory Manager, 1-Click Purge, Search Tester, and License Inspector).

### 2.3 WAL Checkpointing & Encrypted `.sovereign-capsule` Backups
Before taking cold backups or exporting the vault to another workstation, flush SQLite Write-Ahead Logs (WAL):
```bash
python3 -m tools.vault_lifecycle --status
```

---

## 3. How to Ingest New Data & Manage Monitored Directories

You can ingest new server directories or vendor archives through **3 zero-downtime interfaces**:

### Method A: CLI Lifecycle Tool (`tools/vault_lifecycle.py`)
```bash
cd /home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance

# Ingest a new folder into the unified server vault with a domain tag:
python3 -m tools.vault_lifecycle --ingest /path/to/new_docs --domain legal_contracts

# Re-consolidate all server directories (Wiki, ADRs, Agent Skills, Manuals, Commercial, Huawei):
python3 -m tools.vault_lifecycle --consolidate-all
```

### Method B: Web Management Portal (`http://127.0.0.1:8765/`)
1. Navigate to the **Monitored Server Directories & Corpus Manager** panel.
2. Enter the absolute server directory path (e.g., `/home/tlima/Enterprise_Hub/docs/wiki`) and domain tag.
3. Click **[+ Add & Index Directory]** (calls `POST /sources/add`).

### Method C: MCP Tool (`sovereign_scan_onboarding_radar` & `sovereign_inspect_archive`)
Agents can discover unindexed archives via `sovereign_scan_onboarding_radar(target_path="/path/to/folder")` and deep-stream `.zip` / `.hdx` packages via `sovereign_inspect_archive(archive_path="...", ingest=True)`.

---

## 4. How to REMOVE / PURGE Data from the Database

When a directory, project, or temporary corpus should be **completely removed** from the unified database (`sovereign_router.db` + `FTS5` inverted index + `sovereign_graph.db` documents, edges, and orphaned entities), Aegis-Sovereign provides a deterministic cascading purge engine:

### What Happens During a Prefix Purge?
1. **Router B-Tree & FTS5 Cascade (`purge_records_by_prefix`)**: Deletes all rows in `document_records` where `doc_identifier` or `metadata` matches the target path/prefix. The SQLite `AFTER DELETE` trigger (`document_records_ad`) automatically purges every token from the `document_fts` virtual table.
2. **GraphStore Cascade (`purge_documents_by_prefix`)**: Deletes matching documents from `documents`, removes all associated edges in `entity_relations` and `document_entities`, and garbage-collects orphaned nodes in `entities` that have zero remaining edges.
3. **Manifest Sync**: Updates `/home/tlima/Enterprise_Hub/docs/.aegis_vault/monitored_sources.json` and runs `PRAGMA wal_checkpoint(TRUNCATE)`.

### Option 1: CLI Command (`--purge`)
```bash
cd /home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance

# Remove an entire directory or URI prefix from both Router DB (FTS5) and GraphStore:
python3 -m tools.vault_lifecycle --purge "/home/tlima/Enterprise_Hub/docs/commercial"

# Or remove a specific document / corpus prefix:
python3 -m tools.vault_lifecycle --purge "test_temp_corpus://"
```

### Option 2: Web Portal 1-Click `[🗑️ Purge from DB]`
1. Open `http://127.0.0.1:8765/`.
2. Locate the directory row in **Monitored Server Directories**.
3. Click **[🗑️ Purge from DB]** (calls `POST /sources/remove` with `{"path": "..."}`).

### Option 3: MCP Tool (`sovereign_inspect_archive`)
```json
{
  "action": "purge_prefix",
  "prefix": "test_temp_corpus://"
}
```

---

## 5. How to Search Properly (Prong 1 vs. Prong 2 Mastery)

| Query Class | Best Query Syntax | Active Prong | Typical Latency |
| Query Class | Best Query Syntax | Active Prong | In-Engine DB Latency | End-to-End MCP Latency |
| :--- | :--- | :--- | :---: | :---: |
| **Exact Telecom Alarm** | `ALM-20104` or `ALM-3276800192` | **Prong 1 (`deterministic_direct`)** | **`0.03–0.3 ms`** | **`~12–15 ms`** |
| **Exact MML Command** | `DSP OFFLINEUSR` or `ADD NRPCELLDU` | **Prong 1 (`deterministic_direct`)** | **`0.03–0.3 ms`** | **`~12–15 ms`** |
| **Homelab ADR Lookup** | `ADR-40` or `ADR-30` | **Prong 1 (`deterministic_direct`)** | **`0.03–0.3 ms`** | **`~12–15 ms`** |
| **Agent Skill Lookup** | `manage-sovereign-vault` or `manage-traefik` | **Prong 1 (`deterministic_direct`)** | **`0.03–0.3 ms`** | **`~12–15 ms`** |
| **Compound Alarm + Synthesis** | `Why does ALM-20104 occur and how to fix it?` | **Prong 1+2 (`compound_fused`)** | **`1.4–3.5 ms`** | **`~25–45 ms`** |
| **Cross-Doc Graph Dossier** | `sovereign_get_entity_dossier(entity_name="ALM-20104")` | **GraphStore (`1-2 hops`)** | **`0.4–1.2 ms`** | **`~15–18 ms`** |
| **Conceptual / Architecture** | `How does Traefik enforce Tailscale port 443 invariant?` | **Prong 2 (`hybrid_needle`)** | **`1.8–15 ms`** | **`~25–50 ms`** |

> [!NOTE] Latency Measurement Distinctions
> - **In-Engine DB Latency**: Measures pure SQLite B-Tree index lookup (`~0.03 ms`) and in-process Python query route planning (`~0.8 ms`).
> - **End-to-End MCP Latency**: Measures wall-clock time from the AI client's perspective, which includes standard JSON-RPC 2.0 serialization, OS stdio/IPC pipe traversal, and local loopback socket round-trips (`~12–15 ms`).

---

## 6. Complete Integration Guide for the Most Famous AI Harnesses

All AI harnesses connect via standard **MCP over `stdio`** to `core/mcp/server.py`, with environment variables pointing to the unified vault in `docs/.aegis_vault/`.

### 6.1 Google Antigravity (`agy` CLI & IDE)
File: `~/.gemini/antigravity-cli/mcp/sovereign-vault/mcp_config.json` (or global `mcp_config.json`):
```json
{
  "mcpServers": {
    "sovereign-vault": {
      "command": "/home/tlima/Enterprise_Hub/.venv/bin/python3",
      "args": [
        "/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/core/mcp/server.py"
      ],
      "env": {
        "SOVEREIGN_ROUTER_DB": "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db",
        "SOVEREIGN_GRAPH_DB": "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_graph.db",
        "SOVEREIGN_APPLIANCE_URL": "http://127.0.0.1:8765"
      }
    }
  }
}
```

### 6.2 Anthropic Claude Code CLI (`claude`)
Run a single registration command in your terminal:
```bash
claude mcp add sovereign-vault \
  -e SOVEREIGN_ROUTER_DB=/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db \
  -e SOVEREIGN_GRAPH_DB=/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_graph.db \
  -- /home/tlima/Enterprise_Hub/.venv/bin/python3 /home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/core/mcp/server.py
```

### 6.3 Anthropic Claude Desktop (`claude_desktop_config.json`)
File: `~/.config/Claude/claude_desktop_config.json` (Linux) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):
```json
{
  "mcpServers": {
    "sovereign-vault": {
      "command": "/home/tlima/Enterprise_Hub/.venv/bin/python3",
      "args": [
        "/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/core/mcp/server.py"
      ],
      "env": {
        "SOVEREIGN_ROUTER_DB": "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db",
        "SOVEREIGN_GRAPH_DB": "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_graph.db"
      }
    }
  }
}
```

### 6.4 Cursor IDE (`.cursor/mcp.json`)
Create `.cursor/mcp.json` in your workspace root or `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "sovereign-vault": {
      "command": "/home/tlima/Enterprise_Hub/.venv/bin/python3",
      "args": [
        "/home/tlima/Enterprise_Hub/dev/aegis-sovereign-appliance/core/mcp/server.py"
      ],
      "env": {
        "SOVEREIGN_ROUTER_DB": "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_router.db",
        "SOVEREIGN_GRAPH_DB": "/home/tlima/Enterprise_Hub/docs/.aegis_vault/sovereign_graph.db"
      }
    }
  }
}
```

### 6.5 Windsurf / Codeium (`~/.codeium/windsurf/mcp_config.json`)
Add the identical `"sovereign-vault"` entry under `"mcpServers"` in `~/.codeium/windsurf/mcp_config.json`.

### 6.6 VS Code Cline / Roo Code / Continue.dev
In VS Code **Cline** or **Roo Code** MCP Settings (`cline_mcp_settings.json`), add the `"sovereign-vault"` server block above with `disabled: false` and `alwaysAllow: ["sovereign_search_vault", "sovereign_optimize_context", "sovereign_get_entity_dossier", "sovereign_route_and_analyze", "sovereign_inspect_archive", "sovereign_scan_onboarding_radar", "sovereign_node_status"]`.

---

## 7. Attaching & Managing Your Platform License (`Ed25519` `.aegis-license`)

1. **Generate or Inspect License via CLI**:
   ```bash
   python3 -m core.licensing --status
   ```
2. **Attach via Web Portal (`http://127.0.0.1:8765/`)**:
   Paste the signed JSON `.aegis-license` certificate into the **License & Plan Tier** card and click **[Verify & Activate License]** (`POST /license/attach`), which validates the offline `Ed25519` cryptographic signature and persists the active license to `/home/tlima/Enterprise_Hub/docs/.aegis_vault/active_license.json`.
