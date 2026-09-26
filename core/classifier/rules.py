#!/usr/bin/env python3
"""
Entity-Grounded Document Classification & Metadata Enrichment Engine.
Aegis Sovereign Knowledge Appliance.

Extracts entities (CPF, CNPJ, monetary values, dates) and domain organizations,
infers document types, correspondents, and domain tags.

Invariants:
- Zero Plaintext Secrets.
- Local CPU execution (deterministic, zero cloud tokens).
"""

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set

from ..graph.extractor import (
    extract_cpf,
    extract_cnpj,
    extract_monetary_amounts,
    extract_dates,
)

logger = logging.getLogger("sovereign_classifier")

# ==============================================================================
# Domain Heuristic Mappings & Rules
# ==============================================================================

DOC_TYPE_RULES: Dict[str, List[str]] = {
    "Declaração de Imposto de Renda": [
        "declaracao de ajuste anual", "declaração de ajuste anual", "declaracao transmitida",
        "recibo de entrega da declaracao", "recibo de entrega", "declaracao irpf", "dirpf", "irpf"
    ],
    "Informe de Rendimentos": [
        "informe de rendimentos", "informe de rendimento", "fonte pagadora",
        "rendimentos tributáveis", "rendimentos isentos"
    ],
    "Comprovante de Pagamento": [
        "comprovante de pagamento", "comprovante pix", "recibo de pagamento",
        "comprovante de transferencia", "transferencia realizada", "pagamento efetuado", "comprovante de agendamento"
    ],
    "Fatura": [
        "fatura de energia", "conta de luz", "fatura claro", "claro fatura",
        "fatura tim", "fatura vivo", "fatura mensal", "fatura do cartao", "fatura cartao", "demonstrativo de fatura"
    ],
    "Boleto Bancário": [
        "boleto bancario", "linha digitavel", "ficha de compensacao", "recibo do pagador", "taxa condominial"
    ],
    "Contrato": [
        "contrato de locacao", "contrato de locação", "locatario", "locatário", "locador",
        "instrumento particular", "termo de quitacao", "termo de rescisao"
    ],
    "Identificação": [
        "comprovante de inscricao no cpf", "cadastro de pessoas fisicas", "cpf",
        "carteira de identidade", "identidade", "rg", "cnh", "passaporte", "identity check"
    ],
    "Procuração": [
        "procuracao", "procuração", "mandatario", "outorgante", "outorgado", "poderes especiais"
    ],
    "Nota Fiscal": [
        "nota fiscal", "danfe", "nf-e", "nfs-e", "documento auxiliar"
    ],
    "Extrato Bancário": [
        "extrato de conta", "extrato bancario", "extrato de custodia", "extrato mensal"
    ],
    "Certificado": [
        "certificado de vacinacao", "certificado nacional", "certificado de conclusao", "diploma"
    ]
}

ORGANIZATION_RULES: Dict[str, List[str]] = {
    "Receita Federal": [
        "secretaria da receita federal", "receita federal", "ministerio da fazenda", "dirpf", "irpf", "darf", "e-cac"
    ],
    "Nubank": [
        "nu pagamentos s.a.", "nu pagamentos", "nu financeiras", "nubank"
    ],
    "Itaú": [
        "banco itau unibanco", "itau unibanco", "banco itau", "banco itaú", "itau", "itaú"
    ],
    "Bradesco": [
        "banco bradesco", "bradesco"
    ],
    "Banco do Brasil": [
        "banco do brasil s.a.", "banco do brasil"
    ],
    "Santander": [
        "banco santander", "santander"
    ],
    "Inter": [
        "banco inter", "inter"
    ],
    "XP Investimentos": [
        "xp investimentos", "xp cctvm", "xp corretora", "xpml11"
    ],
    "Clear Corretora": [
        "clear corretora", "clear cctvm"
    ],
    "BTG Pactual": [
        "btg pactual", "btg"
    ],
    "Light": [
        "light servicos de eletricidade", "light serviços de eletricidade", "light s.a.", "light"
    ],
    "Claro": [
        "claro s.a.", "claro telecom", "claro internet", "claro"
    ],
    "Prefeitura do Rio de Janeiro": [
        "prefeitura da cidade do rio de janeiro", "prefeitura do rio", "iptu", "darm"
    ],
    "Condomínio Barata Ribeiro": [
        "condominio barata ribeiro", "condomínio barata ribeiro", "barata ribeiro", "barata 726", "barata 301"
    ],
    "QuintoAndar": [
        "quinto andar", "quintoandar"
    ],
    "Mercado Pago": [
        "mercado pago", "mercadopago"
    ],
    "Google": [
        "google brasil", "google"
    ],
    "Apple": [
        "apple brasil", "apple"
    ]
}

TAG_DOMAIN_RULES: Dict[str, List[str]] = {
    "Financeiro": ["banco", "pagamento", "transferencia", "pix", "fatura", "boleto", "valor", "reais", "custodia", "saldo"],
    "Impostos": ["receita federal", "irpf", "dirpf", "darf", "imposto", "restituicao", "tributavel", "iptu"],
    "Investimentos": ["corretagem", "custodia", "fii", "acoes", "rendimentos", "xp", "clear", "dividendos"],
    "Habitação": ["condominio", "aluguel", "locacao", "energia", "luz", "light", "iptu", "gas"],
    "Telecom": ["claro", "tim", "vivo", "internet", "fibra", "telecom", "celular"],
    "Pessoal": ["identidade", "rg", "cpf", "cnh", "passaporte", "vacinacao", "certidao"],
    "Jurídico": ["procuracao", "contrato", "processo", "advogado", "juizo", "mandato"],
    "Saúde": ["vacina", "vacinacao", "exame", "medico", "hospital", "plano de saude"]
}


@dataclass
class ClassificationResult:
    doc_id: Optional[int]
    title: str
    suggested_correspondent: Optional[str]
    suggested_document_type: Optional[str]
    suggested_tags: List[str]
    extracted_entities: Dict[str, Any]
    confidence: float
    applied: bool = False
    changes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "suggested_correspondent": self.suggested_correspondent,
            "suggested_document_type": self.suggested_document_type,
            "suggested_tags": self.suggested_tags,
            "extracted_entities": self.extracted_entities,
            "confidence": round(self.confidence, 2),
            "applied": self.applied,
            "changes": self.changes,
        }


def _normalize_text(text: str) -> str:
    nfkd = unicodedata.normalize('NFKD', text)
    ascii_text = nfkd.encode('ASCII', 'ignore').decode('utf-8')
    return " ".join(ascii_text.lower().split())


def _matches_pattern(pat: str, text: str) -> bool:
    norm_pat = _normalize_text(pat)
    regex = re.compile(r'(?:^|[\s_\W])' + re.escape(norm_pat) + r'(?:$|[\s_\W])', re.IGNORECASE)
    return bool(regex.search(text))


def classify_text_and_title(
    title: str,
    content: str,
    existing_tags: Optional[List[str]] = None,
    doc_id: Optional[int] = None
) -> ClassificationResult:
    """Infers document type, correspondent, and tags based on title, OCR text, and extracted entities."""
    norm_title = _normalize_text(title)
    norm_content = _normalize_text(content[:4000])
    combined = f"{norm_title} {norm_content}"

    # 1. Extract Entities
    cpfs = extract_cpf(content) or extract_cpf(title)
    cnpjs = extract_cnpj(content) or extract_cnpj(title)
    monetary = extract_monetary_amounts(content) or extract_monetary_amounts(title)
    dates = extract_dates(content) or extract_dates(title)

    extracted_entities = {
        "cpfs": [c.normalized_name for c in cpfs],
        "cnpjs": [c.normalized_name for c in cnpjs],
        "monetary_amounts": [m.name for m in monetary],
        "dates": [d.normalized_name for d in dates],
    }

    # 2. Determine Document Type
    suggested_doc_type: Optional[str] = None
    doc_type_confidence = 0.0

    for dt_name, patterns in DOC_TYPE_RULES.items():
        for pat in patterns:
            if _matches_pattern(pat, norm_title):
                suggested_doc_type = dt_name
                doc_type_confidence = 0.95
                break
            elif _matches_pattern(pat, norm_content) and not suggested_doc_type:
                suggested_doc_type = dt_name
                doc_type_confidence = 0.80
        if suggested_doc_type and doc_type_confidence >= 0.9:
            break

    # 3. Determine Correspondent
    suggested_corr: Optional[str] = None
    corr_confidence = 0.0

    for org_name, patterns in sorted(ORGANIZATION_RULES.items(), key=lambda item: -max(len(p) for p in item[1])):
        for pat in patterns:
            if _matches_pattern(pat, norm_title):
                suggested_corr = org_name
                corr_confidence = 0.95
                break
            elif _matches_pattern(pat, norm_content) and not suggested_corr:
                suggested_corr = org_name
                corr_confidence = 0.85
        if suggested_corr and corr_confidence >= 0.9:
            break

    # 4. Infer Domain Tags
    suggested_tags: Set[str] = set(existing_tags or [])
    for domain_tag, keywords in TAG_DOMAIN_RULES.items():
        for kw in keywords:
            if _matches_pattern(kw, combined):
                suggested_tags.add(domain_tag)
                break

    # Calculate overall confidence
    scores = []
    if suggested_doc_type:
        scores.append(doc_type_confidence)
    if suggested_corr:
        scores.append(corr_confidence)
    overall_confidence = (sum(scores) / len(scores)) if scores else 0.50

    return ClassificationResult(
        doc_id=doc_id,
        title=title,
        suggested_correspondent=suggested_corr,
        suggested_document_type=suggested_doc_type,
        suggested_tags=sorted(list(suggested_tags)),
        extracted_entities=extracted_entities,
        confidence=overall_confidence,
    )
