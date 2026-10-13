#!/usr/bin/env python3
"""
Finding R2: Concurrency stress test on SovereignQueryRouter.

Tests concurrent write and read operations across multiple worker threads
sharing a single SovereignQueryRouter instance. Because SQLite connections
do not natively support concurrent transactional write interleaving on a
single connection handle without a connection pool or write serialization mutex,
this test demonstrates the requirement for connection pooling or write serialization.
Marked @pytest.mark.xfail per Wave 2 specification.
"""

import concurrent.futures
import sqlite3
import threading
import pytest

from core.router.query_router import SovereignQueryRouter
from core.security import ClearanceLevel


@pytest.mark.xfail(reason="Concurrent router access requires connection pool / write serialization")
def test_concurrent_router_writes_and_reads(tmp_path):
    """
    Simulates concurrent writers and readers hitting SovereignQueryRouter.
    Without connection pooling or a write-serialization lock, concurrent
    transactions on the single shared SQLite connection fail with
    sqlite3.OperationalError or sqlite3.ProgrammingError.
    """
    db_file = tmp_path / "concurrent_router.db"
    router = SovereignQueryRouter(db_path=db_file)

    # Initial seed
    router.index_document(
        doc_identifier="SEED-001",
        title="Initial Seed Record",
        content="Baseline content for query router verification.",
        clearance_level=ClearanceLevel.PUBLIC,
    )

    errors = []
    num_threads = 12
    iterations_per_thread = 20

    def worker_write(thread_id: int):
        for i in range(iterations_per_thread):
            doc_id = f"DOC-T{thread_id}-{i}"
            try:
                router.index_document(
                    doc_identifier=doc_id,
                    title=f"Concurrent Doc {doc_id}",
                    content=f"Telemetry content written by worker thread {thread_id} iteration {i}",
                    clearance_level=ClearanceLevel.PUBLIC,
                    metadata={"thread": thread_id, "iteration": i},
                )
            except Exception as exc:
                errors.append(exc)

    def worker_read(thread_id: int):
        for i in range(iterations_per_thread):
            try:
                results = router.search_documents(
                    query_text="telemetry content",
                    user_clearance="public",
                    limit=5,
                )
                assert isinstance(results, list)
            except Exception as exc:
                errors.append(exc)

    threads = []
    for t_id in range(num_threads // 2):
        threads.append(threading.Thread(target=worker_write, args=(t_id,)))
        threads.append(threading.Thread(target=worker_read, args=(t_id,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    router.close()

    if errors:
        # Re-raise the first error so xfail records the failure mode
        raise errors[0]

    # If by chance it did not fail, ensure all documents were safely written
    con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    count = con.execute("SELECT COUNT(*) FROM document_records").fetchone()[0]
    con.close()
    expected = 1 + (num_threads // 2) * iterations_per_thread
    assert count == expected, f"Expected {expected} records, found {count}"
