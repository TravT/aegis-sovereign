"""Pluggable structure extraction (ADR-12). Importing this package registers the built-in extractors."""

from .base import (
    RECORD_KINDS,
    Assignment,
    NoExtractorError,
    Node,
    RecordView,
    StructureError,
    StructureExtractor,
    Tree,
)
from .registry import extractor_for, register, registered
from . import hedex, pathtree  # noqa: F401  (registration side effect)
from .policy import PROFILES, SizePolicy, chunk_spans, chunk_text, collapse_by_topic, get_profile
from .runner import apply_structure, build_extractors

__all__ = [
    "RECORD_KINDS",
    "Assignment",
    "NoExtractorError",
    "Node",
    "RecordView",
    "StructureError",
    "StructureExtractor",
    "Tree",
    "extractor_for",
    "register",
    "registered",
    "PROFILES",
    "SizePolicy",
    "chunk_spans",
    "chunk_text",
    "collapse_by_topic",
    "get_profile",
    "apply_structure",
    "build_extractors",
]
