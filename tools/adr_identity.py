"""ADR identity records (Phase 12.3, finding R-g).

The wiki holds two ADR series with the same numbers: homelab ADRs in `adrs/` keep the id "ADR-nn", Aegis ADRs in
`projects/aegis/adrs/` are "Aegis ADR-nn" (owner decision, 13 Oct 2026; files keep their names). Each ADR has one
identity record in the router vault, keyed by that id, so the exact path answers "ADR-16" and "Aegis ADR-16".

Before this tool the ids came from the file name alone: both series wrote "ADR-nn" and the last write won.

    python3 -m tools.adr_identity --router-db PATH --wiki-dir PATH            # dry run: what would change
    python3 -m tools.adr_identity --router-db PATH --wiki-dir PATH --apply    # back up the vault first
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

AEGIS_ADR_DIR = ("projects", "aegis", "adrs")
_FILE_ID = re.compile(r"^ADR-(\d{2,3})[-_]", re.IGNORECASE)
# "ADR-16: ", "ADR 16: ", "Aegis ADR-16 — " ... (repeated prefixes are all removed, then one is put back)
_TITLE_PREFIX = re.compile(r"^\s*(?:Aegis\s+)?ADR[-\s]?\d{1,3}\s*[:—–-]\s*", re.IGNORECASE)
IDENTITY_GLOBS = ("ADR-[0-9]*", "Aegis ADR-[0-9]*")
CONTENT_CAP = 25000  # as tools/vault_lifecycle.py


def adr_identity(fpath: Path, title: str) -> Optional[Tuple[str, str, str]]:
    """(id, display title, series) for an ADR file, or None for any other file."""
    m = _FILE_ID.match(fpath.name)
    if not m or "adrs" not in fpath.parts[:-1]:
        return None
    aegis = tuple(fpath.parts[-4:-1]) == AEGIS_ADR_DIR
    code = f"Aegis ADR-{m.group(1)}" if aegis else f"ADR-{m.group(1)}"
    rest = title.strip()
    while _TITLE_PREFIX.match(rest):
        rest = _TITLE_PREFIX.sub("", rest, count=1)
    return code, f"{code}: {rest}" if rest else code, ("aegis" if aegis else "homelab")


def markdown_title(text: str, fallback: str) -> str:
    """The first H1, else the frontmatter title (the order tools/vault_lifecycle.py uses)."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    m = re.search(r"^title:\s*[\"']?([^\"'\n]+)[\"']?", text, flags=re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else fallback


def _adr_files(wiki_dir: Path) -> List[Path]:
    dirs = [wiki_dir / "adrs", wiki_dir.joinpath(*AEGIS_ADR_DIR)]
    return sorted(p for d in dirs if d.is_dir() for p in d.glob("ADR-*.md"))


def planned_records(wiki_dir: Union[str, Path]) -> Dict[str, Dict[str, Any]]:
    wiki_dir = Path(wiki_dir).resolve()
    out: Dict[str, Dict[str, Any]] = {}
    for f in _adr_files(wiki_dir):
        text = f.read_text(encoding="utf-8", errors="ignore")
        ident = adr_identity(f, markdown_title(text, f.stem))
        if not ident:
            continue
        code, title, series = ident
        if code in out:
            raise ValueError(f"two files claim {code}: {out[code]['metadata']['file_path']} and {f}")
        out[code] = {
            "title": title,
            "content": text[:CONTENT_CAP],
            "metadata": {
                "domain": "homelab_wiki",
                "source_dir": str(wiki_dir),
                "file_path": str(f),
                "virtual_uri": str(f),
                "filename": f.name,
                "adr_id": code,
                "adr_series": series,
            },
        }
    return out


def sync_adr_records(router_db: Union[str, Path], wiki_dir: Union[str, Path], apply: bool = False) -> Dict[str, Any]:
    """Make the vault's ADR identity records match the wiki: one per ADR file, nothing else.

    Returns the plan (`upsert`: ids added or changed, `delete`: id records with no ADR file). With apply=False
    the vault is opened read-only. Writes go through the FTS triggers, so the full-text index follows.
    """
    planned = planned_records(wiki_dir)
    uri = f"file:{Path(router_db)}?mode={'rw' if apply else 'ro'}"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        where = " OR ".join("doc_identifier GLOB ?" for _ in IDENTITY_GLOBS)
        existing = {
            row[0]: row[1:]
            for row in conn.execute(f"SELECT doc_identifier, title, content, metadata FROM document_records WHERE {where}", IDENTITY_GLOBS)
        }
        upsert = sorted(
            code for code, rec in planned.items()
            if existing.get(code) != (rec["title"], rec["content"], json.dumps(rec["metadata"]))
        )
        delete = sorted(set(existing) - set(planned))
        if apply and (upsert or delete):
            cols = {r[1] for r in conn.execute("PRAGMA table_info(document_records)")}
            kind = ", record_kind" if "record_kind" in cols else ""
            with conn:
                for code in upsert:
                    rec = planned[code]
                    conn.execute(
                        f"""
                        INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata{kind})
                        VALUES (?, ?, ?, 0, ?{", 'external'" if kind else ""})
                        ON CONFLICT(doc_identifier) DO UPDATE SET
                            title=excluded.title, content=excluded.content, metadata=excluded.metadata
                        """,
                        (code, rec["title"], rec["content"], json.dumps(rec["metadata"])),
                    )
                conn.executemany("DELETE FROM document_records WHERE doc_identifier = ?", [(c,) for c in delete])
        return {
            "applied": bool(apply),
            "upsert": upsert,
            "delete": delete,
            "unchanged": len(planned) - len(upsert),
            "before": {c: existing[c][0] for c in sorted(existing)},
            "after": {c: planned[c]["title"] for c in sorted(planned)},
        }
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--router-db", required=True)
    ap.add_argument("--wiki-dir", required=True)
    ap.add_argument("--apply", action="store_true", help="write (default: dry run, vault opened read-only)")
    args = ap.parse_args()
    if args.apply:
        from tools.bounded_run import require
        require("ADR identity sync (writes the vault)")
    rep = sync_adr_records(args.router_db, args.wiki_dir, apply=args.apply)
    print(json.dumps({k: rep[k] for k in ("applied", "upsert", "delete", "unchanged")}, indent=1))
    for code in rep["upsert"]:
        print(f"  {code}: {rep['before'].get(code, '(new)')!r} -> {rep['after'][code]!r}")
    for code in rep["delete"]:
        print(f"  {code}: {rep['before'][code]!r} -> (deleted, no ADR file)")


if __name__ == "__main__":
    main()
