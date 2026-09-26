# Ghost Ingestion Pipeline (ADR-35)

The **Ghost Ingestion Pipeline** provides unprivileged, headless document ingestion and OCR extraction without exposing end-user UI surfaces or third-party web portals.

## Architecture

```
[Drop Folder / SMB Share / WebDAV]
                 │
                 ▼
     [data/consume/ Directory]
                 │ (Inotify Watcher)
                 ▼
      [aegis-paperless-ghost]
      (Headless OCR Daemon on 127.0.0.1:8000)
                 │
                 ▼ (Post-Consumption Hook)
     [post_consumption.sh]
                 │
                 ▼ (HTTP POST /webhook/paperless)
       [Sovereign Core (127.0.0.1:8765)]
         ├── FastEmbed ONNX Embedding (Dense 384d + Sparse BM25)
         ├── Deterministic GraphRAG Entity Linking (SQLite WAL)
         └── Action Detection & Event Routing
```

## Security Invariants

1. **Strict Loopback Binding**: `aegis-paperless-ghost` binds strictly to `127.0.0.1:8000`. No external ingress, Traefik routes, or internet listeners.
2. **Zero Cloud Telemetry**: All OCR execution runs locally via Tesseract engine (multilingual PT-BR / EN).
3. **Automated Trigger**: As soon as a document completes OCR, the post-consumption hook posts directly to the Sovereign Core ingestion endpoint.
