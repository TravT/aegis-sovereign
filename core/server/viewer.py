"""
In-Browser Document Viewer and Sanitized HTML Renderer.
Extracts and renders authentic HTML, OpenXML, and Markdown documents from archive streams
with Dark Obsidian styling, relative diagram link rewriting, HedEx tree sidebar navigation,
and zero intrusive raw URI clutter.
"""

import base64
import html
import io
import posixpath
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Optional, Dict, List, Tuple


class DocumentViewer:
    """Renders virtual container archive entries as sanitized, responsive Dark Obsidian HTML with a full HedEx tree sidebar."""

    @staticmethod
    def _render_docx(entry: Any, virtual_uri: str) -> str:
        raw_bytes = getattr(entry, "raw_bytes", b"")
        if not raw_bytes:
            return "<p><em>Empty Word document.</em></p>"
        try:
            import docx
            z = zipfile.ZipFile(io.BytesIO(raw_bytes))
            rel_map: Dict[str, str] = {}
            if "word/_rels/document.xml.rels" in z.namelist():
                rels_xml = z.read("word/_rels/document.xml.rels").decode("utf-8", errors="replace")
                rels_root = ET.fromstring(rels_xml)
                for rel in rels_root:
                    r_id = rel.get("Id")
                    target = rel.get("Target")
                    if r_id and target and target.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".webp")):
                        if not target.startswith("word/"):
                            target = "word/" + target.lstrip("/")
                        rel_map[r_id] = target

            img_data_uris: Dict[str, str] = {}
            for r_id, target in rel_map.items():
                if target in z.namelist():
                    ext = target.rsplit(".", 1)[-1].lower()
                    mime = "image/png" if ext == "png" else ("image/jpeg" if ext in ("jpg", "jpeg") else ("image/svg+xml" if ext == "svg" else "image/png"))
                    b64_str = base64.b64encode(z.read(target)).decode("ascii")
                    img_data_uris[r_id] = f"data:{mime};base64,{b64_str}"

            doc = docx.Document(io.BytesIO(raw_bytes))
            filename = getattr(entry, "entry_name", "Document.docx").split("/")[-1]
            distinct_media_count = len(set(t for t in rel_map.values() if t in z.namelist()))

            body_parts: List[str] = []
            hero_html = f"""
            <div class="doc-format-hero docx-hero">
              <div class="doc-hero-badge">📘 Microsoft Word Document</div>
              <h1 class="doc-hero-title">{html.escape(filename)}</h1>
              <div class="doc-hero-meta">
                <span>📄 {len(doc.paragraphs)} Paragraphs</span>
                <span>📊 {len(doc.tables)} Tables</span>
                <span>🖼️ {distinct_media_count} Embedded Diagrams</span>
              </div>
            </div>
            """
            body_parts.append(hero_html)

            in_list = False
            for child in doc.element.body:
                tag = child.tag
                if tag.endswith("p"):
                    p = docx.text.paragraph.Paragraph(child, doc)
                    p_text = p.text.strip()
                    style_name = (p.style.name if p.style else "").lower()

                    p_xml = p._p.xml
                    para_images = []
                    for r_id, data_uri in img_data_uris.items():
                        if f'r:id="{r_id}"' in p_xml or f'r:embed="{r_id}"' in p_xml or f':id="{r_id}"' in p_xml or f':embed="{r_id}"' in p_xml:
                            para_images.append((r_id, data_uri))

                    if not p_text and not para_images:
                        continue

                    is_list_item = any(k in style_name for k in ("list", "bullet", "item")) or p_text.startswith(("- ", "* ", "• "))
                    if in_list and not is_list_item:
                        body_parts.append("</ul>")
                        in_list = False

                    for _, img_uri in para_images:
                        body_parts.append(f"""
                        <div class="docx-image-card">
                          <img src="{img_uri}" alt="Embedded Diagram" class="docx-embedded-img" />
                        </div>
                        """)

                    if not p_text:
                        continue

                    run_spans = []
                    for r in p.runs:
                        r_txt = html.escape(r.text)
                        if not r_txt:
                            continue
                        if r.bold:
                            r_txt = f"<strong>{r_txt}</strong>"
                        if r.italic:
                            r_txt = f"<em>{r_txt}</em>"
                        run_spans.append(r_txt)
                    formatted_text = "".join(run_spans) if run_spans else html.escape(p_text)

                    upper_text = p_text.upper()
                    if "caution" in style_name or upper_text.startswith("CAUTION:"):
                        body_parts.append(f'<div class="doc-callout callout-caution"><div class="callout-label">⚠️ CAUTION</div><p>{formatted_text}</p></div>')
                    elif "note" in style_name or upper_text.startswith("NOTE:"):
                        body_parts.append(f'<div class="doc-callout callout-note"><div class="callout-label">💡 NOTE</div><p>{formatted_text}</p></div>')
                    elif "warning" in style_name or upper_text.startswith("WARNING:"):
                        body_parts.append(f'<div class="doc-callout callout-warning"><div class="callout-label">🚨 WARNING</div><p>{formatted_text}</p></div>')
                    elif is_list_item:
                        if not in_list:
                            body_parts.append('<ul class="doc-bullet-list">')
                            in_list = True
                        clean_item = p_text.lstrip("-*• ").strip()
                        body_parts.append(f'<li>{html.escape(clean_item)}</li>')
                    elif "heading 1" in style_name or "heading1" in style_name:
                        body_parts.append(f'<h1 class="doc-heading doc-h1">{formatted_text}</h1>')
                    elif "heading 2" in style_name or "heading2" in style_name:
                        body_parts.append(f'<h2 class="doc-heading doc-h2">{formatted_text}</h2>')
                    elif "heading 3" in style_name or "heading3" in style_name:
                        body_parts.append(f'<h3 class="doc-heading doc-h3">{formatted_text}</h3>')
                    elif "heading 4" in style_name or "heading4" in style_name or "heading" in style_name:
                        body_parts.append(f'<h4 class="doc-heading doc-h4">{formatted_text}</h4>')
                    else:
                        body_parts.append(f'<p class="doc-para">{formatted_text}</p>')

                elif tag.endswith("tbl"):
                    if in_list:
                        body_parts.append("</ul>")
                        in_list = False
                    tbl = docx.table.Table(child, doc)
                    if not tbl.rows:
                        continue
                    tbl_html = ['<div class="table-wrap"><table class="doc-table">']
                    for r_idx, row in enumerate(tbl.rows):
                        tbl_html.append("<tr>")
                        seen_tc = set()
                        for cell in row.cells:
                            if cell._tc in seen_tc:
                                continue
                            seen_tc.add(cell._tc)
                            c_text = cell.text.strip()
                            tag_name = "th" if r_idx == 0 else "td"
                            tbl_html.append(f"<{tag_name}>{html.escape(c_text)}</{tag_name}>")
                        tbl_html.append("</tr>")
                    tbl_html.append("</table></div>")
                    body_parts.append("".join(tbl_html))

            if in_list:
                body_parts.append("</ul>")

            return "\n".join(body_parts)

        except Exception as e:
            content_text = getattr(entry, "content_text", "")
            if content_text:
                return f'<div class="doc-fallback"><div class="callout-warning">Rendered with text fallback: {html.escape(str(e))}</div><pre>{html.escape(content_text)}</pre></div>'
            return f'<p class="error-msg">Failed to parse Word document: {html.escape(str(e))}</p>'

    @staticmethod
    def _render_spreadsheet(entry: Any, virtual_uri: str, target_sheet: Optional[str] = None) -> str:
        raw_bytes = getattr(entry, "raw_bytes", b"")
        if not raw_bytes:
            return "<p><em>Empty spreadsheet document.</em></p>"

        filename = getattr(entry, "entry_name", "Spreadsheet.xlsx").split("/")[-1]
        name_lower = filename.lower()

        if not target_sheet and "::sheet::" in virtual_uri:
            frag = virtual_uri.split("::sheet::", 1)[1]
            target_sheet = urllib.parse.unquote(frag.split("::")[0].strip())

        sheets_data: List[Tuple[str, List[List[str]], int]] = []

        if name_lower.endswith((".xlsx", ".xlsm")):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
                for sname in wb.sheetnames:
                    ws = wb[sname]
                    rows: List[List[str]] = []
                    count = 0
                    for row in ws.iter_rows(values_only=True):
                        count += 1
                        if len(rows) < 300:
                            cleaned = ["" if v is None else str(v).strip() for v in row]
                            if any(cleaned):
                                rows.append(cleaned)
                    sheets_data.append((sname, rows, count))
                wb.close()
            except Exception as e:
                return f'<p class="error-msg">Error loading XLSX spreadsheet: {html.escape(str(e))}</p>'

        elif name_lower.endswith(".xls"):
            try:
                import xlrd
                wb = xlrd.open_workbook(file_contents=raw_bytes)
                for sname in wb.sheet_names():
                    ws = wb.sheet_by_name(sname)
                    rows: List[List[str]] = []
                    for r_idx in range(min(300, ws.nrows)):
                        row_vals = ["" if c.value is None else str(c.value).strip() for c in ws.row(r_idx)]
                        if any(row_vals):
                            rows.append(row_vals)
                    sheets_data.append((sname, rows, ws.nrows))
            except Exception as e:
                return f'<p class="error-msg">Error loading XLS spreadsheet: {html.escape(str(e))}</p>'

        if not sheets_data:
            return "<p><em>Spreadsheet contains no sheets.</em></p>"

        active_idx = 0
        if target_sheet:
            for idx, (sname, _, _) in enumerate(sheets_data):
                if sname.lower() == target_sheet.lower():
                    active_idx = idx
                    break

        total_rows_all = sum(cnt for _, _, cnt in sheets_data)

        html_out: List[str] = []
        hero_html = f"""
        <div class="doc-format-hero xlsx-hero">
          <div class="doc-hero-badge">📊 Excel Spreadsheet</div>
          <h1 class="doc-hero-title">{html.escape(filename)}</h1>
          <div class="doc-hero-meta">
            <span>📑 {len(sheets_data)} Sheets</span>
            <span>🔢 {total_rows_all:,} Total Rows</span>
            <span>👁️ Interactive Grid Viewer</span>
          </div>
        </div>
        """
        html_out.append(hero_html)

        tab_buttons = []
        for idx, (sname, r_list, cnt) in enumerate(sheets_data):
            is_active = (idx == active_idx)
            act_cls = "active" if is_active else ""
            tab_buttons.append(
                f'<button type="button" class="sheet-tab-btn {act_cls}" onclick="switchSheetTab(\'sheet-pane-{idx}\', this)">'
                f'<span class="sheet-tab-icon">📄</span> '
                f'<span class="sheet-tab-name">{html.escape(sname)}</span> '
                f'<span class="sheet-tab-badge">{cnt}</span>'
                f'</button>'
            )

        html_out.append(f"""
        <div class="sheet-viewer-controls">
          <div class="sheet-tabs-container">
            {"".join(tab_buttons)}
          </div>
          <div class="sheet-filter-bar">
            <input type="text" class="sheet-filter-input" placeholder="🔍 Search/filter rows in active sheet..." oninput="filterActiveSheet(this.value)" />
          </div>
        </div>
        """)

        for idx, (sname, rows, total_cnt) in enumerate(sheets_data):
            is_active = (idx == active_idx)
            disp_style = "display: block;" if is_active else "display: none;"
            pane_html = [f'<div id="sheet-pane-{idx}" class="sheet-pane" style="{disp_style}">']

            if not rows:
                pane_html.append('<div class="empty-sheet-msg">This worksheet contains no rows.</div>')
            else:
                max_cols = max(len(r) for r in rows)
                col_headers = []
                for c in range(max_cols):
                    col_letter = ""
                    temp = c
                    while temp >= 0:
                        col_letter = chr(temp % 26 + 65) + col_letter
                        temp = temp // 26 - 1
                    col_headers.append(col_letter)

                pane_html.append('<div class="table-wrap sheet-table-wrap">')
                pane_html.append('<table class="sheet-table">')
                pane_html.append('<thead><tr><th class="row-num-col">#</th>')
                for ch in col_headers:
                    pane_html.append(f'<th>{ch}</th>')
                pane_html.append('</tr></thead><tbody>')

                for r_idx, r in enumerate(rows):
                    row_text = " ".join(r).lower()
                    row_num = r_idx + 1
                    is_first_row = (r_idx == 0)
                    row_cls = "sheet-row" + (" sheet-header-row" if is_first_row else "")
                    pane_html.append(f'<tr class="{row_cls}" data-row-text="{html.escape(row_text)}">')
                    pane_html.append(f'<td class="row-num-cell">{row_num}</td>')
                    for c_idx in range(max_cols):
                        val = r[c_idx] if c_idx < len(r) else ""
                        pane_html.append(f'<td>{html.escape(val)}</td>')
                    pane_html.append('</tr>')

                pane_html.append('</tbody></table></div>')

                if total_cnt > len(rows):
                    pane_html.append(f'<div class="sheet-truncation-note">Showing first {len(rows)} of {total_cnt:,} rows in worksheet <strong>{html.escape(sname)}</strong>.</div>')

            pane_html.append('</div>')
            html_out.append("".join(pane_html))

        return "\n".join(html_out)

    @staticmethod
    def _render_archive(entry: Any, virtual_uri: str) -> str:
        raw_bytes = getattr(entry, "raw_bytes", b"")
        if not raw_bytes:
            return "<p><em>Empty archive container.</em></p>"

        filename = getattr(entry, "entry_name", "archive.zip").split("/")[-1]
        try:
            z = zipfile.ZipFile(io.BytesIO(raw_bytes))
            members = [info for info in z.infolist() if not info.is_dir() and not info.filename.endswith("/")]
            total_uncompressed = sum(m.file_size for m in members)

            body_parts = []
            hero_html = f"""
            <div class="doc-format-hero zip-hero">
              <div class="doc-hero-badge">📦 Nested Container Archive</div>
              <h1 class="doc-hero-title">{html.escape(filename)}</h1>
              <div class="doc-hero-meta">
                <span>📁 {len(members)} Files</span>
                <span>💾 {total_uncompressed / 1024 / 1024:.2f} MB Uncompressed</span>
                <span>🔒 Zero-Disk Streaming</span>
              </div>
            </div>
            """
            body_parts.append(hero_html)

            body_parts.append('<div class="table-wrap"><table class="doc-table zip-listing-table">')
            body_parts.append('<thead><tr><th>Entry Name</th><th>Size</th><th>Compressed</th><th>Format</th><th>Action</th></tr></thead><tbody>')

            for m in members:
                m_name = m.filename
                m_ext = m_name.rsplit(".", 1)[-1].lower() if "." in m_name else "file"
                nested_uri = f"{virtual_uri}!{m_name}"
                target_url = f"/archive/view?uri={urllib.parse.quote(nested_uri)}"

                size_str = f"{m.file_size:,} B" if m.file_size < 1024 else f"{m.file_size / 1024:.1f} KB"
                comp_str = f"{m.compress_size:,} B" if m.compress_size < 1024 else f"{m.compress_size / 1024:.1f} KB"
                icon = "📜" if m_ext in ("wsdl", "xsd", "xml") else ("📘" if m_ext == "docx" else ("📊" if m_ext in ("xlsx", "xls") else "📄"))

                body_parts.append(f"""
                <tr>
                  <td class="zip-entry-name"><span class="zip-entry-icon">{icon}</span> {html.escape(m_name)}</td>
                  <td><code>{size_str}</code></td>
                  <td><code>{comp_str}</code></td>
                  <td><span class="zip-format-badge">{html.escape(m_ext.upper())}</span></td>
                  <td><a href="{target_url}" class="zip-open-btn">Open in Viewer ➡</a></td>
                </tr>
                """)

            body_parts.append('</tbody></table></div>')
            return "\n".join(body_parts)

        except Exception as e:
            return f'<p class="error-msg">Error reading nested archive: {html.escape(str(e))}</p>'

    @staticmethod
    def _render_code(entry: Any, virtual_uri: str) -> str:
        filename = getattr(entry, "entry_name", "document.txt").split("/")[-1]
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

        raw_bytes = getattr(entry, "raw_bytes", b"")
        if raw_bytes:
            text = raw_bytes.decode("utf-8", errors="replace")
        else:
            text = getattr(entry, "content_text", "")

        lines = text.splitlines()
        total_lines = len(lines)
        total_chars = len(text)

        badge_name = {
            "wsdl": "📜 WSDL Interface Specification",
            "xsd": "📐 XML Schema Definition (XSD)",
            "xml": "🗂️ XML Document",
            "json": "🔧 JSON Data",
            "sql": "💾 SQL Script",
            "sh": "⚙️ Shell Script",
            "py": "🐍 Python Source",
            "txt": "📄 Plain Text",
        }.get(ext, f"📄 {ext.upper()} File")

        hero_html = f"""
        <div class="doc-format-hero code-hero">
          <div class="doc-hero-badge">{badge_name}</div>
          <h1 class="doc-hero-title">{html.escape(filename)}</h1>
          <div class="doc-hero-meta">
            <span>📏 {total_lines:,} Lines</span>
            <span>💾 {total_chars:,} Characters</span>
            <button type="button" class="btn-copy-code" onclick="copyDocumentContent()">📋 Copy Full Content</button>
          </div>
        </div>
        """

        code_lines_html = []
        for idx, line in enumerate(lines):
            line_no = idx + 1
            escaped = html.escape(line)
            code_lines_html.append(f'<div class="code-line"><span class="line-num">{line_no}</span><span class="line-text">{escaped}</span></div>')

        code_container = f"""
        <div class="code-block-container">
          <div class="code-block-header">
            <span class="code-header-name">{html.escape(filename)}</span>
            <span class="code-header-meta">{ext.upper()} • UTF-8</span>
          </div>
          <pre class="code-pre" id="code-content-pre"><code>{"".join(code_lines_html)}</code></pre>
          <textarea id="raw-code-payload" style="display:none;">{html.escape(text)}</textarea>
        </div>
        """
        return f"{hero_html}\n{code_container}"

    @staticmethod
    def format_entry_to_styled_html(
        entry: Any,
        virtual_uri: str,
        topic_hierarchy: Optional[Dict[str, Any]] = None,
        bookmap_tree: Optional[Dict[str, Any]] = None,
    ) -> str:
        name_lower = getattr(entry, "entry_name", "").lower()
        title = getattr(entry, "entry_name", "Document").split("/")[-1]

        raw_body_html = ""
        is_custom_rendered = False

        if hasattr(entry, "raw_bytes") and entry.raw_bytes and name_lower.endswith(".docx"):
            raw_body_html = DocumentViewer._render_docx(entry, virtual_uri)
            is_custom_rendered = True
        elif hasattr(entry, "raw_bytes") and entry.raw_bytes and name_lower.endswith((".xlsx", ".xlsm", ".xls")):
            raw_body_html = DocumentViewer._render_spreadsheet(entry, virtual_uri)
            is_custom_rendered = True
        elif hasattr(entry, "raw_bytes") and entry.raw_bytes and name_lower.endswith(".zip"):
            raw_body_html = DocumentViewer._render_archive(entry, virtual_uri)
            is_custom_rendered = True
        elif name_lower.endswith((".wsdl", ".xsd", ".xml", ".json", ".txt", ".sh", ".py", ".sql", ".yaml", ".yml")):
            raw_body_html = DocumentViewer._render_code(entry, virtual_uri)
            is_custom_rendered = True
        elif hasattr(entry, "raw_bytes") and entry.raw_bytes and name_lower.endswith((".html", ".htm", ".xhtml")):
            raw_body_html = entry.raw_bytes.decode("utf-8", errors="replace")
        elif getattr(entry, "content_text", None):
            paras = entry.content_text.split("\n\n")
            formatted_paras = []
            for p in paras:
                p_str = p.strip()
                if not p_str:
                    continue
                if p_str.startswith("|") and "|" in p_str[1:]:
                    rows = p_str.split("\n")
                    table_html = "<div class='table-wrap'><table>"
                    for r_idx, row in enumerate(rows):
                        cols = [c.strip() for c in row.split("|")[1:-1]]
                        if not cols:
                            continue
                        tag = "th" if r_idx == 0 else "td"
                        table_html += "<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cols) + "</tr>"
                    table_html += "</table></div>"
                    formatted_paras.append(table_html)
                elif p_str.startswith("#"):
                    level = min(6, len(p_str) - len(p_str.lstrip("#")))
                    heading_txt = p_str.lstrip("#").strip()
                    formatted_paras.append(f"<h{level}>{html.escape(heading_txt)}</h{level}>")
                else:
                    formatted_paras.append(f"<p>{html.escape(p_str)}</p>")
            raw_body_html = "\n".join(formatted_paras)
        else:
            raw_body_html = "<p><em>No readable content in this entry.</em></p>"

        if not is_custom_rendered:
            # Strip scripts that could break iframe / viewer
            raw_body_html = re.sub(r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>", "", raw_body_html, flags=re.IGNORECASE)
            # Strip external/broken link stylesheets (commonltr.css, imagePopup.css, etc.)
            raw_body_html = re.sub(r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*>', "", raw_body_html, flags=re.IGNORECASE)
            raw_body_html = re.sub(r'<link\b[^>]*href=["\'][^"\']*\.css["\'][^>]*>', "", raw_body_html, flags=re.IGNORECASE)

            # Rewrite relative image references (figure/..., ../images/..., etc.) to diagrams endpoint with exact archive URI
            if "#" in virtual_uri:
                archive_base, current_entry = virtual_uri.split("#", 1)
                entry_dir = posixpath.dirname(current_entry)

                def _rewrite_img(m: re.Match) -> str:
                    prefix = m.group(1)
                    src = m.group(2)
                    if src.startswith(("http://", "https://", "data:", "/diagrams")):
                        return m.group(0)
                    target_entry = posixpath.normpath(posixpath.join(entry_dir, src)).lstrip("/")
                    img_uri = f"{archive_base}#{target_entry}"
                    filename = posixpath.basename(target_entry)
                    return f'<img {prefix}src="/diagrams/{urllib.parse.quote(filename)}?uri={urllib.parse.quote(img_uri)}"'

                raw_body_html = re.sub(
                    r'<img\s+([^>]*?)src=["\']([^"\']+\.(?:png|jpg|jpeg|gif|svg|webp))["\']',
                    _rewrite_img,
                    raw_body_html,
                    flags=re.IGNORECASE,
                )
            else:
                raw_body_html = re.sub(
                    r'<img\s+([^>]*?)src=["\'](?:(?:\.\./)+|/)?(?:[^"\'\s]*/)?([^"\'/\s]+\.(?:png|jpg|jpeg|gif|svg|webp))["\']',
                    r'<img \1src="/diagrams/\2"',
                    raw_body_html,
                    flags=re.IGNORECASE,
                )

            # Rewrite relative .html topic links inside the container to stay in viewer
            if "#" in virtual_uri:
                archive_base, current_entry = virtual_uri.split("#", 1)
                entry_dir = posixpath.dirname(current_entry)

                def _rewrite_href(m: re.Match) -> str:
                    prefix = m.group(1)
                    href = m.group(2)
                    if href.startswith(("#", "http://", "https://", "mailto:", "javascript:", "/")):
                        return m.group(0)
                    target_entry = posixpath.normpath(posixpath.join(entry_dir, href)).lstrip("/")
                    new_uri = f"{archive_base}#{target_entry}"
                    return f'<a {prefix}href="/archive/view?uri={urllib.parse.quote(new_uri)}"'

                raw_body_html = re.sub(
                    r'<a\s+([^>]*?)href=["\']([^"\']+\.html?(?:#[^"\']*)?)["\']',
                    _rewrite_href,
                    raw_body_html,
                    flags=re.IGNORECASE,
                )

        breadcrumb_html = ""
        buttons_strip = ""
        bottom_nav_html = ""
        doc_display_title = title

        if topic_hierarchy and topic_hierarchy.get("current"):
            cur = topic_hierarchy["current"]
            doc_display_title = cur.get("title") or cur.get("name") or title
            parent = topic_hierarchy.get("parent")
            prev_t = topic_hierarchy.get("prev_topic")
            next_t = topic_hierarchy.get("next_topic")

            path_text = cur.get("path_text") or cur.get("name") or ""
            if path_text:
                parts = [p.strip() for p in path_text.split(">")]
                crumb_spans = " <span class='crumb-sep'>/</span> ".join(
                    f"<span class='crumb-item'>{html.escape(p)}</span>" for p in parts
                )
                breadcrumb_html = f'<div class="topic-breadcrumbs">{crumb_spans}</div>'

            buttons: List[str] = []
            if prev_t and prev_t.get("uri"):
                p_url = f"/archive/view?uri={urllib.parse.quote(prev_t['uri'])}"
                buttons.append(f'<a href="{p_url}" class="nav-step-btn prev-btn" title="Previous: {html.escape(prev_t["name"])}">⬅ Prev: {html.escape(prev_t["name"])}</a>')
            if parent and parent.get("uri"):
                par_url = f"/archive/view?uri={urllib.parse.quote(parent['uri'])}"
                buttons.append(f'<a href="{par_url}" class="nav-step-btn parent-btn" title="Up to Chapter: {html.escape(parent["name"])}">⬆ Chapter: {html.escape(parent["name"])}</a>')
            elif parent and parent.get("name"):
                buttons.append(f'<span class="nav-step-btn parent-btn" style="opacity: 0.7; cursor: default;">📖 {html.escape(parent["name"])}</span>')
            if next_t and next_t.get("uri"):
                n_url = f"/archive/view?uri={urllib.parse.quote(next_t['uri'])}"
                buttons.append(f'<a href="{n_url}" class="nav-step-btn next-btn" title="Next: {html.escape(next_t["name"])}">Next: {html.escape(next_t["name"])} ➡</a>')

            if buttons:
                buttons_strip = f'<div class="nav-buttons-strip">{" ".join(buttons)}</div>'
                bottom_nav_html = f"""
                <nav class="topic-bottom-nav">
                  <div class="nav-buttons-strip">{" ".join(buttons)}</div>
                </nav>
                """

        # Build Multi-Tiered HedEx "Tree of Trees" Sidebar HTML
        sidebar_tree_html = ""
        package_name = "Huawei Documentation"
        if bookmap_tree:
            package_name = bookmap_tree.get("package") or "Documentation"
            categories = bookmap_tree.get("categories", [])
            nodes = bookmap_tree.get("nodes", [])
            active_chain = set(bookmap_tree.get("active_chain", []))
            active_topic_id = bookmap_tree.get("active_topic_id", "")

            # Group topics in active book by parent_id for hierarchical nesting
            node_ids = {n["topic_id"] for n in nodes}
            children_by_parent: Dict[Optional[str], List[Dict[str, Any]]] = {}
            for n in nodes:
                pid = n.get("parent_id")
                key = pid if (pid in node_ids) else None
                children_by_parent.setdefault(key, []).append(n)

            def _render_topic_sublist(parent_key: Optional[str], depth: int = 1) -> str:
                subnodes = children_by_parent.get(parent_key, [])
                if not subnodes:
                    return ""
                items = []
                for n in subnodes:
                    tid = n["topic_id"]
                    n_name = html.escape(n.get("name") or "Topic")
                    n_uri = n.get("uri")
                    is_act = n.get("is_active", False)
                    is_anc = n.get("is_ancestor", False) or (tid in active_chain and not is_act)
                    child_count = n.get("child_count", 0)
                    has_sublist = tid in children_by_parent

                    cls_list = ["tree-node", f"depth-{min(depth, 6)}"]
                    if is_act:
                        cls_list.append("active")
                    elif is_anc:
                        cls_list.append("ancestor")

                    pad_left = (depth - 1) * 12 + 6
                    if n_uri:
                        target_url = f"/archive/view?uri={urllib.parse.quote(n_uri)}"
                        link_html = f'<a href="{target_url}" class="node-link" title="{n_name}">{n_name}</a>'
                    else:
                        link_html = f'<span class="node-title" title="{n_name}">{n_name}</span>'

                    if child_count > 0:
                        cls_list.append("folder-node")
                        is_expanded = is_act or is_anc
                        chevron = "▼" if is_expanded else "▶"
                        sub_html = _render_topic_sublist(tid, depth + 1)
                        disp = "display: block;" if is_expanded else "display: none;"
                        items.append(
                            f'<li class="{" ".join(cls_list)}" id="node-{tid}" data-title="{n_name.lower()}">'
                            f'<div class="node-row" style="padding-left: {pad_left}px;">'
                            f'<span class="node-toggle" onclick="toggleTopicChildren(event, \'{tid}\')">{chevron}</span>'
                            f'<span class="node-icon">📁</span>'
                            f'{link_html}'
                            f'<span class="node-badge">{child_count}</span>'
                            f'</div>'
                            f'<ul class="node-children-list" id="children-{tid}" style="{disp}">{sub_html}</ul>'
                            f'</li>'
                        )
                    else:
                        cls_list.append("leaf-node")
                        marker = "●" if is_act else "📄"
                        items.append(
                            f'<li class="{" ".join(cls_list)}" id="node-{tid}" data-title="{n_name.lower()}">'
                            f'<div class="node-row" style="padding-left: {pad_left}px;">'
                            f'<span class="node-spacer"></span>'
                            f'<span class="node-icon">{marker}</span>'
                            f'{link_html}'
                            f'</div>'
                            f'</li>'
                        )
                return "".join(items)

            active_topics_html = _render_topic_sublist(None, 1)

            if categories:
                # If no book is currently marked active, activate the first book in active_category (or first book overall)
                has_active = any(b.get("is_active") for cat in categories for b in cat.get("books", []))
                if not has_active and categories:
                    act_cat_name = bookmap_tree.get("active_category", "")
                    matched_cat = next((c for c in categories if c.get("name") == act_cat_name), categories[0])
                    matched_cat["is_active"] = True
                    if matched_cat.get("books"):
                        matched_cat["books"][0]["is_active"] = True

                cat_items = []
                for cat in categories:
                    cat_name = html.escape(cat["name"])
                    cat_is_active = cat.get("is_active", False)
                    open_attr = "open" if cat_is_active else ""
                    books = cat.get("books", [])

                    book_items = []
                    for b in books:
                        b_name = html.escape(b["name"])
                        b_src = html.escape(b["source"])
                        b_count = b["topic_count"]
                        b_active = b.get("is_active", False)
                        pkg = html.escape(bookmap_tree.get("package", ""))

                        if b_active:
                            book_items.append(
                                f'<li class="book-entry active-book-entry">'
                                f'<details class="book-details" open>'
                                f'<summary class="book-summary active-book-summary">'
                                f'<span class="book-icon">📘</span>'
                                f'<span class="book-title" title="{b_name}">{b_name}</span>'
                                f'<span class="book-count">{b_count}</span>'
                                f'</summary>'
                                f'<ul class="tree-list active-tree-list" id="tree-list">{active_topics_html}</ul>'
                                f'</details>'
                                f'</li>'
                            )
                        else:
                            book_items.append(
                                f'<li class="book-entry">'
                                f'<details class="book-details" data-package="{pkg}" data-source="{b_src}">'
                                f'<summary class="book-summary" onclick="loadBookTopicsLazy(this, \'{pkg}\', \'{b_src}\')">'
                                f'<span class="book-icon">📘</span>'
                                f'<span class="book-title" title="{b_name}">{b_name}</span>'
                                f'<span class="book-count">{b_count}</span>'
                                f'</summary>'
                                f'<ul class="tree-list lazy-tree-list"></ul>'
                                f'</details>'
                                f'</li>'
                            )

                    cat_items.append(
                        f'<div class="cat-group">'
                        f'<details class="cat-details" {open_attr}>'
                        f'<summary class="cat-summary">'
                        f'<span class="cat-icon">📁</span>'
                        f'<span class="cat-title">{cat_name}</span>'
                        f'<span class="cat-badge">{len(books)} manuals</span>'
                        f'</summary>'
                        f'<ul class="books-list">{"".join(book_items)}</ul>'
                        f'</details>'
                        f'</div>'
                    )
                sidebar_tree_html = "".join(cat_items)
            else:
                sidebar_tree_html = f'<ul class="tree-list" id="tree-list">{active_topics_html}</ul>'

        # Fallback to local siblings if bookmap_tree not present
        if not sidebar_tree_html and topic_hierarchy and topic_hierarchy.get("siblings"):
            sibs = topic_hierarchy["siblings"]
            cur = topic_hierarchy["current"]
            tree_items = []
            for s in sibs:
                s_name = html.escape(s.get("name") or "Topic")
                s_uri = s.get("uri")
                is_act = (s.get("is_current") or s.get("topic_id") == cur.get("topic_id"))
                cls_list = ["tree-node", "depth-1"]
                if is_act:
                    cls_list.append("active")
                if s_uri:
                    target_url = f"/archive/view?uri={urllib.parse.quote(s_uri)}"
                    tree_items.append(
                        f'<li class="{" ".join(cls_list)}" style="padding-left: 10px;" data-title="{s_name.lower()}">'
                        f'<a href="{target_url}" class="node-link"><span class="node-icon">{"●" if is_act else "📄"}</span> {s_name}</a>'
                        f'</li>'
                    )
                else:
                    tree_items.append(
                        f'<li class="{" ".join(cls_list)} muted" style="padding-left: 10px;" data-title="{s_name.lower()}">'
                        f'<span class="node-title"><span class="node-icon">{"●" if is_act else "📄"}</span> {s_name}</span>'
                        f'</li>'
                    )
            sidebar_tree_html = f'<ul class="tree-list" id="tree-list">{"".join(tree_items)}</ul>'

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(doc_display_title)} — Sovereign Vault Document Viewer</title>
  <style>
    :root {{
      --bg: #07090D;
      --surface: #0C1017;
      --sidebar-bg: #0B0E14;
      --card-bg: #111620;
      --border: rgba(255, 255, 255, 0.08);
      --border-bright: rgba(255, 255, 255, 0.16);
      --text: #E2E8F0;
      --text-muted: #8492A6;
      --gold: #D4AF37;
      --gold-bright: #F5D77F;
      --cyan: #38BDF8;
      --emerald: #10B981;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: "JetBrains Mono", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      height: 100%;
      overflow: hidden;
      line-height: 1.65;
    }}

    /* Top Sticky App Header */
    .app-header {{
      height: 52px;
      background: rgba(11, 14, 20, 0.95);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 1.25rem;
      z-index: 100;
    }}
    .header-left {{
      display: flex;
      align-items: center;
      gap: 0.85rem;
      overflow: hidden;
    }}
    .toggle-sidebar-btn {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 6px;
      padding: 0.35rem 0.6rem;
      font-size: 0.82rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 0.35rem;
      transition: all 0.15s;
    }}
    .toggle-sidebar-btn:hover {{
      color: #FFF;
      background: rgba(255, 255, 255, 0.1);
      border-color: var(--cyan);
    }}
    .header-doc-title {{
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 50vw;
    }}
    .topic-breadcrumbs {{
      font-size: 0.76rem;
      font-family: var(--font-mono);
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 0.4rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .crumb-sep {{ opacity: 0.4; }}
    .header-actions {{
      display: flex;
      align-items: center;
      gap: 0.6rem;
      flex-shrink: 0;
    }}
    .btn-header {{
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 6px;
      padding: 0.35rem 0.75rem;
      font-size: 0.78rem;
      font-family: var(--font-mono);
      text-decoration: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      transition: all 0.15s;
    }}
    .btn-header:hover {{
      color: #FFF;
      background: rgba(255, 255, 255, 0.08);
      border-color: var(--border-bright);
    }}
    .btn-header-primary {{
      background: rgba(212, 175, 55, 0.12);
      border-color: rgba(212, 175, 55, 0.3);
      color: var(--gold-bright);
    }}
    .btn-header-primary:hover {{
      background: rgba(212, 175, 55, 0.22);
      border-color: var(--gold);
      color: #FFF;
    }}

    /* Toast Notification */
    #doc-toast {{
      position: fixed;
      bottom: 1.5rem;
      right: 1.5rem;
      background: #111620;
      border: 1px solid var(--emerald);
      color: var(--emerald);
      padding: 0.5rem 1rem;
      border-radius: 6px;
      font-size: 0.8rem;
      font-family: var(--font-mono);
      display: none;
      z-index: 1000;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.6);
    }}

    /* Main Split Layout */
    .app-body {{
      display: flex;
      height: calc(100% - 52px);
      position: relative;
    }}

    /* Left Sidebar: Native HedEx Hierarchy Tree */
    .sidebar {{
      width: 320px;
      min-width: 320px;
      background: var(--sidebar-bg);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      height: 100%;
      transition: margin-left 0.22s ease-in-out;
    }}
    .sidebar-collapsed .sidebar {{
      margin-left: -320px;
    }}
    .sidebar-header {{
      padding: 0.85rem 1rem;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .manual-tag {{
      display: flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--gold-bright);
      margin-bottom: 0.65rem;
    }}
    .manual-count {{
      font-size: 0.7rem;
      font-family: var(--font-mono);
      color: var(--text-muted);
      background: rgba(255, 255, 255, 0.05);
      padding: 0.1rem 0.35rem;
      border-radius: 4px;
    }}
    .sidebar-search {{
      position: relative;
    }}
    .sidebar-search input {{
      width: 100%;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.38rem 0.65rem;
      font-size: 0.8rem;
      color: var(--text);
      outline: none;
      transition: border-color 0.15s;
    }}
    .sidebar-search input:focus {{
      border-color: var(--cyan);
      background: rgba(255, 255, 255, 0.07);
    }}
    .tree-search-panel {{
      background: #0E131C;
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: 6px;
      margin-bottom: 0.75rem;
      padding: 0.5rem;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
    }}
    .tree-search-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.2rem 0.4rem 0.4rem 0.4rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      font-size: 0.72rem;
      color: var(--cyan);
      font-weight: 600;
    }}
    .tree-search-close {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 0.72rem;
    }}
    .tree-search-close:hover {{
      color: #FFF;
    }}
    .tree-search-results-list {{
      list-style: none;
      max-height: 280px;
      overflow-y: auto;
      margin-top: 0.4rem;
    }}
    .tree-search-item {{
      padding: 0.35rem 0.5rem;
      border-radius: 4px;
      font-size: 0.78rem;
      display: flex;
      flex-direction: column;
      gap: 0.15rem;
      transition: background 0.15s;
    }}
    .tree-search-item:hover {{
      background: rgba(56, 189, 248, 0.12);
    }}
    .tree-search-link {{
      color: #E2E8F0;
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 0.35rem;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .tree-search-link:hover {{
      color: var(--gold-bright);
      text-decoration: none;
    }}
    .tree-search-meta {{
      font-size: 0.65rem;
      color: #64748B;
      font-family: var(--font-mono);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .tree-search-pkg-badge {{
      display: inline-block;
      padding: 0.1rem 0.35rem;
      border-radius: 3px;
      font-size: 0.65rem;
      font-weight: 700;
      font-family: var(--font-mono);
      background: rgba(56, 189, 248, 0.15);
      color: #38BDF8;
      border: 1px solid rgba(56, 189, 248, 0.3);
      flex-shrink: 0;
    }}
    .sidebar-tree-container {{
      flex: 1;
      overflow-y: auto;
      padding: 0.65rem 0.5rem 2rem 0.5rem;
    }}
    /* Multi-Tier HedEx Library Accordions */
    .cat-group {{
      margin-bottom: 0.45rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      padding-bottom: 0.35rem;
    }}
    .cat-details {{
      margin-bottom: 0.2rem;
    }}
    .cat-summary {{
      font-size: 0.8rem;
      font-weight: 700;
      color: #E2E8F0;
      padding: 0.38rem 0.5rem;
      border-radius: 6px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 0.45rem;
      user-select: none;
      transition: background 0.15s;
    }}
    .cat-summary:hover {{
      background: rgba(255, 255, 255, 0.05);
      color: var(--gold-bright);
    }}
    .cat-badge {{
      font-size: 0.68rem;
      font-family: var(--font-mono);
      color: #8492A6;
      background: rgba(255, 255, 255, 0.06);
      padding: 0.05rem 0.35rem;
      border-radius: 4px;
      margin-left: auto;
    }}
    .books-list {{
      list-style: none;
      padding-left: 0.4rem;
      margin: 0.2rem 0;
    }}
    .book-entry {{
      list-style: none;
      margin-bottom: 0.2rem;
    }}
    .book-summary {{
      font-size: 0.77rem;
      font-weight: 600;
      color: #94A3B8;
      padding: 0.32rem 0.5rem;
      border-radius: 5px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 0.4rem;
      user-select: none;
      transition: all 0.15s;
    }}
    .book-summary:hover {{
      color: #FFF;
      background: rgba(255, 255, 255, 0.05);
    }}
    .book-entry.active-book-entry .book-summary {{
      color: var(--gold-bright);
      background: rgba(212, 175, 55, 0.12);
      border: 1px solid rgba(212, 175, 55, 0.3);
    }}
    .book-title {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
    }}
    .book-count {{
      font-size: 0.68rem;
      font-family: var(--font-mono);
      color: #64748B;
      flex-shrink: 0;
    }}
    .tree-list, .node-children-list {{
      list-style: none;
      margin: 0.15rem 0 0.3rem 0;
      padding: 0;
    }}
    .tree-node {{
      border-radius: 4px;
      font-size: 0.8rem;
      line-height: 1.4;
      margin-bottom: 1px;
    }}
    .node-row {{
      display: flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.24rem 0.4rem;
      border-radius: 4px;
      transition: background 0.12s;
    }}
    .node-row:hover {{
      background: rgba(255, 255, 255, 0.05);
    }}
    .node-toggle {{
      width: 14px;
      height: 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.62rem;
      color: #8492A6;
      cursor: pointer;
      flex-shrink: 0;
      user-select: none;
      transition: color 0.15s;
    }}
    .node-toggle:hover {{
      color: #FFF;
    }}
    .node-spacer {{
      width: 14px;
      height: 14px;
      display: inline-block;
      flex-shrink: 0;
    }}
    .node-icon {{
      font-size: 0.72rem;
      flex-shrink: 0;
      opacity: 0.8;
    }}
    .node-link {{
      color: #CBD5E1;
      text-decoration: none;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
      transition: color 0.12s;
    }}
    .node-link:hover {{
      color: var(--cyan);
      text-decoration: underline;
    }}
    .node-title {{
      color: #94A3B8;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
    }}
    .node-badge {{
      font-size: 0.65rem;
      font-family: var(--font-mono);
      color: #64748B;
      background: rgba(255, 255, 255, 0.04);
      padding: 0.02rem 0.28rem;
      border-radius: 3px;
      flex-shrink: 0;
    }}
    .tree-node.active > .node-row {{
      background: rgba(212, 175, 55, 0.18);
      border: 1px solid rgba(212, 175, 55, 0.4);
    }}
    .tree-node.active > .node-row .node-link {{
      color: var(--gold-bright);
      font-weight: 700;
    }}
    .tree-node.ancestor > .node-row .node-link {{
      color: #FFF;
      font-weight: 600;
    }}

    /* Right Main Content Pane */
    .content-pane {{
      flex: 1;
      height: 100%;
      overflow-y: auto;
      padding: 2.2rem 3rem 4rem 3rem;
      background: var(--surface);
    }}
    .content-wrapper {{
      max-width: 960px;
      margin: 0 auto;
    }}

    /* Top Breadcrumb & Step Navigation */
    .content-nav-bar {{
      margin-bottom: 2rem;
      padding-bottom: 1.25rem;
      border-bottom: 1px solid var(--border);
    }}
    .nav-buttons-strip {{
      display: flex;
      gap: 0.65rem;
      flex-wrap: wrap;
      align-items: center;
      margin-top: 0.85rem;
    }}
    .nav-step-btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border);
      color: var(--text-muted);
      font-size: 0.82rem;
      padding: 0.38rem 0.85rem;
      border-radius: 6px;
      text-decoration: none;
      transition: all 0.15s;
    }}
    .nav-step-btn:hover {{
      background: rgba(56, 189, 248, 0.12);
      border-color: var(--cyan);
      color: #FFF;
    }}

    /* Document Typographical Styles */
    h1, h2, h3, h4, h5, h6 {{
      color: #FFF;
      font-weight: 600;
      margin-top: 2rem;
      margin-bottom: 0.85rem;
      letter-spacing: -0.01em;
    }}
    h1 {{ font-size: 1.85rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
    h2 {{ font-size: 1.45rem; }}
    h3 {{ font-size: 1.2rem; }}
    h4 {{ font-size: 1.05rem; }}
    p {{
      margin-bottom: 1.15rem;
      color: #CBD5E1;
    }}
    a {{
      color: var(--cyan);
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
    pre, code {{
      font-family: var(--font-mono);
      background: #06080B;
      color: #38BDF8;
      border-radius: 4px;
    }}
    p code, li code {{
      padding: 0.15rem 0.4rem;
      font-size: 0.88em;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }}
    pre {{
      padding: 1.25rem;
      margin: 1.25rem 0;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow-x: auto;
      line-height: 1.5;
    }}
    ul, ol {{
      margin: 0.75rem 0 1.25rem 1.75rem;
      color: #CBD5E1;
    }}
    li {{ margin-bottom: 0.4rem; }}
    .table-wrap {{
      overflow-x: auto;
      margin: 1.5rem 0;
      border-radius: 8px;
      border: 1px solid var(--border);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
    }}
    th, td {{
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--border);
      text-align: left;
    }}
    th {{
      background: #111620;
      color: var(--gold-bright);
      font-weight: 600;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}
    tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}
    img {{
      max-width: 100%;
      height: auto;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.16);
      margin: 1.25rem 0;
      background: #FFFFFF;
      padding: 14px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45);
      display: inline-block;
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}
    img:hover {{
      box-shadow: 0 6px 24px rgba(0, 0, 0, 0.65);
    }}
    .topic-bottom-nav {{
      margin-top: 3.5rem;
      padding-top: 1.5rem;
      border-top: 1px solid var(--border);
      display: flex;
      justify-content: center;
    }}

    /* Rich Document Visualizer Styles */
    .doc-format-hero {{
      background: linear-gradient(135deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 100%);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.25rem 1.5rem;
      margin-bottom: 2rem;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
    }}
    .doc-hero-badge {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 0.2rem 0.6rem;
      border-radius: 20px;
      margin-bottom: 0.5rem;
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: var(--cyan);
    }}
    .xlsx-hero .doc-hero-badge {{
      background: rgba(16, 185, 129, 0.12);
      border-color: rgba(16, 185, 129, 0.3);
      color: var(--emerald);
    }}
    .zip-hero .doc-hero-badge {{
      background: rgba(245, 158, 11, 0.12);
      border-color: rgba(245, 158, 11, 0.3);
      color: #F59E0B;
    }}
    .code-hero .doc-hero-badge {{
      background: rgba(212, 175, 55, 0.12);
      border-color: rgba(212, 175, 55, 0.3);
      color: var(--gold-bright);
    }}
    .doc-hero-title {{
      font-size: 1.4rem;
      font-weight: 700;
      color: #FFF;
      margin: 0.35rem 0 0.65rem 0;
      border-bottom: none;
      padding-bottom: 0;
      word-break: break-word;
    }}
    .doc-hero-meta {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 1.1rem;
      font-size: 0.78rem;
      font-family: var(--font-mono);
      color: var(--text-muted);
    }}
    .doc-callout {{
      border-radius: 6px;
      padding: 0.85rem 1.1rem;
      margin: 1.25rem 0;
      font-size: 0.88rem;
      line-height: 1.55;
    }}
    .callout-note {{
      background: rgba(56, 189, 248, 0.08);
      border-left: 4px solid var(--cyan);
      color: #BAE6FD;
    }}
    .callout-caution {{
      background: rgba(245, 158, 11, 0.08);
      border-left: 4px solid #F59E0B;
      color: #FDE68A;
    }}
    .callout-warning {{
      background: rgba(239, 68, 68, 0.08);
      border-left: 4px solid #EF4444;
      color: #FECACA;
    }}
    .callout-label {{
      font-weight: 700;
      font-size: 0.75rem;
      letter-spacing: 0.04em;
      margin-bottom: 0.35rem;
    }}
    .doc-callout p {{
      margin-bottom: 0;
      color: inherit;
    }}
    .docx-image-card {{
      margin: 1.5rem 0;
      text-align: center;
    }}
    .docx-embedded-img {{
      max-width: 95%;
      height: auto;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.16);
      background: #FFFFFF;
      padding: 12px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45);
      display: inline-block;
    }}
    .docx-embedded-img:hover {{
      box-shadow: 0 6px 24px rgba(0, 0, 0, 0.65);
    }}
    .doc-bullet-list {{
      margin: 0.5rem 0 1rem 1.5rem;
      color: #CBD5E1;
    }}
    .doc-bullet-list li {{
      margin-bottom: 0.35rem;
    }}

    /* Spreadsheet Visualizer */
    .sheet-viewer-controls {{
      margin-bottom: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }}
    .sheet-tabs-container {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.45rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.65rem;
    }}
    .sheet-tab-btn {{
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 6px;
      padding: 0.38rem 0.75rem;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      transition: all 0.15s;
    }}
    .sheet-tab-btn:hover {{
      color: #FFF;
      background: rgba(255, 255, 255, 0.08);
      border-color: var(--border-bright);
    }}
    .sheet-tab-btn.active {{
      background: rgba(16, 185, 129, 0.14);
      border-color: rgba(16, 185, 129, 0.4);
      color: var(--emerald);
      box-shadow: 0 0 12px rgba(16, 185, 129, 0.15);
    }}
    .sheet-tab-badge {{
      font-size: 0.68rem;
      font-family: var(--font-mono);
      background: rgba(255, 255, 255, 0.06);
      padding: 0.05rem 0.35rem;
      border-radius: 4px;
      color: inherit;
    }}
    .sheet-filter-bar {{
      position: relative;
    }}
    .sheet-filter-input {{
      width: 100%;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.45rem 0.85rem;
      font-size: 0.82rem;
      color: var(--text);
      outline: none;
      transition: border-color 0.15s;
    }}
    .sheet-filter-input:focus {{
      border-color: var(--cyan);
      background: rgba(255, 255, 255, 0.06);
    }}
    .sheet-table-wrap {{
      max-height: 70vh;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    .sheet-table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 0.82rem;
      font-family: var(--font-sans);
    }}
    .sheet-table thead th {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: #111620;
      border-bottom: 2px solid var(--border-bright);
      color: var(--gold-bright);
      font-family: var(--font-mono);
      font-size: 0.75rem;
      padding: 0.5rem 0.75rem;
      text-align: center;
      white-space: nowrap;
    }}
    .sheet-table td {{
      padding: 0.45rem 0.75rem;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      border-right: 1px solid rgba(255, 255, 255, 0.03);
      color: #CBD5E1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 320px;
    }}
    .sheet-row:nth-child(even) td {{
      background: rgba(255, 255, 255, 0.015);
    }}
    .sheet-row:hover td {{
      background: rgba(56, 189, 248, 0.08);
      color: #FFF;
    }}
    .row-num-col, .row-num-cell {{
      width: 44px;
      min-width: 44px;
      text-align: center !important;
      font-family: var(--font-mono);
      font-size: 0.72rem;
      color: #64748B !important;
      background: #0B0E14 !important;
      user-select: none;
      border-right: 1px solid var(--border) !important;
    }}
    .sheet-header-row td {{
      font-weight: 700;
      color: #FFF;
      background: rgba(255, 255, 255, 0.04) !important;
    }}
    .sheet-truncation-note {{
      margin-top: 0.65rem;
      font-size: 0.75rem;
      font-family: var(--font-mono);
      color: #94A3B8;
      text-align: center;
    }}

    /* Nested Archive Table */
    .zip-listing-table td {{
      font-size: 0.82rem;
      padding: 0.55rem 0.85rem;
    }}
    .zip-entry-name {{
      color: #E2E8F0;
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 0.45rem;
    }}
    .zip-format-badge {{
      font-size: 0.68rem;
      font-family: var(--font-mono);
      background: rgba(255, 255, 255, 0.06);
      padding: 0.1rem 0.4rem;
      border-radius: 4px;
      color: var(--cyan);
    }}
    .zip-open-btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      background: rgba(56, 189, 248, 0.1);
      border: 1px solid rgba(56, 189, 248, 0.25);
      color: var(--cyan);
      padding: 0.25rem 0.65rem;
      border-radius: 4px;
      font-size: 0.75rem;
      text-decoration: none;
      transition: all 0.15s;
    }}
    .zip-open-btn:hover {{
      background: rgba(56, 189, 248, 0.2);
      border-color: var(--cyan);
      color: #FFF;
      text-decoration: none;
    }}

    /* Code Block Visualizer */
    .btn-copy-code {{
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border);
      color: var(--cyan);
      border-radius: 6px;
      padding: 0.3rem 0.75rem;
      font-size: 0.75rem;
      font-family: var(--font-mono);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      transition: all 0.15s;
      margin-left: auto;
    }}
    .btn-copy-code:hover {{
      background: rgba(56, 189, 248, 0.15);
      border-color: var(--cyan);
      color: #FFF;
    }}
    .code-block-container {{
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      margin-top: 1.5rem;
      background: #06080B;
    }}
    .code-block-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.45rem 1rem;
      background: #0E131C;
      border-bottom: 1px solid var(--border);
      font-size: 0.76rem;
      font-family: var(--font-mono);
      color: var(--text-muted);
    }}
    .code-pre {{
      padding: 1rem 0;
      margin: 0;
      border: none;
      border-radius: 0;
      background: transparent;
      max-height: 75vh;
      overflow: auto;
      font-size: 0.82rem;
      line-height: 1.5;
    }}
    .code-line {{
      display: flex;
      padding: 0.1rem 1rem;
    }}
    .code-line:hover {{
      background: rgba(255, 255, 255, 0.03);
    }}
    .line-num {{
      width: 45px;
      min-width: 45px;
      text-align: right;
      padding-right: 1.25rem;
      color: #475569;
      user-select: none;
    }}
    .line-text {{
      color: #E2E8F0;
      white-space: pre-wrap;
      word-break: break-all;
    }}

    /* Responsive Mobile Layout */
    @media (max-width: 860px) {{
      .sidebar {{
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        z-index: 50;
        box-shadow: 4px 0 24px rgba(0, 0, 0, 0.8);
      }}
      .content-pane {{
        padding: 1.5rem 1rem;
      }}
    }}
  </style>
</head>
<body>
  <!-- Header Bar -->
  <header class="app-header">
    <div class="header-left">
      <button type="button" class="toggle-sidebar-btn" onclick="toggleSidebar()" title="Toggle Outline Sidebar (Cmd+B)">
        <span>◨</span> <span>Library Tree</span>
      </button>
      <div class="header-doc-title" title="{html.escape(doc_display_title)}">
        📖 {html.escape(doc_display_title)}
      </div>
    </div>
    <div class="header-actions">
      <span style="font-family: var(--font-mono); font-size: 0.74rem; color: var(--emerald); display: inline-flex; align-items: center; gap: 0.35rem; margin-right: 0.75rem;">
        <span>🛡️</span> <span>O_RDONLY Stream</span> • <span>Zero-Disk Verified</span>
      </span>
      <a href="/portal" class="btn-header btn-header-primary">
        <span>⬅</span> <span>Back to Search</span>
      </a>
    </div>
  </header>

  <!-- Toast Notification -->
  <div id="doc-toast">Notification</div>

  <!-- Body Container -->
  <div class="app-body" id="app-body">
    <!-- Left Sidebar: HedEx Tree of Trees -->
    <aside class="sidebar" id="sidebar">
      <div class="sidebar-header">
        <div class="manual-tag">
          <span>📦</span>
          <span title="{html.escape(package_name)} Library">{html.escape(package_name)} Documentation Library</span>
        </div>
        <div class="sidebar-search">
          <input type="text" id="tree-search" placeholder="🔍 Filter &amp; search all manual topics..." oninput="handleTreeSearch(this.value)" />
        </div>
      </div>
      <div class="sidebar-tree-container">
        <div id="tree-search-panel" class="tree-search-panel" style="display: none;">
          <div class="tree-search-header">
            <span id="tree-search-count">0 manual matches</span>
            <button type="button" class="tree-search-close" onclick="closeSearchPanel()">✕ Close</button>
          </div>
          <ul id="tree-search-results-list" class="tree-search-results-list"></ul>
        </div>
        {sidebar_tree_html}
      </div>
    </aside>

    <!-- Right Main Content -->
    <main class="content-pane" id="content-pane">
      <div class="content-wrapper">
        <div class="content-nav-bar">
          {breadcrumb_html}
          {buttons_strip}
        </div>
        <article class="document-article">
          {raw_body_html}
        </article>
        {bottom_nav_html}
      </div>
    </main>
  </div>

  <script>
    const VIRTUAL_URI = "{html.escape(virtual_uri)}";
    const CURRENT_PACKAGE = "{html.escape(package_name)}";

    function showToast(msg) {{
      const toast = document.getElementById("doc-toast");
      if (!toast) return;
      toast.innerText = msg;
      toast.style.display = "block";
      setTimeout(() => {{
        toast.style.display = "none";
      }}, 2500);
    }}

    function toggleSidebar() {{
      document.getElementById("app-body").classList.toggle("sidebar-collapsed");
    }}

    function escapeHtml(str) {{
      if (!str) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }}

    function toggleTopicChildren(event, topicId) {{
      if (event) {{
        event.stopPropagation();
        event.preventDefault();
      }}
      const li = document.getElementById("node-" + topicId);
      const ul = document.getElementById("children-" + topicId);
      if (!li || !ul) return;
      const toggleBtn = li.querySelector(".node-toggle");

      if (ul.style.display !== "none") {{
        ul.style.display = "none";
        if (toggleBtn) toggleBtn.textContent = "▶";
      }} else {{
        if (ul.children.length > 0) {{
          ul.style.display = "block";
          if (toggleBtn) toggleBtn.textContent = "▼";
        }} else {{
          if (toggleBtn) toggleBtn.textContent = "⏳";
          fetch("/topic/tree?mode=children&parent_id=" + encodeURIComponent(topicId))
            .then(res => res.json())
            .then(data => {{
              const children = data.children || [];
              if (children.length === 0) {{
                ul.innerHTML = '<li class="tree-empty" style="padding-left: 20px; font-size: 0.75rem; color: #64748B;">(No subtopics)</li>';
              }} else {{
                let htmlStr = "";
                children.forEach(c => {{
                  const hasSub = c.child_count > 0;
                  const cUri = c.uri ? `/archive/view?uri=${{encodeURIComponent(c.uri)}}` : "";
                  const linkOrSpan = cUri
                    ? `<a href="${{cUri}}" class="node-link" title="${{escapeHtml(c.name)}}">${{escapeHtml(c.name)}}</a>`
                    : `<span class="node-title" title="${{escapeHtml(c.name)}}">${{escapeHtml(c.name)}}</span>`;
                  const pad = ((c.depth || 2) - 1) * 12 + 6;
                  if (hasSub) {{
                    htmlStr += `
                      <li class="tree-node folder-node depth-${{c.depth || 2}}" id="node-${{c.topic_id}}" data-title="${{escapeHtml(c.name.toLowerCase())}}">
                        <div class="node-row" style="padding-left: ${{pad}}px;">
                          <span class="node-toggle" onclick="toggleTopicChildren(event, '${{c.topic_id}}')">▶</span>
                          <span class="node-icon">📁</span>
                          ${{linkOrSpan}}
                          <span class="node-badge">${{c.child_count}}</span>
                        </div>
                        <ul class="node-children-list" id="children-${{c.topic_id}}" style="display: none;"></ul>
                      </li>
                    `;
                  }} else {{
                    htmlStr += `
                      <li class="tree-node leaf-node depth-${{c.depth || 2}}" id="node-${{c.topic_id}}" data-title="${{escapeHtml(c.name.toLowerCase())}}">
                        <div class="node-row" style="padding-left: ${{pad}}px;">
                          <span class="node-spacer"></span>
                          <span class="node-icon">📄</span>
                          ${{linkOrSpan}}
                        </div>
                      </li>
                    `;
                  }}
                }});
                ul.innerHTML = htmlStr;
              }}
              ul.style.display = "block";
              if (toggleBtn) toggleBtn.textContent = "▼";
            }})
            .catch(err => {{
              console.error("Failed to load topic children:", err);
              if (toggleBtn) toggleBtn.textContent = "▶";
            }});
        }}
      }}
    }}

    function loadBookTopicsLazy(summaryEl, package, source) {{
      const details = summaryEl.closest(".book-details");
      if (!details) return;
      const listEl = details.querySelector(".lazy-tree-list");
      if (!listEl || listEl.children.length > 0) return;

      listEl.innerHTML = '<li class="tree-loading" style="padding: 0.5rem 1rem; font-size: 0.75rem; color: #8492A6;">⏳ Loading manual chapters...</li>';

      fetch("/topic/tree?mode=book&package=" + encodeURIComponent(package) + "&source=" + encodeURIComponent(source))
        .then(res => res.json())
        .then(data => {{
          const nodes = data.nodes || [];
          if (nodes.length === 0) {{
            listEl.innerHTML = '<li class="tree-empty" style="padding: 0.5rem 1rem; font-size: 0.75rem; color: #64748B;">(Empty manual)</li>';
            return;
          }}
          let htmlStr = "";
          nodes.forEach(n => {{
            const hasSub = n.child_count > 0;
            const nUri = n.uri ? `/archive/view?uri=${{encodeURIComponent(n.uri)}}` : "";
            const linkOrSpan = nUri
              ? `<a href="${{nUri}}" class="node-link" title="${{escapeHtml(n.name)}}">${{escapeHtml(n.name)}}</a>`
              : `<span class="node-title" title="${{escapeHtml(n.name)}}">${{escapeHtml(n.name)}}</span>`;
            const pad = ((n.depth || 1) - 1) * 12 + 6;
            if (hasSub) {{
              htmlStr += `
                <li class="tree-node folder-node depth-${{n.depth || 1}}" id="node-${{n.topic_id}}" data-title="${{escapeHtml(n.name.toLowerCase())}}">
                  <div class="node-row" style="padding-left: ${{pad}}px;">
                    <span class="node-toggle" onclick="toggleTopicChildren(event, '${{n.topic_id}}')">▶</span>
                    <span class="node-icon">📁</span>
                    ${{linkOrSpan}}
                    <span class="node-badge">${{n.child_count}}</span>
                  </div>
                  <ul class="node-children-list" id="children-${{n.topic_id}}" style="display: none;"></ul>
                </li>
              `;
            }} else {{
              htmlStr += `
                <li class="tree-node leaf-node depth-${{n.depth || 1}}" id="node-${{n.topic_id}}" data-title="${{escapeHtml(n.name.toLowerCase())}}">
                  <div class="node-row" style="padding-left: ${{pad}}px;">
                    <span class="node-spacer"></span>
                    <span class="node-icon">📄</span>
                    ${{linkOrSpan}}
                  </div>
                </li>
              `;
            }}
          }});
          listEl.innerHTML = htmlStr;
        }})
        .catch(err => {{
          console.error("Failed to load book topics:", err);
          listEl.innerHTML = '<li class="tree-error" style="padding: 0.5rem 1rem; font-size: 0.75rem; color: #EF4444;">Failed to load topics</li>';
        }});
    }}

    function filterTreeTopics(query) {{
      const q = (query || "").trim().toLowerCase();
      const items = document.querySelectorAll(".tree-node, .book-entry");
      items.forEach(el => {{
        const title = el.getAttribute("data-title") || el.innerText.toLowerCase();
        if (!q || title.includes(q)) {{
          el.style.display = "";
        }} else {{
          el.style.display = "none";
        }}
      }});
      if (q) {{
        document.querySelectorAll(".cat-details, .book-details").forEach(d => d.open = true);
      }}
    }}

    let searchDebounceTimer = null;
    function handleTreeSearch(query) {{
      filterTreeTopics(query);
      clearTimeout(searchDebounceTimer);
      const q = (query || "").trim();
      const panel = document.getElementById("tree-search-panel");
      const listEl = document.getElementById("tree-search-results-list");
      const countEl = document.getElementById("tree-search-count");
      if (q.length < 2) {{
        if (panel) panel.style.display = "none";
        return;
      }}
      searchDebounceTimer = setTimeout(() => {{
        fetch("/topic/tree?mode=search&q=" + encodeURIComponent(q))
          .then(res => res.json())
          .then(data => {{
            const results = data.results || [];
            if (results.length === 0) {{
              if (panel) panel.style.display = "none";
              return;
            }}
            if (panel && listEl) {{
              countEl.innerText = results.length + " manual topic matches";
              let itemsHtml = "";
              results.forEach(r => {{
                const url = r.uri ? ("/archive/view?uri=" + encodeURIComponent(r.uri)) : "#";
                const pkgBadge = r.package ? `<span class="tree-search-pkg-badge">${{escapeHtml(r.package)}}</span>` : "";
                itemsHtml += `
                  <li class="tree-search-item">
                    <a href="${{url}}" class="tree-search-link" title="${{escapeHtml(r.name)}}">
                      ${{pkgBadge}}
                      <span>${{escapeHtml(r.name)}}</span>
                    </a>
                    <span class="tree-search-meta">${{escapeHtml(r.source || "")}} • depth ${{r.depth}}</span>
                  </li>
                `;
              }});
              listEl.innerHTML = itemsHtml;
              panel.style.display = "block";
            }}
          }})
          .catch(err => console.debug("Topic search error:", err));
      }}, 350);
    }}

    function closeSearchPanel() {{
      const panel = document.getElementById("tree-search-panel");
      if (panel) panel.style.display = "none";
    }}

    // Spreadsheet Visualizer Helpers
    function switchSheetTab(paneId, btnEl) {{
      document.querySelectorAll(".sheet-pane").forEach(p => p.style.display = "none");
      document.querySelectorAll(".sheet-tab-btn").forEach(b => b.classList.remove("active"));
      const target = document.getElementById(paneId);
      if (target) target.style.display = "block";
      if (btnEl) btnEl.classList.add("active");
      const input = document.querySelector(".sheet-filter-input");
      if (input) input.value = "";
    }}

    function filterActiveSheet(query) {{
      const q = (query || "").toLowerCase().trim();
      const activePane = Array.from(document.querySelectorAll(".sheet-pane")).find(p => p.style.display !== "none");
      if (!activePane) return;
      const rows = activePane.querySelectorAll("tbody tr.sheet-row:not(.sheet-header-row)");
      rows.forEach(r => {{
        const text = r.getAttribute("data-row-text") || r.innerText.toLowerCase();
        if (!q || text.includes(q)) {{
          r.style.display = "";
        }} else {{
          r.style.display = "none";
        }}
      }});
    }}

    // Code Visualizer Helpers
    function copyDocumentContent() {{
      const area = document.getElementById("raw-code-payload");
      if (!area) return;
      navigator.clipboard.writeText(area.value).then(() => {{
        showToast("Copied content to clipboard!");
      }}).catch(err => {{
        console.error("Clipboard copy failed:", err);
        showToast("Failed to copy to clipboard");
      }});
    }}

    // Auto-scroll active topic into center view on load
    window.addEventListener("DOMContentLoaded", () => {{
      const activeEl = document.querySelector(".tree-node.active");
      if (activeEl) {{
        activeEl.scrollIntoView({{ block: "center", behavior: "auto" }});
      }}
    }});

    // Keyboard shortcut Cmd+B / Ctrl+B to toggle sidebar
    document.addEventListener("keydown", (e) => {{
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {{
        e.preventDefault();
        toggleSidebar();
      }}
    }});
  </script>
</body>
</html>"""
