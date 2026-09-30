"""
Conformance harness: the automatic gate every file-type handler must pass (ADR-13).

A handler is "done" when `check_handler` returns no problems for representative fixtures, so
adding a format is bounded work: write the handler, add a fixture, run this. It checks that a
handler is

  * lossless   — every character of every section reaches at least one chunk (proved from the
                 chunk source spans, not sampled);
  * deterministic — parsing the same bytes twice gives identical sections;
  * bounded    — no chunk exceeds the tier's chunk size; chunk numbering is contiguous and unique;
  * well-formed — section paths are tuples of non-empty strings, no whitespace-only sections;
  * robust     — empty, truncated, garbage and bit-flipped input raise HandlerError or return a
                 document, never any other exception.
"""

from __future__ import annotations

import random
from typing import List

from core.structure.policy import SizePolicy

from .base import FormatHandler, HandlerError
from .chunking import chunk_document, coverage_gaps


def check_handler(handler: FormatHandler, name: str, data: bytes, policy: SizePolicy, fuzz: bool = True) -> List[str]:
    problems: List[str] = []
    try:
        doc = handler.parse(name, data)
    except HandlerError as exc:
        return [f"fixture rejected by handler: {exc}"]
    except Exception as exc:  # noqa: BLE001 - any other exception is a conformance failure
        return [f"parse raised {type(exc).__name__}: {exc}"]

    again = handler.parse(name, data)
    if [(s.path, s.text, s.locator, s.kind) for s in doc.sections] != [(s.path, s.text, s.locator, s.kind) for s in again.sections]:
        problems.append("not deterministic: two parses of the same bytes differ")

    for i, s in enumerate(doc.sections):
        if not isinstance(s.path, tuple) or any((not isinstance(p, str)) or not p.strip() for p in s.path):
            problems.append(f"section {i}: path must be a tuple of non-empty strings, got {s.path!r}")
        if not s.text.strip():
            problems.append(f"section {i}: whitespace-only text")

    chunks = chunk_document(doc, policy)
    gaps = coverage_gaps(doc, chunks)
    if gaps:
        problems.append(f"not lossless: {len(gaps)} uncovered range(s), first {gaps[0]}")
    if [c.index for c in chunks] != list(range(len(chunks))) or len({c.suffix for c in chunks}) != len(chunks):
        problems.append("chunk numbering is not contiguous and unique")
    too_big = [c.index for c in chunks if len(c.content) > policy.chunk_chars + 1]
    if too_big:
        problems.append(f"{len(too_big)} chunk(s) exceed chunk_chars={policy.chunk_chars} (first index {too_big[0]})")
    if doc.total_chars and not chunks:
        problems.append("document has text but produced no chunks")

    if fuzz:
        rnd = random.Random(1234)
        flipped = bytearray(data)
        for _ in range(min(8, len(flipped))):
            flipped[rnd.randrange(len(flipped))] ^= 0xFF
        garbage = bytes(rnd.randrange(256) for _ in range(512))
        for label, blob in (
            ("empty", b""),
            ("truncated to half", data[: len(data) // 2]),
            ("truncated to 64 bytes", data[:64]),
            ("garbage", garbage),
            ("bit-flipped", bytes(flipped)),
        ):
            try:
                handler.parse(name, blob)
            except HandlerError:
                pass
            except Exception as exc:  # noqa: BLE001
                problems.append(f"robustness ({label}): raised {type(exc).__name__}, expected HandlerError")
    return problems
