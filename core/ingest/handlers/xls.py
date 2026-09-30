"""
Legacy Excel (.xls, BIFF8) handler, standard library only.

Two layers, both implemented here because no spreadsheet library is available in the air-gapped
appliance: an OLE2 compound-file reader (FAT / mini-FAT / directory) and a BIFF8 record reader
(workbook globals, shared string table with CONTINUE records, worksheet cells: LABELSST, LABEL,
NUMBER, RK, MULRK, FORMULA cached results, BOOLERR, and MERGEDCELLS). The cell grid then goes
through the same grid logic as `.xlsx`, so merged headers behave identically.

Not supported (reported as HandlerError so the pipeline can flag the file): encrypted workbooks
(FILEPASS) and BIFF5 (Excel 5/95) files.
"""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

from ..base import FormatHandler, HandlerError, ParsedDocument
from ..registry import register
from .tables import Cells, Merge, fmt_number, grid_to_section

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
END_OF_CHAIN, FREE_SECT = 0xFFFFFFFE, 0xFFFFFFFF
MAX_STREAM = 512 * 1024 * 1024


class Ole2:
    """Minimal OLE2 compound-file reader (read-only, in memory)."""

    def __init__(self, data: bytes) -> None:
        if data[:8] != OLE_MAGIC or len(data) < 512:
            raise HandlerError("not an OLE2 compound file")
        self.data = data
        u16 = lambda o: struct.unpack_from("<H", data, o)[0]
        u32 = lambda o: struct.unpack_from("<I", data, o)[0]
        self.sector = 1 << u16(0x1E)
        self.mini_sector = 1 << u16(0x20)
        self.cutoff = u32(0x38)
        dir_start, minifat_start = u32(0x30), u32(0x3C)
        difat_start, num_difat = u32(0x44), u32(0x48)
        difat = [x for x in struct.unpack_from("<109I", data, 0x4C) if x != FREE_SECT]
        sid, hops = difat_start, 0
        while sid not in (END_OF_CHAIN, FREE_SECT) and hops < max(num_difat, 1) + 8:
            sec = self._sector(sid)
            n = self.sector // 4 - 1
            difat += [x for x in struct.unpack_from(f"<{n}I", sec, 0) if x != FREE_SECT]
            sid = struct.unpack_from("<I", sec, n * 4)[0]
            hops += 1
        fat: List[int] = []
        for sid in difat:
            fat += list(struct.unpack_from(f"<{self.sector // 4}I", self._sector(sid), 0))
        self.fat = fat
        self.dir_bytes = self._chain(dir_start)
        self.entries = self._entries()
        root = self.entries[0] if self.entries else None
        self.ministream = self._chain(root[2]) if root and root[2] not in (END_OF_CHAIN, FREE_SECT) else b""
        self.minifat: List[int] = []
        if minifat_start not in (END_OF_CHAIN, FREE_SECT):
            mf = self._chain(minifat_start)
            self.minifat = list(struct.unpack_from(f"<{len(mf) // 4}I", mf, 0))

    def _sector(self, sid: int) -> bytes:
        off = (sid + 1) * self.sector
        if off + self.sector > len(self.data):
            raise HandlerError("sector beyond end of file")
        return self.data[off : off + self.sector]

    def _chain(self, start: int) -> bytes:
        out, sid, hops = [], start, 0
        while sid not in (END_OF_CHAIN, FREE_SECT):
            if hops > len(self.fat) or sid >= len(self.fat):
                raise HandlerError("corrupt FAT chain")
            out.append(self._sector(sid))
            sid = self.fat[sid]
            hops += 1
            if hops * self.sector > MAX_STREAM:
                raise HandlerError("stream exceeds size guard")
        return b"".join(out)

    def _entries(self) -> List[Tuple[str, int, int, int]]:
        out = []
        for off in range(0, len(self.dir_bytes) - 127, 128):
            e = self.dir_bytes[off : off + 128]
            nlen = struct.unpack_from("<H", e, 0x40)[0]
            name = e[: max(nlen - 2, 0)].decode("utf-16le", "ignore")
            typ = e[0x42]
            start = struct.unpack_from("<I", e, 0x74)[0]
            size = struct.unpack_from("<I", e, 0x78)[0]
            out.append((name, typ, start, size))
        return out

    def stream(self, *names: str) -> Optional[bytes]:
        wanted = {n.lower() for n in names}
        for name, typ, start, size in self.entries:
            if typ == 2 and name.lower() in wanted:
                if size < self.cutoff:
                    out, sid, hops = [], start, 0
                    while sid not in (END_OF_CHAIN, FREE_SECT) and hops <= len(self.minifat):
                        out.append(self.ministream[sid * self.mini_sector : (sid + 1) * self.mini_sector])
                        sid = self.minifat[sid] if sid < len(self.minifat) else END_OF_CHAIN
                        hops += 1
                    return b"".join(out)[:size]
                return self._chain(start)[:size]
        return None


class _Sst:
    """Reads the shared string table across its CONTINUE segments (the flag byte is repeated at each split)."""

    def __init__(self, segs: List[bytes]) -> None:
        self.segs, self.si, self.pos = segs, 0, 0

    def _need(self, n: int) -> bytes:
        # a segment that ends exactly at a string boundary: the next string starts in the next segment
        while self.si < len(self.segs) and self.pos >= len(self.segs[self.si]):
            self.si, self.pos = self.si + 1, 0
        if self.si >= len(self.segs):
            raise HandlerError("SST truncated")
        seg = self.segs[self.si]
        if self.pos + n > len(seg):
            raise HandlerError("SST field split across records")
        b = seg[self.pos : self.pos + n]
        self.pos += n
        return b

    def _skip(self, n: int) -> None:
        while n > 0 and self.si < len(self.segs):
            take = min(n, len(self.segs[self.si]) - self.pos)
            self.pos += take
            n -= take
            if n > 0:
                self.si, self.pos = self.si + 1, 0

    def string(self) -> str:
        cch = struct.unpack("<H", self._need(2))[0]
        flags = self._need(1)[0]
        wide, ext, rich = bool(flags & 1), bool(flags & 4), bool(flags & 8)
        runs = struct.unpack("<H", self._need(2))[0] if rich else 0
        ext_len = struct.unpack("<I", self._need(4))[0] if ext else 0
        out: List[str] = []
        left = cch
        while left > 0:
            seg = self.segs[self.si]
            bpc = 2 if wide else 1
            n = min(left, (len(seg) - self.pos) // bpc)
            raw = seg[self.pos : self.pos + n * bpc]
            out.append(raw.decode("utf-16le", "replace") if wide else raw.decode("latin-1"))
            self.pos += n * bpc
            left -= n
            if left > 0:  # continue in the next record, which starts with its own flag byte
                self.si, self.pos = self.si + 1, 0
                if self.si >= len(self.segs):
                    raise HandlerError("SST truncated in string")
                wide = bool(self.segs[self.si][0] & 1)
                self.pos = 1
        self._skip(4 * runs + ext_len)
        return "".join(out)


def _records(data: bytes, start: int = 0):
    pos = start
    while pos + 4 <= len(data):
        rid, ln = struct.unpack_from("<HH", data, pos)
        yield rid, data[pos + 4 : pos + 4 + ln], pos
        pos += 4 + ln


def _unistr16(b: bytes, pos: int = 0) -> str:
    cch = struct.unpack_from("<H", b, pos)[0]
    flags = b[pos + 2]
    raw = b[pos + 3 : pos + 3 + cch * (2 if flags & 1 else 1)]
    return raw.decode("utf-16le", "replace") if flags & 1 else raw.decode("latin-1")


def _rk(v: int) -> str:
    if v & 2:
        x = float(struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFC))[0] >> 2)
    else:
        x = struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return fmt_number(x / 100 if v & 1 else x)


@register
class XlsHandler(FormatHandler):
    name = "xls"
    version = "1"
    extensions = (".xls",)

    @classmethod
    def detect(cls, name: str, head: bytes) -> bool:
        return super().detect(name, head) and head[:8] == OLE_MAGIC

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        try:
            return self._parse(name, data)
        except HandlerError:
            raise
        except (struct.error, IndexError, ValueError, KeyError) as exc:
            raise HandlerError(f"corrupt .xls: {exc}") from exc

    def _parse(self, name: str, data: bytes) -> ParsedDocument:
        wb = Ole2(data).stream("Workbook", "Book")
        if wb is None:
            raise HandlerError("no Workbook stream (BIFF5 or not an Excel file)")
        if len(wb) < 8 or struct.unpack_from("<H", wb, 0)[0] != 0x0809:
            raise HandlerError("Workbook stream does not start with a BOF record")
        if struct.unpack_from("<H", wb, 4)[0] < 0x0600:
            raise HandlerError("BIFF5 / older Excel files are not supported")
        sheets: List[Tuple[str, int, int, int]] = []  # name, offset, state, type
        sst_segs: List[bytes] = []
        sst_total = 0
        last_was_sst = False
        for rid, d, _ in _records(wb):
            if rid == 0x002F:
                raise HandlerError("workbook is encrypted (FILEPASS)")
            if rid == 0x00FC:
                sst_segs, sst_total, last_was_sst = [d[8:]], struct.unpack_from("<I", d, 4)[0], True
                continue
            if rid == 0x003C and last_was_sst:
                sst_segs.append(d)
                continue
            last_was_sst = False
            if rid == 0x0085:
                off, state, typ = struct.unpack_from("<IBB", d, 0)
                cch, flags = d[6], d[7]
                raw = d[8 : 8 + cch * (2 if flags & 1 else 1)]
                sheets.append(((raw.decode("utf-16le", "replace") if flags & 1 else raw.decode("latin-1")), off, state, typ))
            elif rid == 0x000A:
                break
        sst: List[str] = []
        if sst_segs:
            reader = _Sst(sst_segs)
            for _ in range(sst_total):
                sst.append(reader.string())

        doc = ParsedDocument(name=name, format=self.name, title=self.title_from(name))
        for sname, off, state, typ in sheets:
            if typ != 0:  # 0 = worksheet; charts / macro sheets carry no cells
                continue
            cells, merges = self._sheet(wb, off, sst)
            section = grid_to_section(sname, cells, merges)
            if section is not None:
                doc.sections.append(section)
            if state:
                doc.warnings.append(f"sheet {sname!r} is hidden (indexed anyway)")
        doc.metadata["sheets"] = str(len(doc.sections))
        doc.metadata["dates"] = "stored as raw Excel serial numbers"
        return doc

    @staticmethod
    def _sheet(wb: bytes, off: int, sst: List[str]) -> Tuple[Cells, List[Merge]]:
        cells: Cells = {}
        merges: List[Merge] = []
        depth = 0
        pending: Optional[Tuple[int, int]] = None
        for rid, d, _ in _records(wb, off):
            if rid == 0x0809:
                depth += 1
                continue
            if rid == 0x000A:
                depth -= 1
                if depth <= 0:
                    break
                continue
            if depth != 1:  # nested substreams (charts / embedded objects)
                continue
            if rid == 0x00FD:  # LABELSST
                r, c, _xf, i = struct.unpack_from("<HHHI", d, 0)
                cells[(r + 1, c + 1)] = sst[i] if i < len(sst) else ""
            elif rid == 0x0204:  # LABEL
                r, c, _xf = struct.unpack_from("<HHH", d, 0)
                cells[(r + 1, c + 1)] = _unistr16(d, 6)
            elif rid == 0x0203:  # NUMBER
                r, c, _xf, x = struct.unpack_from("<HHHd", d, 0)
                cells[(r + 1, c + 1)] = fmt_number(x)
            elif rid == 0x027E:  # RK
                r, c, _xf, v = struct.unpack_from("<HHHI", d, 0)
                cells[(r + 1, c + 1)] = _rk(v)
            elif rid == 0x00BD:  # MULRK
                r, c0 = struct.unpack_from("<HH", d, 0)
                n = (len(d) - 6) // 6
                for k in range(n):
                    _xf, v = struct.unpack_from("<HI", d, 4 + 6 * k)
                    cells[(r + 1, c0 + k + 1)] = _rk(v)
            elif rid == 0x0205:  # BOOLERR
                r, c, _xf, val, is_err = struct.unpack_from("<HHHBB", d, 0)
                cells[(r + 1, c + 1)] = "#ERR" if is_err else ("TRUE" if val else "FALSE")
            elif rid == 0x0006:  # FORMULA: cached result
                r, c = struct.unpack_from("<HH", d, 0)
                res = d[6:14]
                if res[6:8] == b"\xff\xff":
                    kind = res[0]
                    if kind == 0:
                        pending = (r + 1, c + 1)  # string result follows in a STRING record
                    elif kind == 1:
                        cells[(r + 1, c + 1)] = "TRUE" if res[2] else "FALSE"
                else:
                    cells[(r + 1, c + 1)] = fmt_number(struct.unpack("<d", res)[0])
            elif rid == 0x0207 and pending is not None:  # STRING
                cells[pending] = _unistr16(d, 0)
                pending = None
            elif rid == 0x00E5:  # MERGEDCELLS
                n = struct.unpack_from("<H", d, 0)[0]
                for k in range(n):
                    r1, r2, c1, c2 = struct.unpack_from("<HHHH", d, 2 + 8 * k)
                    merges.append((r1 + 1, c1 + 1, r2 + 1, c2 + 1))
        return {k: v for k, v in cells.items() if v is not None and str(v).strip()}, merges
