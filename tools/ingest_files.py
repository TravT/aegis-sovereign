#!/usr/bin/env python3
"""
Aegis file ingestion CLI (ADR-13): folder / zip / file -> file-type handlers -> records + topic tree.

  python3 tools/ingest_files.py --db SNAPSHOT.db --profile edge --mode missing \\
      --source REL_USC="docs/Hua_Docs/USC 26.1.0_ReleaseDoc_EN (VM).zip" \\
      [--formats docx,xls,xml] [--dry-run] [--report out.json]

Modes: missing (default; only files with no record yet) | changed (SHA-256 differs) |
grow (re-ingest only when the new parse holds >1.5x the indexed text; never shrinks) | replace.
Tier profiles cap the size one file may add: above the cap it is indexed as a flagged catalog card.
Always run on a snapshot first (`sqlite3 live.db ".backup snap.db"`); use --dry-run to see the
footprint (files, records, characters, net growth) before anything is written.
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

from core.ingest import registered  # noqa: E402
from core.ingest.pipeline import MODES, IngestOptions, ingest_source  # noqa: E402
from core.structure import PROFILES, get_profile  # noqa: E402


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--source", action="append", required=True, metavar="LABEL=PATH", dest="sources")
    ap.add_argument("--profile", default="edge", choices=sorted(PROFILES))
    ap.add_argument("--mode", default="missing", choices=MODES)
    ap.add_argument("--formats", help=f"comma-separated handler names to ingest (available: {', '.join(registered())})")
    ap.add_argument("--clearance", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(list(argv) if argv is not None else None)
    formats = {f.strip() for f in args.formats.split(",")} if args.formats else None
    if formats and not formats <= set(registered()):
        ap.error(f"unknown format(s): {sorted(formats - set(registered()))}")
    reports: Dict[str, object] = {}
    for spec in args.sources:
        label, _, path = spec.partition("=")
        opts = IngestOptions(label, get_profile(args.profile), args.mode, args.clearance, formats, dry_run=args.dry_run)
        reports[label] = ingest_source(args.db, Path(path), opts)
    text = json.dumps(reports, indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
