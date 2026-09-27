#!/usr/bin/env python3
"""
Structured Grammars, Domain RegEx Patterns, and Lexicons (ADR-40 / Chapter 24).
Aegis Sovereign Knowledge Appliance.

Provides pre-compiled domain grammars for Telecom, Pharmacy/ANVISA, Medical/Clinics,
Homelab/Server infrastructure, and anti-hijacking reserved lexicons.
"""

import math
import re
from collections import Counter
from typing import Set


# ---------------------------------------------------------------------------
# Shannon Entropy Calculation
# ---------------------------------------------------------------------------
def calculate_shannon_entropy(text: str) -> float:
    """
    Computes Shannon Entropy in bits for a given text string.
    Formula: H(X) = - sum(P(x) * log2(P(x)))
    """
    if not text:
        return 0.0
    clean = text.strip()
    if not clean:
        return 0.0
    counts = Counter(clean)
    total = len(clean)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


# ---------------------------------------------------------------------------
# Fast-Path Generic Identifiers (Prong 1)
# ---------------------------------------------------------------------------
HEX_PATTERN = re.compile(r'\b(0x[0-9a-fA-F]{4,16})\b')
TICKET_PATTERN = re.compile(
    r'\b([A-Z]{2,6}-\d{2,8}(?:-[A-Z0-9]{1,8})?|[A-Z]{2,6}-[A-Z0-9]{4,12}(?:-[A-Z0-9]{2,12})?)\b'
)
STANDARD_SPEC_PATTERN = re.compile(
    r'\b(3GPP\s+TS\s+\d{2}\.\d{3}|MS\s+\d\.\d{4}\.\d{4}\.\d{3}-\d|CRM-[A-Z]{2}\s+\d{4,7}|CID-10\s+[A-Z]\d{2}(?:\.\d)?)\b'
)
CPF_PATTERN = re.compile(r'\b(\d{3}\.\d{3}\.\d{3}-\d{2})\b')
CNPJ_PATTERN = re.compile(r'\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b')
QUOTED_PHRASE_PATTERN = re.compile(r'"([^"]{2,160})"')


# ---------------------------------------------------------------------------
# Vertical Domain Grammars
# ---------------------------------------------------------------------------

# 1. Telecom Engineering & Academic Libraries
ALARM_ID_PATTERN = re.compile(r'\b(ALM-\d{3,6})\b', re.IGNORECASE)
MML_COMMAND_PATTERN = re.compile(
    r'\b((?:ADD|MOD|RMV|LST|DSP|SET|ACT|DEA|RST|PING|TRC)\s+[A-Z0-9_]{3,20}|NGPING|NGTRACEROUTE)\b'
)
KPI_COUNTER_PATTERN = re.compile(r'\b(VS\.[A-Za-z0-9_.]{5,40})\b')
TELCO_SPEC_PATTERN = re.compile(
    r'\b(3GPP\s+TS\s+\d{2}\.\d{3}(?:\s+v\d+\.\d+\.\d+)?|RFC\s*\d{3,5})\b',
    re.IGNORECASE,
)
ISBN_PATTERN = re.compile(
    r'\b(ISBN(?:-1[03])?:?\s*((?:97[89][-\s]?)?\d{1,5}[-\s]?\d{1,7}[-\s]?\d{1,6}[-\s]?[\dX]))\b',
    re.IGNORECASE,
)

# 2. Pharmacy & ANVISA (pharmacies_and_smb_retail)
LOTE_PATTERN = re.compile(r'\b(LOTE[-:\s]+([A-Z0-9][A-Z0-9\-]{3,20}))\b', re.IGNORECASE)
ANVISA_MS_PATTERN = re.compile(r'\b((?:MS[\s-]*)?(1\.\d{4}\.\d{4}\.\d{3}-\d))\b', re.IGNORECASE)
NFE_CHAVE_PATTERN = re.compile(r'\b(\d{44}|(?:\d{4}[\s-]){10}\d{4})\b')
PORTARIA_344_PATTERN = re.compile(
    r'\b(Lista\s+(A1|A2|A3|B1|B2|C1|C2|C3|C4|C5))\b',
    re.IGNORECASE,
)

# 3. Medical & Boutique Clinics (boutique_medical_and_longevity_clinics)
CID10_PATTERN = re.compile(
    r'(?:(?i:\bCID[-\s]*10?:?\s*([A-TV-Z]\d{2}(?:\.\d)?)\b)|\b([A-TV-Z]\d{2}\.\d)(?!\.\d)\b)'
)
CRM_PATTERN = re.compile(r'\b(CRM[-/\s]*([A-Z]{2})[\s-]*(\d{4,7}))\b', re.IGNORECASE)

# 4. Homelab / Server Infrastructure
ADR_PATTERN = re.compile(r'\b(ADR-\d{1,3})\b', re.IGNORECASE)
SKILL_PATTERN = re.compile(
    r'\b((?:manage|trigger|prowlarr|pihole|nomad|download)-[a-z0-9]+(?:-[a-z0-9]+)+)\b',
    re.IGNORECASE,
)
SKILL_ID_PATTERN = SKILL_PATTERN


# ---------------------------------------------------------------------------
# Bilingual Intent Grammars (Portuguese & English)
# ---------------------------------------------------------------------------
SYNTHESIS_INTENT_PATTERN = re.compile(
    r'\b('
    # Portuguese Triggers
    r'por\s+que|porque|por\s+quê|resuma|resumo|síntese|sintetize|sintetizar|'
    r'explique|explicar|explicação|qual\s+a\s+razão|quais\s+as\s+razões|'
    r'analise|analisar|análise|comparar|compare|diferença\s+entre|'
    r'conclusão|o\s+que\s+significa|descreva|descrever|'
    r'visão\s+geral|panorama\s+geral|tese|macro\s+síntese|'
    r'como\s+funciona|como\s+configurar|como\s+são|quais\s+as\s+regras|quais\s+os\s+requisitos|o\s+que\s+é|'
    # English Triggers
    r'why|explain|explanation|summarize|summary|synthesis|synthesize|'
    r'analyze|analysis|compare|comparison|difference\s+between|'
    r'conclusion|what\s+does\s+.*mean|describe|description|overview|'
    r'macro\s+synthesis|thematic\s+synthesis|executive\s+overview|thesis|'
    r'how\s+does|how\s+are|how\s+to|what\s+are|what\s+is\s+the\s+protocol'
    r')\b',
    re.IGNORECASE,
)

RELATIONAL_INTENT_PATTERN = re.compile(
    r'\b('
    # Portuguese Triggers
    r'relacionamento|relacionamentos|relação|relações|conectado|conexão|conexões|'
    r'ligação|ligações|grafo|hierarquia|proprietário|proprietários|'
    r'participação|participações|estrutura\s+societária|sócio|sócios|'
    r'vínculo|vínculos|rede\s+de|entre\s+.*e\s+.*'
    # English Triggers
    r'|relationship|relationships|relation|relations|connected\s+to|'
    r'connections?\s+between|links?|graph|hierarchy|owner|ownership|'
    r'shareholders?|corporate\s+structure|partners?|network\s+of'
    r')\b',
    re.IGNORECASE,
)

MACRO_SYNTHESIS_PATTERN = re.compile(
    r'\b('
    r'visão\s+geral|panorama\s+geral|tese|macro\s+síntese|estrutura\s+temática|'
    r'análise\s+global|todo\s+o\s+documento|livro\s+completo|todos\s+os\s+capítulos|'
    r'arco\s+narrativo|evolução\s+temática|tema\s+central|ao\s+longo\s+da\s+obra|'
    r'macro\s+synthesis|thematic\s+synthesis|executive\s+overview|thesis|'
    r'overarching\s+theme|narrative\s+arc|central\s+theme|philosophical\s+evolution|'
    r'entire\s+document|whole\s+book|global\s+summary|across\s+all\s+chapters'
    r')\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Anti-Hijacking Reserved Lexicon & Conceptual Lexicon
# ---------------------------------------------------------------------------
RESERVED_LEXICON: Set[str] = {
    # Tax & Finance (PT-BR & Global)
    "TAX", "IRPF", "DIRPF", "DARF", "DAS", "PIS", "COFINS", "CSLL", "ICMS", "ISS", "IOF", "INSS",
    "BACEN", "CDI", "SELIC", "IPCA", "IGPM", "TED", "PIX", "CVM", "DRE", "EBITDA", "ROI", "ROE",
    # Corporate & Executive
    "CEO", "CFO", "COO", "CTO", "CIO", "CRO", "CMO", "CLO", "CHRO", "BOD", "VP", "SVP", "EVP",
    # Legal, Compliance & Regulatory
    "LGPD", "GDPR", "HIPAA", "SOX", "PCI", "SEC", "DOJ", "OAB", "STF", "STJ", "TRF", "TST", "CLT",
    "LAW", "WAR", "ACT", "DOD", "DLP", "MAC", "RBAC", "SLA", "NDA", "MOU", "LOI",
    # Technical & Computing
    "API", "CPU", "GPU", "RAM", "SSD", "HDD", "NVME", "SQL", "NOSQL", "RAG", "LLM", "NLP", "OCR",
    "WAL", "BFS", "DFS", "HTTP", "HTTPS", "REST", "JSON", "YAML", "HTML", "CSS", "DNS", "TLS",
    "TCP", "UDP", "SSH", "BFF", "SDK", "CLI", "UI", "UX", "HNSW", "RRF", "ONNX", "AVX",
    # Common Short Linguistic Particles & Stopwords
    "THE", "AND", "FOR", "NOT", "YES", "WHY", "HOW", "WHO", "WHAT", "WHEN", "QUE", "COM", "SEM",
    "POR", "PARA", "MAS", "SIM", "VER", "DOC", "PDF", "USA", "BRA",
}

CONCEPTUAL_LEXICON: Set[str] = {
    # Architecture, Topology & Homelab
    "ARCHITECTURE", "TOPOLOGY", "CONTAINER", "CLUSTER", "DEVICES", "FAILOVER", "REDUNDANCY",
    "POLICIES", "PROCEDURES", "METRICS", "TELEMETRY", "SECURITY", "GOVERNANCE", "ORCHESTRATION",
    "MONITORING", "BACKUP", "PIPELINE", "MIGRATION", "INGRESS", "ROUTER", "STORAGE", "VIRTUALIZATION",
    "CONSENSUS", "DISCOVERY", "SYNTHESIS", "RUNBOOK", "COMMISSIONING", "PREREQUISITES", "RECOVERY",
    "RESILIENCE", "INFRASTRUCTURE", "PROVISIONING", "REVERSE_PROXY", "TRAEFIK", "NOMAD", "ANSIBLE",
    "GITOPS", "OBSERVABILITY", "AUDIT", "SENSOR", "FLEET", "SELF_HEAL", "SELF_HEALING",
}


__all__ = [
    "calculate_shannon_entropy",
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
    "RESERVED_LEXICON",
    "CONCEPTUAL_LEXICON",
]
