"""D4 prototype: D3 streamer + memoised derived views in inspect_archive (OUTSIDE the repo).

inspect_archive() recomputes, on EVERY call, three things over the FULL member text even when the
caller only wants an 8000-char page: `_extract_structured_sections(content)`, the lower-cased copy
used by `section_filter`, and `_detect_and_parse_markdown_tables(content)`. With D3 the text itself
comes from the entry LRU, so paging request N only needs a slice; D4 memoises those derived views
(keyed by the content string, bounded LRU) so later pages / section jumps are pure slicing.

Why not decode the member "in chunks" for char_offset paging: the response contract carries
`structured_sections` and `has_table`/`table_headers` of the WHOLE document, `section_filter`
searches the whole text, and `_clean_markup_text` runs regexes (<script>...</script>) across the
whole document; a chunked decoder therefore cannot produce identical output. Memoising the full
derived view is the behaviour-preserving way to make later pages O(page).

The virtual_uri branch below is a copy of core/server/archive_inspector.py:70-248 with the memo
inserted; every other branch (archive_path listing, diagrams, ingest) delegates to the original.
"""

from __future__ import annotations

import collections
import hashlib
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.server.archive_inspector import ArchiveInspector
from core.server.constants import _detect_and_parse_markdown_tables, _extract_structured_sections


class _DerivedMemo:
    def __init__(self, budget_chars: int = 16 << 20):
        self.budget = budget_chars
        self._d: "collections.OrderedDict[str, Dict[str, Any]]" = collections.OrderedDict()
        self._chars = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, content: str) -> Dict[str, Any]:
        with self._lock:
            v = self._d.get(content)
            if v is not None:
                self._d.move_to_end(content)
                self.hits += 1
                return v
        self.misses += 1
        v = {
            "structured_sections": _extract_structured_sections(content),
            "table_info": _detect_and_parse_markdown_tables(content),
            "low": None,  # lower-cased text, built lazily on the first section_filter
            "sf": {},
        }
        with self._lock:
            if len(content) * 2 <= self.budget and content not in self._d:
                self._d[content] = v
                self._chars += len(content)
                while self._chars * 2 > self.budget and self._d:
                    k, _ = self._d.popitem(last=False)
                    self._chars -= len(k)
        return v


class InspectorD4(ArchiveInspector):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.memo = _DerivedMemo()

    def inspect_archive(self, archive_path: str = "", virtual_uri: str = "", query: str = "", ingest: bool = False,
                        section_filter: str = "", extract_diagram_to_artifact: bool = False, char_offset: int = 0,
                        max_chars: int = 8000) -> Dict[str, Any]:
        entry_guess = virtual_uri.split("#", 1)[1] if "#" in virtual_uri else ""
        if (not virtual_uri or ingest or extract_diagram_to_artifact
                or entry_guess.lower().endswith((".png", ".jpg", ".gif"))):
            return super().inspect_archive(archive_path, virtual_uri, query, ingest, section_filter,
                                           extract_diagram_to_artifact, char_offset, max_chars)

        default_hua_dir = "/home/tlima/Enterprise_Hub/docs/Hua_Docs"
        if "/tmp/docs_rag_gemini" in archive_path and not Path("/tmp/docs_rag_gemini").exists() and Path(default_hua_dir).exists():
            archive_path = archive_path.replace("/tmp/docs_rag_gemini", default_hua_dir)
        if "/tmp/docs_rag_gemini" in virtual_uri and not Path("/tmp/docs_rag_gemini").exists() and Path(default_hua_dir).exists():
            virtual_uri = virtual_uri.replace("/tmp/docs_rag_gemini", default_hua_dir)

        content_txt = ""
        title_txt = ""
        comp_size = 0
        uncomp_size = 0
        comp_ratio = 3.0
        sha_hash = ""
        arch_p = archive_path or virtual_uri.split("#", 1)[0].removeprefix("archive://")
        entry_n = virtual_uri.split("#", 1)[1] if "#" in virtual_uri else ""
        try:
            cur = self.router._conn.cursor()
            cur.execute(
                "SELECT title, content FROM document_records WHERE doc_identifier = ? OR doc_identifier = ? OR metadata LIKE ?",
                (virtual_uri, virtual_uri.replace(default_hua_dir, "/tmp/docs_rag_gemini"), f"%{virtual_uri}%"),
            )
            row = cur.fetchone()
            if row and row[1]:
                title_txt = row[0] or ""
                content_txt = row[1]
        except Exception:
            pass
        if not entry_n and Path(arch_p).is_file() and Path(arch_p).suffix.lower() in (".md", ".txt", ".json", ".yaml", ".yml", ".html"):
            try:
                raw_file_txt = Path(arch_p).read_text(encoding="utf-8", errors="replace")
                if len(raw_file_txt) > len(content_txt):
                    content_txt = raw_file_txt
                title_txt = title_txt or Path(arch_p).name
                entry_n = Path(arch_p).name
            except Exception:
                pass
        try:
            entry = self.archive_streamer.resolve_virtual_uri(virtual_uri)
            if len(entry.content_text) > len(content_txt):
                content_txt = entry.content_text
            comp_size = entry.compressed_size
            uncomp_size = entry.uncompressed_size
            comp_ratio = round(entry.compression_ratio, 2)
            sha_hash = entry.sha256_hash
            arch_p = entry.archive_path
            entry_n = entry.entry_name
        except Exception:
            if not content_txt:
                raise
            raw_b = content_txt.encode("utf-8", errors="replace")
            uncomp_size = len(raw_b)
            comp_size = max(256, uncomp_size // 3)
            sha_hash = hashlib.sha256(raw_b).hexdigest()

        derived = self.memo.get(content_txt)
        structured_sections = derived["structured_sections"]
        sliced_txt = content_txt
        if section_filter:
            sf_low = section_filter.strip().lower()
            idx = derived["sf"].get(sf_low)
            if idx is None:
                if derived["low"] is None:
                    derived["low"] = content_txt.lower()
                low_txt = derived["low"]
                body_start = min(380, len(low_txt) // 5)
                idx = low_txt.find(f"\n{sf_low}\n", body_start)
                if idx == -1:
                    idx = low_txt.find(f"\n{sf_low}", body_start)
                if idx == -1:
                    idx = low_txt.rfind(sf_low)
                derived["sf"][sf_low] = idx
            if idx != -1:
                sliced_txt = sliced_txt[max(0, idx - 10):]
        if char_offset > 0 and char_offset < len(sliced_txt):
            sliced_txt = sliced_txt[char_offset:]
        trimmed_txt = sliced_txt[:max_chars] if max_chars > 0 else sliced_txt

        table_info = derived["table_info"]
        metadata_dict = {"has_table": table_info["has_table"], "table_headers": table_info["table_headers"]}
        return {
            "mode": "resolve_virtual_uri",
            "virtual_uri": virtual_uri,
            "archive_path": arch_p,
            "entry_name": entry_n,
            "title": title_txt or entry_n,
            "section_filter_applied": section_filter or None,
            "structured_sections": structured_sections,
            "compressed_size": comp_size,
            "uncompressed_size": uncomp_size,
            "compression_ratio": comp_ratio,
            "sha256_hash": sha_hash,
            "content_text": trimmed_txt,
            "extracted_text": trimmed_txt,
            "has_table": table_info["has_table"],
            "table_headers": table_info["table_headers"],
            "metadata": metadata_dict,
            "diagram_url": None,
            "extracted_diagrams": [],
            "zero_disk_extraction": True,
            "ingested": False,
        }
