---
title: "Manual 03: Connector Matrix & External Integrations"
category: operations
type: documentation
node: homelab
domain: ai-data
tags:
  - homelab/appliance
  - integration/api
  - database/connectors
  - product/appliance
status: active
last_reviewed: 2026-09-17
aliases:
  - Connector Matrix Guide
  - External Integrations & Ingress
---

# 🔌 Manual 03: Connector Matrix, External Databases & Volume Hot-Swapping

> **Parent Suite**: [Sovereign Appliance Manual Index](README.md)  
> **Previous Step**: [Manual 02: Database Initialization](02_database_initialization_and_vector_store.md)  
> **Target Capabilities**: ERP Connectors, External SQL Integration, Client Vault Migration  

---

## 1. Supported Integration Matrix

The Sovereign Appliance exposes a clean hexagonal boundary, allowing integration with external databases and corporate document streams without altering core code:

| Ingress Source | Connector Protocol | Ingestion Frequency | Typical Use Case |
| :--- | :--- | :--- | :--- |
| **Paperless-ngx** | Internal REST API + Post-Consumption Hook | Event-Driven (Real-time < 5s) | Core Scanned Archive, Receipts, Contracts |
| **PostgreSQL / MySQL** | Read-Only SQL Replica / CDC | Periodic Poll or Event Trigger | Private ERPs, CRM Transactions, Bank Accounts |
| **Network Shared Drive** | SMB / CIFS / NFS Mount | Watchdog Filesystem Daemon | Law Firm Active Case Folders, Scan Station |
| **WebDAV Cloud Vault** | HTTP WebDAV Client | Scheduled Hourly / Daily | Executive Offsite Encrypted Folder Sync |
| **Custom ERP / REST** | HTTP Webhook (`/webhook/erp`) | Event-Driven JSON Push | SAP, Totvs, ContaAzul Transaction Feeds |

---

## 2. Connecting to External Relational Databases

To ingest tabular records (e.g. accounting journals, invoices, customer dossiers) from an external corporate database:

### Read-Only Connection Pattern
Configure database parameters in `/opt/sovereign-vault/docker-compose.yml`:
```yaml
services:
  sovereign-core:
    environment:
      EXTERNAL_DB_TYPE: postgresql  # postgresql, mysql, mssql
      EXTERNAL_DB_HOST: 192.168.1.50
      EXTERNAL_DB_PORT: 5432
      EXTERNAL_DB_NAME: corporate_erp
      EXTERNAL_DB_USER: sovereign_readonly
      EXTERNAL_DB_PASSWORD: ${VAULT_ERP_PASSWORD}
```

### Ingestion Script Pipeline
The appliance runs a lightweight tabular-to-chunk mapper that converts rows into searchable markdown documents with entity metadata:
```bash
# Execute external database table extraction
docker exec -it aegis-sovereign-core python3 scripts/rag_external_db_sync.py --table invoices
```

---

## 3. Hot-Swapping & Migrating Client Vaults

One of the foundational architectural features defined in [ADR-35](../adrs/ADR-35-Sovereign-Knowledge-Appliance-Packaging-and-Commercial-Architecture.md) is **zero-lock-in vault portability**. An entire client's private intelligence core consists of only two volume folders:

```text
Portable Client Vault Package:
  ├── qdrant/storage/   (Dense & Sparse Vectors)
  └── rag/              (SQLite graph_store.db + Indexer State JSON)
```

### To Unplug and Export a Client Vault:
```bash
# 1. Stop container stack gracefully
cd /opt/sovereign-vault && docker compose stop

# 2. Archive client data room
tar -czvf client_vault_snapshot_2026.tar.gz \
  data/appliance/qdrant \
  data/appliance/rag \
  data/appliance/paperless/media
```

### To Plug In a New Client Vault:
```bash
# 1. Extract snapshot into target data directory
tar -xzvf client_vault_snapshot_2026.tar.gz -C /opt/sovereign-vault/

# 2. Restart container stack
cd /opt/sovereign-vault && docker compose up -d

# 3. Verify immediate instant retrieval (< 5 seconds)
curl -s http://127.0.0.1:8765/health | jq .
```

---

## 4. Webhook Ingestion API Specification

External systems can push documents or event payloads directly into the Sovereign Gateway via HTTP POST:

```bash
# Push document ingestion event
curl -s -X POST http://<APPLIANCE_IP>:8765/webhook/paperless \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "1042",
    "file_name": "Contrato_Social_2026.pdf",
    "correspondent": "Junta Comercial",
    "tags": "Contratos,Societario",
    "source": "external_api"
  }'
```

---

## Next Steps
* Proceed to **[Manual 04: MCP Harness & Agent Configuration](04_mcp_harness_and_agent_configuration.md)** to connect coding assistants and LLMs to the appliance.
