"""
Ingestion pipeline (ADR-13): source -> file-type handler -> lossless chunks -> records + topic tree.

  * Sources: a folder (read in place, never copied), a zip (streamed in memory, nested zips
    followed to `max_depth`) or a single file. `.hwics` members belong to the HedEx extractor.
  * Modes:  `missing`  ingest only files with no record yet (safe default; never touches
                       existing, possibly curated, records);
            `changed`  re-ingest a file only when its SHA-256 differs from the stored one;
            `grow`     re-ingest only when the new parse holds >1.5x the text indexed now, so
                       truncated files are repaired and complete ones are left alone (never shrinks);
            `replace`  always re-ingest (replaces the file's own records, e.g. truncated ones).
    Only records owned by the file are replaced: the file's own identifier, `::part::N`, and the
    older `::sheet::` / `#rows` patterns. Curated records that merely point at the file are kept.
  * Every record is written with `topic_id` and `record_kind` at ingest time, and the topic tree
    gains a node per heading, so structure never needs a second pass.
  * `dry_run` performs everything except the writes and reports the footprint.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import posixpath
import sqlite3
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from core.structure.policy import SizePolicy
from core.structure.runner import ensure_schema

from .base import HandlerError, ParsedDocument
from .catalog import apply_cap
from .chunking import Chunk, chunk_document
from .registry import handler_for

MODES = ("missing", "changed", "grow", "replace")
MAX_RATIO = 150.0
_SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


@dataclass
class IngestOptions:
    label: str
    policy: SizePolicy
    mode: str = "missing"
    clearance: int = 0
    formats: Optional[Set[str]] = None  # restrict to these handler names
    max_file_bytes: int = 200 * 1024 * 1024
    max_depth: int = 2  # nested archive depth
    dry_run: bool = False


@dataclass
class SourceFile:
    member: str  # path inside the source; nested archives joined with "!"
    uri: str
    size: int
    read: Callable[[], bytes]


def _safe(name: str) -> bool:
    n = name.replace("\\", "/")
    return not (n.startswith("/") or ".." in n.split("/") or n.endswith("/"))


def _skip(name: str) -> bool:
    base = posixpath.basename(name).lower()
    return base in _SKIP_NAMES or base.startswith("~$") or "__macosx" in name.lower() or name.lower().endswith(".hwics")


def _walk_zip(zf: zipfile.ZipFile, prefix: str, uri_root: str, opts: IngestOptions, depth: int) -> Iterator[SourceFile]:
    for info in zf.infolist():
        name = info.filename
        if info.is_dir() or not _safe(name) or _skip(name):
            continue
        if info.file_size > opts.max_file_bytes or (info.compress_size and info.file_size / info.compress_size > MAX_RATIO):
            yield SourceFile(prefix + name, f"{uri_root}#{prefix}{name}", info.file_size, lambda: (_ for _ in ()).throw(HandlerError("exceeds size / ratio guard")))
            continue
        member = prefix + name
        if name.lower().endswith(".zip") and depth < opts.max_depth:
            try:
                nested = zipfile.ZipFile(io.BytesIO(zf.read(info)))
            except zipfile.BadZipFile:
                continue
            yield from _walk_zip(nested, member + "!", uri_root, opts, depth + 1)
            continue
        yield SourceFile(member, f"{uri_root}#{member}", info.file_size, (lambda i=info: zf.read(i)))


def iter_source(source: Path, opts: IngestOptions) -> Iterator[SourceFile]:
    source = Path(source)
    if source.is_dir():
        for dirpath, dirnames, filenames in os.walk(source):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fn in sorted(filenames):
                path = Path(dirpath) / fn
                if fn.startswith(".") or _skip(fn) or path.is_symlink():
                    continue
                rel = path.relative_to(source).as_posix()
                yield SourceFile(rel, str(path), path.stat().st_size, (lambda p=path: p.read_bytes()))
    elif zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            yield from _walk_zip(zf, "", f"archive://{source.resolve()}", opts, 1)
    elif source.is_file():
        yield SourceFile(source.name, str(source.resolve()), source.stat().st_size, source.read_bytes)
    else:
        raise FileNotFoundError(source)


# ------------------------------------------------------------------------------------ database
def _owned(conn: sqlite3.Connection, uri: str) -> List[Tuple[int, str, str]]:
    return conn.execute(
        "SELECT id, doc_identifier, metadata FROM document_records WHERE doc_identifier = ? "
        "OR (doc_identifier >= ? AND doc_identifier < ?) OR (doc_identifier >= ? AND doc_identifier < ?)",
        (uri, uri + "::", uri + ":;", uri + "#", uri + "$"),
    ).fetchall()


def _prune_orphan_nodes(conn: sqlite3.Connection, file_key: str) -> None:
    lo, hi = file_key + "#", file_key + "$"
    while True:
        ids = [
            r[0]
            for r in conn.execute(
                "SELECT n.topic_id FROM topic_nodes n WHERE n.topic_id >= ? AND n.topic_id < ? "
                "AND NOT EXISTS (SELECT 1 FROM document_records r WHERE r.topic_id = n.topic_id) "
                "AND NOT EXISTS (SELECT 1 FROM topic_edges e WHERE e.parent = n.topic_id)",
                (lo, hi),
            )
        ]
        if not ids:
            return
        conn.executemany("DELETE FROM topic_edges WHERE child = ?", [(i,) for i in ids])
        conn.executemany("DELETE FROM topic_nodes WHERE topic_id = ?", [(i,) for i in ids])


def _add_node(conn, key: str, label: str, name: str, depth: int, path_text: str, parent: Optional[str], policy: SizePolicy) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO topic_nodes VALUES (?,?,?,?,?,?)",
        (key, label, name, depth, "ingest", path_text if policy.store_paths else None),
    )
    # NULL-safe: a primary key containing NULL (the root's parent) is never "equal", so OR IGNORE would duplicate it
    conn.execute(
        "INSERT INTO topic_edges SELECT ?, ?, 1 WHERE NOT EXISTS (SELECT 1 FROM topic_edges WHERE child = ? AND parent IS ?)",
        (key, parent, key, parent),
    )


def _write_tree(conn, opts: IngestOptions, member: str, paths: Iterable[Tuple[str, ...]]) -> Tuple[str, Dict[Tuple[str, ...], str]]:
    """Create the folder / file / heading nodes. Every heading of the document becomes a node (the outline
    is complete) even when its text was merged into a parent chunk; such outline nodes simply have no record."""
    label, policy = opts.label, opts.policy
    root = f"{label}:path:"
    _add_node(conn, root, label, label, 1, label, None, policy)
    segs = [s for s in member.replace("!", "/").split("/") if s]
    parent, names = root, [label]
    for k, seg in enumerate(segs, start=1):
        key = f"{label}:path:{'/'.join(segs[:k])}"
        names.append(seg)
        _add_node(conn, key, label, seg, k + 1, " > ".join(names), parent, policy)
        parent = key
    file_key = parent
    keys: Dict[Tuple[str, ...], str] = {(): file_key}
    for path in sorted(set(paths)):
        for level in range(1, len(path) + 1):
            sub = path[:level]
            if sub in keys:
                continue
            key = f"{file_key}#sec:" + "/".join(h.replace("/", "∕") for h in sub)
            _add_node(conn, key, label, sub[-1], len(segs) + 1 + level, " > ".join(names + list(sub)), keys[sub[:-1]], policy)
            keys[sub] = key
    return file_key, keys


def _title(doc: ParsedDocument, c: Chunk) -> str:
    t = doc.title
    if c.path:
        t += " — " + " > ".join(c.path[-2:])
    if c.locator:
        t += f" ({c.locator})"
    if c.total > 1:
        t += f" [{c.index + 1}/{c.total}]"
    return t[:240]


def ingest_source(db_path: Path, source: Path, opts: IngestOptions) -> Dict[str, object]:
    if opts.mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    started = time.time()
    conn = sqlite3.connect(str(db_path), timeout=60)
    if not opts.dry_run:
        ensure_schema(conn, rebuild=False)
    skipped: Dict[str, int] = {}
    failed: List[Dict[str, str]] = []
    by_format: Dict[str, Dict[str, int]] = {}
    unsupported: Dict[str, int] = {}
    over_cap: List[Dict[str, object]] = []
    warnings: List[str] = []
    seen = ingested = 0
    ins_rec = del_rec = ins_chars = del_chars = 0

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for sf in iter_source(source, opts):
        seen += 1
        try:
            data = sf.read()
        except Exception as exc:  # noqa: BLE001 - unreadable member: report, continue
            failed.append({"file": sf.member, "error": str(exc)[:160]})
            continue
        handler = handler_for(sf.member, data[:16])
        if handler is None:
            ext = posixpath.splitext(sf.member.lower())[1] or "(none)"
            unsupported[ext] = unsupported.get(ext, 0) + 1
            skip("unsupported")
            continue
        if opts.formats and handler.name not in opts.formats:
            skip("format-filter")
            continue
        sha = hashlib.sha256(data).hexdigest()
        owned = _owned(conn, sf.uri)
        if owned and opts.mode == "missing":
            skip("exists")
            continue
        if owned and opts.mode == "changed" and any(sha in (m or "") for _, _, m in owned):
            skip("unchanged")
            continue
        try:
            doc = handler.parse(sf.member, data)
            fidelity, full_chars = "full", doc.total_chars
            if opts.policy.max_file_chars:
                doc, carded = apply_cap(doc, opts.policy.max_file_chars)
                if carded:
                    fidelity = "catalog"
                    over_cap.append({"file": sf.member, "chars": full_chars, "sheets": carded})
            chunks = chunk_document(doc, opts.policy)
        except HandlerError as exc:
            failed.append({"file": sf.member, "error": str(exc)[:160]})
            continue
        new_chars = sum(len(c.content) for c in chunks)
        old_chars = 0
        if owned:
            ids = [i for i, _, _ in owned]
            old_chars = sum(r[0] for r in conn.execute(f"SELECT length(content) FROM document_records WHERE id IN ({','.join('?' * len(ids))})", ids))
        if owned and opts.mode == "grow" and new_chars <= 1.5 * old_chars:
            skip("not-larger" if fidelity == "full" else "kept-existing (cards not larger)")
            continue
        fmt = by_format.setdefault(handler.name, {"files": 0, "chunks": 0, "chars": 0})
        fmt["files"] += 1
        fmt["chunks"] += len(chunks)
        fmt["chars"] += sum(len(c.content) for c in chunks)
        for w in doc.warnings[:2]:
            if len(warnings) < 30:
                warnings.append(f"{sf.member}: {w}")
        ingested += 1
        ins_rec += len(chunks)
        ins_chars += sum(len(c.content) for c in chunks)
        if owned:
            del_rec += len(owned)
            del_chars += old_chars
        if opts.dry_run:
            continue
        with conn:
            file_key = f"{opts.label}:path:{sf.member.replace('!', '/')}"
            if owned:
                conn.executemany("DELETE FROM document_records WHERE id = ?", [(i,) for i, _, _ in owned])
                _prune_orphan_nodes(conn, file_key)
            _, keys = _write_tree(conn, opts, sf.member, [s.path for s in doc.sections] + [c.path for c in chunks])
            meta_common = {
                "virtual_uri": sf.uri,
                "format": handler.name,
                "parser": f"{handler.name}/{handler.version}",
                "source_sha256": sha,
                "source_bytes": len(data),
                "fidelity": fidelity,
                "full_chars": full_chars,
            }
            rows = []
            for c in chunks:
                meta = dict(meta_common, section_path=list(c.path), locator=c.locator, chunk_index=c.index, chunk_total=c.total)
                rows.append(
                    (
                        f"{sf.uri}{c.suffix}",
                        _title(doc, c),
                        c.content,
                        opts.clearance,
                        json.dumps(meta, ensure_ascii=False),
                        keys.get(c.path, keys[()]),
                        "native",
                    )
                )
            conn.executemany(
                "INSERT INTO document_records (doc_identifier, title, content, clearance_level, metadata, topic_id, record_kind) "
                "VALUES (?,?,?,?,?,?,?)",
                rows,
            )
    if not opts.dry_run:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO structure_meta VALUES (?,?)",
                (
                    f"ingest:{opts.label}",
                    json.dumps({"applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "mode": opts.mode, "profile": opts.policy.name, "files": ingested}),
                ),
            )
    conn.close()
    return {
        "source": str(source),
        "label": opts.label,
        "mode": opts.mode,
        "profile": opts.policy.name,
        "dry_run": opts.dry_run,
        "files": {"seen": seen, "ingested": ingested, "skipped": skipped, "failed": failed},
        "records": {"inserted": ins_rec, "deleted": del_rec},
        "chars": {"inserted": ins_chars, "deleted": del_chars, "net": ins_chars - del_chars},
        "by_format": by_format,
        "catalog_cards": over_cap,
        "unsupported_extensions": dict(sorted(unsupported.items(), key=lambda kv: -kv[1])[:15]),
        "warnings": warnings,
        "seconds": round(time.time() - started, 1),
    }
