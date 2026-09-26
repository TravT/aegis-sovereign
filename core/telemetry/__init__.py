"""
Aegis Sovereign Knowledge Appliance — Zero-Knowledge Telemetry & MinHash LSH Deduplication
==========================================================================================

Implements:
- ADR-10: Zero-Knowledge Telemetry, Zstandard Dictionary Compression (`fleet_v1.zstd_dict`),
  and LGPD Art. 12 / GDPR Recital 26 Anonymous Data Safe Harbor Enforcement.
- ADR-09: Sub-millisecond 64-permutation MinHash LSH Near-Duplicate Ingestion Filter.
"""

from .zstd_telemetry import (
    FORBIDDEN_TELEMETRY_KEYS,
    MinHashDeduplicator,
    TelemetryPrivacyError,
    ZeroKnowledgeTelemetryCompressor,
    build_sample_telemetry_payload,
    pseudonymize_identifier,
    sanitize_telemetry_payload,
)

__all__ = [
    "FORBIDDEN_TELEMETRY_KEYS",
    "TelemetryPrivacyError",
    "sanitize_telemetry_payload",
    "pseudonymize_identifier",
    "ZeroKnowledgeTelemetryCompressor",
    "build_sample_telemetry_payload",
    "MinHashDeduplicator",
]
