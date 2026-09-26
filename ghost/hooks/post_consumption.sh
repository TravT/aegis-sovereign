#!/usr/bin/env bash
# Aegis Sovereign Appliance — Ghost Ingestion Post-Consumption Hook
# Invoked by Paperless-ngx daemon immediately upon OCR completion.
# Forwards document payload to Sovereign Core on 127.0.0.1:8765.

set -euo pipefail

SOVEREIGN_CORE_URL="${SOVEREIGN_CORE_URL:-http://127.0.0.1:8765/webhook/paperless}"

DOC_ID="${DOCUMENT_ID:-0}"
DOC_TITLE="${DOCUMENT_FILE_NAME:-unknown}"
DOC_CORRESPONDENT="${DOCUMENT_CORRESPONDENT:-}"
DOC_TYPE="${DOCUMENT_TYPE:-}"

# Escape JSON text safely using Python or jq if available, fallback to basic escaping
PAYLOAD=$(python3 -c "
import json, os
data = {
    'document_id': os.getenv('DOCUMENT_ID', '0'),
    'title': os.getenv('DOCUMENT_FILE_NAME', 'unknown'),
    'correspondent': os.getenv('DOCUMENT_CORRESPONDENT', ''),
    'document_type': os.getenv('DOCUMENT_TYPE', ''),
    'created': os.getenv('DOCUMENT_CREATED', ''),
    'file_name': os.getenv('DOCUMENT_FILE_NAME', ''),
    'content': os.getenv('DOCUMENT_TEXT', '')
}
print(json.dumps(data))
" 2>/dev/null || echo "{\"document_id\": \"$DOC_ID\", \"title\": \"$DOC_TITLE\"}")

echo "[Aegis Ghost Hook] Forwarding Document #$DOC_ID ($DOC_TITLE) to Sovereign Core..."

curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$SOVEREIGN_CORE_URL" >/dev/null 2>&1 || echo "[Aegis Ghost Hook] Warning: Failed to reach Sovereign Core at $SOVEREIGN_CORE_URL"

exit 0
