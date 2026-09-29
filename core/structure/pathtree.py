"""
Path-tree structure extractor: the tree is the folder hierarchy.

Covers anything whose organisation IS its path — a work folder on a laptop (Tier 1 zero-copy,
in-place), a documentation zip made of numbered folders (Huawei *ReleaseDoc* packages), a mail
export laid out per folder. Nodes are created on demand for the records that exist, so the tree
costs a few rows per indexed file and never walks or copies the source.

Sub-items of one file get their own child node, so a workbook's sheets and row chunks and a
manual's parts each have exactly one native record:

    <root> > 04. NorthBound > USC 26.1.0 Alarm List.xlsx > Alarms
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

from .base import Assignment, Node, RecordView, StructureExtractor, Tree
from .registry import register

SHEET_SEP = "::sheet::"


def best_uri(rec: RecordView) -> str:
    """Production records keep the plain file path in `virtual_uri` metadata and put a sheet / row-chunk
    suffix only in `doc_identifier`; take the more specific of the two."""
    ident, uri = rec.doc_identifier, rec.virtual_uri
    return ident if len(ident) > len(uri) and ident.startswith(uri) else uri


def split_inner(virtual_uri: str) -> Optional[Tuple[str, Optional[str]]]:
    """`archive://x.zip#a/b.xlsx::sheet::S` -> ("a/b.xlsx", "S"); `...#a/b.xlsx#rows_1` -> ("a/b.xlsx", "rows_1")."""
    if "#" not in virtual_uri:
        return None
    inner = virtual_uri.split("#", 1)[1]
    if SHEET_SEP in inner:
        file_part, sub = inner.split(SHEET_SEP, 1)
        return file_part, sub
    if "#" in inner:
        file_part, sub = inner.split("#", 1)
        return file_part, sub
    return inner, None


@register
class PathTreeExtractor(StructureExtractor):
    name = "pathtree"
    priority = 90  # generic fallback: specialised extractors get the first look

    @classmethod
    def detect(cls, source: Path) -> bool:
        source = Path(source)
        if source.is_dir():
            return True
        if source.is_file() and zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as z:
                return not any(n.lower().endswith(".hwics") for n in z.namelist())
        return False

    def build_tree(self) -> Tree:
        self.tree = Tree()
        self._add(self._key(""), self.label, 1, "path", self.label, None)
        return self.tree

    def _key(self, rel: str) -> str:
        return f"{self.label}:path:{rel}"

    def _add(self, key: str, name: str, depth: int, source: str, path_text: str, parent: Optional[str]) -> Node:
        node = self.tree.nodes.get(key)
        if node is None:
            node = Node(key, name, depth, source, path_text)
            self.tree.nodes[key] = node
            self.tree.edges.append((key, parent, 1))
        return node

    def claims(self, rec: RecordView) -> bool:
        uri = best_uri(rec)
        if self.source.is_dir():
            root = str(self.source).rstrip("/") + "/"
            return uri.startswith(root) or uri.startswith("file://" + root)
        return self.source.name in uri and "#" in uri

    def _relative_parts(self, rec: RecordView) -> Optional[Tuple[List[str], Optional[str]]]:
        uri = best_uri(rec)
        if self.source.is_dir():
            root = str(self.source).rstrip("/") + "/"
            rel = uri.split(root, 1)[1] if root in uri else None
            return ([p for p in rel.split("/") if p], None) if rel else None
        parts = split_inner(uri)
        if parts is None:
            return None
        return [p for p in parts[0].split("/") if p], parts[1]

    def assign(self, rec: RecordView) -> Assignment:
        if not self.tree.nodes:
            self.build_tree()
        rp = self._relative_parts(rec)
        if rp is None or not rp[0]:
            return Assignment(None, "synthetic", None, "no-path")
        segments, sub = rp
        node = self.tree.nodes[self._key("")]  # the single root, created by build_tree()
        parent = node.key
        names = [self.label]
        rel_parts: List[str] = []
        for seg in segments:
            rel_parts.append(seg)
            names.append(seg)
            node = self._add(self._key("/".join(rel_parts)), seg, len(names), "path", " > ".join(names), parent)
            parent = node.key
        if sub:
            names.append(sub)
            node = self._add(
                self._key("/".join(rel_parts) + "#" + sub), sub, len(names), "path", " > ".join(names), parent
            )
        # As with HedEx: a record whose own identifier IS the item's path is native; a curated record
        # standing on the item (dossiers, summaries) is composite and keeps the same topic.
        native = rec.doc_identifier == best_uri(rec) or rec.doc_identifier.endswith("/" + "/".join(segments) + (
            ("::sheet::" + sub) if sub and SHEET_SEP in rec.doc_identifier else ("#" + sub if sub else "")
        ))
        return Assignment(node.key, "native" if native else "composite", None)
