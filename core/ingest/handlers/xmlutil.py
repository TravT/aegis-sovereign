"""Small XML helpers shared by the handlers."""

from __future__ import annotations

import re

from ..base import HandlerError

_ENTITY = re.compile(rb"<!ENTITY", re.IGNORECASE)


def guard_xml(raw: bytes) -> bytes:
    """Reject entity declarations (billion-laughs / external entity attacks) before parsing."""
    if _ENTITY.search(raw[:200_000]):
        raise HandlerError("entity declarations are not allowed in XML input")
    return raw


def local(tag: str) -> str:
    """Element name without its namespace."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag
