"""
Document Classification & Metadata Enrichment Engine for Aegis Sovereign Knowledge Appliance.
"""

from .rules import (
    ClassificationResult,
    classify_text_and_title,
    DOC_TYPE_RULES,
    ORGANIZATION_RULES,
    TAG_DOMAIN_RULES,
)

__all__ = [
    "ClassificationResult",
    "classify_text_and_title",
    "DOC_TYPE_RULES",
    "ORGANIZATION_RULES",
    "TAG_DOMAIN_RULES",
]
