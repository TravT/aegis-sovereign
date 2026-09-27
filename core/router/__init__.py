#!/usr/bin/env python3
"""
Aegis Sovereign Knowledge Appliance - Router Package.
Provides Two-Pronged Hybrid Retrieval & Resilient Intent Routing (ADR-40).
"""

from .grammars import (
    calculate_shannon_entropy,
    HEX_PATTERN,
    TICKET_PATTERN,
    STANDARD_SPEC_PATTERN,
    CPF_PATTERN,
    CNPJ_PATTERN,
    QUOTED_PHRASE_PATTERN,
    ALARM_ID_PATTERN,
    MML_COMMAND_PATTERN,
    KPI_COUNTER_PATTERN,
    TELCO_SPEC_PATTERN,
    ISBN_PATTERN,
    LOTE_PATTERN,
    ANVISA_MS_PATTERN,
    NFE_CHAVE_PATTERN,
    PORTARIA_344_PATTERN,
    CID10_PATTERN,
    CRM_PATTERN,
    ADR_PATTERN,
    SKILL_PATTERN,
    SKILL_ID_PATTERN,
    SYNTHESIS_INTENT_PATTERN,
    RELATIONAL_INTENT_PATTERN,
    MACRO_SYNTHESIS_PATTERN,
    RESERVED_LEXICON,
    CONCEPTUAL_LEXICON,
)

from .classifier import (
    QueryRouteType,
    RouteType,
    ConfidenceLevel,
    ExtractedIdentifier,
    RouteDecision,
    score_epistemic_confidence,
    classify_query_intent,
)

from .query_router import SovereignQueryRouter

__all__ = [
    "QueryRouteType",
    "RouteType",
    "ConfidenceLevel",
    "ExtractedIdentifier",
    "RouteDecision",
    "score_epistemic_confidence",
    "classify_query_intent",
    "calculate_shannon_entropy",
    "RESERVED_LEXICON",
    "CONCEPTUAL_LEXICON",
    "HEX_PATTERN",
    "TICKET_PATTERN",
    "STANDARD_SPEC_PATTERN",
    "CPF_PATTERN",
    "CNPJ_PATTERN",
    "QUOTED_PHRASE_PATTERN",
    "ALARM_ID_PATTERN",
    "MML_COMMAND_PATTERN",
    "KPI_COUNTER_PATTERN",
    "TELCO_SPEC_PATTERN",
    "ISBN_PATTERN",
    "LOTE_PATTERN",
    "ANVISA_MS_PATTERN",
    "NFE_CHAVE_PATTERN",
    "PORTARIA_344_PATTERN",
    "CID10_PATTERN",
    "CRM_PATTERN",
    "ADR_PATTERN",
    "SKILL_PATTERN",
    "SKILL_ID_PATTERN",
    "SYNTHESIS_INTENT_PATTERN",
    "RELATIONAL_INTENT_PATTERN",
    "MACRO_SYNTHESIS_PATTERN",
    "SovereignQueryRouter",
]
