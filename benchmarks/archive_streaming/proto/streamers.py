"""Prototype archive streamers D1..D3 (OUTSIDE the repo; never edits it).

All designs subclass the repo's `SovereignArchiveStreamer` (D0) and keep its public surface
(`resolve_virtual_uri`, `stream_archive`, `parse_virtual_uri`, ...), its error types and messages,
and its text extraction (`_extract_openxml_bytes_text`, `_clean_markup_text`) byte for byte.
What changes is only HOW bytes reach the zip parser:

  D1  outer archive opened as a seekable O_RDONLY file object (zipfile reads the central directory
      plus the requested member only); member bytes accumulated in one growing buffer instead of a
      chunk list + b"".join (halves the transient copy). Nested containers are still materialised.
  D2  D1 + nested containers are never materialised: a STORED inner zip is read through a zero-copy
      offset window over the outer fd (os.pread); a DEFLATED inner zip is handed to zipfile as the
      stdlib seekable ZipExtFile (every backward seek re-inflates from the start of the member).
  D2i D2 but DEFLATED inner zips go through `IndexedInflateFile`: a seekable adapter that keeps
      in-memory zlib checkpoints (decompressobj.copy() every `spacing` bytes of output), so a
      backward seek restarts from the nearest checkpoint instead of from zero. One inflate pass per
      request instead of 2-3; CRC-32 of the inner member is still verified on the sequential pass.
  D3  D2i + a per-process cache: open archives (outer ZipFile, inner ZipFile + checkpoint index)
      keyed by (realpath, st_dev, st_ino, st_size, st_mtime_ns), and an LRU of resolved
      ArchiveEntry objects with a byte budget. Single-flight per archive key.

Zero disk extraction holds for every design: nothing is written anywhere; all buffers are RAM.
"""

from __future__ import annotations

import bisect
import collections
import dataclasses
import hashlib
import io
import os
import struct
import sys
import threading
import zipfile
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from core.containers.archive_streamer import (  # the repo's D0 module
    ArchiveEntry,
    ArchiveSecurityError,
    SovereignArchiveStreamer,
    _clean_markup_text,
    _extract_openxml_bytes_text,
)

_BINARY_ASSET_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".cfs", ".cfe", ".si", ".ttf", ".woff", ".woff2",
}
_ZIP_FAMILY = (".zip", ".epub", ".hdx", ".hwics", ".xlsx", ".xlsm", ".docx")
_LOCAL_HEADER = struct.Struct("<4s2B4HL2L2H")  # zipfile.structFileHeader
_O_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)


def _text_for(filename: str, content_bytes: bytes, sha256_hex: str) -> str:
    """Identical to D0's per-member text extraction (fast path and loop path agree)."""
    _, ext = os.path.splitext(filename.lower())
    if ext in _BINARY_ASSET_EXTS:
        return f"[Binary Asset: {filename} ({len(content_bytes)} bytes, sha256={sha256_hex[:16]})]"
    if ext in (".xlsx", ".xlsm", ".docx"):
        return _extract_openxml_bytes_text(content_bytes, filename)
    return _clean_markup_text(content_bytes.decode("utf-8", errors="replace"), filename)


# --------------------------------------------------------------------------- file objects
class PreadFile(io.RawIOBase):
    """Seekable read-only view of [start, start+length) of an O_RDONLY fd, via os.pread.

    Position is private to the object (pread never moves the fd offset), so several views may share
    one fd concurrently. Used for the outer archive (whole file) and, zero-copy, for STORED members.
    """

    def __init__(self, fd: int, start: int = 0, length: Optional[int] = None, owns_fd: bool = False, name: str = ""):
        super().__init__()
        self.fd = fd
        self.start = start
        self.length = os.fstat(fd).st_size - start if length is None else length
        self._pos = 0
        self._owns = owns_fd
        self.name = name

    @classmethod
    def open(cls, path: Union[str, Path]) -> "PreadFile":
        fd = os.open(str(path), _O_FLAGS)
        try:
            return cls(fd, owns_fd=True, name=str(path))
        except Exception:
            os.close(fd)
            raise

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            pos = offset
        elif whence == 1:
            pos = self._pos + offset
        elif whence == 2:
            pos = self.length + offset
        else:
            raise ValueError("bad whence")
        if pos < 0:
            raise OSError("negative seek")
        self._pos = pos
        return pos

    def pread(self, n: int, pos: int) -> bytes:
        if pos >= self.length or n <= 0:
            return b""
        return os.pread(self.fd, min(n, self.length - pos), self.start + pos)

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.length - self._pos
        data = self.pread(n, self._pos)
        self._pos += len(data)
        return data

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)

    def close(self) -> None:
        if not self.closed and self._owns:
            try:
                os.close(self.fd)
            except OSError:
                pass
        super().close()


class InflateIndex:
    """Checkpoints into one raw-DEFLATE stream: (uncompressed_pos, compressed_pos, decompressobj copy)."""

    def __init__(self, spacing: int = 4 << 20):
        self.spacing = spacing
        self.upos: List[int] = [0]
        self.points: List[Tuple[int, int, Optional[object]]] = [(0, 0, None)]
        self.crc_verified = False
        self.lock = threading.Lock()

    def best(self, target: int) -> Tuple[int, int, Optional[object]]:
        with self.lock:
            i = bisect.bisect_right(self.upos, target) - 1
            return self.points[max(0, i)]

    def maybe_add(self, upos: int, cpos: int, dobj) -> None:
        with self.lock:
            if upos >= self.upos[-1] + self.spacing:
                self.upos.append(upos)
                self.points.append((upos, cpos, dobj.copy()))

    def approx_bytes(self) -> int:
        return len(self.points) * (32768 + 7200 + 200)  # zlib window + inflate state + tuple


class IndexedInflateFile(io.RawIOBase):
    """Seekable read-only view of the uncompressed bytes of ONE DEFLATED zip member.

    Reads compressed bytes with os.pread from the outer fd, inflates with zlib (raw, wbits=-15) in
    bounded steps (max 1 MiB of output per step: bounded memory, no bomb amplification) and stops
    at the declared uncompressed size. Backward seeks restore the nearest `InflateIndex` checkpoint.
    CRC-32 is verified whenever the stream is decoded sequentially from 0 to the end (the first
    zipfile open always does that, because the central directory sits at the end).
    """

    CHUNK = 256 * 1024
    OUT_MAX = 1 << 20

    def __init__(self, base: PreadFile, data_start: int, compress_size: int, file_size: int, crc: int, index: InflateIndex):
        super().__init__()
        self._base = base
        self._cstart = data_start
        self._csize = compress_size
        self.length = file_size
        self._crc_expected = crc
        self.index = index
        self._pos = 0
        self._d = None
        self._cpos = 0
        self._upos = 0
        self._tail = b""
        self._blk = b""
        self._blk_start = 0
        self._crc = 0
        self._crc_seq = False
        self.inflated_bytes = 0  # instrumentation: total output produced (work done)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            pos = offset
        elif whence == 1:
            pos = self._pos + offset
        elif whence == 2:
            pos = self.length + offset
        else:
            raise ValueError("bad whence")
        self._pos = max(0, min(pos, self.length))
        return self._pos

    def _restore(self, target: int) -> None:
        upos, cpos, dobj = self.index.best(target)
        self._d = dobj.copy() if dobj is not None else zlib.decompressobj(-15)
        self._upos, self._cpos, self._tail = upos, cpos, b""
        self._crc, self._crc_seq = 0, (upos == 0)

    def _step(self) -> bytes:
        if self._d.eof:
            return b""
        if self._tail:
            data = self._tail
        else:
            n = min(self.CHUNK, self._csize - self._cpos)
            if n <= 0:
                out = self._d.flush()
                if not out:
                    raise zipfile.BadZipFile("Truncated DEFLATE stream in nested member")
                data = b""
            else:
                data = self._base.pread(n, self._cstart + self._cpos)
                if len(data) != n:
                    raise EOFError("Unexpected end of outer archive")
                self._cpos += n
        out = self._d.decompress(data, self.OUT_MAX) if data else out
        self._tail = self._d.unconsumed_tail
        if self._upos + len(out) > self.length:
            raise zipfile.BadZipFile("Nested member inflates beyond its declared size")
        self._blk_start, self._blk = self._upos, out
        self._upos += len(out)
        self.inflated_bytes += len(out)
        if self._crc_seq:
            self._crc = zlib.crc32(out, self._crc)
            if self._upos == self.length:
                if self._crc != self._crc_expected:
                    raise zipfile.BadZipFile("Bad CRC-32 for nested member")
                self.index.crc_verified = True
        if not self._tail and not self._d.eof:
            self.index.maybe_add(self._upos, self._cpos, self._d)
        return out

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.length - self._pos
        n = min(n, self.length - self._pos)
        if n <= 0:
            return b""
        res = bytearray()
        pos = self._pos
        while len(res) < n:
            b0, b1 = self._blk_start, self._blk_start + len(self._blk)
            if b0 <= pos < b1:
                take = self._blk[pos - b0 : pos - b0 + (n - len(res))]
                res += take
                pos += len(take)
                continue
            if self._d is None or self._upos > pos:
                self._restore(pos)
            if self._upos <= pos:
                # skip forward: decode blocks until the block that contains pos
                if not self._step():
                    break
        self._pos = pos
        return bytes(res)

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def _member_data_start(base: PreadFile, info: zipfile.ZipInfo) -> int:
    """Offset (relative to `base`) of a member's data, validated like zipfile.ZipFile.open()."""
    hdr = base.pread(_LOCAL_HEADER.size, info.header_offset)
    if len(hdr) != _LOCAL_HEADER.size:
        raise zipfile.BadZipFile("Truncated file header")
    fh = _LOCAL_HEADER.unpack(hdr)
    if fh[0] != zipfile.stringFileHeader:
        raise zipfile.BadZipFile("Bad magic number for file header")
    fname_len, extra_len = fh[10], fh[11]
    fname = base.pread(fname_len, info.header_offset + _LOCAL_HEADER.size)
    enc = "utf-8" if info.flag_bits & 0x800 else "cp437"
    if fname.decode(enc, errors="replace") != info.orig_filename:
        raise zipfile.BadZipFile(f"File name in directory {info.orig_filename!r} and header {fname!r} differ.")
    return info.header_offset + _LOCAL_HEADER.size + fname_len + extra_len


# --------------------------------------------------------------------------- streamer
class ProtoStreamer(SovereignArchiveStreamer):
    """Configurable prototype. nested_mode: 'materialize' (D1) | 'zipext' (D2) | 'indexed' (D2i/D3)."""

    def __init__(self, *args, nested_mode: str = "materialize", cache: Optional["ArchiveCache"] = None,
                 checkpoint_spacing: int = 4 << 20, **kwargs):
        super().__init__(*args, **kwargs)
        self.nested_mode = nested_mode
        self.cache = cache
        self.checkpoint_spacing = checkpoint_spacing
        self.stats = collections.Counter()

    # -- bounded member read: same checks, same order, same 64 KiB granularity as D0, one buffer
    def _read_member_bytes_bounded(self, zf, info, max_bytes, cumulative_bytes=0):
        buf = io.BytesIO()
        with zf.open(info, mode="r") as member_fp:
            actual_read = 0
            while True:
                chunk = member_fp.read(65536)
                if not chunk:
                    break
                actual_read += len(chunk)
                actual_ratio = float(actual_read) / float(max(1, info.compress_size))
                if actual_ratio > self.max_compression_ratio:
                    raise ArchiveSecurityError(
                        f"Zip-bomb compression ratio exceeded ({actual_ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
                    )
                if actual_read > max_bytes:
                    raise ArchiveSecurityError(f"Archive entry exceeds max_entry_bytes ({actual_read} > {max_bytes})")
                if cumulative_bytes + actual_read > self.max_total_bytes:
                    raise ArchiveSecurityError("Cumulative archive size exceeds max_total_bytes")
                buf.write(chunk)
        return buf.getvalue()  # CPython returns the internal bytes without a copy

    # -- nested containers
    def _check_nested_declared(self, info: zipfile.ZipInfo, cumulative: int) -> None:
        ratio = float(info.file_size) / float(max(1, info.compress_size))
        if ratio > self.max_compression_ratio:
            raise ArchiveSecurityError(
                f"Zip-bomb compression ratio exceeded ({ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
            )
        if cumulative + info.file_size > self.max_total_bytes:
            raise ArchiveSecurityError(
                f"Cumulative archive size exceeds max_total_bytes ({cumulative + info.file_size} > {self.max_total_bytes})"
            )

    def _open_nested(self, zf: zipfile.ZipFile, base, info: zipfile.ZipInfo, cumulative: int, cache_key=None) -> zipfile.ZipFile:
        """Open a zip member that is itself a zip, without extracting it to disk."""
        if self.nested_mode == "materialize" or info.flag_bits & 0x1:
            inner = self._read_member_bytes_bounded(zf=zf, info=info, max_bytes=self.max_total_bytes, cumulative_bytes=cumulative)
            self.stats["nested_materialized_bytes"] += len(inner)
            return zipfile.ZipFile(io.BytesIO(inner), mode="r")
        self._check_nested_declared(info, cumulative)
        if isinstance(base, PreadFile):
            start = _member_data_start(base, info)
            if info.compress_type == zipfile.ZIP_STORED:
                self.stats["nested_window"] += 1
                return zipfile.ZipFile(PreadFile(base.fd, base.start + start, info.compress_size), mode="r")
            if info.compress_type == zipfile.ZIP_DEFLATED and self.nested_mode == "indexed":
                index = self.cache.inflate_index(cache_key, info, self.checkpoint_spacing) if (self.cache and cache_key) else InflateIndex(self.checkpoint_spacing)
                f = IndexedInflateFile(base, start, info.compress_size, info.file_size, info.CRC, index)
                self.stats["nested_indexed"] += 1
                zinner = zipfile.ZipFile(f, mode="r")
                zinner._proto_inflater = f  # instrumentation
                return zinner
        self.stats["nested_zipext"] += 1
        return zipfile.ZipFile(zf.open(info), mode="r")

    # -- the D0 _stream_zip_buffer body, over an already-open ZipFile
    def _stream_zipfile(self, zf: zipfile.ZipFile, base, archive_path_str: str, is_epub: bool = False,
                        target_entry: Optional[str] = None, cache_key=None) -> List[ArchiveEntry]:
        entries: List[ArchiveEntry] = []
        cumulative_bytes = 0
        if target_entry is not None and target_entry in zf.NameToInfo:
            self._validate_entry_path(target_entry)
            info = zf.NameToInfo[target_entry]
            if not info.is_dir() and not info.filename.endswith("/"):
                ratio = self._validate_sizes_and_ratio(info.compress_size, info.file_size, 0)
                content_bytes = self._read_member_bytes_bounded(zf=zf, info=info, max_bytes=self.max_entry_bytes, cumulative_bytes=0)
                final_ratio = float(len(content_bytes)) / float(max(1, info.compress_size))
                if final_ratio > self.max_compression_ratio:
                    raise ArchiveSecurityError(
                        f"Zip-bomb compression ratio exceeded ({final_ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
                    )
                sha256_hex = hashlib.sha256(content_bytes).hexdigest()
                return [ArchiveEntry(
                    virtual_uri=self.build_virtual_uri(archive_path_str, info.filename),
                    archive_path=archive_path_str,
                    entry_name=info.filename,
                    compressed_size=info.compress_size,
                    uncompressed_size=len(content_bytes),
                    compression_ratio=final_ratio if len(content_bytes) > 0 else ratio,
                    content_text=_text_for(info.filename, content_bytes, sha256_hex),
                    sha256_hash=sha256_hex,
                    raw_bytes=content_bytes,
                )]

        for info in zf.infolist():
            self._validate_entry_path(info.filename)
            if info.is_dir() or info.filename.endswith("/"):
                continue
            lower_member = info.filename.lower()
            if lower_member.endswith((".hwics", ".hdx")) and target_entry != info.filename:
                nested_ratio = float(info.file_size) / float(max(1, info.compress_size))
                if nested_ratio > self.max_compression_ratio:
                    raise ArchiveSecurityError(
                        f"Zip-bomb compression ratio exceeded ({nested_ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
                    )
                if cumulative_bytes + info.file_size > self.max_total_bytes:
                    raise ArchiveSecurityError(
                        f"Cumulative archive size exceeds max_total_bytes "
                        f"({cumulative_bytes + info.file_size} > {self.max_total_bytes})"
                    )
                nested_target = target_entry
                if nested_target and nested_target.startswith(f"{info.filename}/"):
                    nested_target = nested_target[len(info.filename) + 1 :]
                with self._open_nested(zf, base, info, cumulative_bytes,
                                       cache_key=(cache_key, info.filename) if cache_key else None) as inner_zf:
                    nested_entries = self._stream_zipfile(inner_zf, None, f"{archive_path_str}!{info.filename}",
                                                          is_epub=False, target_entry=nested_target)
                for ne in nested_entries:
                    cumulative_bytes += ne.uncompressed_size
                    if cumulative_bytes > self.max_total_bytes:
                        raise ArchiveSecurityError("Cumulative archive size exceeds max_total_bytes")
                entries.extend(nested_entries)
                continue
            ratio = self._validate_sizes_and_ratio(info.compress_size, info.file_size, cumulative_bytes)
            if target_entry is not None and info.filename != target_entry:
                continue
            if target_entry is None and not self._should_include_entry(info.filename, is_epub=is_epub):
                continue
            content_bytes = self._read_member_bytes_bounded(zf=zf, info=info, max_bytes=self.max_entry_bytes, cumulative_bytes=cumulative_bytes)
            cumulative_bytes += len(content_bytes)
            final_ratio = float(len(content_bytes)) / float(max(1, info.compress_size))
            if final_ratio > self.max_compression_ratio:
                raise ArchiveSecurityError(
                    f"Zip-bomb compression ratio exceeded ({final_ratio:.2f}:1 > {self.max_compression_ratio:.2f}:1)"
                )
            sha256_hex = hashlib.sha256(content_bytes).hexdigest()
            entries.append(ArchiveEntry(
                virtual_uri=self.build_virtual_uri(archive_path_str, info.filename),
                archive_path=archive_path_str,
                entry_name=info.filename,
                compressed_size=info.compress_size,
                uncompressed_size=len(content_bytes),
                compression_ratio=final_ratio if len(content_bytes) > 0 else ratio,
                content_text=_text_for(info.filename, content_bytes, sha256_hex),
                sha256_hash=sha256_hex,
                raw_bytes=content_bytes,
            ))
        return entries

    # -- dispatch
    def _dispatch_archive(self, archive_path, target_entry=None):
        outer_path_str, inner_container_entry = self.parse_compound_archive_path(archive_path)
        path_obj = Path(outer_path_str)
        archive_path_str = str(archive_path)
        lower_name = path_obj.name.lower()

        if self.cache is not None:
            return self.cache.dispatch(self, path_obj, archive_path_str, inner_container_entry, target_entry)

        if inner_container_entry is not None:
            self._validate_entry_path(inner_container_entry)
            with PreadFile.open(path_obj) as base, zipfile.ZipFile(base, mode="r") as outer_zf:
                try:
                    inner_info = outer_zf.getinfo(inner_container_entry)
                except KeyError as exc:
                    raise KeyError(f"Nested container {inner_container_entry!r} not found in {outer_path_str!r}") from exc
                with self._open_nested(outer_zf, base, inner_info, 0) as inner_zf:
                    res = self._stream_zipfile(inner_zf, None, archive_path_str,
                                               is_epub=inner_container_entry.lower().endswith(".epub"),
                                               target_entry=target_entry)
                    f = getattr(inner_zf, "_proto_inflater", None)
                    if f is not None:
                        self.stats["inflated_bytes"] += f.inflated_bytes
                        self.stats["checkpoints"] = len(f.index.points)
                    return res

        is_zip_family = lower_name.endswith(_ZIP_FAMILY)
        if not is_zip_family and not lower_name.endswith((".tar.zst", ".tzst", ".tar.gz", ".tgz", ".tar")):
            with PreadFile.open(path_obj) as probe:
                is_zip_family = probe.pread(4, 0) == b"PK\x03\x04"
        if is_zip_family:
            with PreadFile.open(path_obj) as base, zipfile.ZipFile(base, mode="r") as zf:
                return self._stream_zipfile(zf, base, archive_path_str, is_epub=lower_name.endswith(".epub"),
                                            target_entry=target_entry)
        # tar family: unchanged D0 behaviour (not on the Huawei path; see PLAN.md phase 3)
        return super()._dispatch_archive(archive_path, target_entry)


# --------------------------------------------------------------------------- D3 cache
class _OpenArchive:
    def __init__(self, key, base: PreadFile, zf: zipfile.ZipFile):
        self.key = key
        self.base = base
        self.zf = zf
        self.inner: Dict[str, zipfile.ZipFile] = {}
        self.lock = threading.RLock()

    def close(self):
        for z in self.inner.values():
            z.close()
        self.zf.close()
        self.base.close()


class ArchiveCache:
    """Per-process cache: open archives (central directories + inflate checkpoints) and resolved entries."""

    def __init__(self, max_archives: int = 8, entry_budget_bytes: int = 64 << 20, max_entry_fraction: float = 0.25):
        self.max_archives = max_archives
        self.entry_budget = entry_budget_bytes
        self.max_entry_bytes = int(entry_budget_bytes * max_entry_fraction)
        self._lock = threading.Lock()
        self._archives: "collections.OrderedDict[tuple, _OpenArchive]" = collections.OrderedDict()
        self._key_locks: Dict[str, threading.Lock] = {}
        self._indexes: Dict[tuple, InflateIndex] = {}
        self._entries: "collections.OrderedDict[tuple, Tuple[ArchiveEntry, int]]" = collections.OrderedDict()
        self._entry_bytes = 0
        self.stats = collections.Counter()

    @staticmethod
    def _stat_key(path: Path, st: os.stat_result) -> tuple:
        return (os.path.realpath(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

    def inflate_index(self, key, info: zipfile.ZipInfo, spacing: int) -> InflateIndex:
        with self._lock:
            idx = self._indexes.get(key)
            if idx is None:
                idx = self._indexes[key] = InflateIndex(spacing)
            return idx

    def _open(self, path: Path) -> _OpenArchive:
        rp = os.path.realpath(path)
        with self._lock:
            klock = self._key_locks.setdefault(rp, threading.Lock())
        with klock:  # single-flight per path
            key = self._stat_key(path, os.stat(path))
            with self._lock:
                arc = self._archives.get(key)
                if arc is not None:
                    self._archives.move_to_end(key)
                    self.stats["archive_hit"] += 1
                    return arc
                stale = [k for k in self._archives if k[0] == rp]
                for k in stale:
                    self._archives.pop(k).close()
                    self.stats["archive_invalidated"] += 1
            base = PreadFile.open(path)
            if self._stat_key(path, os.fstat(base.fd)) != key:  # replaced between stat and open
                base.close()
                raise OSError(f"Archive changed while opening: {path}")
            arc = _OpenArchive(key, base, zipfile.ZipFile(base, mode="r"))
            with self._lock:
                self._archives[key] = arc
                self.stats["archive_miss"] += 1
                while len(self._archives) > self.max_archives:
                    self._archives.popitem(last=False)[1].close()
            return arc

    def _get_entry(self, ekey):
        with self._lock:
            hit = self._entries.get(ekey)
            if hit is None:
                self.stats["entry_miss"] += 1
                return None
            self._entries.move_to_end(ekey)
            self.stats["entry_hit"] += 1
            return dataclasses.replace(hit[0])

    def _put_entry(self, ekey, entry: ArchiveEntry) -> None:
        cost = sys.getsizeof(entry.content_text) + len(entry.raw_bytes) + 512
        if cost > self.max_entry_bytes:
            return
        with self._lock:
            if ekey in self._entries:
                return
            self._entries[ekey] = (entry, cost)
            self._entry_bytes += cost
            while self._entry_bytes > self.entry_budget and self._entries:
                _, (_, c) = self._entries.popitem(last=False)
                self._entry_bytes -= c

    def dispatch(self, streamer: ProtoStreamer, path_obj: Path, archive_path_str: str,
                 inner_container_entry: Optional[str], target_entry: Optional[str]) -> List[ArchiveEntry]:
        lower_name = path_obj.name.lower()
        if inner_container_entry is None and not lower_name.endswith(_ZIP_FAMILY):
            c, streamer.cache = streamer.cache, None
            try:
                return streamer._dispatch_archive(archive_path_str, target_entry)
            finally:
                streamer.cache = c
        if inner_container_entry is not None:
            streamer._validate_entry_path(inner_container_entry)
        arc = self._open(path_obj)
        ekey = (arc.key, inner_container_entry, target_entry)
        if target_entry is not None:
            cached = self._get_entry(ekey)
            if cached is not None:
                return [cached]
        if inner_container_entry is None:
            res = streamer._stream_zipfile(arc.zf, arc.base, archive_path_str, is_epub=lower_name.endswith(".epub"),
                                           target_entry=target_entry, cache_key=arc.key)
        else:
            with arc.lock:
                inner_zf = arc.inner.get(inner_container_entry)
                if inner_zf is None:
                    try:
                        inner_info = arc.zf.getinfo(inner_container_entry)
                    except KeyError as exc:
                        raise KeyError(f"Nested container {inner_container_entry!r} not found in {str(path_obj)!r}") from exc
                    inner_zf = streamer._open_nested(arc.zf, arc.base, inner_info, 0, cache_key=(arc.key, inner_container_entry))
                    arc.inner[inner_container_entry] = inner_zf
                    self.stats["inner_open"] += 1
            res = streamer._stream_zipfile(inner_zf, None, archive_path_str,
                                           is_epub=inner_container_entry.lower().endswith(".epub"), target_entry=target_entry)
        if target_entry is not None and len(res) == 1:
            self._put_entry(ekey, res[0])
        return res

    def index_bytes(self) -> int:
        return sum(i.approx_bytes() for i in self._indexes.values())


# --------------------------------------------------------------------------- registry
def make_streamer(design: str, cache: Optional[ArchiveCache] = None) -> SovereignArchiveStreamer:
    if design == "D0":
        return SovereignArchiveStreamer()
    if design == "D1":
        return ProtoStreamer(nested_mode="materialize")
    if design == "D2":
        return ProtoStreamer(nested_mode="zipext")
    if design == "D2i":
        return ProtoStreamer(nested_mode="indexed")
    if design in ("D3", "D4"):
        return ProtoStreamer(nested_mode="indexed", cache=cache or ArchiveCache())
    raise ValueError(design)
