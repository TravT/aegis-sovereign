"""
Shared spreadsheet logic (xlsx, xls, csv): turn a sparse cell grid into self-contained row lines.

  * merged cells are expanded (a merged header or group label appears in every cell it spans);
  * title rows (a single label on top of the sheet) are kept as text but are not headers;
  * multi-row headers ("Inspection scenario" over "Item" / "Criteria") are combined per column
    as `Parent > Child`, so a row read on its own still says what every value means;
  * each data row becomes one line `<row number>: Header: value | Header: value`.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from ..base import Section

LABEL_MAX = 60
Cells = Dict[Tuple[int, int], str]  # (row, col) 1-based -> text
Merge = Tuple[int, int, int, int]  # first row, first col, last row, last col


def col_letters(idx: int) -> str:
    out = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def fmt_number(x: float) -> str:
    if x != x or x in (float("inf"), float("-inf")):
        return str(x)
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return format(x, ".15g")


def grid_to_section(sheet: str, cells: Cells, merges: List[Merge]) -> Section | None:
    cells = {k: v.strip() for k, v in cells.items() if v is not None and str(v).strip()}
    if not cells:
        return None
    original = dict(cells)
    hspan_rows: Set[int] = set()
    for r1, c1, r2, c2 in merges:
        value = original.get((r1, c1), "")
        if c2 > c1:
            hspan_rows.update(range(r1, r2 + 1))
        if value:
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    cells.setdefault((r, c), value)
    rows = sorted({r for r, _ in cells})
    max_col = max(c for _, c in cells)

    def row_cells(r: int, source: Cells) -> List[str]:
        return [source.get((r, c), "") for c in range(1, max_col + 1)]

    # Prose-like sheets (one column, or too few rows for a header to mean anything) are kept as plain rows.
    used_cols = {c for _, c in cells}
    if len(used_cols) <= 1 or len(rows) <= 3:
        plain = [f"{r}: " + " | ".join(v for v in row_cells(r, cells) if v) for r in rows]
        return Section((sheet,), "\n".join(plain), locator=f"sheet:{sheet}", kind="rows")

    # leading title rows: exactly one label in the ORIGINAL cells
    lines: List[str] = []
    i = 0
    while i < len(rows) - 1 and sum(1 for c in range(1, max_col + 1) if original.get((rows[i], c))) == 1 and rows[i] not in hspan_rows:
        lines.append(f"{rows[i]}: {next(v for v in row_cells(rows[i], original) if v)}")
        i += 1
    if i >= len(rows):
        i = len(rows) - 1
    header_rows = [rows[i]]
    # a header row that contains horizontal merges is a parent header: the next row completes it
    while header_rows[-1] in hspan_rows and (header_rows[-1] + 1) in rows and len(header_rows) < 4:
        header_rows.append(header_rows[-1] + 1)
    labels: List[str] = []
    for c in range(1, max_col + 1):
        parts: List[str] = []
        for h in header_rows:
            v = cells.get((h, c), "")
            if v and (not parts or parts[-1] != v):
                parts.append(v)
        labels.append(" > ".join(parts) if parts else f"Column {col_letters(c)}")
    # Long labels are shown short in every row and stated in full once, at the top of the sheet.
    short = [l if len(l) <= LABEL_MAX else l[: LABEL_MAX - 3].rstrip() + "..." for l in labels]
    legend = [f"Column {col_letters(c + 1)} = {l}" for c, l in enumerate(labels) if len(l) > LABEL_MAX]
    lines = legend + lines
    for r in rows:
        if r <= header_rows[-1] and r >= header_rows[0]:
            continue
        if r < header_rows[0]:
            continue
        pairs = [f"{short[c - 1]}: {cells[(r, c)]}" for c in range(1, max_col + 1) if cells.get((r, c))]
        if pairs:
            lines.append(f"{r}: " + " | ".join(pairs))
    if not lines:  # header only
        lines = [f"{header_rows[0]}: " + " | ".join(l for l in labels if not l.startswith("Column "))]
    return Section((sheet,), "\n".join(lines), locator=f"sheet:{sheet}", kind="rows")
