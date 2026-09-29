#!/usr/bin/env python3
"""
Aegis structure migration CLI (thin wrapper over `core.structure`, see ADR-12).

Gives every already-indexed record a place in its source's own tree, using whichever
registered extractor recognises each source (HedEx bookmaps, folder/zip paths, ...), and
records the tier size profile that was applied. Additive and idempotent; always run it on a
snapshot first (`sqlite3 live.db ".backup snap.db"`).

  python3 tools/migrate_topic_tree.py --db SNAPSHOT.db --profile edge \\
      --source USC=/path/USC.zip --source UPCF=/path/UPCF.zip \\
      --source RELEASE=/path/USC_ReleaseDoc.zip [--dry-run] [--report out.json]

`--package NAME=PATH` is accepted as an alias of `--source` (Stage 1 spelling).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

APPLIANCE_ROOT = Path(__file__).resolve().parent.parent
if str(APPLIANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLIANCE_ROOT))

from core.structure import PROFILES, SizePolicy, apply_structure, get_profile  # noqa: E402
from core.structure.hedex import (  # noqa: E402,F401  (re-exported for Stage 1 callers and tests)
    TopicTreeError,
    console_for,
    dc_identifier,
    open_hwics,
    parse_bookmaps,
    parse_navi,
    title_matches_topic,
)


def migrate(
    db_path: Path,
    packages: Dict[str, Path],
    dry_run: bool = False,
    policy: Optional[SizePolicy] = None,
) -> Dict[str, object]:
    """Stage 1 entry point, now routed through the extractor registry."""
    return apply_structure(db_path, packages, policy=policy, dry_run=dry_run)


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path, help="router database (use a snapshot)")
    ap.add_argument("--source", "--package", action="append", required=True, metavar="LABEL=PATH", dest="sources")
    ap.add_argument("--profile", default="edge", choices=sorted(PROFILES), help="tier size profile (default: edge)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(list(argv) if argv is not None else None)
    sources: Dict[str, Path] = {}
    for spec in args.sources:
        label, _, path = spec.partition("=")
        sources[label] = Path(path)
    report = apply_structure(args.db, sources, policy=get_profile(args.profile), dry_run=args.dry_run)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
