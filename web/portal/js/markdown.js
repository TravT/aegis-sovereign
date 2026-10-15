/**
 * Aegis Sovereign Web Portal - Markdown & Document Rendering Engine
 * Client-side Markdown renderer for answers, cards and the source inspector:
 * - Headings, paragraphs, nested lists (any indent), task lists, rules, block quotes
 * - GitHub alert callouts (> [!NOTE], [!TIP], [!IMPORTANT], [!WARNING], [!CAUTION])
 * - Tables with escaped pipes (\|) and <br> in cells
 * - Fenced code blocks with 1-click copy; ```mermaid blocks drawn by the vendored Mermaid
 * - $$ display and $ inline math drawn by the vendored KaTeX
 * - Wiki links opened in the inspector drawer, citation chips [1], [2]
 * Mermaid and KaTeX are pinned in web/portal/vendor (air-gapped: no CDN) and load only when a document needs them;
 * call enhanceRenderedMarkdown(element) after inserting renderMarkdown() output.
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

// ---------------------------------------------------------------------------
// Inline formatting
// ---------------------------------------------------------------------------
// Code spans, escapes, math and links are cut out into numbered slots first, so emphasis never touches their
// content; the remaining text is HTML-escaped. <br> is the only tag let through (wiki tables use it in cells).

const MD_SLOT = "\u0000";

function mathHtml(tex, display) {
  const cls = display ? "md-math-display" : "md-math-inline";
  const tag = display ? "div" : "span";
  return `<${tag} class="${cls}" data-tex="${escapeHtml(tex.trim())}"><code>${escapeHtml(tex.trim())}</code></${tag}>`;
}

function formatEmphasis(s) {
  s = s.replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^\w])__(?=\S)([\s\S]*?\S)__(?!\w)/g, "$1<strong>$2</strong>");
  s = s.replace(/~~(?=\S)([\s\S]*?\S)~~/g, "<del>$1</del>");
  s = s.replace(/(^|[^*\w])\*([^\s*]|[^\s*][^*]*?[^\s*])\*(?![*\w])/g, "$1<em>$2</em>");
  s = s.replace(/(^|[^\w])_([^\s_]|[^\s_][^_]*?[^\s_])_(?!\w)/g, "$1<em>$2</em>");
  return s;
}

function mdSlug(text) {
  return String(text).toLowerCase().replace(/<[^>]*>/g, "").replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "-");
}

function scrollToMdAnchor(el) {
  const root = el.closest(".inspector-content-rendered, .md-doc") || document;
  const target = root.querySelector(`[data-anchor="${CSS.escape(el.dataset.mdAnchor || "")}"]`);
  if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  return false;
}

function renderMdLink(label, url, currentUri) {
  const labelHtml = formatEmphasis(escapeHtml(label));
  const plainLabel = label.replace(/\u0000\d+\u0000/g, "");
  if (/^(https?:|mailto:)/i.test(url)) {
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" class="portal-doc-link external" title="External Link: ${escapeHtml(url)}">${labelHtml} ↗</a>`;
  }
  const hashAt = url.indexOf("#");
  const path = hashAt >= 0 ? url.slice(0, hashAt) : url;
  const fragment = hashAt >= 0 ? url.slice(hashAt + 1) : "";
  if (!path) {
    return `<a href="#" data-md-anchor="${escapeHtml(mdSlug(decodeURIComponent(fragment)))}" onclick="return scrollToMdAnchor(this)" class="portal-doc-link anchor-link">${labelHtml}</a>`;
  }
  if (/^[a-z][a-z0-9+.\-]*:/i.test(path) && !/^archive:/i.test(path)) {
    return labelHtml;  // unknown scheme (javascript:, data:, ...): shown as text, never a link
  }
  const base = currentUri || (typeof window !== "undefined" && window.currentInspectedUri) || "";
  const resolved = resolveRelativeWikiPath(base, decodeURIComponent(path));
  const viewerUrl = `/archive/view?uri=${encodeURIComponent(resolved)}`;
  return `<a href="${viewerUrl}" data-wiki-uri="${escapeHtml(resolved)}" onclick="return typeof handleWikiLinkClick === 'function' ? handleWikiLinkClick(this.dataset.wikiUri, event) : true" class="portal-doc-link wiki-link internal-wiki-link" title="Open ${escapeHtml(plainLabel)} in drawer">${labelHtml}</a>`;
}

function formatInlineMd(text, currentUri) {
  if (!text) return "";
  const slots = [];
  const keep = (html) => { slots.push(html); return `${MD_SLOT}${slots.length - 1}${MD_SLOT}`; };
  let s = String(text).replace(/\u0000/g, "");

  // Code spans: shown verbatim.
  s = s.replace(/(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/g, (m, ticks, code) => keep(`<code class="md-inline-code">${escapeHtml(code)}</code>`));
  // Math before backslash escapes, so \$ inside a formula stays TeX: $$...$$ inline, then $...$ by the pandoc rule
  // (no space inside the dollars, closing $ not followed by a letter or digit), so "$5 and $10" stays text.
  s = s.replace(/(?<!\\)\$\$((?:\\\$|[^$])+?)\$\$/g, (m, tex) => keep(mathHtml(tex, false)));
  s = s.replace(/(?<![\\$])\$(?=[^\s$])((?:\\\$|[^$\n])*?[^\s$\\])\$(?![\w$])/g, (m, tex) => keep(mathHtml(tex, false)));
  s = s.replace(/(?<![\\$])\$([^\s$\\])\$(?![\w$])/g, (m, tex) => keep(mathHtml(tex, false)));
  // Backslash escapes: \| \* \_ \$ \[ stay literal.
  s = s.replace(/\\([\\`*_{}\[\]()#+\-.!|$~<>])/g, (m, ch) => keep(escapeHtml(ch)));
  // Obsidian wikilinks [[target|alias]]: the label as text.
  s = s.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (m, target, alias) => keep(escapeHtml(alias || target)));
  // Links: kept whole so emphasis never touches a URL.
  s = s.replace(/\[([^\]]+)\]\(<?([^)\s>]+)>?(?:\s+"[^"]*")?\)/g, (m, label, url) => keep(renderMdLink(label, url, currentUri)));

  s = formatEmphasis(escapeHtml(s));
  s = s.replace(/&lt;br\s*\/?&gt;/gi, "<br>");
  // Citation chips: [1], [2]
  s = s.replace(/\[(\d+)\]/g, '<span class="citation-chip" onclick="scrollToSource($1)" title="Jump to verified source [$1]">[$1]</span>');

  for (let pass = 0; pass < 4 && s.includes(MD_SLOT); pass++) {
    s = s.replace(/\u0000(\d+)\u0000/g, (m, i) => slots[Number(i)] ?? "");
  }
  return s;
}

// ---------------------------------------------------------------------------
// Block rendering
// ---------------------------------------------------------------------------

const MD_CALLOUTS = {
  note: "ℹ️", tip: "💡", important: "⚠️", warning: "🚨", caution: "⛔",
};

function splitTableRow(line) {
  let body = line.trim();
  if (body.startsWith("|")) body = body.slice(1);
  if (body.endsWith("|") && !body.endsWith("\\|")) body = body.slice(0, -1);
  return body.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
}

function isTableSeparator(line) {
  const t = line.trim();
  return t.startsWith("|") && t.includes("-") && /^\|?[\s:\-|]+\|?$/.test(t);
}

function renderMarkdownBlocks(text, currentUri) {
  const lines = String(text).replace(/\r\n?/g, "\n").replace(/\t/g, "    ").split("\n");
  const out = [];
  const lists = [];          // open lists, innermost last: { tag, indent }
  let para = [];             // paragraph lines waiting to be joined
  let quote = null;          // { kind: "quote" | callout type, title, lines }
  let table = false;         // inside a table body
  let fence = null;          // { marker, lang, indent, lines }
  let mathBlock = null;      // { lines }
  let liOpen = false;        // the last thing written is list-item text a lazy line can continue
  const inline = (t) => formatInlineMd(t, currentUri);

  function flushPara() {
    if (para.length) {
      out.push(`<p class="md-p">${inline(para.join(" "))}</p>`);
      para = [];
    }
  }
  function flushTable() {
    if (table) { out.push("</tbody></table></div>"); table = false; }
  }
  function flushQuote() {
    if (!quote) return;
    const inner = renderMarkdownBlocks(quote.lines.join("\n"), currentUri);
    if (quote.kind === "quote") {
      out.push(`<blockquote class="md-quote">${inner}</blockquote>`);
    } else {
      const known = Object.prototype.hasOwnProperty.call(MD_CALLOUTS, quote.kind);
      const cls = known ? quote.kind : "note";
      // Obsidian form "> [!NOTE] Title": the title keeps its case; otherwise the type is the label.
      const title = quote.title ? `<strong class="callout-title">${inline(quote.title)}</strong>` : `<strong>${escapeHtml(quote.kind.toUpperCase())}</strong>`;
      out.push(`<div class="callout-box callout-${cls}"><div class="callout-header"><span>${MD_CALLOUTS[cls]}</span> ${title}</div><div class="callout-body">${inner}</div></div>`);
    }
    quote = null;
  }
  function closeListsFrom(indent) {
    while (lists.length && lists[lists.length - 1].indent >= indent) {
      out.push(`</li></${lists.pop().tag}>`);
    }
  }
  // A block at this indent: lists at the same or deeper indent end; a shallower list item keeps it as content.
  function beginBlock(indent) {
    flushPara();
    flushTable();
    flushQuote();
    closeListsFrom(indent);
    liOpen = false;
  }
  function emitFence(f) {
    const src = f.lines.join("\n");
    if (f.lang.toLowerCase() === "mermaid") {
      out.push(`<div class="md-mermaid" data-src="${escapeHtml(src)}"><pre class="code-pre md-mermaid-src"><code>${escapeHtml(src)}</code></pre></div>`);
      return;
    }
    out.push(`<div class="code-block-wrap"><div class="code-header"><span class="code-lang">${escapeHtml(f.lang || "code")}</span><button type="button" class="code-copy-btn" onclick="copyCodeFromBlock(this)">📋 Copy</button></div><pre class="code-pre"><code>${escapeHtml(src)}</code></pre></div>`);
  }

  for (const raw of lines) {
    const trimmed = raw.trim();
    const indent = raw.length - raw.trimStart().length;

    if (fence) {
      const close = trimmed.match(/^(`{3,}|~{3,})$/);
      if (close && close[1][0] === fence.marker[0] && close[1].length >= fence.marker.length) {
        emitFence(fence);
        fence = null;
      } else {
        fence.lines.push(raw.slice(Math.min(fence.indent, indent)));
      }
      continue;
    }
    if (mathBlock) {
      if (trimmed.endsWith("$$")) {
        mathBlock.lines.push(trimmed.slice(0, -2));
        out.push(mathHtml(mathBlock.lines.join("\n"), true));
        mathBlock = null;
      } else {
        mathBlock.lines.push(trimmed);
      }
      continue;
    }
    if (quote) {
      if (trimmed.startsWith(">")) {
        const body = trimmed.replace(/^>\s?/, "");
        const next = quote.kind !== "quote" && body.match(/^\[!(\w+)\][+-]?\s*(.*)$/);
        if (next) {  // a list of callouts, one per line: each starts its own box
          flushQuote();
          quote = { kind: next[1].toLowerCase(), title: next[2], lines: [] };
        } else {
          quote.lines.push(body);
        }
        continue;
      }
      flushQuote();
    }
    if (table && !trimmed.startsWith("|")) flushTable();

    if (!trimmed) {
      flushPara();
      liOpen = false;
      continue;
    }

    const fenceOpen = trimmed.match(/^(`{3,}|~{3,})\s*([^`\s]*)/);
    if (fenceOpen) {
      beginBlock(indent);
      fence = { marker: fenceOpen[1], lang: fenceOpen[2] || "", indent, lines: [] };
      continue;
    }

    if (trimmed.startsWith("$$")) {
      beginBlock(indent);
      const single = trimmed.match(/^\$\$([\s\S]+)\$\$$/);
      if (single) {
        out.push(mathHtml(single[1], true));
      } else {
        mathBlock = { lines: [trimmed.slice(2)] };
      }
      continue;
    }

    if (/^((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(trimmed)) {
      beginBlock(indent);
      out.push('<hr class="md-hr">');
      continue;
    }

    const heading = indent < 4 && trimmed.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (heading) {
      beginBlock(indent);
      const level = heading[1].length;
      out.push(`<h${level} class="md-h${level}" data-anchor="${escapeHtml(mdSlug(heading[2]))}">${inline(heading[2])}</h${level}>`);
      continue;
    }

    if (trimmed.startsWith("|")) {
      if (isTableSeparator(trimmed)) continue;
      const cells = splitTableRow(trimmed);
      if (!table) {
        beginBlock(indent);
        table = true;
        out.push('<div class="table-wrap"><table class="md-table"><thead><tr>');
        out.push(cells.map((c) => `<th>${inline(c)}</th>`).join(""));
        out.push("</tr></thead><tbody>");
      } else {
        out.push(`<tr>${cells.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`);
      }
      continue;
    }

    if (trimmed.startsWith(">")) {
      beginBlock(indent);
      const callout = trimmed.match(/^>\s*\[!(\w+)\][+-]?\s*(.*)$/);
      quote = callout
        ? { kind: callout[1].toLowerCase(), title: callout[2], lines: [] }
        : { kind: "quote", title: "", lines: [trimmed.replace(/^>\s?/, "")] };
      continue;
    }

    const item = raw.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
    if (item) {
      flushPara();
      flushTable();
      const itemIndent = item[1].length;
      const tag = /\d/.test(item[2]) ? "ol" : "ul";
      while (lists.length && lists[lists.length - 1].indent > itemIndent) {
        out.push(`</li></${lists.pop().tag}>`);
      }
      const top = lists[lists.length - 1];
      if (top && top.indent === itemIndent && top.tag === tag) {
        out.push("</li>");
      } else {
        if (top && top.indent === itemIndent) out.push(`</li></${lists.pop().tag}>`);
        const start = tag === "ol" && parseInt(item[2], 10) !== 1 ? ` start="${parseInt(item[2], 10)}"` : "";
        out.push(`<${tag} class="md-${tag}"${start}>`);
        lists.push({ tag, indent: itemIndent });
      }
      const task = item[3].match(/^\[([ xX])\]\s+(.*)$/);
      const liClass = tag === "ol" ? "md-oli" : "md-li";
      if (task) {
        const checked = task[1] !== " " ? " checked" : "";
        out.push(`<li class="${liClass} md-task"><input type="checkbox" disabled${checked}> ${inline(task[2])}`);
      } else {
        out.push(`<li class="${liClass}">${inline(item[3])}`);
      }
      liOpen = true;
      continue;
    }

    // Plain text: a lazy continuation of the list item just written, or a paragraph line.
    if (liOpen && !para.length) {
      out.push(" " + inline(trimmed));
      continue;
    }
    if (!para.length) beginBlock(indent);
    para.push(trimmed);
  }

  if (fence) emitFence(fence);
  if (mathBlock) out.push(mathHtml(mathBlock.lines.join("\n"), true));
  flushPara();
  flushTable();
  flushQuote();
  closeListsFrom(-1);
  return out.join("\n");
}

function renderMarkdown(md, currentUri) {
  if (!md) return "";
  const { meta, cleanText } = parseYamlFrontmatter(md);
  return renderMetaPillsHtml(meta) + renderMarkdownBlocks(cleanText, currentUri);
}

// ---------------------------------------------------------------------------
// Diagrams and math: vendored, pinned libraries (web/portal/vendor/VENDOR.md), loaded only when a document needs them
// ---------------------------------------------------------------------------

const MD_VENDOR = {
  mermaid: "/portal/vendor/mermaid-12.2.0/mermaid.min.js",
  katexJs: "/portal/vendor/katex-0.19.0/katex.min.js",
  katexCss: "/portal/vendor/katex-0.19.0/katex.min.css",
};
const mdScriptLoads = {};
let mdMermaidInitialised = false;
let mdMermaidSeq = 0;

function loadVendorScript(src) {
  if (!mdScriptLoads[src]) {
    mdScriptLoads[src] = new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = src;
      el.onload = resolve;
      el.onerror = () => { delete mdScriptLoads[src]; el.remove(); reject(new Error(`could not load ${src}`)); };
      document.head.appendChild(el);
    });
  }
  return mdScriptLoads[src];
}

function loadVendorCss(href) {
  if (document.querySelector(`link[href="${href}"]`)) return;
  const el = document.createElement("link");
  el.rel = "stylesheet";
  el.href = href;
  document.head.appendChild(el);
}

async function renderMathNodes(nodes) {
  loadVendorCss(MD_VENDOR.katexCss);
  try {
    await loadVendorScript(MD_VENDOR.katexJs);
  } catch (err) {
    console.warn("Math stays as TeX source:", err.message);
    return;
  }
  nodes.forEach((n) => {
    const tex = texCompat(n.dataset.tex);
    n.removeAttribute("data-tex");
    window.katex.render(tex, n, { displayMode: n.classList.contains("md-math-display"), throwOnError: false });
  });
}

// KaTeX rejects a bare "_" inside \text{...} (MathJax, which GitHub uses, shows it); the wiki writes \text{topic_id}.
function texCompat(tex) {
  return tex.replace(/\\text\{([^{}]*)\}/g, (m, t) => `\\text{${t.replace(/(?<!\\)_/g, "\\_")}}`);
}

async function renderMermaidNodes(nodes) {
  try {
    await loadVendorScript(MD_VENDOR.mermaid);
  } catch (err) {
    console.warn("Diagrams stay as source:", err.message);
    return;
  }
  if (!mdMermaidInitialised) {
    window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "dark", suppressErrorRendering: true });
    mdMermaidInitialised = true;
  }
  for (const n of nodes) {  // one at a time: Mermaid renders through shared state
    const src = n.dataset.src;
    n.removeAttribute("data-src");
    const id = `md-mermaid-${++mdMermaidSeq}`;
    try {
      const { svg } = await window.mermaid.render(id, src);
      n.innerHTML = svg;
      // Mermaid fits a diagram to the pane, so all of it is visible; a wide one gets a "Full size" toggle that draws
      // it at its natural size in a frame that scrolls sideways (small labels become readable).
      const svgEl = n.querySelector("svg");
      const natural = svgEl && svgEl.viewBox && svgEl.viewBox.baseVal ? svgEl.viewBox.baseVal.width : 0;
      if (natural > n.clientWidth * 1.15) {
        n.insertAdjacentHTML("afterbegin", '<button type="button" class="md-mermaid-zoom" onclick="toggleMermaidSize(this)">⤢ Full size</button>');
        svgEl.dataset.naturalWidth = String(Math.round(natural));
      }
    } catch (err) {
      document.getElementById(`d${id}`)?.remove();
      const msg = String((err && err.message) || err).split("\n")[0];
      n.classList.add("md-mermaid-error");
      n.insertAdjacentHTML("afterbegin", `<div class="md-mermaid-note">Diagram could not be drawn (${escapeHtml(msg)}); its source:</div>`);
    }
  }
}

function toggleMermaidSize(btn) {
  const box = btn.closest(".md-mermaid");
  const svgEl = box && box.querySelector("svg");
  if (!svgEl) return;
  const natural = box.classList.toggle("md-mermaid-natural");
  svgEl.style.maxWidth = natural ? "none" : `${svgEl.dataset.naturalWidth}px`;
  svgEl.style.width = natural ? `${svgEl.dataset.naturalWidth}px` : "100%";
  btn.textContent = natural ? "⤡ Fit to pane" : "⤢ Full size";
}

// Draws the math and Mermaid blocks renderMarkdown left in `root`. Resolves when done; a failed library leaves
// the source visible rather than breaking the document.
async function enhanceRenderedMarkdown(root) {
  if (!root) return;
  const math = Array.from(root.querySelectorAll(".md-math-display[data-tex], .md-math-inline[data-tex]"));
  const diagrams = Array.from(root.querySelectorAll(".md-mermaid[data-src]"));
  const jobs = [];
  if (math.length) jobs.push(renderMathNodes(math));
  if (diagrams.length) jobs.push(renderMermaidNodes(diagrams));
  await Promise.allSettled(jobs);
}
