"""ADR-16: concurrent previews must not share one SQLite connection, and a failed lookup must be reported.

`inspect_archive` used to read the router database through the router's single shared connection from every
request thread, and swallowed any error: under concurrency a preview sometimes came back without its title
and content (2 of 10 concurrent runs in the benchmark).
"""

import logging
import sqlite3
import threading
import time

import pytest

from core.router.query_router import SovereignQueryRouter
from core.server.archive_inspector import ArchiveInspector

URI = "archive:///data/pkg.zip#resources/alarms/1.html"


class _GuardedConnection:
    """Wraps the router's connection and records any moment two threads are inside it at once."""

    def __init__(self, real):
        self._real = real
        self._inside = 0
        self._lock = threading.Lock()
        self.overlaps = 0

    def cursor(self):
        guard = self
        real_cursor = self._real.cursor()

        class _Cursor:
            def execute(self, *args, **kwargs):
                with guard._lock:
                    guard._inside += 1
                    if guard._inside > 1:
                        guard.overlaps += 1
                time.sleep(0.02)
                try:
                    return real_cursor.execute(*args, **kwargs)
                finally:
                    with guard._lock:
                        guard._inside -= 1

            def fetchone(self):
                return real_cursor.fetchone()

        return _Cursor()

    def __getattr__(self, name):
        return getattr(self._real, name)


class _NoArchive:
    """A streamer that cannot resolve anything, so the database row is the only source of the preview."""

    def resolve_virtual_uri(self, _uri):
        raise KeyError("not in any archive")


def _router(tmp_path, in_memory=False):
    router = SovereignQueryRouter(db_path=None if in_memory else tmp_path / "router.db")
    with router._conn:
        router._conn.execute(
            "INSERT INTO document_records (doc_identifier, title, content) VALUES (?, ?, ?)",
            (URI, "ALM-1 Title", "DB content of the alarm"),
        )
    return router


def _run_concurrently(inspector, n=8):
    results, errors = [], []

    def go():
        try:
            results.append(inspector.inspect_archive(virtual_uri=URI))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return results, errors


@pytest.mark.parametrize("in_memory", [False, True], ids=["file-database", "in-memory-database"])
def test_concurrent_previews_all_get_their_title_and_content(tmp_path, in_memory):
    router = _router(tmp_path, in_memory)
    router._conn = guard = _GuardedConnection(router._conn)
    results, errors = _run_concurrently(ArchiveInspector(archive_streamer=_NoArchive(), router=router))
    assert errors == []
    assert len(results) == 8
    assert all(r["title"] == "ALM-1 Title" and r["content_text"] == "DB content of the alarm" for r in results)
    assert guard.overlaps == 0       # the shared connection was never used by two threads at once


def test_a_failed_database_lookup_is_logged_not_swallowed(tmp_path, caplog):
    router = _router(tmp_path)

    def broken(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    router._conn = type("Broken", (), {"cursor": broken})()
    router.db_path = ":memory:"                                    # force the shared-connection path
    inspector = ArchiveInspector(archive_streamer=_NoArchive(), router=router)
    with caplog.at_level(logging.WARNING, logger="sovereign_server.archive_inspector"):
        with pytest.raises(KeyError):
            inspector.inspect_archive(virtual_uri=URI)
    assert any("database is locked" in record.getMessage() for record in caplog.records)
