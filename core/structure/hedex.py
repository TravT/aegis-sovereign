"""
HedEx / DITA structure extractor (Huawei `.hwics` packages).

Two vendor trees describe a package and both are read:

  * reference bookmaps  `resources/infocenter_service/map/pid_bookmap_*.xml`
        <topic name=".." id="MMLREF_123"> — joined to a page by the page's own
        `<meta name="DC.Identifier" content="EN-US_MMLREF_123">`
  * narrative tree      `resources/navi.xml`
        <topic txt=".." url="toctopics/x.html"> — joined by exact file path; it carries the
        front matter and feature descriptions the bookmaps do not list

A record's file is taken from its `virtual_uri` (`...hwics#<path inside the package>`).
"""

from __future__ import annotations

import collections
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import Assignment, Node, RecordView, StructureError, StructureExtractor, Tree
from .registry import register

BOOKMAP_RE = re.compile(r"pid_bookmap_[^/]*\.xml$", re.IGNORECASE)
DC_ID_RE = re.compile(rb'name="DC\.Identifier"\s+content="([^"]+)"', re.IGNORECASE)
XXE_RE = re.compile(r"<!ENTITY", re.IGNORECASE)

# Ordered, first match wins; applied to the first three bookmap levels of command subtrees only.
CONSOLE_RULES: List[Tuple[str, "re.Pattern[str]"]] = [
    ("pgw_web_lmt", re.compile(r"PGW Web LMT", re.I)),
    ("mml_machine", re.compile(r"Machine-Machine", re.I)),
    ("engineering", re.compile(r"Engineering Command", re.I)),
    ("high_risk", re.compile(r"High-Risk Command", re.I)),
    ("expert_params", re.compile(r"Expert Maintained Parameters", re.I)),
    ("cli", re.compile(r"\bCLI\b", re.I)),
    ("gui", re.compile(r"\bGUI\b|WebUI", re.I)),
    ("om_mml", re.compile(r"Operation and Maintenance Commands", re.I)),
]
COMMAND_ROOT_RE = re.compile(r"Command|MML|\bCLI\b", re.I)

_KEY_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]{2,}(?: [A-Z0-9]{3,})?\b")
_WORDS_RE = re.compile(r"[a-z0-9]+")
_IGNORED_KEYS = {"USC", "UPCF", "ALM", "MML"}


class TopicTreeError(StructureError):
    """Unsafe or unreadable HedEx archive."""


@dataclass
class NaviTopic:
    idx: int
    name: str
    url: Optional[str]
    parent: Optional[int]
    depth: int


def open_hwics(zip_path: Path) -> zipfile.ZipFile:
    """The inner `.hwics` of a Huawei package zip, fully in memory (a bare `.hwics` is opened in place)."""
    zip_path = Path(zip_path)
    if zip_path.suffix.lower() == ".hwics":
        return zipfile.ZipFile(zip_path)
    with zipfile.ZipFile(zip_path) as outer:
        inner = [i for i in outer.infolist() if i.filename.lower().endswith(".hwics")]
        if not inner:
            raise TopicTreeError(f"no .hwics inside {zip_path.name}")
        return zipfile.ZipFile(io.BytesIO(outer.read(inner[0])))


def parse_bookmaps(hwics: zipfile.ZipFile, label: str) -> Tree:
    tree = Tree()
    seen_parents: Dict[str, set] = collections.defaultdict(set)

    def walk(el: ET.Element, parent_key: Optional[str], names: List[str], bookmap: str) -> None:
        for child in el:
            if child.tag.lower() != "topic":
                continue
            name = (child.attrib.get("name") or "").strip()
            tid = (child.attrib.get("id") or "").strip()
            path = names + [name]
            key = f"{label}:{tid}" if tid else None
            if key:
                if key not in tree.nodes:
                    tree.nodes[key] = Node(key, name, len(path), bookmap, " > ".join(path))
                    tree.edges.append((key, parent_key, 1))
                elif parent_key not in seen_parents[key]:
                    tree.edges.append((key, parent_key, 0))
                    if key not in tree.multi_parent:
                        tree.multi_parent.append(key)
                seen_parents[key].add(parent_key)
            walk(child, key if key else parent_key, path, bookmap)

    for name in sorted(hwics.namelist()):
        if not BOOKMAP_RE.search(name):
            continue
        raw = hwics.read(name).decode("utf-8", "ignore")
        if XXE_RE.search(raw):
            raise TopicTreeError(f"entity declaration forbidden in bookmap {name}")
        walk(ET.fromstring(raw), None, [], name.rsplit("/", 1)[-1])
    return tree


def parse_navi(hwics: zipfile.ZipFile) -> Tuple[List[NaviTopic], Dict[str, int]]:
    topics: List[NaviTopic] = []
    by_url: Dict[str, int] = {}
    if "resources/navi.xml" not in hwics.namelist():
        return topics, by_url
    raw = hwics.read("resources/navi.xml").decode("utf-8", "ignore")
    if XXE_RE.search(raw):
        raise TopicTreeError("entity declaration forbidden in navi.xml")

    def walk(el: ET.Element, parent: Optional[int], depth: int) -> None:
        for child in el:
            if child.tag.lower() != "topic":
                continue
            url = (child.attrib.get("url") or "").strip()
            path = ("resources/" + url.lstrip("./")).replace("//", "/") if url else None
            t = NaviTopic(len(topics), (child.attrib.get("txt") or "").strip(), path, parent, depth)
            topics.append(t)
            if path:
                by_url.setdefault(path, t.idx)
            walk(child, t.idx, depth + 1)

    walk(ET.fromstring(raw), None, 1)
    return topics, by_url


def materialize_navi(tree: Tree, label: str, topics: List[NaviTopic], idx: int) -> Node:
    """Create (once) the nodes/edges of a navi-only topic and all its ancestors."""
    key = f"{label}:navi:{idx}"
    if key in tree.nodes:
        return tree.nodes[key]
    chain, cur = [], idx
    while cur is not None:
        chain.append(cur)
        cur = topics[cur].parent
    names: List[str] = []
    parent_key: Optional[str] = None
    for i in reversed(chain):
        names.append(topics[i].name)
        k = f"{label}:navi:{i}"
        if k not in tree.nodes:
            tree.nodes[k] = Node(k, topics[i].name, len(names), "navi.xml", " > ".join(names))
            tree.edges.append((k, parent_key, 1))
        parent_key = k
    return tree.nodes[key]


def console_for(path_text: str) -> Optional[str]:
    """Command family of a topic, from the first three levels of its path. None for non-command topics."""
    levels = [p.strip() for p in path_text.split(" > ")]
    if not any(COMMAND_ROOT_RE.search(p) for p in levels[:2]):
        return None
    head = " > ".join(levels[:3])
    for label, rx in CONSOLE_RULES:
        if rx.search(head):
            return label
    return None


def dc_identifier(html: bytes) -> Optional[str]:
    m = DC_ID_RE.search(html[:6000])
    return re.sub(r"^EN-US_", "", m.group(1).decode("utf-8", "ignore")) if m else None


def title_matches_topic(title: str, topic_name: str) -> bool:
    """The record's key (command / counter / alarm id) appears in the topic name, or titles overlap >= 60%."""
    head = title.split(" — ")[0]
    keys = {k for k in _KEY_TOKEN_RE.findall(head) if k not in _IGNORED_KEYS}
    keys |= set(re.findall(r"\d{5,}", title)) | set(re.findall(r"ALM-\d+", title))
    low = topic_name.lower()
    if any(k.lower() in low for k in keys):
        return True
    a, b = set(_WORDS_RE.findall(title.lower())), set(_WORDS_RE.findall(low))
    return bool(b) and len(a & b) / len(b) >= 0.6


def _record_file(virtual_uri: str) -> Optional[str]:
    return virtual_uri.split(".hwics#", 1)[1] if ".hwics#" in virtual_uri else None


@register
class HedexExtractor(StructureExtractor):
    name = "hedex"
    priority = 10

    def __init__(self, source: Path, label: str) -> None:
        super().__init__(source, label)
        self._hwics: Optional[zipfile.ZipFile] = None
        self._names: set = set()
        self._navi: Tuple[List[NaviTopic], Dict[str, int]] = ([], {})

    @classmethod
    def detect(cls, source: Path) -> bool:
        source = Path(source)
        if not source.is_file() or not zipfile.is_zipfile(source):
            return False
        if source.suffix.lower() == ".hwics":
            return True
        with zipfile.ZipFile(source) as z:
            return any(n.lower().endswith(".hwics") for n in z.namelist())

    def build_tree(self) -> Tree:
        self._hwics = open_hwics(self.source)
        self._names = set(self._hwics.namelist())
        self.tree = parse_bookmaps(self._hwics, self.label)
        self._navi = parse_navi(self._hwics)
        return self.tree

    def claims(self, rec: RecordView) -> bool:
        return self.source.stem in rec.virtual_uri

    def assign(self, rec: RecordView) -> Assignment:
        fpath = _record_file(rec.virtual_uri)
        native_file = bool(fpath) and rec.doc_identifier.endswith(fpath)
        tid = None
        if fpath and fpath in self._names:
            tid = dc_identifier(self._hwics.read(fpath))
        node = self.tree.nodes.get(f"{self.label}:{tid}") if tid else None
        via = "bookmap"
        if node is None and fpath and fpath in self._navi[1]:
            node = materialize_navi(self.tree, self.label, self._navi[0], self._navi[1][fpath])
            via = "navi"
        if node is None:
            return Assignment(None, "synthetic", None, "no-topic")
        # A record whose identifier IS the file path is trusted. Curated records (short names,
        # ALM-*, dossiers) can carry a borrowed virtual_uri, so their title must agree with the topic.
        if via == "bookmap" and not native_file and not title_matches_topic(rec.title, node.name):
            return Assignment(None, "synthetic", None, f"title-mismatch:{node.name[:60]}")
        return Assignment(node.key, "native" if native_file else "composite", console_for(node.path_text))
