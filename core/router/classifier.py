#!/usr/bin/env python3
"""
Query Intent Classifier & Epistemic Route Determination (ADR-40 / Chapter 24).
Aegis Sovereign Knowledge Appliance.

Classifies operator queries into deterministic fast-path lookups (<2ms),
relational graph audits, hybrid vector/lexical retrieval, or macro synthesis,
while guarding against acronym hijacking and unverified hallucinations.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, Tuple

from .grammars import (
    calculate_shannon_entropy,
    HEX_PATTERN,
    TICKET_PATTERN,
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


class QueryRouteType(str, Enum):
    DETERMINISTIC_DIRECT = "deterministic_direct"
    RELATIONAL_GRAPH = "relational_graph"
    HYBRID_NEEDLE = "hybrid_needle"
    MACRO_SYNTHESIS = "macro_synthesis"
    COMPOUND_FUSED = "compound_fused"


# RouteType alias for backward and cross-module compatibility
RouteType = QueryRouteType


class ConfidenceLevel(str, Enum):
    HIGH_DETERMINISTIC_EXACT = "HIGH_DETERMINISTIC_EXACT"
    HIGH_VERIFIED = "HIGH_VERIFIED"
    MEDIUM_RELEVANT = "MEDIUM_RELEVANT"
    MEDIUM_PARTIAL = "MEDIUM_PARTIAL"
    LOW_MARGINAL = "LOW_MARGINAL"
    LOW_UNVERIFIED = "LOW_UNVERIFIED"
    LOW_EPISTEMIC_REFUSAL = "LOW_EPISTEMIC_REFUSAL"
    SUGGESTIONS_AVAILABLE = "SUGGESTIONS_AVAILABLE"
    UNVERIFIED_SUGGESTIONS_AVAILABLE = "UNVERIFIED_SUGGESTIONS_AVAILABLE"
    RELATED_TOPICS_FOUND = "RELATED_TOPICS_FOUND"
    NOT_FOUND = "NOT_FOUND"


@dataclass
class ExtractedIdentifier:
    id_type: str  # "hex", "ticket", "cpf", "cnpj", "lote", "anvisa_ms", "nfe_chave", "portaria_344_lista", "cid10", "crm", "telco_spec", "isbn", "agent_skill", "wiki_adr", "quoted_phrase", "high_entropy_code"
    raw_value: str
    normalized_value: str
    confidence: float = 1.0
    entropy: float = 0.0
    domain: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id_type": self.id_type,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "confidence": self.confidence,
            "entropy": self.entropy,
        }
        if self.domain:
            d["domain"] = self.domain
        return d


@dataclass
class RouteDecision:
    route_type: QueryRouteType
    extracted_identifier: Optional[ExtractedIdentifier] = None
    bypass_vector_search: bool = False
    safe_fail_on_missing_id: bool = False
    fallback_active: bool = False
    fallback_reason: Optional[str] = None
    suggested_retrieval_mode: str = "high_precision"  # "high_precision", "exact_entity", "legal_discovery"
    suggested_analytical_depth: str = "flash_needle"  # "flash_needle", "relational_audit", "deep_synthesis"
    suggested_graph_hops: int = 0
    needs_synthesis: bool = False
    target_entity: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_type": self.route_type.value,
            "extracted_identifier": self.extracted_identifier.to_dict() if self.extracted_identifier else None,
            "bypass_vector_search": self.bypass_vector_search,
            "safe_fail_on_missing_id": self.safe_fail_on_missing_id,
            "fallback_active": self.fallback_active,
            "fallback_reason": self.fallback_reason,
            "suggested_retrieval_mode": self.suggested_retrieval_mode,
            "suggested_analytical_depth": self.suggested_analytical_depth,
            "suggested_graph_hops": self.suggested_graph_hops,
            "needs_synthesis": self.needs_synthesis,
            "target_entity": self.target_entity,
        }


def score_epistemic_confidence(
    top_score: float,
    is_deterministic_direct: bool = False,
    has_results: bool = True,
) -> Tuple[float, str, ConfidenceLevel]:
    """
    Computes normalized epistemic confidence band and classification enum
    conforming to ADR-09 and ADR-40 invariants.
    """
    if not has_results and is_deterministic_direct:
        return 0.0, "LOW_EPISTEMIC_REFUSAL (0% - Not Found)", ConfidenceLevel.LOW_EPISTEMIC_REFUSAL

    if top_score >= 0.85:
        pct = int(round(top_score * 100))
        return round(top_score, 4), f"HIGH_VERIFIED ({pct}%)", ConfidenceLevel.HIGH_VERIFIED
    elif top_score >= 0.55:
        pct = int(round(top_score * 100))
        return round(top_score, 4), f"MEDIUM_RELEVANT ({pct}%)", ConfidenceLevel.MEDIUM_RELEVANT
    elif top_score >= 0.35:
        pct = int(round(top_score * 100))
        return round(top_score, 4), f"LOW_MARGINAL ({pct}%)", ConfidenceLevel.LOW_MARGINAL
    else:
        pct = int(round(top_score * 100))
        return round(top_score, 4), f"LOW_EPISTEMIC_REFUSAL ({pct}%)", ConfidenceLevel.LOW_EPISTEMIC_REFUSAL


def classify_query_intent(raw_query: str) -> RouteDecision:
    """
    Performs resilient token classification, entropy verification, anti-hijack checks,
    vertical domain grammar matching (ADR-06 & Chapter 24), and bilingual intent mapping
    to produce a deterministic RouteDecision.
    """
    clean_q = raw_query.strip()
    if not clean_q:
        return RouteDecision(
            route_type=QueryRouteType.HYBRID_NEEDLE,
            suggested_retrieval_mode="high_precision",
            suggested_analytical_depth="flash_needle",
            needs_synthesis=False,
        )

    # 1. Anti-Hijack Guard: Check single-word domain terms & common acronyms
    single_word_upper = clean_q.upper()
    if single_word_upper in RESERVED_LEXICON or single_word_upper in CONCEPTUAL_LEXICON:
        # Common domain words (TAX, CEO, DARF, LGPD, ARCHITECTURE) must NEVER trigger fast-path
        return RouteDecision(
            route_type=QueryRouteType.HYBRID_NEEDLE,
            extracted_identifier=None,
            bypass_vector_search=False,
            safe_fail_on_missing_id=False,
            suggested_retrieval_mode="high_precision",
            suggested_analytical_depth="flash_needle",
            needs_synthesis=False,
        )

    # 2. Extract Structured & Vertical Domain Identifiers
    extracted_id: Optional[ExtractedIdentifier] = None

    # Check Hex (e.g. 0x80070005)
    hex_match = HEX_PATTERN.search(clean_q)
    if hex_match:
        val = hex_match.group(1)
        extracted_id = ExtractedIdentifier(
            id_type="hex",
            raw_value=val,
            normalized_value=val.lower(),
            confidence=1.0,
            entropy=calculate_shannon_entropy(val),
        )

    # Check CNPJ (e.g. 12.345.678/0001-90)
    if not extracted_id:
        cnpj_match = CNPJ_PATTERN.search(clean_q)
        if cnpj_match:
            val = cnpj_match.group(1)
            norm = re.sub(r'[^\d]', '', val)
            extracted_id = ExtractedIdentifier(
                id_type="cnpj",
                raw_value=val,
                normalized_value=norm,
                confidence=1.0,
                entropy=calculate_shannon_entropy(val),
            )

    # Check CPF (e.g. 123.456.789-00)
    if not extracted_id:
        cpf_match = CPF_PATTERN.search(clean_q)
        if cpf_match:
            val = cpf_match.group(1)
            norm = re.sub(r'[^\d]', '', val)
            extracted_id = ExtractedIdentifier(
                id_type="cpf",
                raw_value=val,
                normalized_value=norm,
                confidence=1.0,
                entropy=calculate_shannon_entropy(val),
            )

    # --- Vertical 1: Pharmacy & ANVISA (pharmacies_and_smb_retail) ---
    # Check NF-e 44-digit Chave de Acesso
    if not extracted_id:
        nfe_match = NFE_CHAVE_PATTERN.search(clean_q)
        if nfe_match:
            raw_val = nfe_match.group(1).strip()
            norm_val = re.sub(r'[^\d]', '', raw_val)
            if len(norm_val) == 44:
                extracted_id = ExtractedIdentifier(
                    id_type="nfe_chave",
                    raw_value=raw_val,
                    normalized_value=norm_val,
                    confidence=1.0,
                    entropy=calculate_shannon_entropy(norm_val),
                    domain="pharmacies_and_smb_retail",
                )

    # Check ANVISA Registro MS (e.g. MS 1.0235.1234.001-2 or 1.0235.1234.001-2)
    if not extracted_id:
        ms_match = ANVISA_MS_PATTERN.search(clean_q)
        if ms_match:
            raw_val = ms_match.group(1).strip()
            norm_val = ms_match.group(2).strip()
            extracted_id = ExtractedIdentifier(
                id_type="anvisa_ms",
                raw_value=raw_val,
                normalized_value=norm_val,
                confidence=1.0,
                entropy=calculate_shannon_entropy(norm_val),
                domain="pharmacies_and_smb_retail",
            )

    # Check Pharmacy Batch LOTE (e.g. LOTE-202609B, Lote: L2409-A, LOTE 88412A)
    if not extracted_id:
        lote_match = LOTE_PATTERN.search(clean_q)
        if lote_match:
            raw_val = lote_match.group(1).strip()
            batch_code = lote_match.group(2).strip().upper()
            extracted_id = ExtractedIdentifier(
                id_type="lote",
                raw_value=raw_val,
                normalized_value=batch_code,
                confidence=1.0,
                entropy=calculate_shannon_entropy(batch_code),
                domain="pharmacies_and_smb_retail",
            )

    # Check Portaria 344 Controlled Substance List (e.g. Lista B1, Lista A1)
    if not extracted_id:
        p344_match = PORTARIA_344_PATTERN.search(clean_q)
        if p344_match:
            raw_val = p344_match.group(1).strip()
            list_code = f"Lista {p344_match.group(2).upper()}"
            extracted_id = ExtractedIdentifier(
                id_type="portaria_344_lista",
                raw_value=raw_val,
                normalized_value=list_code,
                confidence=0.98,
                entropy=calculate_shannon_entropy(list_code),
                domain="pharmacies_and_smb_retail",
            )

    # --- Vertical 2: Medical & Boutique Clinics (boutique_medical_and_longevity_clinics) ---
    # Check Physician CRM (e.g. CRM-SP 123456)
    if not extracted_id:
        crm_match = CRM_PATTERN.search(clean_q)
        if crm_match:
            raw_val = crm_match.group(1).strip()
            uf = crm_match.group(2).upper()
            num = crm_match.group(3)
            norm_val = f"CRM-{uf} {num}"
            extracted_id = ExtractedIdentifier(
                id_type="crm",
                raw_value=raw_val,
                normalized_value=norm_val,
                confidence=1.0,
                entropy=calculate_shannon_entropy(norm_val),
                domain="boutique_medical_and_longevity_clinics",
            )

    # Check ICD-10 / CID-10 disease codes (e.g. CID-10 E11.9, F41.1, I10.0)
    if not extracted_id:
        cid_match = CID10_PATTERN.search(clean_q)
        if cid_match:
            raw_val = cid_match.group(0).strip()
            code_val = (cid_match.group(1) or cid_match.group(2)).upper()
            extracted_id = ExtractedIdentifier(
                id_type="cid10",
                raw_value=raw_val,
                normalized_value=code_val,
                confidence=0.99,
                entropy=calculate_shannon_entropy(code_val),
                domain="boutique_medical_and_longevity_clinics",
            )

    # --- Vertical 3: Telco Engineering Manuals & Academic Libraries ---
    # Check Telecom Alarm ID (e.g. ALM-26235, ALM-29201, ALM-26522, ALM-20104)
    if not extracted_id:
        alm_match = ALARM_ID_PATTERN.search(clean_q)
        if alm_match:
            raw_val = alm_match.group(1).strip()
            norm_val = raw_val.upper()
            extracted_id = ExtractedIdentifier(
                id_type="telecom_alarm",
                raw_value=raw_val,
                normalized_value=norm_val,
                confidence=1.0,
                entropy=calculate_shannon_entropy(norm_val),
                domain="telco_and_academic_libraries",
            )

    # Check Telecom MML Command (e.g. DSP OPTMODULE, MOD NRDUCELL, LST ALMAF, ADD GNBCUCP)
    if not extracted_id:
        mml_match = MML_COMMAND_PATTERN.search(clean_q)
        if mml_match:
            raw_val = mml_match.group(1).strip()
            norm_val = re.sub(r'\s+', ' ', raw_val.upper())
            extracted_id = ExtractedIdentifier(
                id_type="mml_command",
                raw_value=raw_val,
                normalized_value=norm_val,
                confidence=1.0,
                entropy=calculate_shannon_entropy(norm_val),
                domain="telco_and_academic_libraries",
            )

    # Check 3GPP / Vendor KPI Counter (e.g. VS.NR.RRC.ConnEstab.Succ, VS.NR.MAC.DL.Throughput)
    if not extracted_id:
        kpi_match = KPI_COUNTER_PATTERN.search(clean_q)
        if kpi_match:
            raw_val = kpi_match.group(1).strip()
            extracted_id = ExtractedIdentifier(
                id_type="telecom_kpi",
                raw_value=raw_val,
                normalized_value=raw_val,
                confidence=1.0,
                entropy=calculate_shannon_entropy(raw_val),
                domain="telco_and_academic_libraries",
            )

    # Check 3GPP TS & IETF RFC specifications (e.g. 3GPP TS 38.331, RFC 9114)
    if not extracted_id:
        telco_match = TELCO_SPEC_PATTERN.search(clean_q)
        if telco_match:
            raw_val = telco_match.group(1).strip()
            norm_val = re.sub(r'\s+', ' ', raw_val)
            extracted_id = ExtractedIdentifier(
                id_type="telco_spec",
                raw_value=raw_val,
                normalized_value=norm_val,
                confidence=1.0,
                entropy=calculate_shannon_entropy(norm_val),
                domain="telco_and_academic_libraries",
            )

    # Check ISBN-10 / ISBN-13
    if not extracted_id:
        isbn_match = ISBN_PATTERN.search(clean_q)
        if isbn_match:
            raw_val = isbn_match.group(1).strip()
            norm_val = re.sub(r'[^\dX]', '', isbn_match.group(2).upper())
            extracted_id = ExtractedIdentifier(
                id_type="isbn",
                raw_value=raw_val,
                normalized_value=norm_val,
                confidence=1.0,
                entropy=calculate_shannon_entropy(norm_val),
                domain="telco_and_academic_libraries",
            )

    # --- Vertical 4: Homelab, Server Architecture & Agent Skills ---
    # Check Homelab Architectural Decision Record (e.g. ADR-40, ADR-30, ADR-20)
    if not extracted_id:
        adr_match = ADR_PATTERN.search(clean_q)
        if adr_match:
            raw_val = adr_match.group(1).strip().upper()
            extracted_id = ExtractedIdentifier(
                id_type="wiki_adr",
                raw_value=raw_val,
                normalized_value=raw_val,
                confidence=1.0,
                entropy=calculate_shannon_entropy(raw_val),
                domain="homelab_wiki",
            )

    # Check Agent Skill ID (e.g. manage-sovereign-vault, manage-traefik, trigger-n8n-workflows)
    if not extracted_id:
        skill_match = SKILL_PATTERN.search(clean_q) or SKILL_ID_PATTERN.search(clean_q)
        if skill_match:
            raw_val = skill_match.group(1).strip()
            norm_val = raw_val.lower()
            extracted_id = ExtractedIdentifier(
                id_type="agent_skill",
                raw_value=raw_val,
                normalized_value=norm_val,
                confidence=1.0,
                entropy=calculate_shannon_entropy(norm_val),
                domain="agent_skills",
            )

    # Check Ticket (e.g. TCK-1092, SEC-9901, INC-2026-8841)
    if not extracted_id:
        ticket_match = TICKET_PATTERN.search(clean_q)
        if ticket_match:
            val = ticket_match.group(1)
            extracted_id = ExtractedIdentifier(
                id_type="ticket",
                raw_value=val,
                normalized_value=val.upper(),
                confidence=1.0,
                entropy=calculate_shannon_entropy(val),
            )

    # Check Quoted Phrase (e.g. "Clause 14.2")
    if not extracted_id:
        quote_match = QUOTED_PHRASE_PATTERN.search(clean_q)
        if quote_match:
            val = quote_match.group(1)
            extracted_id = ExtractedIdentifier(
                id_type="quoted_phrase",
                raw_value=f'"{val}"',
                normalized_value=val,
                confidence=0.98,
                entropy=calculate_shannon_entropy(val),
            )

    # Check General High-Entropy Alphanumeric Code (H >= 2.8 and NOT in RESERVED_LEXICON)
    if not extracted_id:
        tokens = re.findall(r'\b[A-Za-z0-9_-]{4,20}\b', clean_q)
        for tok in tokens:
            upper_tok = tok.upper()
            if upper_tok in RESERVED_LEXICON or upper_tok in CONCEPTUAL_LEXICON:
                continue
            ent = calculate_shannon_entropy(tok)
            # Must contain at least one digit and one letter, or high entropy
            has_digit = any(c.isdigit() for c in tok)
            has_letter = any(c.isalpha() for c in tok)
            if has_digit and has_letter and ent >= 2.8:
                extracted_id = ExtractedIdentifier(
                    id_type="high_entropy_code",
                    raw_value=tok,
                    normalized_value=tok,
                    confidence=0.90,
                    entropy=ent,
                )
                break

    # 3. Assess Intent Patterns
    has_synthesis_intent = bool(SYNTHESIS_INTENT_PATTERN.search(clean_q))
    has_relational_intent = bool(RELATIONAL_INTENT_PATTERN.search(clean_q))
    has_macro_intent = bool(MACRO_SYNTHESIS_PATTERN.search(clean_q))
    has_question_intent = "?" in clean_q and extracted_id is not None and extracted_id.id_type == "portaria_344_lista"

    # 4. Route Decision Logic
    if extracted_id:
        # Compound query: contains an exact identifier BUT ALSO requests synthesis/analysis
        if has_synthesis_intent or has_macro_intent or has_question_intent:
            return RouteDecision(
                route_type=QueryRouteType.COMPOUND_FUSED,
                extracted_identifier=extracted_id,
                bypass_vector_search=False,
                safe_fail_on_missing_id=False,
                suggested_retrieval_mode="exact_entity",
                suggested_analytical_depth="deep_synthesis",
                needs_synthesis=True,
            )
        elif has_relational_intent:
            return RouteDecision(
                route_type=QueryRouteType.COMPOUND_FUSED,
                extracted_identifier=extracted_id,
                bypass_vector_search=False,
                safe_fail_on_missing_id=False,
                suggested_retrieval_mode="exact_entity",
                suggested_analytical_depth="relational_audit",
                suggested_graph_hops=2,
                needs_synthesis=True,
            )
        else:
            # Pure deterministic fast-path lookup (<2ms, 0 cloud tokens, safe failure)
            return RouteDecision(
                route_type=QueryRouteType.DETERMINISTIC_DIRECT,
                extracted_identifier=extracted_id,
                bypass_vector_search=True,
                safe_fail_on_missing_id=True,
                suggested_retrieval_mode="high_precision",
                suggested_analytical_depth="flash_needle",
                needs_synthesis=False,
            )

    # No identifier present: Cognitive Prong 2 routing
    if has_macro_intent:
        return RouteDecision(
            route_type=QueryRouteType.MACRO_SYNTHESIS,
            extracted_identifier=None,
            bypass_vector_search=False,
            safe_fail_on_missing_id=False,
            suggested_retrieval_mode="high_precision",
            suggested_analytical_depth="deep_synthesis",
            needs_synthesis=True,
        )

    if has_relational_intent:
        return RouteDecision(
            route_type=QueryRouteType.RELATIONAL_GRAPH,
            extracted_identifier=None,
            bypass_vector_search=False,
            safe_fail_on_missing_id=False,
            suggested_retrieval_mode="exact_entity",
            suggested_analytical_depth="relational_audit",
            suggested_graph_hops=2,
            needs_synthesis=True,
        )

    if has_synthesis_intent:
        return RouteDecision(
            route_type=QueryRouteType.HYBRID_NEEDLE,
            extracted_identifier=None,
            bypass_vector_search=False,
            safe_fail_on_missing_id=False,
            suggested_retrieval_mode="high_precision",
            suggested_analytical_depth="flash_needle",
            needs_synthesis=True,
        )

    # Default natural query
    return RouteDecision(
        route_type=QueryRouteType.HYBRID_NEEDLE,
        extracted_identifier=None,
        bypass_vector_search=False,
        safe_fail_on_missing_id=False,
        suggested_retrieval_mode="high_precision",
        suggested_analytical_depth="flash_needle",
        needs_synthesis=False,
    )


__all__ = [
    "QueryRouteType",
    "RouteType",
    "ConfidenceLevel",
    "ExtractedIdentifier",
    "RouteDecision",
    "score_epistemic_confidence",
    "classify_query_intent",
]
