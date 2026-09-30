"""Registry of file-type handlers, ordered by priority (lower first)."""

from __future__ import annotations

from typing import List, Optional, Type

from .base import FormatHandler

_REGISTRY: List[Type[FormatHandler]] = []


def register(cls: Type[FormatHandler]) -> Type[FormatHandler]:
    if cls not in _REGISTRY:
        _REGISTRY.append(cls)
        _REGISTRY.sort(key=lambda c: (c.priority, c.name))
    return cls


def registered() -> List[str]:
    return [c.name for c in _REGISTRY]


def handler_for(name: str, head: bytes = b"") -> Optional[FormatHandler]:
    """First registered handler that recognises the file, or None (caller reports it as unsupported)."""
    for cls in _REGISTRY:
        if cls.detect(name, head):
            return cls()
    return None
