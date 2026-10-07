"""ADR-16: a bounded per-process cache for archive reads.

It keeps two things, so a second preview of the same package costs about a millisecond instead of a second:
  * open archives: the parsed central directory of the outer zip and of each opened inner package, plus the
    inflate checkpoint index of every deflated inner package (about 3.3 MB for a 350 MB package);
  * a small LRU of resolved entries, with a byte budget.

Archives are keyed by (real path, device, inode, size, mtime in ns): replacing or rewriting a file in place
invalidates it. An archive evicted or invalidated while a request is still reading it is closed only when the
last request lets go. Nothing is written to disk.

Sized by environment: AEGIS_ARCHIVE_CACHE=0 disables it, AEGIS_ARCHIVE_CACHE_ARCHIVES (default 8) and
AEGIS_ARCHIVE_ENTRY_CACHE_MB (default 64) bound it.
"""

from __future__ import annotations

import collections
import contextlib
import dataclasses
import os
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from .archive_io import InflateIndex, PreadFile


class OpenArchive:
    """An open outer zip and the inner packages already opened from it."""

    def __init__(self, key: tuple, base: PreadFile, zf: zipfile.ZipFile):
        self.key = key
        self.base = base
        self.zf = zf
        self.inner: Dict[str, zipfile.ZipFile] = {}
        self.lock = threading.RLock()
        self.users = 0
        self.retired = False

    def close(self) -> None:
        for inner in self.inner.values():
            inner.close()
        self.zf.close()
        self.base.close()


class ArchiveCache:
    def __init__(self, max_archives: int = 8, entry_budget_bytes: int = 64 << 20, max_entry_fraction: float = 0.25):
        self.max_archives = max_archives
        self.entry_budget = entry_budget_bytes
        self.max_entry_bytes = int(entry_budget_bytes * max_entry_fraction)
        self._lock = threading.Lock()
        self._archives: "collections.OrderedDict[tuple, OpenArchive]" = collections.OrderedDict()
        self._open_locks: Dict[str, threading.Lock] = {}
        self._indexes: Dict[tuple, InflateIndex] = {}
        self._entries: "collections.OrderedDict[tuple, Tuple[Any, int]]" = collections.OrderedDict()
        self.entry_bytes = 0
        self.stats: "collections.Counter[str]" = collections.Counter()

    # -- open archives
    @staticmethod
    def _stat_key(path: Path, st: os.stat_result) -> tuple:
        return (os.path.realpath(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

    def _retire(self, arc: OpenArchive) -> None:
        """Called with self._lock held: close now if nobody is reading it, else when the last reader leaves."""
        arc.retired = True
        if arc.users == 0:
            arc.close()

    @contextlib.contextmanager
    def archive(self, path: Path) -> Iterator[OpenArchive]:
        arc = self._acquire(path)
        try:
            yield arc
        finally:
            with self._lock:
                arc.users -= 1
                if arc.retired and arc.users == 0:
                    arc.close()

    def _acquire(self, path: Path) -> OpenArchive:
        real = os.path.realpath(path)
        with self._lock:
            open_lock = self._open_locks.setdefault(real, threading.Lock())
        with open_lock:  # one opener per path at a time
            key = self._stat_key(path, os.stat(path))
            with self._lock:
                arc = self._archives.get(key)
                if arc is not None:
                    self._archives.move_to_end(key)
                    arc.users += 1
                    self.stats["archive_hit"] += 1
                    return arc
                for stale in [k for k in self._archives if k[0] == real]:
                    self._retire(self._archives.pop(stale))
                    self._indexes = {k: v for k, v in self._indexes.items() if k[0] != stale}
                    self.stats["archive_invalidated"] += 1
            base = PreadFile.open(path)
            if self._stat_key(path, os.fstat(base.fd)) != key:  # replaced between the stat and the open
                base.close()
                raise OSError(f"Archive changed while opening: {path}")
            try:
                arc = OpenArchive(key, base, zipfile.ZipFile(base, mode="r"))
            except Exception:
                base.close()
                raise
            with self._lock:
                self._archives[key] = arc
                arc.users += 1
                self.stats["archive_miss"] += 1
                while len(self._archives) > self.max_archives:
                    oldest_key, oldest = self._archives.popitem(last=False)
                    self._retire(oldest)
                    self._indexes = {k: v for k, v in self._indexes.items() if k[0] != oldest_key}
            return arc

    def inflate_index(self, key: tuple, spacing: int) -> InflateIndex:
        with self._lock:
            idx = self._indexes.get(key)
            if idx is None:
                idx = self._indexes[key] = InflateIndex(spacing)
            return idx

    def index_bytes(self) -> int:
        with self._lock:
            return sum(i.approx_bytes() for i in self._indexes.values())

    # -- resolved entries
    def get_entry(self, key: tuple) -> Optional[Any]:
        with self._lock:
            hit = self._entries.get(key)
            if hit is None:
                self.stats["entry_miss"] += 1
                return None
            self._entries.move_to_end(key)
            self.stats["entry_hit"] += 1
            return dataclasses.replace(hit[0])  # a copy: callers cannot alter what is cached

    def put_entry(self, key: tuple, entry: Any) -> None:
        cost = sys.getsizeof(entry.content_text) + len(entry.raw_bytes) + 512
        if cost > self.max_entry_bytes:
            return
        with self._lock:
            if key in self._entries:
                return
            self._entries[key] = (dataclasses.replace(entry), cost)
            self.entry_bytes += cost
            while self.entry_bytes > self.entry_budget and self._entries:
                _, (_, evicted_cost) = self._entries.popitem(last=False)
                self.entry_bytes -= evicted_cost


_shared: Optional[ArchiveCache] = None
_shared_lock = threading.Lock()


def shared_cache() -> Optional[ArchiveCache]:
    """The process-wide cache every streamer uses by default (so per-call streamers benefit too), or None if disabled."""
    global _shared
    if os.environ.get("AEGIS_ARCHIVE_CACHE", "1") == "0":
        return None
    with _shared_lock:
        if _shared is None:
            _shared = ArchiveCache(
                max_archives=int(os.environ.get("AEGIS_ARCHIVE_CACHE_ARCHIVES", "8")),
                entry_budget_bytes=int(os.environ.get("AEGIS_ARCHIVE_ENTRY_CACHE_MB", "64")) << 20,
            )
        return _shared
