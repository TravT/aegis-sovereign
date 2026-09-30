"""Builders for small, real-format fixtures (docx, xlsx, pptx, xls/BIFF8-in-OLE2) used by the ingest tests."""

from __future__ import annotations

import io
import struct
import zipfile
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ------------------------------------------------------------------------------------- docx
def make_docx(
    body: Sequence[Tuple[str, str]],
    tables: Optional[Dict[int, List[List[str]]]] = None,
    footnotes: Sequence[str] = (),
    sdt_indexes: Sequence[int] = (),
    title: str = "",
) -> bytes:
    """body = [(styleId, text)]; tables = {insert-before-index: rows}; sdt_indexes wrap a paragraph in a content control."""
    styles = f"""<w:styles xmlns:w="{W_NS}">
      <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
      <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>
      <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/></w:style>
      <w:style w:type="paragraph" w:styleId="MyHeading"><w:name w:val="My Heading"/><w:basedOn w:val="Heading2"/></w:style>
      <w:style w:type="paragraph" w:styleId="Outlined"><w:name w:val="Outlined"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
      <w:style w:type="paragraph" w:styleId="TableHeading"><w:name w:val="Table Heading"/></w:style>
      <w:style w:type="paragraph" w:styleId="TOC1"><w:name w:val="toc 1"/></w:style>
      <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
    </w:styles>"""
    parts: List[str] = []
    for i, (style, text) in enumerate(body):
        if tables and i in tables:
            rows = "".join(
                "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{escape(c)}</w:t></w:r></w:p></w:tc>" for c in row) + "</w:tr>"
                for row in tables[i]
            )
            parts.append(f"<w:tbl>{rows}</w:tbl>")
        p = f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        parts.append(f"<w:sdt><w:sdtContent>{p}</w:sdtContent></w:sdt>" if i in sdt_indexes else p)
    doc = f'<w:document xmlns:w="{W_NS}"><w:body>{"".join(parts)}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        if footnotes:
            fn = "".join(
                f'<w:footnote w:id="{i + 1}"><w:p><w:r><w:t>{escape(t)}</w:t></w:r></w:p></w:footnote>' for i, t in enumerate(footnotes)
            )
            z.writestr("word/footnotes.xml", f'<w:footnotes xmlns:w="{W_NS}">{fn}</w:footnotes>')
        if title:
            z.writestr("docProps/core.xml", f"<cp:coreProperties xmlns:dc='x'><dc:title>{escape(title)}</dc:title></cp:coreProperties>")
        z.writestr("word/media/image1.png", b"\x89PNG")
    return buf.getvalue()


# ------------------------------------------------------------------------------------- xlsx
def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(sheets: Dict[str, Tuple[Dict[Tuple[int, int], object], List[str], bool]]) -> bytes:
    """sheets = {name: (cells{(row,col): str|number}, merges['A1:C1'], hidden)}"""
    sst: List[str] = []
    idx: Dict[str, int] = {}

    def si(text: str) -> int:
        if text not in idx:
            idx[text] = len(sst)
            sst.append(text)
        return idx[text]

    wb_sheets, rels, parts = [], [], {}
    for n, (name, (cells, merges, hidden)) in enumerate(sheets.items(), start=1):
        rows: Dict[int, List[str]] = {}
        for (r, c), v in sorted(cells.items()):
            ref = f"{_col(c)}{r}"
            if isinstance(v, str):
                rows.setdefault(r, []).append(f'<c r="{ref}" t="s"><v>{si(v)}</v></c>')
            else:
                rows.setdefault(r, []).append(f'<c r="{ref}"><v>{v}</v></c>')
        data = "".join(f'<row r="{r}">{"".join(cs)}</row>' for r, cs in sorted(rows.items()))
        mc = f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + "</mergeCells>" if merges else ""
        parts[f"xl/worksheets/sheet{n}.xml"] = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{data}</sheetData>{mc}</worksheet>"
        )
        state = ' state="hidden"' if hidden else ""
        wb_sheets.append(f'<sheet name="{escape(name)}" sheetId="{n}"{state} r:id="rId{n}"/>')
        rels.append(f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml"/>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(wb_sheets)}</sheets></workbook>',
        )
        z.writestr("xl/_rels/workbook.xml.rels", f"<Relationships>{''.join(rels)}</Relationships>")
        z.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + "".join(f"<si><t>{escape(s)}</t></si>" for s in sst)
            + "</sst>",
        )
        for path, xml in parts.items():
            z.writestr(path, xml)
    return buf.getvalue()


# ------------------------------------------------------------------------------------- pptx
def make_pptx(slides: Sequence[Tuple[str, Sequence[str], str]]) -> bytes:
    """slides = [(title, body lines, notes)]"""
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    P = "http://schemas.openxmlformats.org/presentationml/2006/main"
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>' for i in range(len(slides)))
        z.writestr("ppt/presentation.xml", f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>')
        z.writestr(
            "ppt/_rels/presentation.xml.rels",
            "<Relationships>" + "".join(f'<Relationship Id="rId{i + 1}" Target="slides/slide{i + 1}.xml"/>' for i in range(len(slides))) + "</Relationships>",
        )
        for i, (title, lines, notes) in enumerate(slides, start=1):
            paras = lambda ls: "".join(f"<a:p><a:r><a:t>{escape(t)}</a:t></a:r></a:p>" for t in ls)
            body = "".join(f"<p:sp><p:nvSpPr><p:nvPr/></p:nvSpPr><p:txBody>{paras([ln])}</p:txBody></p:sp>" for ln in lines)
            ttl = f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody>{paras([title])}</p:txBody></p:sp>' if title else ""
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>{ttl}{body}</p:spTree></p:cSld></p:sld>')
            if notes:
                z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", f'<Relationships><Relationship Id="rId1" Target="../notesSlides/notesSlide{i}.xml"/></Relationships>')
                z.writestr(
                    f"ppt/notesSlides/notesSlide{i}.xml",
                    f'<p:notes xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody>{paras([notes])}</p:txBody></p:sp></p:spTree></p:cSld></p:notes>',
                )
    return buf.getvalue()


# -------------------------------------------------------------------------- xls (BIFF8 in OLE2)
def _rec(rid: int, data: bytes = b"") -> bytes:
    return struct.pack("<HH", rid, len(data)) + data


def _ustr(text: str) -> bytes:  # 8-bit "compressed" unicode string body (no length prefix)
    return text.encode("latin-1")


def _sst_records(strings: Sequence[str], exact_boundary: bool) -> bytes:
    """SST split across a CONTINUE record. exact_boundary=True splits between strings (no flag byte);
    False splits inside the last string's characters (the continued segment starts with a flag byte)."""
    head = struct.pack("<II", len(strings), len(strings))
    body = b"".join(struct.pack("<HB", len(s), 0) + _ustr(s) for s in strings[:-1])
    last = strings[-1]
    if exact_boundary:
        return _rec(0x00FC, head + body) + _rec(0x003C, struct.pack("<HB", len(last), 0) + _ustr(last))
    cut = len(last) // 2
    return _rec(0x00FC, head + body + struct.pack("<HB", len(last), 0) + _ustr(last[:cut])) + _rec(0x003C, b"\x00" + _ustr(last[cut:]))


def make_xls(
    sheet_name: str,
    cells: Dict[Tuple[int, int], object],
    merges: Sequence[Tuple[int, int, int, int]] = (),
    exact_boundary: bool = False,
    pad_to: int = 4200,
) -> bytes:
    """One worksheet. cells{(row,col) 1-based: str|int|float}; merges (r1,c1,r2,c2) 1-based inclusive."""
    strings = sorted({v for v in cells.values() if isinstance(v, str)}) or ["-"]
    sidx = {s: i for i, s in enumerate(strings)}
    bof_g = _rec(0x0809, struct.pack("<HHHHII", 0x0600, 0x0005, 0x0DBB, 0x07CC, 0, 6))
    codepage = _rec(0x0042, struct.pack("<H", 1252))
    sst = _sst_records(strings, exact_boundary)
    eof = _rec(0x000A)
    name = sheet_name.encode("latin-1")
    boundsheet_len = 4 + 6 + 2 + len(name)
    sheet_offset = len(bof_g) + len(codepage) + boundsheet_len + len(sst) + len(eof)
    boundsheet = _rec(0x0085, struct.pack("<IBB", sheet_offset, 0, 0) + struct.pack("<BB", len(name), 0) + name)
    globals_ = bof_g + codepage + boundsheet + sst + eof
    assert len(globals_) == sheet_offset
    sheet = _rec(0x0809, struct.pack("<HHHHII", 0x0600, 0x0010, 0x0DBB, 0x07CC, 0, 6))
    if merges:
        sheet += _rec(0x00E5, struct.pack("<H", len(merges)) + b"".join(struct.pack("<HHHH", r1 - 1, r2 - 1, c1 - 1, c2 - 1) for r1, c1, r2, c2 in merges))
    for (r, c), v in sorted(cells.items()):
        if isinstance(v, str):
            sheet += _rec(0x00FD, struct.pack("<HHHI", r - 1, c - 1, 0, sidx[v]))
        elif isinstance(v, int):
            sheet += _rec(0x027E, struct.pack("<HHHI", r - 1, c - 1, 0, (v << 2) | 2))  # RK integer
        else:
            sheet += _rec(0x0203, struct.pack("<HHHd", r - 1, c - 1, 0, float(v)))
    sheet += eof
    stream = globals_ + sheet
    stream += b"\x00" * max(pad_to - len(stream), 0)
    return _ole2({"Workbook": stream})


def _ole2(streams: Dict[str, bytes]) -> bytes:
    """Smallest valid OLE2 writer: 512-byte sectors, one FAT sector, streams >= 4096 bytes (no mini stream)."""
    sector = 512
    end, fatsect = 0xFFFFFFFE, 0xFFFFFFFD
    sectors_of = {}
    next_sector = 2  # 0 = FAT, 1 = directory
    payload: List[bytes] = []
    fat = {0: fatsect, 1: end}
    for name, data in streams.items():
        n = (len(data) + sector - 1) // sector
        sectors_of[name] = (next_sector, len(data))
        for k in range(n):
            fat[next_sector + k] = next_sector + k + 1 if k < n - 1 else end
            payload.append(data[k * sector : (k + 1) * sector].ljust(sector, b"\x00"))
        next_sector += n
    fat_sector = b"".join(struct.pack("<I", fat.get(i, 0xFFFFFFFF)) for i in range(sector // 4))

    def dirent(name: str, typ: int, start: int, size: int, child: int = 0xFFFFFFFF) -> bytes:
        raw = name.encode("utf-16le") + b"\x00\x00"
        e = raw.ljust(64, b"\x00") + struct.pack("<HBB", len(raw), typ, 1) + struct.pack("<III", 0xFFFFFFFF, 0xFFFFFFFF, child)
        e = e.ljust(0x74, b"\x00") + struct.pack("<II", start, size) + b"\x00\x00\x00\x00"
        return e.ljust(128, b"\x00")

    entries = [dirent("Root Entry", 5, end, 0, child=1)]
    for name, (start, size) in sectors_of.items():
        entries.append(dirent(name, 2, start, size))
    directory = b"".join(entries).ljust(sector, b"\x00")
    header = bytearray(512)
    header[:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHHH", header, 0x18, 0x003E, 0x0003, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", header, 0x2C, 1, 1, 0, 4096, end, 0, end, 0, 0)
    struct.pack_into("<109I", header, 0x4C, 0, *([0xFFFFFFFF] * 108))
    return bytes(header) + fat_sector + directory + b"".join(payload)
