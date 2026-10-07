"""ADR-16: random-access, read-only file objects so archives are never read whole into RAM.

`PreadFile`           a seekable view of an O_RDONLY descriptor (or a slice of it) through os.pread. The
                      position is private to the view, so many views can share one descriptor.
`IndexedInflateFile`  a seekable view of the uncompressed bytes of ONE deflated zip member, for the case of
                      a package (.hwics) stored deflated inside an outer zip. zlib cannot seek, so it keeps
                      in-memory checkpoints (decompressobj copies, every few MiB of output) and a backward
                      seek restarts from the nearest one instead of from zero.

Nothing here writes to disk, and every buffer is bounded: inflation produces at most OUT_MAX bytes per step
and stops at the size the zip header declared, so a lying header cannot amplify (ADR-07 zip-bomb guard).
"""

from __future__ import annotations

import bisect
import io
import os
import struct
import threading
import zipfile
import zlib
from pathlib import Path
from typing import List, Optional, Tuple, Union

_LOCAL_HEADER = struct.Struct("<4s2B4HL2L2H")  # zipfile.structFileHeader
O_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)


class PreadFile(io.RawIOBase):
    """Seekable read-only view of [start, start + length) of an O_RDONLY descriptor."""

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
        fd = os.open(str(path), O_FLAGS)
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
    """Checkpoints into one raw DEFLATE stream: (uncompressed position, compressed position, decompressobj copy)."""

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
    """Seekable read-only view of the uncompressed bytes of one DEFLATED zip member.

    CRC-32 is verified whenever the stream is decoded sequentially from 0 to the end; the first open of a
    zip always does that, because its central directory sits at the end.
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
        self.inflated_bytes = 0   # total output produced: the work done, for tests and benchmarks

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

    def _step(self) -> Optional[bytes]:
        """Inflate the next block; None once the stream has ended (an empty block is not the end)."""
        if self._d.eof:
            return None
        if self._tail:
            out = self._d.decompress(self._tail, self.OUT_MAX)
        else:
            n = min(self.CHUNK, self._csize - self._cpos)
            if n <= 0:
                out = self._d.flush()
                if not out:
                    raise zipfile.BadZipFile("Truncated DEFLATE stream in nested member")
            else:
                data = self._base.pread(n, self._cstart + self._cpos)
                if len(data) != n:
                    raise EOFError("Unexpected end of outer archive")
                self._cpos += n
                out = self._d.decompress(data, self.OUT_MAX)
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
                take = self._blk[pos - b0: pos - b0 + (n - len(res))]
                res += take
                pos += len(take)
                continue
            if self._d is None or self._upos > pos:
                self._restore(pos)
            if self._upos <= pos and self._step() is None:
                break
        self._pos = pos
        return bytes(res)

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def member_data_start(base: PreadFile, info: zipfile.ZipInfo) -> int:
    """Offset (relative to `base`) of a member's data, validated the way zipfile.ZipFile.open() validates it."""
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
