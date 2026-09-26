# Aegis Sovereign Knowledge Appliance — 7-Tool MCP v2 Empirical Benchmark Report

- **Generated Timestamp**: `2026-09-24T18:52:22Z`
- **MCP Server Protocol**: `stdio JSON-RPC 2.0` + `SovereignHTTPHandler` (`core/mcp/server.py`)
- **Total MCP Tools Verified**: **7 / 7** (`100% Pass`)
- **Warm Iterations per Scenario**: `10`
- **Overall Median Latency (`p50`)**: **`2.137 ms`**
- **Worst-Case Tail Latency (`p95`)**: **`7.203 ms`**

---

## 1. Real-World Enterprise & Homelab Format Ingestion Performance

| Format / Parser | Sample Artifact | Key Entities Extracted | Prong-1 Router Records | GraphRAG Edges | Ingest Latency (`ms`) |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **SEFAZ NF-e v4.00 XML** (`NfeXmlParser`) | `benchmarks/data/real_formats/nfe_v400_pharma_lote.xml` | Chave `352609123456...`, Batches `LOTE-202609B, LOTE-202608A`, ANVISA `1023504910024, 1023501180019` | 13 | 9 | `10.566 ms` |
| **RFC-5322 Email Thread** (`MboxEmailParser`) | `benchmarks/data/real_formats/noc_incident_thread.mbox` | 3 threaded messages (`INC-2026-8841`, `ALM-26235`, `DSP OPTMODULE`) | 6 | 31 | `6.309 ms` |
| **Clinical Biomarker CSV** (`TabularCsvParser`) | `benchmarks/data/real_formats/clinical_longevity_panel.csv` | 3 patients (`CPF`, `CID-10 E11.9`, `CRM-SP 184920`, `ApoB`, `hs-CRP`) | 20 | 17 | `8.278 ms` |
| **Telecom Vendor `.hdx`** (`HdxTelecomIngestor`) | `benchmarks/data/sample_5g_ran_bbu5900.hdx` | 4 Alarms, 4 MMLs, 5 3GPP KPIs | 19 | 21 | `22.927 ms` |

**Total Multi-Format Corpus Ingestion Wall-Clock Time**: **`48.16 ms`**

---

## 2. Empirical Latency & Payload Benchmark Across All 7 MCP Tools

| Scenario ID | MCP Tool Name | `p50` (ms) | `p95` (ms) | `mean` (ms) | Payload (Bytes) | Est. Tokens | Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `1A_prong1_deterministic_fast_path` | **`sovereign_route_and_analyze`** | `1.939` | `3.599` | `2.142` | `8,695` | `~2,173` | ✅ Verified |
| `1B_prong2_compound_fused_synthesis` | **`sovereign_route_and_analyze`** | `6.854` | `7.203` | `6.897` | `24,825` | `~6,206` | ✅ Verified |
| `2_optimize_context_5_executive_knobs` | **`sovereign_optimize_context`** | `4.365` | `4.64` | `4.399` | `5,201` | `~1,300` | ✅ Verified |
| `3_search_vault_hybrid_rrf` | **`sovereign_search_vault`** | `4.706` | `4.936` | `4.731` | `11,370` | `~2,842` | ✅ Verified |
| `4A_entity_dossier_telecom_alarm` | **`sovereign_get_entity_dossier`** | `2.137` | `2.345` | `2.162` | `9,376` | `~2,344` | ✅ Verified |
| `4B_entity_dossier_pharma_lote` | **`sovereign_get_entity_dossier`** | `1.949` | `2.155` | `1.957` | `8,636` | `~2,159` | ✅ Verified |
| `5_inspect_archive_zero_copy_hdx` | **`sovereign_inspect_archive`** | `3.183` | `3.376` | `3.202` | `10,046` | `~2,511` | ✅ Verified |
| `6_scan_onboarding_radar` | **`sovereign_scan_onboarding_radar`** | `1.169` | `1.349` | `1.184` | `1,130` | `~282` | ✅ Verified |
| `7_node_status_health_telemetry` | **`sovereign_node_status`** | `0.771` | `0.927` | `0.786` | `958` | `~239` | ✅ Verified |

---

## 3. Capability Verification Matrix by Tool

### `sovereign_route_and_analyze` — Prong 1 B-Tree/FTS5 Deterministic Fast-Path for ALM-26235 & LOTE-202609B (<2ms engine target)
- **Latency**: `p50 = 1.939 ms` | `p95 = 3.599 ms` | `mean = 2.142 ms` (`min = 1.866 ms`, `max = 3.599 ms`)
- **Wire Efficiency**: `8,695 bytes` (`~2,173 tokens`)
- Verified: route_type == deterministic_direct
- Verified: execution_mode == deterministic_direct_fast_path
- Verified: Matched SEFAZ <rastro> batch LOTE-202609B & ANVISA cProdANVISA 1023504910024

### `sovereign_route_and_analyze` — Prong 2 Compound Fused Query with Local NanoRunner Synthesis & Citations
- **Latency**: `p50 = 6.854 ms` | `p95 = 7.203 ms` | `mean = 6.897 ms` (`min = 6.766 ms`, `max = 7.203 ms`)
- **Wire Efficiency**: `24,825 bytes` (`~6,206 tokens`)
- Verified: route_type == compound_fused
- Verified: NanoRunner fast_summary with explicit execution_mode telemetry
- Verified: Cross-correlates .hdx ALM-26235 manual + .mbox INC-2026-8841 thread

### `sovereign_optimize_context` — Context Condenser with all 5 Executive Knobs (relational_audit, verbatim_footnotes, visual_plates, clearance, compliance_auditor)
- **Latency**: `p50 = 4.365 ms` | `p95 = 4.64 ms` | `mean = 4.399 ms` (`min = 4.32 ms`, `max = 4.64 ms`)
- **Wire Efficiency**: `5,201 bytes` (`~1,300 tokens`)
- Verified: Guaranteed >= 40% token savings (95.4% empirical compression)
- Verified: All 5 Executive Knobs enforced & echoed in telemetry
- Verified: Attached GraphRAG dossier + citations across NF-e XML & Clinical CSV

### `sovereign_search_vault` — Hybrid Dense + BM25 Sparse Reciprocal Rank Fusion (RRF) Search
- **Latency**: `p50 = 4.706 ms` | `p95 = 4.936 ms` | `mean = 4.731 ms` (`min = 4.647 ms`, `max = 4.936 ms`)
- **Wire Efficiency**: `11,370 bytes` (`~2,842 tokens`)
- Verified: Reciprocal Rank Fusion (dense + BM25 sparse_weight=1.6)
- Verified: Retrieves both .mbox NOC thread and .hdx BBU5900 alarm reference

### `sovereign_get_entity_dossier` — Multi-Hop GraphRAG Entity Dossier for ALM-26235 (spanning .hdx + .mbox)
- **Latency**: `p50 = 2.137 ms` | `p95 = 2.345 ms` | `mean = 2.162 ms` (`min = 2.114 ms`, `max = 2.345 ms`)
- **Wire Efficiency**: `9,376 bytes` (`~2,344 tokens`)
- Verified: Multi-hop GraphRAG edges: AFFECTS_NE (BBU5900), DIAGNOSED_BY_MML (DSP OPTMODULE), REMEDIATED_BY_MML (MOD NRDUCELL)
- Verified: Cross-format link: CORRELATED_WITH INC-2026-8841 from RFC-5322 .mbox archive

### `sovereign_get_entity_dossier` — Multi-Hop GraphRAG Entity Dossier for LOTE-202609B (spanning SEFAZ NF-e v4.00 XML + Clinical CSV)
- **Latency**: `p50 = 1.949 ms` | `p95 = 2.155 ms` | `mean = 1.957 ms` (`min = 1.861 ms`, `max = 2.155 ms`)
- **Wire Efficiency**: `8,636 bytes` (`~2,159 tokens`)
- Verified: Traces LOTE-202609B -> NF-e Chave 35260912345678000195550010000489121098273645
- Verified: Traces LOTE-202609B -> REGISTERED_ANVISA 1023504910024 & Emitter CNPJ 12.345.678/0001-95

### `sovereign_inspect_archive` — Zero-Disk-Extraction In-Memory .hdx Streaming & archive:// Virtual URI Resolution
- **Latency**: `p50 = 3.183 ms` | `p95 = 3.376 ms` | `mean = 3.202 ms` (`min = 3.16 ms`, `max = 3.376 ms`)
- **Wire Efficiency**: `10,046 bytes` (`~2,511 tokens`)
- Verified: 100% in-memory O_RDONLY streaming (zero temporary files on disk)
- Verified: Canonical virtual URI: archive://...sample_5g_ran_bbu5900.hdx#pages/03_alm_26235_optical_fault.html
- Verified: SHA-256 integrity hash + compression ratio zip-bomb guard

### `sovereign_scan_onboarding_radar` — Read-Only 60-Second Auto-Discovery Onboarding Radar across Multi-Domain Directories
- **Latency**: `p50 = 1.169 ms` | `p95 = 1.349 ms` | `mean = 1.184 ms` (`min = 1.15 ms`, `max = 1.349 ms`)
- **Wire Efficiency**: `1,130 bytes` (`~282 tokens`)
- Verified: Discovers and scores real_formats/ and benchmarks/data/ directories via os.scandir
- Verified: Classifies domain categories & priority scores in <5ms

### `sovereign_node_status` — Appliance Node Health, GraphRAG Entity/Relation Counts, and Plan Readiness
- **Latency**: `p50 = 0.771 ms` | `p95 = 0.927 ms` | `mean = 0.786 ms` (`min = 0.748 ms`, `max = 0.927 ms`)
- **Wire Efficiency**: `958 bytes` (`~239 tokens`)
- Verified: Reports live GraphStore entity/relation counts & query counters
- Verified: Verifies ENTERPRISE plan tier & active vector collection status
