"""
Structure-extraction contract (ADR-12).

A *structure extractor* turns one source (a vendor package, a zip, a folder, a mailbox...)
into a relational tree of topics and tells the runner where each already-indexed record
sits in that tree. It never calls a model: everything here is deterministic, stdlib-only
and streams the source in memory, so the same code runs on a laptop (Tier 1), an edge
appliance (Tier 2) and a datacenter (Tier 3).

Adding a format means adding one subclass and registering it; the runner, the schema and
the graph/visualisation layers do not change.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Dict, List, Optional, Tuple

# native     : the record IS the source item (page, file, sheet)
# composite  : a curated record standing on a native item (same topic, extra/derived text)
# synthetic  : a record with no reliable source item (dossiers, boilerplate, mismatches)
# external   : a record that no configured source claims (wiki notes, other corpora)
RECORD_KINDS = ("native", "composite", "synthetic", "external")


class StructureError(Exception):
    """Raised for unreadable or unsafe sources."""


class NoExtractorError(StructureError):
    """No registered extractor recognises the source."""


@dataclass(frozen=True)
class RecordView:
    """The minimum the runner shows an extractor about an indexed record (never its content)."""

    id: int
    doc_identifier: str
    title: str
    virtual_uri: str  # where the record came from; falls back to doc_identifier


@dataclass
class Node:
    key: str  # globally unique: "<label>:<local id>"
    name: str
    depth: int
    source: str  # which file / mechanism produced the node (bookmap file, "navi.xml", "path")
    path_text: str  # full " > " path; stored only when the tier policy asks for it


@dataclass
class Tree:
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Tuple[str, Optional[str], int]] = field(default_factory=list)  # (child, parent, is_primary)
    multi_parent: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Assignment:
    topic_key: Optional[str]
    kind: str
    console: Optional[str] = None
    review: str = ""  # non-empty => list this record for human review


class StructureExtractor(abc.ABC):
    """One extractor instance is bound to one source and one label (e.g. package name)."""

    name: ClassVar[str]
    priority: ClassVar[int] = 100  # lower is tried first when several extractors detect a source

    def __init__(self, source: Path, label: str) -> None:
        self.source = Path(source)
        self.label = label
        self.tree = Tree()

    @classmethod
    @abc.abstractmethod
    def detect(cls, source: Path) -> bool:
        """Cheap check (extension / magic / a directory listing): can this extractor read `source`?"""

    @abc.abstractmethod
    def build_tree(self) -> Tree:
        """Populate and return `self.tree`. May stay partial if nodes are materialised in assign()."""

    @abc.abstractmethod
    def claims(self, rec: RecordView) -> bool:
        """Does this record come from this extractor's source?"""

    @abc.abstractmethod
    def assign(self, rec: RecordView) -> Assignment:
        """Place a claimed record in the tree. May add nodes/edges to `self.tree`."""

    def close(self) -> None:  # pragma: no cover - optional hook
        return None
