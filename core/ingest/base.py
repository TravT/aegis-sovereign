"""
File-type handler contract (ADR-13).

A *format handler* turns the bytes of ONE file into a structured, lossless `ParsedDocument`:
a list of `Section`s, each carrying its heading path, its text and (for tabular data) row
locators. Handlers know their file type deeply (Word heading styles, Excel merged headers,
BIFF8 records, WSDL operations...) and nothing about databases, tiers or chunk sizes; the shared
chunker and pipeline do the rest. Every handler is deterministic, stdlib-only and must pass
`core.ingest.conformance.check_handler` (lossless, deterministic, bounded, corrupt-input safe).
"""

from __future__ import annotations

import abc
import functools
import posixpath
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Tuple


class HandlerError(Exception):
    """The file cannot be read by this handler (corrupt, encrypted, unsupported variant)."""


# Everything a corrupt or hostile file can make a parser raise. The base class converts these to
# HandlerError so a bad file is reported and skipped, never allowed to crash an ingestion run.
_CORRUPT_INPUT = (
    zlib.error, zipfile.BadZipFile, EOFError, OSError, ValueError, UnicodeError,
    ET.ParseError, struct.error, IndexError, KeyError, OverflowError, RecursionError, MemoryError,
)


def _guarded(parse):
    @functools.wraps(parse)
    def wrapper(self, name, data):
        try:
            return parse(self, name, data)
        except HandlerError:
            raise
        except _CORRUPT_INPUT as exc:
            raise HandlerError(f"{type(exc).__name__}: {exc}") from exc

    wrapper._guarded = True
    return wrapper


@dataclass(frozen=True)
class Section:
    """One contiguous piece of a document under a heading path.

    path        heading path from the document root, e.g. ("Installing", "Prerequisites")
    text        the section's full text, newline separated (never truncated)
    locator     where it lives in the source ("sheet:Alarms", "slide 4", "" for prose)
    kind        "text" | "rows"; "rows" sections hold one spreadsheet row per line, each starting
                with its row number and a colon ("12: Header: value | ..."), which the chunker
                turns into "rows 12-40" locators
    """

    path: Tuple[str, ...]
    text: str
    locator: str = ""
    kind: str = "text"


@dataclass
class ParsedDocument:
    name: str  # file name (last path component)
    format: str  # handler name
    title: str
    sections: List[Section] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def total_chars(self) -> int:
        return sum(len(s.text) for s in self.sections)


class FormatHandler(abc.ABC):
    name: ClassVar[str]
    version: ClassVar[str] = "1"
    extensions: ClassVar[Tuple[str, ...]] = ()
    priority: ClassVar[int] = 100  # lower is tried first

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        parse = cls.__dict__.get("parse")
        if parse is not None and not getattr(parse, "_guarded", False):
            cls.parse = _guarded(parse)  # type: ignore[method-assign]

    @classmethod
    def detect(cls, name: str, head: bytes) -> bool:
        """Cheap check from the file name and the first bytes. Default: extension match."""
        return posixpath.splitext(name.lower())[1] in cls.extensions

    @abc.abstractmethod
    def parse(self, name: str, data: bytes) -> ParsedDocument:
        """Parse the whole file. Raise HandlerError (only) when it cannot be read."""

    @staticmethod
    def title_from(name: str) -> str:
        base = posixpath.basename(name)
        return posixpath.splitext(base)[0] or base
