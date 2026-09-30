"""Links between layers, only where a deterministic key exists.

An alarm entity ``ALM-<n>`` is described by every manual topic whose title starts with that id.
MML commands have no such key (5 of 1,213 match a topic title exactly), so they are left to the
relationship extraction of Task 14.3 rather than guessed.
"""

import re
from collections import defaultdict
from typing import Dict, List

from .tree import TreeView

_ALARM_TITLE = re.compile(r"^(ALM-\d+)(?!\d)")
_ALARM_ID = re.compile(r"^ALM-\d+$")


def alarm_topics(view: TreeView) -> Dict[str, List[str]]:
    """Alarm id -> ids of the visible topics of ``view`` that describe it (tree order)."""
    found: Dict[str, List[str]] = defaultdict(list)
    for nid, node in view.nodes.items():
        match = _ALARM_TITLE.match(node.label)
        if match:
            found[match.group(1)].append(nid)
    return dict(found)


def is_alarm_id(label: str) -> bool:
    return bool(_ALARM_ID.match(label))
