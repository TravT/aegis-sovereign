"""Registry of structure extractors, ordered by priority (lower first)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Type

from .base import NoExtractorError, StructureExtractor

_REGISTRY: List[Type[StructureExtractor]] = []


def register(cls: Type[StructureExtractor]) -> Type[StructureExtractor]:
    """Class decorator: make an extractor discoverable. Re-registering a class is a no-op."""
    if cls not in _REGISTRY:
        _REGISTRY.append(cls)
        _REGISTRY.sort(key=lambda c: (c.priority, c.name))
    return cls


def registered() -> List[str]:
    return [c.name for c in _REGISTRY]


def extractor_for(source: Path, label: str) -> StructureExtractor:
    """Instantiate the first registered extractor that recognises `source`."""
    source = Path(source)
    for cls in _REGISTRY:
        if cls.detect(source):
            return cls(source, label)
    raise NoExtractorError(f"no structure extractor recognises {source} (registered: {registered()})")
