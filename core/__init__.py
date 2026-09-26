"""
Aegis Sovereign Knowledge Appliance — Core Engine
100% Air-Gapped | FastEmbed ONNX int8 | GraphRAG SQLite WAL | Context Optimization
"""

from .chunker import parse_frontmatter, split_into_header_sections, parse_and_chunk_markdown, MarkdownChunk
try:
    from .indexer.dual_encoder import SovereignIndexer
except ImportError:
    SovereignIndexer = None  # type: ignore
try:
    from .search.searcher import SovereignSearcher, reciprocal_rank_fusion
except ImportError:
    SovereignSearcher = None  # type: ignore
    reciprocal_rank_fusion = None  # type: ignore
try:
    from .proxy.context_condenser import ContextCondenser, OptimizationResult
except ImportError:
    ContextCondenser = None  # type: ignore
    OptimizationResult = None  # type: ignore
from .graph.store import GraphStore
from .graph.extractor import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    extract_cpf,
    extract_cnpj,
    extract_monetary_amounts,
    extract_dates,
    extract_services,
    extract_ips_and_ports,
)
from .graph.indexer import GraphIndexer
from .classifier.rules import ClassificationResult, classify_text_and_title
from .dispatcher.actions import DocumentAction, ActionEvaluator, ActionDispatcher

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "parse_frontmatter",
    "split_into_header_sections",
    "parse_and_chunk_markdown",
    "MarkdownChunk",
    "SovereignIndexer",
    "SovereignSearcher",
    "reciprocal_rank_fusion",
    "ContextCondenser",
    "OptimizationResult",
    "GraphStore",
    "ExtractedEntity",
    "ExtractedRelation",
    "ExtractionResult",
    "extract_cpf",
    "extract_cnpj",
    "extract_monetary_amounts",
    "extract_dates",
    "extract_services",
    "extract_ips_and_ports",
    "GraphIndexer",
    "ClassificationResult",
    "classify_text_and_title",
    "DocumentAction",
    "ActionEvaluator",
    "ActionDispatcher",
]
