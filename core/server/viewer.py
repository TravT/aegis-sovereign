"""
In-Browser Document Viewer and Sanitized HTML Renderer.
Extracts and renders authentic HTML, OpenXML, and Markdown documents from archive streams
with Dark Obsidian styling, relative diagram link rewriting, HedEx tree sidebar navigation,
and zero intrusive raw URI clutter.
"""

import html
import posixpath
import re
import urllib.parse
from typing import Any, Optional, Dict, List


class DocumentViewer:
    """Renders virtual container archive entries as sanitized, responsive Dark Obsidian HTML with a full HedEx tree sidebar."""

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

        # Build Sidebar Tree HTML
        sidebar_tree_html = ""
        manual_title = "Document Outline"
        manual_count = 0
        if bookmap_tree and bookmap_tree.get("nodes"):
            manual_title = bookmap_tree.get("manual_title") or "Manual Contents"
            nodes = bookmap_tree["nodes"]
            manual_count = len(nodes)
            tree_items = []
            for n in nodes:
                depth = max(1, min(6, n.get("depth", 1)))
                n_name = html.escape(n.get("name") or "Topic")
                n_uri = n.get("uri")
                is_act = n.get("is_active", False)
                is_anc = n.get("is_ancestor", False)

                cls_list = ["tree-node", f"depth-{depth}"]
                if is_act:
                    cls_list.append("active")
                elif is_anc:
                    cls_list.append("ancestor")

                pad_left = (depth - 1) * 14 + 10
                if n_uri:
                    target_url = f"/archive/view?uri={urllib.parse.quote(n_uri)}"
                    marker = "●" if is_act else "📄"
                    tree_items.append(
                        f'<li class="{" ".join(cls_list)}" style="padding-left: {pad_left}px;" data-title="{n_name.lower()}">'
                        f'<a href="{target_url}" title="{n_name}"><span class="tree-bullet">{marker}</span> {n_name}</a>'
                        f'</li>'
                    )
                else:
                    marker = "●" if is_act else "📁"
                    tree_items.append(
                        f'<li class="{" ".join(cls_list)} muted" style="padding-left: {pad_left}px;" data-title="{n_name.lower()}">'
                        f'<span><span class="tree-bullet">{marker}</span> {n_name}</span>'
                        f'</li>'
                    )
            sidebar_tree_html = "".join(tree_items)

        # Fallback to local siblings if bookmap_tree not present
        if not sidebar_tree_html and topic_hierarchy and topic_hierarchy.get("siblings"):
            sibs = topic_hierarchy["siblings"]
            cur = topic_hierarchy["current"]
            manual_title = "Chapter Sections"
            manual_count = len(sibs)
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
                        f'<a href="{target_url}"><span class="tree-bullet">{"●" if is_act else "📄"}</span> {s_name}</a>'
                        f'</li>'
                    )
                else:
                    tree_items.append(
                        f'<li class="{" ".join(cls_list)} muted" style="padding-left: 10px;" data-title="{s_name.lower()}">'
                        f'<span><span class="tree-bullet">{"●" if is_act else "📄"}</span> {s_name}</span>'
                        f'</li>'
                    )
            sidebar_tree_html = "".join(tree_items)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(doc_display_title)} — Sovereign Knowledge Appliance</title>
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
    .sidebar-tree-container {{
      flex: 1;
      overflow-y: auto;
      padding: 0.65rem 0.5rem 2rem 0.5rem;
    }}
    .tree-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 0.15rem;
    }}
    .tree-node {{
      border-radius: 5px;
      font-size: 0.82rem;
      line-height: 1.45;
      transition: background 0.12s;
    }}
    .tree-node a, .tree-node span {{
      display: flex;
      align-items: baseline;
      gap: 0.45rem;
      padding: 0.35rem 0.5rem;
      color: var(--text-muted);
      text-decoration: none;
      word-break: break-word;
    }}
    .tree-node a:hover {{
      color: #FFF;
      background: rgba(255, 255, 255, 0.04);
      border-radius: 5px;
    }}
    .tree-node.active {{
      background: rgba(212, 175, 55, 0.12);
      border: 1px solid rgba(212, 175, 55, 0.35);
    }}
    .tree-node.active a {{
      color: var(--gold-bright);
      font-weight: 600;
    }}
    .tree-node.ancestor a {{
      color: var(--text);
      font-weight: 500;
    }}
    .tree-node.muted span {{
      color: var(--text-muted);
      opacity: 0.75;
    }}
    .tree-bullet {{
      font-size: 0.72rem;
      opacity: 0.7;
      flex-shrink: 0;
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
      border-radius: 6px;
      border: 1px solid var(--border);
      margin: 1rem 0;
      background: #000;
      display: inline-block;
    }}
    .topic-bottom-nav {{
      margin-top: 3.5rem;
      padding-top: 1.5rem;
      border-top: 1px solid var(--border);
      display: flex;
      justify-content: center;
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
        <span>◨</span> <span>Outline</span>
      </button>
      <div class="header-doc-title" title="{html.escape(doc_display_title)}">
        📖 {html.escape(doc_display_title)}
      </div>
    </div>
    <div class="header-actions">
      <button type="button" class="btn-header" onclick="copyVirtualUri()" title="Copy Virtual Archive URI">
        <span>📋</span> <span>Copy URI</span>
      </button>
      <a href="/portal" class="btn-header btn-header-primary">
        <span>⬅</span> <span>Back to Search</span>
      </a>
    </div>
  </header>

  <!-- Toast Notification -->
  <div id="doc-toast">Copied URI to clipboard!</div>

  <!-- Body Container -->
  <div class="app-body" id="app-body">
    <!-- Left Sidebar: HedEx Tree -->
    <aside class="sidebar" id="sidebar">
      <div class="sidebar-header">
        <div class="manual-tag">
          <span>📘</span>
          <span title="{html.escape(manual_title)}">{html.escape(manual_title)}</span>
          <span class="manual-count">{manual_count}</span>
        </div>
        <div class="sidebar-search">
          <input type="text" id="tree-search" placeholder="🔍 Filter manual topics..." oninput="filterTreeTopics(this.value)" />
        </div>
      </div>
      <div class="sidebar-tree-container">
        <ul class="tree-list" id="tree-list">
          {sidebar_tree_html}
        </ul>
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

    function copyVirtualUri() {{
      const uri = VIRTUAL_URI;
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(uri).then(() => {{
          showToast("Virtual URI copied to clipboard!");
        }}).catch(() => {{
          fallbackCopyText(uri);
        }});
      }} else {{
        fallbackCopyText(uri);
      }}
    }}

    function fallbackCopyText(text) {{
      try {{
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        showToast("Virtual URI copied to clipboard!");
      }} catch (err) {{
        showToast("Failed to copy URI.");
      }}
    }}

    function showToast(msg) {{
      const toast = document.getElementById("doc-toast");
      toast.innerText = msg;
      toast.style.display = "block";
      setTimeout(() => {{
        toast.style.display = "none";
      }}, 2500);
    }}

    function toggleSidebar() {{
      document.getElementById("app-body").classList.toggle("sidebar-collapsed");
    }}

    function filterTreeTopics(query) {{
      const q = (query || "").trim().toLowerCase();
      const items = document.querySelectorAll("#tree-list .tree-node");
      items.forEach(el => {{
        const title = el.getAttribute("data-title") || "";
        if (!q || title.includes(q)) {{
          el.style.display = "";
        }} else {{
          el.style.display = "none";
        }}
      }});
    }}

    // Auto-scroll active topic into center view on load
    window.addEventListener("DOMContentLoaded", () => {{
      const activeEl = document.querySelector("#tree-list .tree-node.active");
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
