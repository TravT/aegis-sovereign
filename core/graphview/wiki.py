"""The wiki layer: the homelab notes and the markdown links between them, read straight from the
markdown files (``docs/wiki`` is mounted read-only next to the vault), so it is always fresh."""

import hashlib
import os
import posixpath
import re
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..security import ClearanceLevel
from .flat import FlatView
from .model import Edge, Node

DEFAULT_CLEARANCE = int(ClearanceLevel.PUBLIC)  # as the notes already are in the vault's document table
GOVERNING_TYPES = {"decision", "adr"}

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r'(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
_H1 = re.compile(r"^# +(.+?)\s*$", re.M)
_WIKI_MARKER = "/docs/wiki/"


class _Note:
    def __init__(self, rel: str, text: str):
        self.rel = rel
        match = _FRONTMATTER.match(text)
        body = text[match.end():] if match else text
        self.meta: Dict[str, str] = {}
        if match:
            for line in match.group(1).splitlines():
                key = re.match(r"^([A-Za-z_][\w-]*):[ \t]*(.*)$", line)
                if key:
                    self.meta[key.group(1)] = key.group(2).strip().strip("\"'")
        h1 = _H1.search(_FENCE.sub("", body))
        self.title = self.meta.get("title") or (h1.group(1) if h1 else Path(rel).stem)
        self.kind = self.meta.get("type") or "note"
        folder = posixpath.dirname(rel).split("/")[0]
        self.theme = self.meta.get("domain") or self.meta.get("category") or folder
        self.clearance = self._clearance()
        self.hrefs = _LINK.findall(_INLINE_CODE.sub("", _FENCE.sub("", body)))

    def _clearance(self) -> int:
        raw = self.meta.get("clearance_level") or self.meta.get("clearance")
        if raw is None:
            return DEFAULT_CLEARANCE
        try:
            return int(ClearanceLevel.from_string(raw))
        except ValueError:
            return int(ClearanceLevel.RESTRICTED)  # an unreadable level fails closed


class WikiLayer:
    def __init__(self, wiki_dir: str):
        self._root = Path(wiki_dir)

    def _files(self) -> List[Path]:
        if not self._root.is_dir():
            return []
        return sorted(
            p for p in self._root.rglob("*.md")
            if not any(part.startswith(".") for part in p.relative_to(self._root).parts)
        )

    def signature(self) -> str:
        """Changes when any note is added, removed or edited."""
        parts = []
        for p in self._files():
            st = os.stat(p)
            parts.append(f"{p.relative_to(self._root).as_posix()}:{st.st_mtime_ns}:{st.st_size}")
        return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]

    def build(self, level: int) -> FlatView:
        notes = {
            rel: _Note(rel, p.read_text(encoding="utf-8", errors="replace"))
            for p in self._files()
            for rel in [p.relative_to(self._root).as_posix()]
        }
        visible = {rel for rel, note in notes.items() if note.clearance <= level}
        nodes = {
            f"w:{rel}": Node(notes[rel].title, notes[rel].kind, "wiki", 0, notes[rel].theme)
            for rel in notes if rel in visible
        }
        seen: Dict[Tuple[str, str], str] = {}
        for rel in notes:
            if rel not in visible:
                continue
            for href in notes[rel].hrefs:
                target = self._resolve(rel, href, notes)
                if target is None or target == rel or target not in visible:
                    continue
                governed = notes[target].kind in GOVERNING_TYPES and notes[rel].kind not in GOVERNING_TYPES
                seen.setdefault((rel, target), "GOVERNED_BY" if governed else "LINKS_TO")
        edges: List[Edge] = [(f"w:{s}", f"w:{t}", kind) for (s, t), kind in seen.items()]
        return FlatView(nodes, edges)

    @staticmethod
    def _resolve(source: str, href: str, notes: Dict[str, _Note]) -> Optional[str]:
        """The note a markdown link points to, or None (external, anchor-only, non-note, dead)."""
        if href.startswith(("http:", "https:", "mailto:", "#")):
            return None
        if href.startswith("file://"):
            path = href[len("file://"):]
            if _WIKI_MARKER not in path:
                return None
            rel = path.split(_WIKI_MARKER, 1)[1]
        else:
            rel = posixpath.join(posixpath.dirname(source), href)
        rel = urllib.parse.unquote(rel.split("#", 1)[0].split("?", 1)[0])
        rel = posixpath.normpath(rel)
        return rel if rel.endswith(".md") and rel in notes else None
