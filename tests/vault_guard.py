"""Pytest plugin: find (and block) every write a test makes to the production vault (PRJ-06 step 12.6 audit).

    pytest -p tests.vault_guard tests/                       # block and record (default)
    VAULT_GUARD=record pytest -p tests.vault_guard tests/    # record only (writes go through)
    VAULT_GUARD_REPORT=/tmp/vg.json ...                      # also write the findings as JSON

Covers, inside the pytest process:
- SQLite: an authorizer on every connection (opened with sqlite3.connect) whose file is under the production vault; INSERT, UPDATE, DELETE,
  row writes (INSERT, UPDATE, DELETE on a table) are denied ("not authorized") and recorded; schema statements
  (start-up `CREATE ... IF NOT EXISTS`) are recorded and allowed. Reads are recorded per test too.
- Files: Python-level writes, renames and deletes under the vault (audit events `open`, `os.*`, `shutil.*`).
- Qdrant: write calls (upsert, delete, collection changes) on a client connected to a server, not a local path.
Not covered: subprocesses, and writes made by native code outside Python's audit events.
"""

import json
import os
import sqlite3
import sys
import threading
from collections import defaultdict

PROD_VAULT = os.path.realpath(os.environ.get("VAULT_GUARD_ROOT", "/home/tlima/Enterprise_Hub/docs/.aegis_vault"))
MODE = os.environ.get("VAULT_GUARD", "deny")  # deny | record

_WRITE_ACTIONS = {
    getattr(sqlite3, name)
    for name in dir(sqlite3)
    if name.startswith(("SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_CREATE_", "SQLITE_DROP_",
                        "SQLITE_ALTER_TABLE", "SQLITE_REINDEX"))
    and not name.startswith(("SQLITE_CREATE_TEMP", "SQLITE_DROP_TEMP"))
}
_QDRANT_WRITES = ("upsert", "delete", "delete_collection", "create_collection", "recreate_collection",
                  "update_collection", "delete_vectors", "update_vectors", "set_payload", "overwrite_payload",
                  "delete_payload", "clear_payload", "upload_points", "upload_collection", "batch_update_points",
                  "create_payload_index", "delete_payload_index")

_state = {"test": "<collection>"}
_local = threading.local()
_writes = defaultdict(set)   # test -> {"sqlite:<file>:<op> <table>", "file:...", "qdrant:..."}
_reads = defaultdict(set)    # test -> {"<file>"}
_ddl = defaultdict(set)      # test -> {"<file>:<op> <object>"} (allowed, see the authorizer)
_ROW_ACTIONS = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}


def _in_vault(path) -> bool:
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False
    p = os.fsdecode(path)
    if p.startswith("file:"):
        p = p[5:].split("?", 1)[0]
    if p in ("", ":memory:"):
        return False
    try:
        real = os.path.realpath(p)
    except (OSError, ValueError):
        return False
    return real == PROD_VAULT or real.startswith(PROD_VAULT + os.sep)


def _sqlite_authorizer(fname):
    # Authorizer action codes only: SQLite reuses the same numbers for result codes and limits.
    action_names = {getattr(sqlite3, n): n for n in dir(sqlite3)
                    if n.startswith(("SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_CREATE_", "SQLITE_DROP_",
                                     "SQLITE_ALTER_TABLE", "SQLITE_REINDEX"))}

    def authorize(action, arg1, arg2, dbname, source):
        if action in _WRITE_ACTIONS and dbname not in ("temp",):
            op = action_names.get(action, str(action)).removeprefix("SQLITE_")
            # Schema statements: start-up code runs `CREATE ... IF NOT EXISTS`, which the authorizer cannot tell
            # from a real CREATE. They are recorded and allowed; compare the schema before and after a run to
            # prove none landed. Row writes (INSERT/UPDATE/DELETE on a table) are denied.
            if action not in _ROW_ACTIONS or (arg1 or "").startswith("sqlite_"):
                _ddl[_state["test"]].add(f"{fname}:{op} {arg1 or ''}".rstrip())
                return sqlite3.SQLITE_OK
            _writes[_state["test"]].add(f"sqlite:{fname}:{op} {arg1 or ''}".rstrip())
            return sqlite3.SQLITE_DENY if MODE == "deny" else sqlite3.SQLITE_OK
        return sqlite3.SQLITE_OK

    return authorize


def _audit(event, args):
    try:
        if event == "sqlite3.connect":
            # Cross-check: a vault connection not opened through the guarded sqlite3.connect is reported.
            if args and _in_vault(args[0]) and not getattr(_local, "guarded", False):
                _writes[_state["test"]].add(f"sqlite:UNGUARDED connect {os.path.basename(os.fsdecode(args[0]))}")
        elif event == "open":
            path, mode, flags = (list(args) + [None, None, None])[:3]
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
            if writing and _in_vault(path):
                _writes[_state["test"]].add(f"file:open {os.path.relpath(os.fsdecode(path), PROD_VAULT)}")
                if MODE == "deny":
                    raise PermissionError(f"vault_guard: test wrote to the production vault: {path}")
        elif event in ("os.remove", "os.rename", "os.mkdir", "os.rmdir", "shutil.rmtree", "shutil.copyfile", "shutil.move"):
            paths = [a for a in args if isinstance(a, (str, bytes, os.PathLike))]
            # copyfile/rename/move: the destination is the last path argument
            target = paths[-1] if event in ("os.rename", "shutil.copyfile", "shutil.move") and paths else (paths[0] if paths else None)
            if event == "os.mkdir" and target is not None and os.path.isdir(target):
                target = None  # mkdir(exist_ok=True) on a folder that exists changes nothing
            if target is not None and _in_vault(target):
                _writes[_state["test"]].add(f"file:{event} {os.path.relpath(os.fsdecode(target), PROD_VAULT)}")
                if MODE == "deny":
                    raise PermissionError(f"vault_guard: test changed the production vault: {event} {target}")
    except PermissionError:
        raise
    except Exception:  # noqa: BLE001 - an audit hook must never break the code it watches
        pass


def _guard_qdrant():
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        return
    for name in _QDRANT_WRITES:
        orig = getattr(QdrantClient, name, None)
        if orig is None or getattr(orig, "_vault_guard", False):
            continue

        def make(orig, name):
            def wrapper(self, *a, **kw):
                inner = type(getattr(self, "_client", None)).__name__
                if "Local" not in inner:  # a server (the live one on this host), not a local or in-memory store
                    _writes[_state["test"]].add(f"qdrant:{name} {a[0] if a else kw.get('collection_name', '')}")
                    if MODE == "deny":
                        raise PermissionError(f"vault_guard: test wrote to a Qdrant server: {name}")
                return orig(self, *a, **kw)
            wrapper._vault_guard = True
            return wrapper

        setattr(QdrantClient, name, make(orig, name))


_orig_connect = sqlite3.connect


def _guarded_connect(database, *args, **kwargs):
    """sqlite3.connect, plus an authorizer on connections to the production vault. (The authorizer cannot be set
    from the `sqlite3.connect/handle` audit event: the connection is not initialised yet.)"""
    _local.guarded = True
    try:
        conn = _orig_connect(database, *args, **kwargs)
    finally:
        _local.guarded = False
    if _in_vault(database):
        fname = os.path.basename(os.fsdecode(database).split("?", 1)[0])
        _reads[_state["test"]].add(fname)
        conn.set_authorizer(_sqlite_authorizer(fname))
    return conn


sqlite3.connect = _guarded_connect
sys.addaudithook(_audit)
_guard_qdrant()


def pytest_runtest_setup(item):
    _state["test"] = item.nodeid


def pytest_runtest_teardown(item):
    _state["test"] = item.nodeid


def pytest_terminal_summary(terminalreporter):
    tr = terminalreporter
    tr.section(f"vault_guard ({MODE}): production vault {PROD_VAULT}")
    writers = {t: sorted(w) for t, w in _writes.items() if w}
    readers = sorted(t for t in _reads if t not in writers)
    tr.write_line(f"{len(writers)} test(s) tried to write; {len(readers)} more only read the production vault")
    for t, ws in sorted(writers.items()):
        tr.write_line(f"WRITE {t}")
        for w in ws[:6]:
            tr.write_line(f"    {w}")
        if len(ws) > 6:
            tr.write_line(f"    ... {len(ws) - 6} more")
    for t in readers:
        tr.write_line(f"READ  {t}: {', '.join(sorted(_reads[t]))}")
    ddl = sorted({d for v in _ddl.values() for d in v})
    tr.write_line(f"schema statements allowed on the vault (start-up IF NOT EXISTS; check the schema is unchanged): {len(ddl)} kinds in {len(_ddl)} tests")
    for d in ddl[:12]:
        tr.write_line(f"    {d}")
    out = os.environ.get("VAULT_GUARD_REPORT")
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"mode": MODE, "writes": writers, "reads": {t: sorted(v) for t, v in _reads.items()}, "ddl": {t: sorted(v) for t, v in _ddl.items()}}, fh, indent=1)
