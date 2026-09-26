"""Aegis Sovereign Appliance administrative and cryptographic tools."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
for _sp in (_REPO_ROOT / ".venv" / "lib").glob("python*/site-packages"):
    if str(_sp) not in sys.path:
        sys.path.insert(0, str(_sp))

from tools.benchmark_generator import SyntheticCorpusGenerator
from tools.capsule import CapsuleIntegrityError, SovereignCapsuleManager
from tools.package_update import (
    SovereignUpdatePackager,
    UpdateIntegrityError,
    verify_and_apply_update,
)

__all__ = [
    "CapsuleIntegrityError",
    "SovereignCapsuleManager",
    "SyntheticCorpusGenerator",
    "SovereignUpdatePackager",
    "UpdateIntegrityError",
    "verify_and_apply_update",
]

