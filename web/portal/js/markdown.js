/**
 * Aegis Sovereign Web Portal - Markdown & Document Rendering Engine
 * Fully client-side zero-dependency Markdown parser supporting:
 * - Clickable Document & Viewer links [Text](URL)
 * - Interactive Citation Chips [1], [2]
 * - GitHub Alert Callouts (> [!IMPORTANT], > [!NOTE], > [!WARNING], > [!TIP])
 * - Responsive Markdown Tables (| Col | Col |)
 * - Fenced Code Blocks (```mml ... ```) with 1-click clipboard copy
 * - MML Command Pills with 1-click execution / copy
 */

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function copyMmlFromCard(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text);
  }
  if (typeof showPortalToast === "function") {
    showPortalToast(`📋 Copied MML command: ${text.slice(0, 45)}`);
  }
}

function copyCodeFromBlock(btn) {
  const wrap = btn.closest(".code-block-wrap");
  if (!wrap) return;
  const codeEl = wrap.querySelector("code");
  if (codeEl && navigator.clipboard) {
    navigator.clipboard.writeText(codeEl.innerText);
    const origText = btn.innerHTML;
    btn.innerHTML = "✓ Copied!";
    setTimeout(() => { btn.innerHTML = origText; }, 2000);
    if (typeof showPortalToast === "function") {
      showPortalToast("📋 Copied code block to clipboard!");
    }
  }
}

function scrollToSource(index) {
  const el = document.getElementById(`source-card-${index}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('highlight-pulse');
    setTimeout(() => el.classList.remove('highlight-pulse'), 2500);
  }
}

function resolveRelativeWikiPath(baseUri, relHref) {
  if (!relHref) return "";
  if (/^(https?:|mailto:|#|\/archive\/view)/i.test(relHref)) {
    return relHref;
  }
  let isArchive = (baseUri || "").startsWith("archive://");
  let rawBase = isArchive ? baseUri.slice("archive://".length) : (baseUri || "");
  
  if (!rawBase) {
    rawBase = "/home/tlima/Enterprise_Hub/docs/wiki/README.md";
  }

  if (relHref.startsWith("/home/tlima/Enterprise_Hub/")) {
    return isArchive ? `archive://${relHref}` : relHref;
  }

  let baseDir = rawBase.includes("/") ? rawBase.substring(0, rawBase.lastIndexOf("/")) : "/home/tlima/Enterprise_Hub/docs/wiki";
  let parts = baseDir.split("/").filter(Boolean);
  let relParts = relHref.split("/").filter(Boolean);

  for (let p of relParts) {
    if (p === ".") continue;
    if (p === "..") {
      if (parts.length > 0) parts.pop();
    } else {
      parts.push(p);
    }
  }

  let resolved = "/" + parts.join("/");
  return isArchive ? `archive://${resolved}` : `archive://${resolved}`;
}

function parseYamlFrontmatter(text) {
  if (!text || typeof text !== "string") return { meta: {}, cleanText: text || "" };
  const match = text.match(/^\s*---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/);
  if (!match) return { meta: {}, cleanText: text };

  const rawMeta = match[1];
  const cleanText = text.slice(match[0].length).trim();
  const meta = {};

  const lines = rawMeta.split("\n");
  for (let line of lines) {
    const colonIdx = line.indexOf(":");
    if (colonIdx > 0) {
      const key = line.slice(0, colonIdx).trim();
      let val = line.slice(colonIdx + 1).trim();
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      meta[key] = val;
    }
  }

  return { meta, cleanText };
}

function renderMetaPillsHtml(meta) {
  if (!meta || Object.keys(meta).length === 0) return "";
  let pills = [];

  if (meta.status) {
    const st = escapeHtml(meta.status);
    const cls = st.toLowerCase().includes("active") || st.toLowerCase().includes("completed") ? "pill-emerald" : "pill-gold";
    pills.push(`<span class="meta-pill ${cls}">Status: <strong>${st}</strong></span>`);
  }
  if (meta.type) {
    pills.push(`<span class="meta-pill pill-cyan">Type: <strong>${escapeHtml(meta.type)}</strong></span>`);
  }
  if (meta.domain) {
    pills.push(`<span class="meta-pill pill-purple">Domain: <strong>${escapeHtml(meta.domain)}</strong></span>`);
  }
  if (meta.tags) {
    const tags = String(meta.tags).replace(/[\[\]"]/g, "").split(",").map(t => t.trim()).filter(Boolean);
    tags.slice(0, 3).forEach(t => {
      pills.push(`<span class="meta-pill pill-tag">#${escapeHtml(t)}</span>`);
    });
  }
  if (meta.last_reviewed) {
    pills.push(`<span class="meta-pill pill-neutral">Reviewed: ${escapeHtml(meta.last_reviewed)}</span>`);
  }

  if (!pills.length) return "";
  return `<div class="card-meta-pills">${pills.join("")}</div>`;
}

function formatInlineMd(text, currentUri) {
  if (!text) return "";
  let s = escapeHtml(text);
  
  // Strong: **bold**
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  
  // Italic: *italic*
  s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  
  // Inline code: `code`
  s = s.replace(/`([^`]+)`/g, '<code class="md-inline-code">$1</code>');
  
  // Markdown links: [Text](URL) -> smart relative wiki link or external link
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, label, url) {
    const isExternal = /^(https?:|mailto:)/i.test(url);
    if (isExternal) {
      return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="portal-doc-link external" title="External Link: ${url}">${label} ↗</a>`;
    }
    const base = currentUri || (typeof window !== "undefined" && window.currentInspectedUri) || "";
    const resolved = resolveRelativeWikiPath(base, url);
    const viewerUrl = `/archive/view?uri=${encodeURIComponent(resolved)}`;
    return `<a href="${viewerUrl}" onclick="if (typeof handleWikiLinkClick === 'function') { return handleWikiLinkClick('${escapeHtml(resolved)}', event); }" class="portal-doc-link wiki-link internal-wiki-link" title="Open ${escapeHtml(label)} in drawer">${label}</a>`;
  });
  
  // Citation chips: [1], [2]
  s = s.replace(/\[(\d+)\]/g, '<span class="citation-chip" onclick="scrollToSource($1)" title="Jump to verified source [$1]">[$1]</span>');
  
  return s;
}

function renderMarkdown(md, currentUri) {
  if (!md) return "";
  
  // Extract and cleanly format YAML frontmatter if present
  const { meta, cleanText } = parseYamlFrontmatter(md);
  const pillsHeader = renderMetaPillsHtml(meta);
  
  const lines = cleanText.split("\n");
  let html = [];
  if (pillsHeader) {
    html.push(pillsHeader);
  }
  let inUl = false;
  let inOl = false;
  let inTable = false;
  let inCode = false;
  let codeLang = "";
  let codeBuffer = [];
  let inCallout = false;
  let calloutType = "important";
  let calloutBuffer = [];

  function flushLists() {
    if (inUl) { html.push("</ul>"); inUl = false; }
    if (inOl) { html.push("</ol>"); inOl = false; }
  }

  function flushTable() {
    if (inTable) {
      html.push("</tbody></table></div>");
      inTable = false;
    }
  }

  function flushCallout() {
    if (inCallout) {
      const typeIcons = {
        important: "⚠️",
        note: "ℹ️",
        warning: "🚨",
        tip: "💡"
      };
      const icon = typeIcons[calloutType] || "📌";
      const bodyHtml = calloutBuffer.map(l => formatInlineMd(l)).join("<br>");
      html.push(`
        <div class="callout-box callout-${calloutType}">
          <div class="callout-header"><span>${icon}</span> <strong>${calloutType.toUpperCase()}</strong></div>
          <div class="callout-body">${bodyHtml}</div>
        </div>
      `);
      inCallout = false;
      calloutBuffer = [];
    }
  }

  for (let i = 0; i < lines.length; i++) {
    let rawLine = lines[i];
    let line = rawLine.trim();

    // 1. Code fences ```
    if (line.startsWith("```")) {
      flushLists();
      flushTable();
      flushCallout();
      if (!inCode) {
        inCode = true;
        codeLang = line.slice(3).trim() || "code";
        codeBuffer = [];
      } else {
        inCode = false;
        const codeText = escapeHtml(codeBuffer.join("\n"));
        html.push(`
          <div class="code-block-wrap">
            <div class="code-header">
              <span class="code-lang">${escapeHtml(codeLang)}</span>
              <button type="button" class="code-copy-btn" onclick="copyCodeFromBlock(this)">📋 Copy</button>
            </div>
            <pre class="code-pre"><code>${codeText}</code></pre>
          </div>
        `);
        codeBuffer = [];
      }
      continue;
    }

    if (inCode) {
      codeBuffer.push(rawLine);
      continue;
    }

    // 2. Callouts (> [!IMPORTANT], > [!NOTE], etc.)
    const calloutMatch = line.match(/^>\s*\[!(IMPORTANT|NOTE|WARNING|TIP)\]/i);
    if (calloutMatch) {
      flushLists();
      flushTable();
      flushCallout();
      inCallout = true;
      calloutType = calloutMatch[1].toLowerCase();
      calloutBuffer = [];
      continue;
    }

    if (inCallout) {
      if (line.startsWith(">")) {
        calloutBuffer.push(line.replace(/^>\s*/, ""));
        continue;
      } else if (!line) {
        continue;
      } else {
        flushCallout();
      }
    }

    // 3. Tables (| Col 1 | Col 2 |)
    if (line.startsWith("|") && line.endsWith("|")) {
      flushLists();
      flushCallout();
      if (/^\|[\s:\-|]+\|$/.test(line)) {
        continue;
      }
      const cells = line.slice(1, -1).split("|").map(c => c.trim());
      if (!inTable) {
        inTable = true;
        html.push('<div class="table-wrap"><table class="md-table"><thead><tr>');
        for (let c of cells) {
          html.push(`<th>${formatInlineMd(c)}</th>`);
        }
        html.push('</tr></thead><tbody>');
      } else {
        html.push('<tr>');
        for (let c of cells) {
          html.push(`<td>${formatInlineMd(c)}</td>`);
        }
        html.push('</tr>');
      }
      continue;
    } else {
      flushTable();
    }

    // Blank lines
    if (!line) {
      flushLists();
      flushCallout();
      continue;
    }

    // 4. Headings
    if (line.startsWith("#### ")) {
      flushLists();
      html.push(`<h4 class="md-h4">${formatInlineMd(line.slice(5))}</h4>`);
    } else if (line.startsWith("### ")) {
      flushLists();
      html.push(`<h3 class="md-h3">${formatInlineMd(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      flushLists();
      html.push(`<h2 class="md-h2">${formatInlineMd(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      flushLists();
      html.push(`<h1 class="md-h1">${formatInlineMd(line.slice(2))}</h1>`);
    }
    // 5. Unordered lists
    else if (/^[-*]\s+/.test(line)) {
      if (inOl) { html.push("</ol>"); inOl = false; }
      if (!inUl) { html.push('<ul class="md-ul">'); inUl = true; }
      html.push(`<li class="md-li">${formatInlineMd(line.replace(/^[-*]\s+/, ""))}</li>`);
    }
    // 6. Ordered lists
    else if (/^\d+\.\s+/.test(line)) {
      if (inUl) { html.push("</ul>"); inUl = false; }
      if (!inOl) { html.push('<ol class="md-ol">'); inOl = true; }
      html.push(`<li class="md-oli">${formatInlineMd(line.replace(/^\d+\.\s+/, ""))}</li>`);
    }
    // 7. Standard Paragraphs
    else {
      flushLists();
      html.push(`<p class="md-p">${formatInlineMd(line)}</p>`);
    }
  }

  flushLists();
  flushTable();
  flushCallout();

  return html.join("\n");
}
