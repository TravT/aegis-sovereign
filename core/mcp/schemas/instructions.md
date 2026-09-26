---
name: manage-sovereign-vault
description: Query, route, inspect archives, discover corpora, and calibrate the air-gapped Aegis Sovereign Knowledge Appliance via the 7-Tool Model Context Protocol (MCP v2) specification.
---

# Manage Sovereign Vault (7-Tool MCP v2 Specification & Context Architecture)

This skill enables AI agents (Cloud Orchestrators, Subagents, Claude Desktop, Cursor, and Antigravity CLI) to interact with the **Aegis Sovereign Knowledge Appliance** ([ADR-35](../../docs/wiki/adrs/ADR-35-Sovereign-Knowledge-Appliance-Packaging-and-Commercial-Architecture.md), [ADR-40](../../docs/wiki/projects/aegis/adrs/ADR-06-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md)) through its native Model Context Protocol (MCP) server `sovereign-vault`.

The appliance operates with **0.00 KB external cloud egress**, executing sub-millisecond SQLite B-Tree/FTS5 lookups (Prong 1), hybrid Dual-Encoder ONNX + BM25 + GraphRAG + RAPTOR retrieval (Prong 2), zero-copy in-memory `.hdx`/`.hwics`/`.zip` streaming (`ADR-07`), and `<60s` workspace discovery (`ADR-08`), cutting cloud prompt tokens by **98.7% (guaranteed ≥ 40%)**.

> **⚡ MANDATORY 1-CALL RESOLUTION PROTOCOL (READ FIRST)**:
> 1. **Do NOT read `.json` schema files in `/home/tlima/.gemini/antigravity-cli/mcp/sovereign-vault/`** — all tool schemas are documented below.
> 2. **Start with a SINGLE call to `sovereign_route_and_analyze`** (`{"query": "<your query>", "limit": 3, "user_clearance": "restricted", "synthesize": true}`). Do **NOT** fire parallel calls to `sovereign_search_vault` or `sovereign_get_entity_dossier` on Turn 1.
> 3. **Why 1 Call Suffices**: `sovereign_route_and_analyze` automatically executes **Smart Section-Aware Compaction** (preserving `Description`, `Thresholds`, `Impact on the System`, `Possible Causes`, and `Procedure` while condensing boilerplate parameter rows) AND automatically attaches the multi-hop `graph_dossier` (`DIAGNOSED_BY_MML`, `REMEDIATED_BY_MML`, `MEASURED_BY_COUNTER`, `HAS_DIAGRAM`).
> 4. **When to Stop**: If `results[0]["content"]` and `results[1]["content"]` already contain the `Possible Causes` and `Procedure` answering the user's question (`confidence_band: "HIGH_VERIFIED"` or `"HIGH_DETERMINISTIC_EXACT"`), **answer the user immediately after that single MCP call**! Only call `sovereign_inspect_archive` (`section_filter`, `extract_diagram_to_artifact`) if you specifically need the condensed middle parameter table or to export a PNG diagram.
> 5. **Strict MCP-Only Governance**: Never run `python3 -c` / `sqlite3` / `zipfile` scripts via `run_command` to inspect the database or archives.

---

## 1. The 7-Tool Agent Routing Decision Matrix

Select the optimal tool from the `sovereign-vault` MCP server using this decision matrix:

| # | MCP Tool Name | Architectural Tier / ADR | Primary Use Case & When to Select | Latency Profile | Cloud Token Impact |
| :- | :--- | :--- | :--- | :--- | :--- |
| **1** | `sovereign_route_and_analyze` | **Two-Pronged Router & Selective Synthesis Gate** (`ADR-06` / `ADR-40`) | **Default Entry Point.** Automatically classifies queries into **Prong 1** (`<1ms` SQLite B-Tree/FTS5 for exact IDs: `ALM-xxxxx`, `DSP OPTMODULE`, `LOTE-xxxx`, `CPF`/`CNPJ`, 44-digit `NF-e` keys, `3GPP TS`, `CID-10`) or **Prong 2** (Hybrid ONNX + BM25 / GraphRAG / RAPTOR), applies the Selective Synthesis Gate, and returns `fast_summary` with explicit `execution_mode` (`neural_ollama_local`, `extractive_template_fallback`, `epistemic_refusal`, `deterministic_direct_fast_path`). | **0.45 ms** (Prong 1)<br>**18–85 ms** (Prong 2) | **100% compute saved** on Prong 1; **98.7% token reduction** on Prong 2 |
| **2** | `sovereign_optimize_context` | **Deep 5-Knob Context Condenser** (`ADR-35` / `Manual 06`) | When an orchestrator needs a customized, citation-grounded evidence block tuned across **5 executive knobs** (`analytical_depth`, `evidence_grounding`, `include_visual_plates`, `user_clearance`, `critical_posture`). | **45–116 ms** | **98.7% token reduction** (38,400 $\rightarrow$ ~310 tokens) |
| **3** | `sovereign_search_vault` | **Direct Prong 2 Dual-Encoder + BM25 RRF** | When an agent requires raw, uncondensed scored chunks (`chunk_id`, `score`, `text`, `metadata`) for custom downstream processing or cross-comparison. | **12–40 ms** | Returns raw Top-$K$ chunks (`limit`: 1–20) |
| **4** | `sovereign_get_entity_dossier` | **SQLite WAL GraphRAG Multi-Hop Traversal** | When auditing an entity or identifier across **1 to 5 relational hops**, returning all connected nodes and directed edges (`ISSUED_NFE`, `CONTAINS_LOTE`, `CAUSED_BY`, `DIAGNOSED_BY_MML`, `REMEDIATED_BY_MML`). | **1.2–8.5 ms** | Compact structured graph JSON (~180 tokens) |
| **5** | `sovereign_inspect_archive` | **Zero-Copy In-Memory Container Streamer** (`ADR-07`) | When inspecting or resolving files inside `.hdx` (Huawei/Telco HedEx), `.zip`, `.tar.zst`, or `.epub` archives purely in RAM (`O_RDONLY`, `io.BytesIO`) with `<100:1` zip-bomb protection and `archive://<path>#<entry>` virtual URIs. | **3–35 ms** | Zero disk I/O; streams only requested entry or `.hdx` summary |
| **6** | `sovereign_scan_onboarding_radar` | **60-Second Auto-Discovery Radar** (`ADR-08`) | When onboarding a new host directory or auditing workspace folders to rank candidate domains (`0–100` priority score) across `fiscal_nfe`, `medical_clinical`, `legal_contracts`, `engineering_manuals`, and `general_knowledge`. | **5–250 ms** (`<60s` strict cap) | Zero file content egress; metadata summary only |
| **7** | `sovereign_node_status` | **Appliance Health & MAC Telemetry** | Real-time diagnostic check before batch operations; returns appliance health, indexed chunk/entity counts, active MAC clearance enforcement, and sub-millisecond readiness. | **< 2 ms** | ~80 tokens |

---

## 2. Complete 7-Tool Reference, Schemas & `call_mcp_tool` Examples

### Tool 1: `sovereign_route_and_analyze` (Primary Entry Point — `ADR-40`)

Automatically inspects query morphology using compiled deterministic regex patterns and semantic intent heuristics:
- **Prong 1 (`deterministic_direct`)**: Matches exact telecom alarms (`ALM-26235`), MML commands (`DSP OPTMODULE`), batch IDs (`LOTE-7788-VAC`), Brazilian tax IDs (`CPF`/`CNPJ`), 44-digit `NF-e` access keys, `3GPP TS` specs, and `CID-10` codes. Executes `<1ms` SQLite B-Tree/FTS5 lookup with Mandatory Access Control (`user_clearance`) pushed down into the SQL `WHERE` clause. Bypasses vector embedding and LLM synthesis (`synthesis_gate_status: "skipped_direct_lookup"`).
- **Prong 2 (`hybrid_needle`, `relational_graph`, `macro_synthesis`, `compound_fused`)**: Executes Dual-Encoder ONNX + BM25 RRF, multi-hop GraphRAG traversal, and RAPTOR hierarchical trees, then invokes `NanoRunner` with a 3-tier resilience chain (`neural_ollama_local` $\rightarrow$ `extractive_template_fallback` $\rightarrow$ `epistemic_refusal`).

**Parameters**:
- `query` (*string, required*): User question, exact identifier, or compound analytical prompt.
- `user_clearance` (*string, optional*): `"public"` | `"internal"` | `"restricted"` (default) | `"confidential"` | `"secret"` | `"top_secret"`.
- `limit` (*integer, optional*): Maximum verified records to return (`1` to `20`, default: `5`).
- `synthesize` (*boolean, optional*): Run local `NanoRunner` synthesis and attach `fast_summary` (default: `true`).

**`call_mcp_tool` Invocation Example**:
```json
{
  "ServerName": "sovereign-vault",
  "ToolName": "sovereign_route_and_analyze",
  "Arguments": {
    "query": "ALM-26235 BBU Optical Module Fault",
    "user_clearance": "restricted",
    "limit": 5,
    "synthesize": true
  }
}
```

**Return JSON Schema**:
```json
{
  "query": "ALM-26235 BBU Optical Module Fault",
  "route_type": "deterministic_direct",
  "identifiers_detected": ["ALM-26235"],
  "user_clearance": "restricted",
  "latency_ms": 0.48,
  "needs_synthesis": false,
  "synthesis_gate_status": "skipped_direct_lookup",
  "execution_mode": "deterministic_direct_fast_path",
  "results": [
    {
      "doc_id": "hdx-gnodeb-v100r019-alm-26235",
      "title": "ALM-26235 BBU Optical Module Fault",
      "source_tier": "sqlite_btree_exact",
      "clearance_level": "internal",
      "score": 1.0,
      "snippet": "ALM-26235: BBU Optical Module Fault (Critical). Cause: RX optical power below -24.0 dBm..."
    }
  ],
  "fast_summary": null
}
```

---

### Tool 2: `sovereign_optimize_context` (Deep 5-Knob Context Condenser)

Compresses raw multi-document archives into a **98.7% token-reduced** verified evidence block governed by **5 Executive Tuning Knobs**:

1. **`analytical_depth`**:
   - `"flash_needle"` (default): Top 3 surgical chunks for immediate factual pinpointing.
   - `"relational_audit"`: Injects multi-hop GraphRAG entity links, invoice chains, and counterparty edges.
   - `"deep_synthesis"`: Includes hierarchical RAPTOR L1/L2 summaries alongside leaf evidence exhibits.
2. **`evidence_grounding`**:
   - `"verbatim_footnotes"` (default): Enforces strict `[Source #]` citations and verbatim textual quotes.
   - `"executive_abstract"`: Produces a high-density executive briefing with provenance footers.
3. **`include_visual_plates`** (*boolean*, default: `false`): Attaches OCR table matrices, engineering schematics, and PDF/NF-e visual plate descriptors.
4. **`user_clearance`**: `"public"` | `"internal"` | `"confidential"` | `"restricted"` (default). Enforces MAC filtering prior to context assembly.
5. **`critical_posture`**:
   - `"neutral"` (default): Objective analytical synthesis.
   - `"compliance_auditor"`: Highlights regulatory gaps, tax anomalies, expired lots, or contractual liabilities.
   - `"scholarly"`: Preserves methodological nuances and standard specifications (`3GPP`, `ISO`, `ABNT`).

**`call_mcp_tool` Invocation Example**:
```json
{
  "ServerName": "sovereign-vault",
  "ToolName": "sovereign_optimize_context",
  "Arguments": {
    "query": "Audit vaccine batch LOTE-7788-VAC cold-chain excursion and NF-e provenance",
    "analytical_depth": "relational_audit",
    "evidence_grounding": "verbatim_footnotes",
    "include_visual_plates": true,
    "user_clearance": "confidential",
    "critical_posture": "compliance_auditor",
    "max_chunks": 5
  }
}
```

**Return JSON Schema**:
```json
{
  "query": "Audit vaccine batch LOTE-7788-VAC cold-chain excursion and NF-e provenance",
  "optimized_context": "[Source 1: NF-e 35260912345678000199550010000098761000098765] BioFarma Ltda supplied LOTE-7788-VAC (R$ 185,400.00)...\n[Graph Dossier] BioFarma Ltda --[ISSUED_NFE]--> NF-e 9876 --[CONTAINS_LOTE]--> LOTE-7788-VAC",
  "token_economics": {
    "raw_corpus_tokens": 38400,
    "optimized_tokens": 312,
    "savings_pct": 99.18
  },
  "knobs_applied": {
    "analytical_depth": "relational_audit",
    "evidence_grounding": "verbatim_footnotes",
    "include_visual_plates": true,
    "user_clearance": "confidential",
    "critical_posture": "compliance_auditor"
  },
  "verified_chunks": []
}
```

---

### Tool 3: `sovereign_search_vault` (Direct Prong 2 Dual-Encoder + Sparse BM25 RRF)

Executes direct Dual-Encoder vector (`FastEmbed ONNX int8`) + Sparse BM25 Reciprocal Rank Fusion (RRF) retrieval when an agent wants raw scored chunks (`chunk_id`, `score`, `text`, `metadata`) without condensation.

**Parameters**:
- `query` (*string, required*): Semantic or lexical search query.
- `corpus` (*string, optional*): `"all"` (default), `"wiki"`, or `"paperless"`.
- `limit` (*integer, optional*): Number of chunks (`1` to `20`, default: `5`).
- `score_threshold` (*number, optional*): Minimum RRF score threshold (default: `0.0`).
- `retrieval_mode` (*string, optional*): `"high_precision"` | `"legal_discovery"` | `"exact_entity"`.

**`call_mcp_tool` Invocation Example**:
```json
{
  "ServerName": "sovereign-vault",
  "ToolName": "sovereign_search_vault",
  "Arguments": {
    "query": "Traefik v3 port 443 socket binding tailscaled conflict",
    "corpus": "wiki",
    "limit": 3,
    "retrieval_mode": "high_precision"
  }
}
```

**Return JSON Schema**:
```json
{
  "query": "Traefik v3 port 443 socket binding tailscaled conflict",
  "results": [
    {
      "chunk_id": "wiki-traefik-nomad-01",
      "score": 0.942,
      "text": "In nomad_jobs/traefik.nomad, [entryPoints.websecure] MUST strictly bind to 192.168.0.48:443...",
      "metadata": {
        "file_path": "docs/wiki/system_overview.md",
        "clearance": "restricted"
      }
    }
  ]
}
```

---

### Tool 4: `sovereign_get_entity_dossier` (SQLite WAL GraphRAG Multi-Hop Traversal)

Traverses the SQLite WAL relational knowledge graph across **`1` to `5` hops**, returning all connected entities and directed edges (`ISSUED_NFE`, `CONTAINS_LOTE`, `CAUSED_BY`, `DIAGNOSED_BY_MML`, `REMEDIATED_BY_MML`) for a specific entity or identifier.

**Parameters**:
- `entity` (*string, required*): Entity name or exact identifier (e.g., `"ALM-26235"`, `"LOTE-7788-VAC"`, `"12.345.678/0001-99"`, `"BioFarma Ltda"`). *(Also accepts alias `entity_name`)*.
- `hops` (*integer, optional*): Multi-hop traversal depth from `1` to `5` (default: `2`).

**`call_mcp_tool` Invocation Example**:
```json
{
  "ServerName": "sovereign-vault",
  "ToolName": "sovereign_get_entity_dossier",
  "Arguments": {
    "entity": "ALM-26235",
    "hops": 3
  }
}
```

**Return JSON Schema**:
```json
{
  "entity": "ALM-26235",
  "hops_traversed": 3,
  "nodes": [
    {"id": "ALM-26235", "type": "telecom_alarm", "label": "BBU Optical Module Fault"},
    {"id": "DSP OPTMODULE", "type": "mml_command", "label": "Query Optical Transceiver Telemetry"},
    {"id": "RST BRD", "type": "mml_command", "label": "Reset Baseband Subboard"}
  ],
  "edges": [
    {"source": "ALM-26235", "target": "DSP OPTMODULE", "relation": "DIAGNOSED_BY_MML"},
    {"source": "ALM-26235", "target": "RST BRD", "relation": "REMEDIATED_BY_MML"},
    {"source": "ALM-26235", "target": "CPRI_LOS_FAULT", "relation": "CAUSED_BY"}
  ]
}
```

---

### Tool 5: `sovereign_inspect_archive` (Zero-Copy In-Memory Container Streamer — `ADR-07`)

Streams `.hdx` (Huawei/Telco HedEx packages), `.zip`, `.tar.zst`, and `.epub` archives purely in memory (`O_RDONLY`, `io.BytesIO`) with **zero temporary disk files** and strict **`<100:1` zip-bomb decompression ratio protection**. Lists `archive://<path>#<entry>` virtual URIs, extracts `.hdx` telecom domain summaries (Alarms, MML commands, KPI counters, RAPTOR tree count), or resolves a single virtual URI directly.

**Parameters**:
- `action` (*string, optional*): `"inspect"` (default), `"relocate_prefix"` (atomically re-points all `archive://` URIs and graph edges from `old_prefix` to `new_prefix` without re-indexing from scratch), `"purge_prefix"` (deletes records/edges under `old_prefix`), or `"corpus_stats"` (returns live SQLite FTS5 & GraphStore entity counts).
- `archive_path` (*string, optional*): Absolute path to `.hdx`, `.hwics`, `.zip`, `.tar.zst`, `.xlsx`, `.docx`, or `.epub` archive (e.g. `/home/tlima/Enterprise_Hub/docs/Hua_Docs/...`).
- `virtual_uri` (*string, optional*): Canonical virtual URI (`archive://<archive_path>#<entry_name>`) to resolve directly in RAM (`zero_disk_extraction: true`).
- `section_filter` (*string, optional*): Jump directly to a specific section heading inside a long HTML/DOCX document (e.g. `"Possible Causes"`, `"Procedure"`, `"Parameters"`) without writing custom Python string slicing!
- `char_offset` (*integer, optional*): Character offset (`0+`) for paginating through very long (`>6,000` char) internal archive entries.
- `max_chars` (*integer, optional*): Maximum characters to return (default: `4000`).
- `old_prefix` / `new_prefix` (*string, optional*): Used with `action="relocate_prefix"` or `"purge_prefix"` (e.g., relocating `/tmp/docs_rag_gemini` to `/home/tlima/Enterprise_Hub/docs/Hua_Docs`).
- `query` (*string, optional*): Filter internal archive entries by keyword, alarm code, or MML command.
- `ingest` (*boolean, optional*): Whether to persist matched entries into the knowledge graph (default: `false`).

> **Strict MCP-Only Governance Invariant**: Agents MUST NEVER write ad-hoc Python scripts (`sqlite3.connect(...)` or `zipfile.ZipFile(...)`) to query the database or slice HTML pages directly. Every query, section jump (`section_filter`), prefix relocation (`relocate_prefix`), and archive inspection MUST execute through the 7 MCP tools (or via `.venv/bin/python3 scripts/sovereign_mcp.py --call <tool_name> '<json>'`).

**`call_mcp_tool` Invocation Examples**:
```json
{
  "ServerName": "sovereign-vault",
  "ToolName": "sovereign_inspect_archive",
  "Arguments": {
    "virtual_uri": "archive:///home/tlima/Enterprise_Hub/docs/Hua_Docs/HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.zip!HUAWEI USC Unified Signaling Controller 26.1.0 Product Documentation (VM) 02.hwics#resources/alarms/20104.html",
    "section_filter": "Possible Causes",
    "max_chars": 1500
  }
}
```

**Return JSON Schema**:
```json
{
  "mode": "stream_archive",
  "archive_path": ".../DBS3900_5G_gNodeB_V100R019C10.hdx",
  "container_format": ".hdx",
  "total_entries": 4,
  "matched_entries_count": 1,
  "zero_disk_extraction": true,
  "hdx_telecom_summary": {
    "package_title": "DBS3900 & DBS5900 5G gNodeB V100R019C10 Product Documentation",
    "alarms_extracted": ["ALM-26235", "ALM-29201"],
    "mml_commands_extracted": ["DSP OPTMODULE", "ACT CELL", "RST BRD"],
    "kpi_counters_extracted": ["N.Cell.Throughput.DL.Avg", "VS.CPRI.BitErrorRate"],
    "raptor_nodes_count": 5
  },
  "entries": [
    {
      "virtual_uri": "archive:///.../DBS3900_5G_gNodeB_V100R019C10.hdx#alarms/alm_26235_optical_fault.xml",
      "entry_name": "alarms/alm_26235_optical_fault.xml",
      "compression_ratio": 2.41,
      "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "content_text": "<Alarm id=\"ALM-26235\" name=\"BBU Optical Module Fault\">..."
    }
  ]
}
```

---

### Tool 6: `sovereign_scan_onboarding_radar` (60-Second Auto-Discovery Radar — `ADR-08`)

Executes a non-intrusive, strictly read-only (`os.scandir`) workspace traversal bounded by a hard `<60s` timeout. Automatically classifies candidate directories across 5 enterprise knowledge domains (`fiscal_nfe`, `medical_clinical`, `legal_contracts`, `engineering_manuals`, `general_knowledge`) and scores each folder from `0` to `100` based on high-value file density (`.hdx`, `.xml`, `.pdf`, `.mbox`, `.docx`).

**Parameters**:
- `root_paths` (*array of strings, required*): List of root directory paths to scan.
- `max_scan_seconds` (*number, optional*): Time budget in seconds (`1.0` to `60.0`, default: `15.0`).

**`call_mcp_tool` Invocation Example**:
```json
{
  "ServerName": "sovereign-vault",
  "ToolName": "sovereign_scan_onboarding_radar",
  "Arguments": {
    "root_paths": ["/home/tlima/Enterprise_Hub/docs/wiki"],
    "max_scan_seconds": 10.0
  }
}
```

**Return JSON Schema**:
```json
{
  "status": "completed",
  "root_paths": ["/home/tlima/Enterprise_Hub/docs/wiki"],
  "max_scan_seconds": 10.0,
  "total_candidates": 4,
  "candidates": [
    {
      "path": "/home/tlima/Enterprise_Hub/docs/wiki/appliance",
      "file_count": 12,
      "total_bytes": 148290,
      "supported_extensions": {".md": 12},
      "domain_category": "engineering_manuals",
      "priority_score": 88.5
    }
  ]
}
```

---

### Tool 7: `sovereign_node_status` (Real-Time Diagnostic & MAC Readiness)

Queries the live health, SQLite WAL / Qdrant index counts, MAC clearance enforcement status, and sub-millisecond readiness of the Sovereign Appliance node.

**Parameters**: `{}` (None).

**`call_mcp_tool` Invocation Example**:
```json
{
  "ServerName": "sovereign-vault",
  "ToolName": "sovereign_node_status",
  "Arguments": {}
}
```

**Return JSON Schema**:
```json
{
  "status": "healthy",
  "appliance_version": "2.0.0",
  "sqlite_wal_ready": true,
  "qdrant_connected": true,
  "mac_enforcement": "strict_pushdown",
  "indexed_chunks": 1420,
  "indexed_entities": 385,
  "sub_ms_prong1_ready": true
}
```

---

## 3. Agent Best Practices, Context-Frugal Protocol & Confidence Bands

### 3.1 Context-Frugal Agent Protocol (Zero Output-Spill Rules)

To guarantee that MCP tool responses remain under `< 7 KB` (`~1,500` tokens) and fit directly inline in the agent's context window without spilling into `.system_generated/steps/*/output.txt`:

1. **Always Enforce `limit: 3` on Initial Queries**:
   - Pass `"limit": 3` (and optional `"max_chars_per_result": 1800`) when calling `sovereign_route_and_analyze` or `sovereign_search_vault`.
   - **Never request `limit: 10` or `limit: 20` on exploratory queries**, as pulling 20 full HTML manuals simultaneously wastes context tokens.
2. **Use the 2-Stage Progressive Zoom Pattern**:
   - **Stage 1 (Discovery & Routing — `~4–6 KB`)**: Call `sovereign_route_and_analyze(query="...", limit=3, user_clearance="restricted")`. Read the top-level `confidence_score`, `confidence_band`, `fast_summary`, and the `virtual_uri` (`archive://...#resources/...`) of `results[0]`.
   - **Stage 2 (Targeted Deep Read — `~3–4 KB`, Only If Needed)**: If a specific procedure table or step list in `results[0].virtual_uri` needs full expansion, call `sovereign_inspect_archive(virtual_uri=results[0].virtual_uri, max_chars=4000)` on that **single `virtual_uri`**.
3. **Cap Graph Traversal at `hops: 2` (`max_neighbors: 12`)**:
   - When calling `sovereign_get_entity_dossier`, keep `"hops": 2` (and `"max_neighbors": 12`) to avoid traversing through generic product hub nodes (`USC 26.1.0` / `UPCF 26.1.0`).
4. **Authorized `user_clearance` Strings**:
   - Valid clearance levels are `"public"`, `"internal"`, `"confidential"`, and `"restricted"` (aliases `"top_secret"`, `"secret"`, and `"admin"` automatically map to `"restricted"`).

### 3.2 Consumer-Facing Confidence Telemetry (`confidence_score` & `confidence_band`)

Every MCP response places calibrated epistemic telemetry at the **very top of the JSON payload** (`confidence_score`, `confidence_band`, `epistemic_status`, and `token_budget_telemetry`), as well as inside each individual `results[i]` card:

| Confidence Band | Score Range | Epistemic Status | How the Agent Must Interpret & Report It |
| :--- | :---: | :---: | :--- |
| **`HIGH_DETERMINISTIC_EXACT (99%)`** | `0.95 – 1.00` | `VERIFIED_GROUNDED` | Exact B-Tree / FTS5 match on primary ID (`ALM-xxxx`, `MML`, `LOTE`, `CNPJ`). Cite directly with 100% certainty; zero LLM synthesis required. |
| **`HIGH_VERIFIED (85%–98%)`** | `0.85 – 0.98` | `VERIFIED_GROUNDED` | High token/semantic overlap + DITA Feature Configuration match (`5GFUP_Service` / `WHFD-*`). Present answer with `[confidence_band]` badge and `virtual_uri`. |
| **`MEDIUM_RELEVANT (55%–84%)`** | `0.55 – 0.84` | `VERIFIED_GROUNDED` | Partial multi-topic match (common in fragmented DITA micro-topics). Synthesize carefully and provide the `virtual_uri` for click-through inspection. |
| **`LOW_MARGINAL (35%–54%)`** | `0.35 – 0.54` | `VERIFIED_GROUNDED` | Weak lexical match. Warn the user that confidence is marginal and suggest refining the identifier or product module. |
| **`LOW_EPISTEMIC_REFUSAL (<35%)`** | `< 0.35` | `REFUSED_BELOW_35PCT_FLOOR` | **Mandatory `ADR-09` Epistemic Refusal**. Do NOT guess or extrapolate; report that no verified evidence exceeded the 35% safety floor. |

### 3.3 DO vs. DO NOT Checklist

- **DO** always report the `confidence_band` (e.g., `Confidence: HIGH_VERIFIED (98%)`) and the canonical `virtual_uri` (`archive://...`) in your user-facing response so the engineer can verify the exact source page.
- **DO** check `token_budget_telemetry.estimated_tokens` at the top of the response to track context savings.
- **DO NOT** dump raw multi-page files into cloud context when `sovereign_route_and_analyze(limit=3)` or `sovereign_optimize_context(max_chunks=3)` condenses them by `94%–99%` locally.

---

## 4. Related Documentation & Runbooks

- **[Sovereign Operator Manual Suite](../../docs/wiki/appliance/README.md)** (Manuals 01 through 14)
- **[Chapter 23: Sovereign Knowledge Appliance Architecture](../../docs/wiki/23_sovereign_knowledge_appliance_and_commercial_stack.md)**
- **[ADR-40 (ADR-06): Two-Pronged Hybrid Retrieval & Resilient Intent Routing](../../docs/wiki/projects/aegis/adrs/ADR-06-Two-Pronged-Hybrid-Retrieval-and-Resilient-Intent-Routing.md)**
- **[ADR-41 (ADR-07): Virtual Container Streaming & Cognitive Graph Intelligence](../../docs/wiki/projects/aegis/adrs/ADR-07-Virtual-Container-Streaming-and-Cognitive-Graph-Intelligence.md)**
- **[ADR-42 (ADR-08): Zero-Friction Onboarding, Ambient Connectors & Data Portability](../../docs/wiki/projects/aegis/adrs/ADR-08-Zero-Friction-Onboarding-Ambient-Connectors-and-Data-Portability.md)**

