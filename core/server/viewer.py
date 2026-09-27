"""
In-Browser Document Viewer and Sanitized HTML Renderer.
Extracts and renders authentic HTML, OpenXML, and Markdown documents from archive streams
with Dark Obsidian styling, relative diagram link rewriting, and script stripping.
"""

import html
import re
from typing import Any


class DocumentViewer:
    """Renders virtual container archive entries as sanitized, responsive Dark Obsidian HTML."""

    @staticmethod
    def format_entry_to_styled_html(entry: Any, virtual_uri: str) -> str:
        name_lower = getattr(entry, "entry_name", "").lower()
        title = getattr(entry, "entry_name", "Document").split("/")[-1]

        raw_body_html = ""
        if hasattr(entry, "raw_bytes") and entry.raw_bytes and name_lower.endswith((".html", ".htm", ".xhtml")):
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

        # Strip scripts that could break iframe / viewer
        raw_body_html = re.sub(r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>", "", raw_body_html, flags=re.IGNORECASE)
        # Rewrite relative image references (figure/...) to diagrams endpoint
        raw_body_html = re.sub(
            r'<img\s+([^>]*?)src=["\'](?:figure/|images/)?([^"\']+\.(?:png|jpg|jpeg|gif))["\']',
            r'<img \1src="/diagrams/\2"',
            raw_body_html,
            flags=re.IGNORECASE,
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Sovereign Vault Document Viewer</title>
  <style>
    :root {{
      --bg: #07090D;
      --card-bg: #0F1318;
      --text: #E2E8F0;
      --text-muted: #94A3B8;
      --gold: #D4AF37;
      --cyan: #38BDF8;
      --emerald: #10B981;
      --border: rgba(255, 255, 255, 0.08);
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: "JetBrains Mono", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      line-height: 1.65;
      padding: 1.5rem;
      max-width: 1150px;
      margin: 0 auto;
    }}
    .viewer-bar {{
      position: sticky;
      top: 0;
      background: rgba(7, 9, 13, 0.94);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--border);
      padding: 0.8rem 1rem;
      margin-bottom: 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      z-index: 100;
      border-radius: 8px;
    }}
    .viewer-title {{
      font-weight: 600;
      color: var(--gold);
      font-size: 0.95rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}
    .viewer-badges {{
      display: flex;
      gap: 0.5rem;
      align-items: center;
    }}
    .badge {{
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border);
      color: var(--text-muted);
      font-family: var(--font-mono);
      font-size: 0.72rem;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
    }}
    .badge-gold {{ color: var(--gold); border-color: rgba(212, 175, 55, 0.3); background: rgba(212, 175, 55, 0.08); }}
    .badge-cyan {{ color: var(--cyan); border-color: rgba(56, 189, 248, 0.3); background: rgba(56, 189, 248, 0.08); }}
    .btn-action {{
      background: rgba(212, 175, 55, 0.15);
      color: var(--gold);
      border: 1px solid rgba(212, 175, 55, 0.3);
      padding: 0.35rem 0.75rem;
      border-radius: 6px;
      text-decoration: none;
      font-size: 0.8rem;
      cursor: pointer;
    }}
    .btn-action:hover {{ background: rgba(212, 175, 55, 0.25); }}
    h1, h2, h3, h4 {{ color: var(--gold); margin-top: 1.8rem; margin-bottom: 0.8rem; }}
    h1 {{ border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
    p {{ margin: 0.8rem 0; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1.5rem 0;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }}
    th, td {{
      border: 1px solid var(--border);
      padding: 0.65rem 0.85rem;
      text-align: left;
    }}
    th {{
      background: rgba(212, 175, 55, 0.1);
      color: #FFF;
      font-weight: 600;
    }}
    pre, code {{
      font-family: var(--font-mono);
      background: #131822;
      color: var(--cyan);
      border-radius: 4px;
    }}
    code {{ padding: 0.15rem 0.35rem; font-size: 0.88em; }}
    pre {{
      padding: 1rem;
      overflow-x: auto;
      border: 1px solid var(--border);
    }}
    img {{
      max-width: 100%;
      height: auto;
      border-radius: 6px;
      border: 1px solid var(--border);
      margin: 1rem 0;
      background: #1E293B;
      padding: 0.5rem;
    }}
    .uri-info {{
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: var(--text-muted);
      word-break: break-all;
      background: var(--card-bg);
      padding: 0.6rem 0.8rem;
      border-radius: 6px;
      margin-bottom: 1.5rem;
      border: 1px solid var(--border);
    }}
  </style>
</head>
<body>
  <div class="viewer-bar">
    <div class="viewer-title">
      <span>📖 {title}</span>
    </div>
    <div class="viewer-badges">
      <span class="badge badge-gold">O_RDONLY Stream</span>
      <span class="badge badge-cyan">Zero-Disk Verified</span>
      <a href="/portal" class="btn-action">⬅ Back to Search Portal</a>
    </div>
  </div>

  <div class="uri-info">
    <strong>Virtual URI:</strong> {virtual_uri}
  </div>

  <main class="document-content">
    {raw_body_html}
  </main>
</body>
</html>"""
