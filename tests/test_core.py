#!/usr/bin/env python3
"""
Comprehensive Unit & Integration Test Suite for Aegis Sovereign Knowledge Appliance.
Tests chunking, graph extraction, SQLite WAL graph store, classification,
action dispatching, hybrid RRF search fusion, and context condenser token economics.
"""

import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure aegis-sovereign-appliance is on path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from core.chunker import (
    Chunk,
    MarkdownChunk,
    parse_frontmatter,
    split_into_header_sections,
    parse_and_chunk_markdown,
    dynamic_syntactic_chunk_text,
)
from core.graph.extractor import (
    extract_cpf,
    extract_cnpj,
    extract_monetary_amounts,
    extract_dates,
    extract_services,
    extract_ips_and_ports,
    extract_wiki_entities,
    extract_paperless_entities,
)
from core.graph.store import GraphStore
from core.classifier.rules import classify_text_and_title
from core.dispatcher.actions import (
    DocumentAction,
    ActionEvaluator,
    ActionDispatcher,
    extract_due_dates,
    extract_max_monetary_amount,
)
from core.search.searcher import reciprocal_rank_fusion
from core.proxy.context_condenser import ContextCondenser, OptimizationResult


class MockSearcher:
    """Mock searcher to test ContextCondenser without needing remote Qdrant daemon."""
    def __init__(self, hits=None):
        self.hits = hits or []

    def search(self, query, limit=5, collection_name=None, retrieval_mode="high_precision", confidence_floor=0.0):
        return self.hits[:limit]


# ==============================================================================
# 1. Chunker Tests
# ==============================================================================

def test_parse_frontmatter():
    doc = """---
title: Test Document
tags: [legal, finance]
last_reviewed: 2026-09-18
---
# First Header
Body text goes here.
"""
    meta, body, offset = parse_frontmatter(doc)
    assert meta["title"] == "Test Document"
    assert "legal" in meta["tags"]
    assert offset == 5
    assert "# First Header" in body


def test_split_into_header_sections():
    body = """# Section 1
Content 1

## Section 1.1
Content 1.1

# Section 2
Content 2
"""
    sections = split_into_header_sections(body, line_offset=0)
    assert len(sections) == 3
    assert sections[0]["header"] == "Section 1"
    assert sections[1]["header"] == "Section 1.1"
    assert sections[2]["header"] == "Section 2"


def test_parse_and_chunk_markdown():
    doc = """---
title: Architecture Spec
tags: [spec, test]
---
# Executive Summary
This is the sovereign appliance architecture.

## Deployment Details
Deploying across local nodes without cloud egress.
"""
    chunks = parse_and_chunk_markdown(doc, "spec.md")
    assert len(chunks) >= 2
    assert chunks[0].doc_title == "Architecture Spec"
    assert "spec" in chunks[0].tags
    assert chunks[0].boundary_type in ("header", "paragraph", "clause", "math_preserved")
    assert chunks[0].token_estimate > 0


def test_dynamic_syntactic_clause_boundary_chunking():
    """
    Validates Chapter 24 Dynamic Syntactic Clause-Boundary Windowing:
    - Snaps cleanly at paragraph and clause/sentence boundaries (; or .) instead of mid-word/mid-thought.
    - Enforces target token window (128 to 400 tokens) and 64-token sliding overlap.
    - Populates boundary_type and token_estimate on Chunk dataclass.
    """
    clause_1 = (
        "Cláusula Primeira: O presente instrumento regula a custódia e escrituração digital "
        "dos medicamentos sujeitos a controle especial da Portaria SVS/MS nº 344/1998; "
        "todas as movimentações de estoque devem ser registradas no SNGPC sem atraso. "
    ) * 4
    clause_2 = (
        "Cláusula Segunda: Em caso de divergência de inventário físico entre o lote físico "
        "e a nota fiscal eletrônica, o farmacêutico responsável técnico deverá bloquear "
        "imediatamente a comercialização do lote afetado; a auditoria interna será acionada. "
    ) * 4

    long_text = f"{clause_1}\n\n{clause_2}"
    chunks = dynamic_syntactic_chunk_text(
        long_text,
        min_tokens=128,
        max_tokens=300,
        overlap_tokens=64,
        doc_title="POP Farmácia",
        filepath="pop_farmacia.md",
    )
    assert len(chunks) >= 2
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.boundary_type in ("header", "paragraph", "clause", "math_preserved")
        assert c.token_estimate > 0
        # Ensure no mid-word spectral leakage at the end of non-final chunks
        assert c.raw_content[-1] in (".", ";", "!", "?", "$", "`") or c.boundary_type in ("paragraph", "header")


def test_latex_math_and_code_block_preservation():
    """
    Validates that LaTeX display math blocks ($$\\iint_S (\\nabla \\times \\mathbf{F}) \\cdot d\\mathbf{S}$$)
    and fenced code blocks (```...```) are NEVER split mid-block across chunk boundaries.
    """
    stokes_equation = (
        "$$\n"
        "\\iint_S (\\nabla \\times \\mathbf{F}) \\cdot d\\mathbf{S} = "
        "\\oint_{\\partial S} \\mathbf{F} \\cdot d\\mathbf{r} + "
        "\\int_0^{2\\pi} \\int_0^R r^3 \\cos^2(\\theta) \\, dr \\, d\\theta\n"
        "$$"
    )
    preamble = (
        "In vector calculus, Stokes' Theorem relates the surface integral of the curl of a vector "
        "field over a surface S in Euclidean three-space to the line integral of the vector field "
        "over its boundary. This foundational theorem generalizes Green's theorem; "
    ) * 3
    postamble = (
        "Furthermore, the divergence theorem relates the flux of a vector field through a closed "
        "surface to the divergence of the field in the volume enclosed. Every oriented smooth surface "
        "must preserve orientation consistency across boundary parameterizations."
    ) * 3

    doc = f"# Vector Calculus Chapter 16\n\n{preamble}\n\n{stokes_equation}\n\n{postamble}"
    # Choose a max_chunk_chars that lands right around the Stokes equation block
    chunks = parse_and_chunk_markdown(doc, filepath="stewart_calculus.md", max_chunk_chars=650)
    assert len(chunks) >= 2

    # Verify the entire Stokes' Theorem display math block is preserved 100% intact in at least one chunk
    math_chunks = [c for c in chunks if "\\iint_S (\\nabla \\times \\mathbf{F}) \\cdot d\\mathbf{S}" in c.raw_content]
    assert len(math_chunks) >= 1
    for mc in math_chunks:
        assert mc.raw_content.count("$$") >= 2
        assert stokes_equation in mc.raw_content
        assert mc.boundary_type == "math_preserved"



# ==============================================================================
# 2. Graph Extractor Tests
# ==============================================================================

def test_entity_extractors():
    sample_text = """
    Contrato assinado por João Silva, CPF 123.456.789-00,
    representando a empresa Alfa Ltda, CNPJ 12.345.678/0001-90.
    Valor mensal fixado em R$ 4.500,50 com vencimento em 2026-10-15.
    Conectado ao servidor traefik rodando em 192.168.1.100:443.
    """
    cpfs = extract_cpf(sample_text)
    assert len(cpfs) == 1
    assert cpfs[0].name == "123.456.789-00"

    cnpjs = extract_cnpj(sample_text)
    assert len(cnpjs) == 1
    assert cnpjs[0].name == "12.345.678/0001-90"

    amounts = extract_monetary_amounts(sample_text)
    assert len(amounts) == 1
    assert amounts[0].metadata["value"] == 4500.50

    dates = extract_dates(sample_text)
    assert any(d.normalized_name == "2026-10-15" for d in dates)

    services = extract_services(sample_text)
    assert any(s.normalized_name == "traefik" for s in services)

    ips, ports, ip_rels = extract_ips_and_ports(sample_text)
    assert any(i.name == "192.168.1.100" for i in ips)
    assert any(p.name == "443" for p in ports)
    assert len(ip_rels) >= 1


# ==============================================================================
# 3. Graph Store Tests (In-Memory SQLite)
# ==============================================================================

def test_graph_store_lifecycle():
    store = GraphStore(db_path=":memory:")

    # Index document with entities and relations
    doc_id = store.index_document(
        corpus="legal",
        doc_identifier="contrato_01.pdf",
        title="Contrato de Locação",
        created_date="2026-09-15",
        url="archive://contrato_01.pdf",
        entities=[
            {"name": "Alfa Ltda", "entity_type": "correspondent", "normalized_name": "alfa ltda"},
            {"name": "12.345.678/0001-90", "entity_type": "cnpj", "normalized_name": "12.345.678/0001-90"},
            {"name": "R$ 4.500,00", "entity_type": "monetary", "normalized_name": "R$ 4.500,00"},
            {"name": "2026-09-15", "entity_type": "date", "normalized_name": "2026-09-15"},
        ],
        relations=[
            {"source": "Alfa Ltda", "target": "12.345.678/0001-90", "relation_type": "has_cnpj"}
        ]
    )
    assert doc_id == 1

    # Traverse neighborhood
    neighborhood = store.get_entity_neighborhood("Alfa Ltda", max_depth=1)
    assert neighborhood["entity"]["name"] == "Alfa Ltda"
    assert len(neighborhood["neighbors"]) >= 1
    assert neighborhood["neighbors"][0]["entity"]["name"] == "12.345.678/0001-90"

    # Compile dossier
    dossier = store.compile_dossier("Alfa Ltda")
    assert dossier["entity"]["name"] == "Alfa Ltda"
    assert dossier["total_documents"] == 1
    assert dossier["total_monetary_amount"] == 4500.00
    assert len(dossier["dates"]) == 1

    # Check stats
    stats = store.get_entity_statistics()
    assert stats["total_documents"] == 1
    assert stats["total_entities"] == 4
    assert stats["total_relations"] == 1

    store.close()


# ==============================================================================
# 4. Classifier Tests
# ==============================================================================

def test_classifier_rules():
    title = "recibo de entrega da declaracao de ajuste anual 2026.pdf"
    content = """
    SECRETARIA DA RECEITA FEDERAL DO BRASIL
    Declaração de Ajuste Anual do Imposto sobre a Renda
    Exercício 2026
    CPF: 111.222.333-44
    Total de rendimentos tributáveis: R$ 120.000,00
    """
    result = classify_text_and_title(title=title, content=content)
    assert result.suggested_document_type == "Declaração de Imposto de Renda"
    assert result.suggested_correspondent == "Receita Federal"
    assert "Impostos" in result.suggested_tags
    assert "111.222.333-44" in result.extracted_entities["cpfs"]
    assert result.confidence >= 0.85


# ==============================================================================
# 5. Action Dispatcher Tests
# ==============================================================================

def test_action_evaluator():
    today = datetime.date(2026, 10, 1)
    evaluator = ActionEvaluator(current_date=today)

    # Overdue bill
    doc_overdue = {
        "id": 101,
        "title": "Fatura Light",
        "content": "Valor: R$ 350,00. Vencimento em: 25/09/2026",
        "correspondent": "Light"
    }
    actions = evaluator.evaluate_document(doc_overdue)
    assert any(a.action_type == "OVERDUE_BILL" for a in actions)

    # Bill due soon
    doc_soon = {
        "id": 102,
        "title": "Boleto Condomínio",
        "content": "Pagar até 03/10/2026. Valor R$ 1.500,00",
        "correspondent": "Condomínio Barata Ribeiro"
    }
    actions_soon = evaluator.evaluate_document(doc_soon)
    assert any(a.action_type == "BILL_DUE_SOON" for a in actions_soon)
    assert any(a.action_type == "HIGH_VALUE_PAYMENT" for a in actions_soon)


def test_action_dispatcher_deduplication():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        temp_path = Path(tf.name)

    try:
        dispatcher = ActionDispatcher(state_file=temp_path)
        action = DocumentAction(
            doc_id=201,
            action_type="OVERDUE_BILL",
            severity="CRITICAL",
            title="Conta Vencida",
            message="Overdue payment",
            amount=500.0,
            due_date="2026-09-20"
        )

        # First dispatch
        res1 = dispatcher.dispatch([action])
        assert len(res1) == 1

        # Second dispatch (must be deduplicated and skipped)
        res2 = dispatcher.dispatch([action])
        assert len(res2) == 0

    finally:
        if temp_path.exists():
            temp_path.unlink()


# ==============================================================================
# 6. Hybrid Search RRF Tests
# ==============================================================================

def test_reciprocal_rank_fusion():
    dense_hits = [
        {"id": "doc1", "score": 0.95, "payload": {"title": "Doc 1"}},
        {"id": "doc2", "score": 0.85, "payload": {"title": "Doc 2"}},
    ]
    sparse_hits = [
        {"id": "doc2", "score": 12.5, "payload": {"title": "Doc 2"}},
        {"id": "doc3", "score": 10.0, "payload": {"title": "Doc 3"}},
    ]

    fused = reciprocal_rank_fusion(dense_hits, sparse_hits, k=60)
    assert len(fused) == 3
    # doc2 appeared in both dense and sparse, should be ranked first
    assert fused[0]["id"] == "doc2"
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"]


# ==============================================================================
# 7. Context Condenser Tests
# ==============================================================================

def test_context_condenser_token_economics():
    mock_hits = [
        {
            "id": "p1",
            "rrf_score": 0.032,
            "payload": {
                "doc_title": "Tax Report",
                "file_path": "/docs/tax.md",
                "heading": "Deductions",
                "text": "Total deductible medical expenses: R$ 15.000,00."
            }
        }
    ]
    mock_searcher = MockSearcher(hits=mock_hits)
    condenser = ContextCondenser(searcher=mock_searcher, baseline_raw_tokens=25000)

    result = condenser.optimize(query="medical expenses", max_chunks=1)
    assert result.verified_evidence_chunks == 1
    assert "Tax Report" in result.citations[0]["title"]
    assert result.token_economics["raw_archive_tokens"] == 25000
    assert result.token_economics["optimized_input_tokens"] < 100
    assert float(result.token_economics["real_world_token_reduction_pct"].rstrip("%")) > 95.0
