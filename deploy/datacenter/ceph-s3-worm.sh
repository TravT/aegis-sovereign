#!/usr/bin/env bash
# Aegis Sovereign Datacenter Platform — Ceph S3 WORM Immutability Provisioning (ADR-38)
# Enforces SEC Rule 17a-4 / BACEN compliance with Object Lock in COMPLIANCE mode.
# Write-Once-Read-Many (WORM): Even root / admin cannot delete locked objects.

set -euo pipefail

BUCKET_NAME="${1:-aegis-sovereign-archive}"
RETENTION_DAYS="${2:-1825}" # Default 5 years

echo "======================================================================"
echo " Provisioning Aegis Sovereign Immutable WORM S3 Bucket: $BUCKET_NAME"
echo " Retention Period: $RETENTION_DAYS days (COMPLIANCE MODE)"
echo "======================================================================"

# 1. Create S3 Bucket with Object Lock enabled
aws s3api create-bucket \
  --bucket "$BUCKET_NAME" \
  --object-lock-enabled-for-bucket

# 2. Put Object Lock Configuration in COMPLIANCE Mode
aws s3api put-object-lock-configuration \
  --bucket "$BUCKET_NAME" \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Days": '"$RETENTION_DAYS"'
      }
    }
  }'

# 3. Enable Versioning (Required for Object Lock)
aws s3api put-bucket-versioning \
  --bucket "$BUCKET_NAME" \
  --versioning-configuration Status=Enabled

echo "✅ Immutable WORM Bucket '$BUCKET_NAME' successfully configured."
echo "   All uploaded documents are mathematically un-deletable until expiration."
