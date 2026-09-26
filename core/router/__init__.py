#!/usr/bin/env python3
"""
Aegis Sovereign Knowledge Appliance - Router Package.
Provides Two-Pronged Hybrid Retrieval & Resilient Intent Routing (ADR-40).
"""

from .query_router import (
    QueryRouteType,
    ExtractedIdentifier,
    RouteDecision,
    calculate_shannon_entropy,
    RESERVED_LEXICON,
    HEX_PATTERN,
    TICKET_PATTERN,
    CPF_PATTERN,
    CNPJ_PATTERN,
    QUOTED_PHRASE_PATTERN,
    ALARM_ID_PATTERN,
    MML_COMMAND_PATTERN,
    KPI_COUNTER_PATTERN,
    SYNTHESIS_INTENT_PATTERN,
    RELATIONAL_INTENT_PATTERN,
    MACRO_SYNTHESIS_PATTERN,
    SovereignQueryRouter,
)

__all__ = [
    "QueryRouteType",
    "ExtractedIdentifier",
    "RouteDecision",
    "calculate_shannon_entropy",
    "RESERVED_LEXICON",
    "HEX_PATTERN",
    "TICKET_PATTERN",
    "CPF_PATTERN",
    "CNPJ_PATTERN",
    "QUOTED_PHRASE_PATTERN",
    "ALARM_ID_PATTERN",
    "MML_COMMAND_PATTERN",
    "KPI_COUNTER_PATTERN",
    "SYNTHESIS_INTENT_PATTERN",
    "RELATIONAL_INTENT_PATTERN",
    "MACRO_SYNTHESIS_PATTERN",
    "SovereignQueryRouter",
]
