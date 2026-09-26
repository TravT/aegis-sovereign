---
title: "Manual 02: Database Initialization & Vector Store Architecture"
category: operations
type: documentation
node: homelab
domain: ai-data
tags:
  - homelab/appliance
  - ai/rag
  - database/qdrant
  - database/sqlite
status: active
last_reviewed: 2026-09-17
aliases:
  - Database Initialization Guide
  - Vector Store & Graph Setup
---

# 🧠 Manual 02: Database Initialization & Vector Store Architecture

> **Parent Suite**: [Sovereign Appliance Manual Index](README.md)  
> **Previous Step**: [Manual 01: Deployment Guide](01_deployment_guide.md)  
> **Key Technologies**: Qdrant v1.19+, FastEmbed ONNX int8, BM25 Lexical, SQLite 3.45+ (WAL Mode)  

---

## 1. Core Data Store Architecture

The Sovereign Appliance manages two complementary data engines to provide zero-hallucination grounded retrieval:

```text
Data Storage Architecture:
  ├── 1. Vector Store (Qdrant)
  │    ├── wiki_chunks        (Obsidian Technical Documentation & ADRs)
  │    └── paperless_chunks   (Scanned Contracts, Invoices, Receipts, Legal Filings)
  └── 2. Relational Knowledge Graph (SQLite WAL)
       └── graph_store.db     (Extracted Entities, CNPJ/CPF, Due Dates, Monetary Flows)
```

---

## 2. Vector Collection Specifications

Qdrant collections are initialized dynamically upon the first index run. All vector distances enforce **Cosine Similarity**:

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, SparseVectorParams

client = QdrantClient(url="http://127.0.0.1:6333")

# Dense Vector Config (384 Dimensions, Cosine Distance)
dense_config = VectorParams(size=384, distance=Distance.COSINE)

# Sparse Vector Config (BM25 Lexical Model)
sparse_config = SparseVectorParams()

# Initialize Collection
client.create_collection(
    collection_name="wiki_chunks",
    vectors_config={"dense": dense_config},
    sparse_vectors_config={"sparse": sparse_config}
)
```

### Models Utilized
* **Dense Embedding**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` executed locally via FastEmbed ONNX Runtime (CPU int8 quantized, sub-15ms embedding).
* **Sparse Lexical**: `Qdrant/bm25` (handles exact numeric matches, serial numbers, tax IDs, and court docket codes).

---

## 3. Relational Knowledge Graph Schema (SQLite WAL)

The relational knowledge graph resides at `/opt/sovereign-vault/data/appliance/rag/graph_store.db` with Write-Ahead Logging (WAL) enabled for high-concurrency access:

```sql
-- Core Entity Registry
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,       -- COMPANY, INDIVIDUAL, COURT, AGENCY
    tax_id TEXT,                     -- CNPJ / CPF
    metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Document Reference Registry
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT,                   -- CONTRATO, TED, NOTA_FISCAL, INTIMACAO
    source_path TEXT,
    created_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bidirectional Graph Relations
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    source_entity TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    relation_type TEXT NOT NULL,     -- SHAREHOLDER, TRANSFERRED_MONEY, LAWSUIT, TENANT
    monetary_value REAL,
    due_date TEXT,
    document_id TEXT,
    evidence_chunk TEXT,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);
```

---

## 4. Seeding & Building the Databases

### Automatic Boot Seeding
When the `aegis-sovereign-core` container starts, `scripts/rag_watcher.py` automatically checks the documentation directory and seeds `wiki_chunks` in under 30 seconds:
```bash
# Verify initial boot indexing results
curl -s http://127.0.0.1:8765/health | jq .last_result
```

### Manual Trigger for Vector & Graph Re-Index
To trigger an on-demand re-index across all documents:
```bash
# Via HTTP Gateway API
curl -s -X POST "http://127.0.0.1:8765/reindex?corpus=all" | jq .

# Direct Container CLI (inside appliance)
docker exec -it aegis-sovereign-core python3 scripts/rag_indexer.py --force
docker exec -it aegis-sovereign-core python3 scripts/rag_graph_indexer.py --rebuild
```

---

## 5. Incremental Synchronization & SHA-256 Hashing

To avoid redundant CPU cycles, indexing is stateful and incremental. SHA-256 checksums are tracked in `data/appliance/rag/indexer_state.json`. Only modified or new documents trigger chunking and vector recalculation.

---

## Next Steps
* Proceed to **[Manual 03: Connector Matrix & External Integrations](03_connector_matrix_and_external_integrations.md)** to connect external databases and ERPs.
