"""File-type aware ingestion (ADR-13). Importing this package registers the built-in handlers."""

from .base import FormatHandler, HandlerError, ParsedDocument, Section
from .registry import handler_for, register, registered
from . import handlers  # noqa: F401  (registration side effect)
from .chunking import Chunk, chunk_document, coverage_gaps

__all__ = [
    "FormatHandler",
    "HandlerError",
    "ParsedDocument",
    "Section",
    "Chunk",
    "chunk_document",
    "coverage_gaps",
    "handler_for",
    "register",
    "registered",
]
