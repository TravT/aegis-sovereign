/* PROTOTYPE (throwaway) - Variant B: "Command bar + answer log".
   One surface, no tabs. A single command bar sits in the thumb zone; it takes identifiers, questions
   and "/" commands (graph, directories, license, LLM...). Each query appends an answer block to a
   log; sources expand INLINE (no sheet). The graph is a full-screen mode; admin is one "Appliance"
   page reached from the palette. Desktop: centred log + a right context column + a top ⌘K palette. */
(function () {
  "use strict";
  const { DATA, esc, icon, fmt, answerHtml, routeLine, predict, placeRing } = PROTO;

  const COMMANDS = [
    { id: "graph", ic: "graph", t: "Open graph explorer", k: "/graph" },
    { id: "dirs", ic: "folder", t: "Monitored directories", k: "/dirs" },
    { id: "license", ic: "key", t: "License", k: "/license" },
    { id: "tools", ic: "plug", t: "Connect an AI tool (MCP)", k: "/mcp" },
    { id: "llm", ic: "cpu", t: "Turn local LLM on", k: "/llm" },
    { id: "scope", ic: "sliders", t: "Search scope: all vaults", k: "/scope" },
    { id: "clear", ic: "x", t: "Clear the log", k: "/clear" },
  ];
  const GRAPH_COMMANDS = [
    { id: "g3d", ic: "cube", t: "Switch to 3D", k: "/3d" },
    { id: "gedges", ic: "link", t: "Hide edges", k: "/edges" },
    { id: "gall", ic: "layers", t: "Load all 45,425 manual nodes", k: "/all" },
    { id: "gcat", ic: "sliders", t: "Filter categories (4)", k: "/only" },
    { id: "gclr", ic: "shield", t: "Clearance: restricted", k: "/clearance" },
    { id: "gfit", ic: "target", t: "Fit whole graph", k: "/fit" },
  ];
  const S = { log: [], palette: false, pq: "", mode: "log", page: null, anchor: null, confirm: null, node: null, layer: "entity", llm: false, toast: "" };
  let root;
  const wide = () => window.matchMedia("(min-width: 900px)").matches;

  function shell() {
    return `
    <div class="vb mode-${S.mode}">
      <header class="vb-top">
        <span class="vb-mark" aria-hidden="true">Æ</span><span class="vb-name">Aegis</span>
        <span class="vb-status"><span class="vb-dot"></span><span>Online · read-only</span></span>
      </header>
      <h1 class="sr-only">Aegis Sovereign knowledge search</h1>
      <main class="vb-main" id="vb-main">
        ${S.log.length ? S.log.map(block).join("") : welcome()}
      </main>
      ${wide() ? `<aside class="vb-context" aria-label="Context">${context()}</aside>` : ""}
      ${bar()}
      ${S.mode === "graph" ? graph() : ""}
      ${S.page ? page() : ""}
      ${S.palette ? palette() : ""}
      ${S.confirm !== null ? confirmDlg() : ""}
      <div class="vb-toast" role="status" aria-live="polite"></div>
    </div>`;
  }

  function welcome() {
    return `<section class="vb-welcome">
      <p class="vb-hello">Look up an identifier or ask a question.</p>
      <p class="vb-sub">Type <kbd>/</kbd> in the bar for everything else: graph, directories, license, AI tools.</p>
      <div class="vb-chips">${DATA.examples.exact.slice(0, 3).map(([id]) => `<button type="button" class="vb-chip mono" data-act="run" data-arg="${esc(id)}">${esc(id)}</button>`).join("")}
        <button type="button" class="vb-chip" data-act="run" data-arg="${esc(DATA.examples.ask[0])}">${esc(DATA.examples.ask[0])}</button></div>
    </section>`;
  }

  function block(b, bi) {
    const r = b.res, rl = routeLine(r), last = bi === S.log.length - 1;
    if (!last && !b.open) {
      return `<article class="vb-block folded"><button type="button" class="vb-fold" data-act="unfold" data-arg="${bi}">
        <span class="vb-q">${esc(r.query)}</span><span class="badge ${rl.cls}">${icon(rl.icon, "sm")}${rl.label}</span></button></article>`;
    }
    return `<article class="vb-block" aria-label="Result for ${esc(r.query)}">
      <header class="vb-bh"><span class="vb-q">${esc(r.query)}</span></header>
      <div class="vb-route"><span class="badge ${rl.cls}">${icon(rl.icon, "sm")}${rl.label}</span><span class="vb-muted">${esc(rl.meta)}</span></div>
      ${r.fast_summary ? `<div class="vb-answer">${answerHtml(r.fast_summary.answer)}</div>` : ""}
      ${r.suggestions ? `<p>Not registered. Try: </p><div class="vb-chips">${r.suggestions.map((s) => `<button type="button" class="vb-chip mono" data-act="run" data-arg="${esc(s.identifier)}">${esc(s.identifier)}</button>`).join("")}</div>` : ""}
      <ol class="vb-srcs">${r.results.map((x, i) => srcRow(b, bi, x, i)).join("")}</ol>
      ${r.graph_dossier ? `<p class="vb-next">Next: ${r.graph_dossier.by_relation.DIAGNOSED_BY_MML.concat(r.graph_dossier.by_relation.REMEDIATED_BY_MML).slice(0, 3).map((m) => `<button type="button" class="vb-chip mono sm" data-act="run" data-arg="${esc(m)}">${esc(m)}</button>`).join("")}
        <button type="button" class="vb-chip sm" data-act="graph">${icon("graph", "sm")} Graph</button></p>` : ""}
    </article>`;
  }
  function srcRow(b, bi, x, i) {
    const open = b.srcOpen === i;
    const sec = b.section || "";
    const text = open ? DATA.inspect(x.virtual_uri, sec === "__diagram" ? "" : sec).content_text : "";
    return `<li class="vb-src${open ? " open" : ""}" id="src-${i + 1}">
      <button type="button" class="vb-src-h" data-act="src" data-b="${bi}" data-arg="${i}" aria-expanded="${open}">
        <span class="vb-n">${i + 1}</span><span class="vb-src-t">${esc(x.title)}<small>${esc(x.kind)} · ${esc(x.package)}</small></span>${icon("chev-d", "sm")}
      </button>
      ${open ? `<div class="vb-src-body">
        <div class="vb-tabs" role="tablist" aria-label="Section">${DATA.sectionTabs.map(([k, l]) => `<button type="button" role="tab" aria-selected="${sec === k}" data-act="sec" data-b="${bi}" data-arg="${esc(k)}">${l}</button>`).join("")}</div>
        ${sec === "__diagram" ? `<div class="vb-diagram">${icon("image", "lg")}<span>Diagram extracted on request</span></div>` : `<p class="vb-text">${esc(text)}</p>`}
        <div class="vb-src-actions"><a href="#" class="vb-link" data-act="toast" data-arg="Opens /archive/view in a new tab">${icon("ext", "sm")} Full manual</a>
          ${x.has_procedure ? `<button type="button" class="vb-link" data-act="toast" data-arg="MML copied">${icon("copy", "sm")} Copy MML</button>` : ""}</div>
      </div>` : ""}
    </li>`;
  }

  function context() {
    const last = S.log[S.log.length - 1];
    if (!last || !last.res.graph_dossier) return `<div class="vb-ctx-empty">${icon("graph", "lg")}<p>Related entities and a graph preview appear here after a lookup.</p></div>`;
    const d = last.res.graph_dossier.by_relation;
    return `<h2 class="vb-h2">In the graph</h2>
      <button type="button" class="vb-mini" data-act="graph" aria-label="Open ALM-20104 in the graph explorer"><img src="${DATA.graph.img.entity[0]}" alt="" /><span>${icon("graph", "sm")} Open in explorer</span></button>
      <h2 class="vb-h2">Diagnose with</h2><div class="vb-chips">${d.DIAGNOSED_BY_MML.map((m) => `<button type="button" class="vb-chip mono sm" data-act="run" data-arg="${esc(m)}">${esc(m)}</button>`).join("")}</div>
      <h2 class="vb-h2">Fix with</h2><div class="vb-chips">${d.REMEDIATED_BY_MML.map((m) => `<button type="button" class="vb-chip mono sm" data-act="run" data-arg="${esc(m)}">${esc(m)}</button>`).join("")}</div>
      <h2 class="vb-h2">KPIs</h2><p class="vb-muted mono small">${d.MEASURED_BY_COUNTER.map(esc).join("<br>")}</p>`;
  }

  function bar() {
    const graphMode = S.mode === "graph";
    return `<form class="vb-bar" role="search" data-form="bar">
      <button type="button" class="vb-cmd" data-act="palette" aria-label="All commands">${icon("command")}</button>
      <label class="sr-only" for="vb-q">${graphMode ? "Find a node" : "Identifier, question or / command"}</label>
      <input id="vb-q" type="search" enterkeyhint="${graphMode ? "search" : "go"}" autocomplete="off" spellcheck="false" placeholder="${graphMode ? "Find a node" : "Identifier, question or /"}" />
      <button type="submit" class="vb-send" aria-label="Run">${icon("send")}</button>
      <p class="vb-predict" id="vb-predict" aria-live="polite"></p>
    </form>`;
  }

  function palette() {
    const q = S.pq.replace(/^\//, "").toLowerCase();
    const base = S.mode === "graph" ? GRAPH_COMMANDS : COMMANDS;
    const cmds = base.filter((c) => !q || c.t.toLowerCase().includes(q) || c.k.includes(q)).map((c) => c.id === "llm" ? Object.assign({}, c, { t: S.llm ? "Turn local LLM off" : "Turn local LLM on" }) : c);
    const recent = S.pq.startsWith("/") || S.mode === "graph" ? [] : DATA.recent;
    return `<div class="vb-scrim" data-act="close"></div>
    <section class="vb-palette" role="dialog" aria-modal="true" aria-labelledby="vb-pal-t" tabindex="-1">
      <h2 id="vb-pal-t" class="sr-only">Commands</h2>
      ${wide() ? `<div class="vb-pal-in">${icon("search")}<input id="vb-pq" placeholder="Type a command or search" value="${esc(S.pq)}" autocomplete="off" /><kbd>esc</kbd></div>` : ""}
      <div class="vb-pal-list">
        ${recent.length ? `<h3>Recent</h3>${recent.map((r) => `<button type="button" class="vb-pal-row" data-act="run" data-arg="${esc(r)}">${icon("clock")}<span>${esc(r)}</span></button>`).join("")}` : ""}
        <h3>${S.mode === "graph" ? "Graph view" : "Go to"}</h3>${cmds.map((c) => `<button type="button" class="vb-pal-row" data-act="cmd" data-arg="${c.id}">${icon(c.ic)}<span>${esc(c.t)}</span><kbd>${c.k}</kbd></button>`).join("")}
      </div>
    </section>`;
  }

  function graph() {
    const n = S.node;
    return `<section class="vb-graph" role="dialog" aria-modal="true" aria-label="Graph explorer">
      <div class="vb-stage"><img src="${DATA.graph.img[S.layer][wide() ? 1 : 0]}" alt="Knowledge graph (static stand-in for the WebGL canvas)" />${n ? `<span class="vb-ring" data-ring aria-hidden="true"></span>` : ""}</div>
      <div class="vb-g-top">
        <button type="button" class="vb-round" data-act="close-graph" aria-label="Close graph">${icon("x")}</button>
        <div class="vb-g-layers" role="radiogroup" aria-label="Layer">${DATA.graph.layers.map(([id, l, , sh]) => `<button type="button" role="radio" aria-checked="${S.layer === id}" data-act="layer" data-arg="${id}" aria-label="${esc(l)}">${esc(wide() ? l : sh)}</button>`).join("")}</div>
        <button type="button" class="vb-round" data-act="palette" aria-label="View options">${icon("sliders")}</button>
      </div>
      <button type="button" class="vb-round vb-fit" data-act="toast" data-arg="Fit" aria-label="Fit whole graph">${icon("target")}</button>
      ${n ? `<div class="vb-node"><div class="vb-node-t"><b class="mono">${esc(n.label)}</b><span class="vb-muted small">${esc(n.kind)} · 9 connections</span></div>
        <button type="button" class="vb-chip" data-act="run-close" data-arg="${esc(n.label)}">${icon("search", "sm")} Search</button>
        <button type="button" class="vb-chip" data-act="toast" data-arg="Connections list">${icon("link", "sm")} 9</button></div>` : ""}
    </section>`;
  }

  function page() {
    const l = DATA.license;
    const sec = (id, ic, t, body) => `<details class="vb-sec" id="sec-${id}" ${S.anchor === id || (!S.anchor && id === "llm") ? "open" : ""}><summary>${icon(ic)}<span>${t}</span>${icon("chev-d", "sm")}</summary><div class="vb-sec-b">${body}</div></details>`;
    return `<section class="vb-page" role="dialog" aria-modal="true" aria-labelledby="vb-page-t" tabindex="-1">
      <header class="vb-page-h"><h2 id="vb-page-t">Appliance</h2><button type="button" class="vb-round" data-act="close" aria-label="Close">${icon("x")}</button></header>
      <p class="vb-muted pad">${fmt(DATA.status.records)} records · ${fmt(DATA.status.entities)} entities · ${esc(DATA.status.host)}</p>
      ${sec("llm", "cpu", "Local LLM", `<div class="vb-line"><span>${S.llm ? "Running" : "Standby · no CPU or RAM used"}</span><button type="button" class="vb-btn ${S.llm ? "" : "gold"}" data-act="llm">${S.llm ? "Turn off" : "Turn on"}</button></div>`)}
      ${sec("dirs", "folder", "Monitored directories", DATA.sources.map((s, i) => `<div class="vb-dir"><div class="vb-dir-t"><span class="mono">${esc(s.path)}</span><small>${esc(s.domain)} · ${fmt(s.indexed_records)} records</small></div>
          <div class="vb-dir-a"><button type="button" class="vb-btn" data-act="toast" data-arg="Re-sync started">${icon("refresh", "sm")} Re-sync</button><button type="button" class="vb-btn danger" data-act="confirm" data-arg="${i}" aria-label="Remove ${esc(s.path)} from index">${icon("trash", "sm")}</button></div></div>`).join("") +
          `<button type="button" class="vb-btn wide" data-act="toast" data-arg="Add directory form">${icon("plus", "sm")} Add directory</button>`)}
      ${sec("license", "key", `License · ${esc(l.tier)}`, `<dl class="vb-dl"><dt>Status</dt><dd>${icon("check", "sm")} Signature verified</dd><dt>Expires</dt><dd>${esc(l.expires_at)}</dd><dt>Customer</dt><dd class="mono">${esc(l.customer_id)}</dd><dt>Key</dt><dd class="mono">${esc(l.public_key_fingerprint)}</dd></dl>
          <button type="button" class="vb-btn wide" data-act="toast" data-arg="Token form">${icon("key", "sm")} Replace token…</button>`)}
      ${sec("tools", "plug", "AI tool connections", `<label class="sr-only" for="vb-h">Tool</label><select id="vb-h" class="vb-select">${DATA.harnesses.map(([k, n]) => `<option>${esc(n)}</option>`).join("")}</select>
          <pre class="vb-pre">${esc(DATA.snippet)}</pre><button type="button" class="vb-btn gold wide" data-act="toast" data-arg="Snippet copied">${icon("copy", "sm")} Copy snippet</button>`)}
    </section>`;
  }
  function confirmDlg() {
    const s = DATA.sources[S.confirm];
    return `<div class="vb-scrim top" data-act="cancel"></div><section class="vb-confirm" role="alertdialog" aria-modal="true" aria-labelledby="vb-c-t" tabindex="-1">
      <h2 id="vb-c-t">Remove from index?</h2><p>Deletes <b>${fmt(s.indexed_records)} records</b> and their graph edges for <span class="mono">${esc(s.path)}</span>. Files on disk stay.</p>
      <div class="vb-two"><button type="button" class="vb-btn" data-act="cancel">Cancel</button><button type="button" class="vb-btn danger solid" data-act="toast" data-arg="Removed">Remove</button></div></section>`;
  }

  // ------------------------------------------------------------------------------------ behaviour
  function render(focus) {
    root.innerHTML = shell();
    placeRing(root.querySelector(".vb-stage"));
    const dlg = root.querySelector(".vb-confirm, .vb-palette, .vb-page");
    if (focus) { const el = root.querySelector(focus); if (el) el.focus({ preventScroll: true }); }
    else if (dlg) dlg.focus({ preventScroll: true });
    const main = root.querySelector(".vb-main"); if (main && !S.page && !S.palette) main.scrollTop = main.scrollHeight;
  }
  function run(q) {
    if (q.startsWith("/")) { const c = COMMANDS.find((x) => x.k === q.split(" ")[0]); if (c) return cmd(c.id); }
    S.log.forEach((b) => { b.open = false; });
    S.log.push({ res: DATA.route(q), srcOpen: null, section: "" });
    S.palette = false; S.mode = "log"; render();
  }
  function cmd(id) {
    S.palette = false;
    if (id === "graph") { S.mode = "graph"; S.node = DATA.graph.node; }
    else if (id === "dirs" || id === "license" || id === "tools") { S.page = true; S.anchor = id; }
    else if (id === "llm") { S.llm = !S.llm; toastLater(S.llm ? "Local LLM starting…" : "Local LLM stopping…"); }
    else if (id === "clear") S.log = [];
    else if (id.startsWith("g")) toastLater("Graph: " + id.slice(1));
    else toastLater("Scope sheet");
    render();
  }
  function toastLater(m) { setTimeout(() => toast(m), 30); }
  function toast(m) { const t = root.querySelector(".vb-toast"); if (!t) return; t.textContent = m; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 1800); }
  function onClick(e) {
    const el = e.target.closest("[data-act]"); if (!el) return;
    const a = el.dataset.act, arg = el.dataset.arg;
    if (el.tagName === "A") e.preventDefault();
    if (a === "run") run(arg);
    else if (a === "run-close") { S.mode = "log"; run(arg); }
    else if (a === "src") { const b = S.log[Number(el.dataset.b)]; b.srcOpen = b.srcOpen === Number(arg) ? null : Number(arg); b.section = ""; render(`[data-act=src][data-b="${el.dataset.b}"][data-arg="${arg}"]`); }
    else if (a === "sec") { S.log[Number(el.dataset.b)].section = arg; render(`[data-act=sec][data-arg="${arg}"]`); }
    else if (a === "unfold") { S.log[Number(arg)].open = true; render(); }
    else if (a === "palette") { S.palette = true; S.pq = ""; render(wide() ? "#vb-pq" : null); }
    else if (a === "cmd") cmd(arg);
    else if (a === "graph") cmd("graph");
    else if (a === "close-graph") { S.mode = "log"; render(); }
    else if (a === "layer") { S.layer = arg; S.node = null; render(); }
    else if (a === "close") { S.palette = false; S.page = null; render(); }
    else if (a === "confirm") { S.confirm = Number(arg); render(); }
    else if (a === "cancel") { S.confirm = null; render(); }
    else if (a === "llm") { S.llm = !S.llm; render(); }
    else if (a === "toast") toast(arg);
  }
  function onSubmit(e) {
    e.preventDefault(); const v = root.querySelector("#vb-q").value.trim();
    if (S.mode === "graph") { S.node = DATA.graph.node; S.layer = "entity"; render(); return; }
    if (v) run(v); else { S.palette = true; render(); }
  }
  function onInput(e) {
    if (e.target.id === "vb-q") {
      const v = e.target.value; const p = root.querySelector("#vb-predict");
      if (v === "/") { S.palette = true; S.pq = "/"; render(); return; }
      if (p) p.textContent = S.mode === "graph" ? "" : predict(v);
    }
    if (e.target.id === "vb-pq") { S.pq = e.target.value; const pos = e.target.selectionStart; render("#vb-pq"); const i = root.querySelector("#vb-pq"); if (i) i.setSelectionRange(pos, pos); }
  }

  PROTO.VARIANTS.B = {
    name: "Command bar + answer log",
    mount(el, ctx) {
      root = el;
      root.addEventListener("click", onClick); root.addEventListener("submit", onSubmit); root.addEventListener("input", onInput);
      window.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { S.palette = false; S.page = null; S.confirm = null; if (S.mode === "graph") S.mode = "log"; render(); }
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); S.palette = true; render(wide() ? "#vb-pq" : null); }
      });
      const sc = ctx.screen;
      if (["results", "source", "answer"].includes(sc)) S.log.push({ res: DATA.route("ALM-20104"), srcOpen: sc === "source" ? 0 : null, section: sc === "source" ? "Possible Causes" : "" });
      if (sc === "answer") S.log.push({ res: DATA.route("Why did ALM-20104 trigger and how do we fix it?"), srcOpen: null, section: "" });
      if (sc === "graph" || sc === "graph-options") { S.log.push({ res: DATA.route("ALM-20104"), srcOpen: null, section: "" }); S.mode = "graph"; S.node = sc === "graph" ? DATA.graph.node : null; }
      if (sc === "graph-options" || sc === "palette") S.palette = true;
      if (sc === "settings") { S.page = true; S.anchor = "llm"; }
      if (["sources", "license", "tools"].includes(sc)) { S.page = true; S.anchor = sc === "sources" ? "dirs" : sc; }
      if (sc === "confirm") { S.page = true; S.anchor = "dirs"; S.confirm = 2; }
      render();
    },
  };
})();
