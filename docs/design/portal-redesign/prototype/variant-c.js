/* PROTOTYPE (throwaway) - Variant C: "Map model" (graph-first canvas + bottom sheet + drawer).
   The knowledge graph is the home screen, full-bleed, like a map. A floating search pill sits on top;
   results, the source reader and node details live in ONE bottom sheet with three snap points
   (peek / half / full). Admin lives in a left drawer behind the menu button.
   Desktop: the sheet docks as a left side panel (Google-Maps-like); the graph fills the rest. */
(function () {
  "use strict";
  const { DATA, esc, icon, fmt, answerHtml, routeLine, predict, placeRing } = PROTO;

  const S = { snap: "peek", view: "explore", res: null, src: null, section: "", q: "", layer: "entity", node: null,
    drawer: false, dview: null, confirm: null, llm: false, opts: false };
  let root;
  const wide = () => window.matchMedia("(min-width: 900px)").matches;

  function shell() {
    return `
    <div class="vc snap-${S.snap} ${S.drawer ? "drawer-open" : ""}">
      <main class="vc-map" aria-label="Knowledge graph">
        <h1 class="sr-only">Aegis Sovereign: knowledge graph and search</h1>
        <div class="vc-stage"><img src="${DATA.graph.img[S.layer][wide() ? 1 : 0]}" alt="Knowledge graph, ${esc(S.layer)} layer (static stand-in for the WebGL canvas)" />${S.node ? `<span class="vc-ring" data-ring aria-hidden="true"></span>` : ""}</div>
        <div class="vc-map-tools">
          <button type="button" class="vc-fab" data-act="opts" aria-label="Map options" aria-expanded="${S.opts}">${icon("layers")}</button>
          <button type="button" class="vc-fab" data-act="toast" data-arg="Fit" aria-label="Fit whole graph">${icon("target")}</button>
        </div>
        ${S.opts ? opts() : ""}
      </main>
      <div class="vc-float">
        <form class="vc-pill" role="search" data-form="q">
          <button type="button" class="vc-pill-btn" data-act="drawer" aria-label="Menu: settings and admin" aria-expanded="${S.drawer}">${icon("menu")}</button>
          <label class="sr-only" for="vc-q">Search identifiers, questions or nodes</label>
          <input id="vc-q" type="search" enterkeyhint="search" autocomplete="off" spellcheck="false" placeholder="Search the vault" value="${esc(S.q)}" />
          ${S.q ? `<button type="button" class="vc-pill-btn" data-act="clear" aria-label="Clear search">${icon("x")}</button>` : `<span class="vc-pill-status" title="Appliance online"><span class="vc-dot"></span><span class="sr-only">Online</span></span>`}
        </form>
        <div class="vc-layers" role="radiogroup" aria-label="Graph layer">${DATA.graph.layers.map(([id, l]) => `<button type="button" role="radio" aria-checked="${S.layer === id}" data-act="layer" data-arg="${id}">${esc(l)}</button>`).join("")}</div>
      </div>
      <section class="vc-sheet" aria-label="${S.view === "source" ? "Source" : "Results"}">
        <button type="button" class="vc-grip" data-act="snap" aria-label="Resize panel (now ${S.snap})"><span></span></button>
        <div class="vc-sheet-body">${sheetBody()}</div>
      </section>
      ${S.drawer ? drawer() : ""}
      ${S.confirm !== null ? confirmDlg() : ""}
      <div class="vc-toast" role="status" aria-live="polite"></div>
    </div>`;
  }

  function sheetBody() {
    if (S.view === "source") return source();
    if (S.view === "results") return results();
    if (S.view === "node") return nodeCard();
    return explore();
  }
  function explore() {
    return `<h2 class="vc-h2">Explore</h2>
      <p class="vc-muted">Pan and pinch the graph, tap a node, or search above.</p>
      <div class="vc-chips">${DATA.recent.map((r) => `<button type="button" class="vc-chip" data-act="run" data-arg="${esc(r)}">${icon("clock", "sm")}<span class="${DATA.ID_RE.test(r) ? "mono" : ""}">${esc(r)}</span></button>`).join("")}</div>
      <h3 class="vc-h3">Examples</h3>
      <div class="vc-chips">${DATA.examples.exact.map(([id]) => `<button type="button" class="vc-chip mono" data-act="run" data-arg="${esc(id)}">${esc(id)}</button>`).join("")}${DATA.examples.ask.slice(0, 2).map((q) => `<button type="button" class="vc-chip" data-act="run" data-arg="${esc(q)}">${esc(q)}</button>`).join("")}</div>`;
  }
  function results() {
    const r = S.res, rl = routeLine(r);
    return `<div class="vc-rhead"><span class="badge ${rl.cls}">${icon(rl.icon, "sm")}${rl.label}</span><span class="vc-muted small">${esc(rl.meta)}</span></div>
      ${r.fast_summary ? `<div class="vc-answer">${answerHtml(r.fast_summary.answer)}</div>` : ""}
      ${r.suggestions ? `<div class="vc-chips">${r.suggestions.map((s) => `<button type="button" class="vc-chip mono" data-act="run" data-arg="${esc(s.identifier)}">${esc(s.identifier)}</button>`).join("")}</div>` : ""}
      <ul class="vc-list">${r.results.map((x, i) => `<li id="src-${i + 1}"><button type="button" class="vc-item" data-act="open" data-arg="${i}">
        <span class="vc-item-ic">${icon("doc")}</span><span class="vc-item-t">${esc(x.title)}<small>${esc(x.kind)} · ${esc(x.package)}</small><span class="vc-item-d">${esc(x.structured_sections.Description || "")}</span></span>${icon("chev-r", "sm")}</button></li>`).join("")}</ul>
      ${r.graph_dossier ? `<p class="vc-muted small vc-on-map">${icon("graph", "sm")} ALM-20104 and its 9 neighbours are highlighted on the graph.</p>` : ""}`;
  }
  function source() {
    const s = S.src, insp = DATA.inspect(s.virtual_uri, S.section === "__diagram" ? "" : S.section);
    return `<div class="vc-src-h"><button type="button" class="vc-back" data-act="back" aria-label="Back to results">${icon("chev-l")}</button>
        <div class="vc-src-t"><h2>${esc(s.title)}</h2><span class="vc-muted small">${esc(s.kind)} · ${esc(s.package)}</span></div></div>
      <div class="vc-tabs" role="tablist" aria-label="Section">${DATA.sectionTabs.map(([k, l]) => `<button type="button" role="tab" aria-selected="${S.section === k}" data-act="sec" data-arg="${esc(k)}">${l}</button>`).join("")}</div>
      ${S.section === "__diagram" ? `<div class="vc-diagram">${icon("image", "lg")}<span>Diagram extracted on request</span></div>` : `<p class="vc-text">${esc(insp.content_text)}</p>`}
      <div class="vc-src-actions"><a href="#" class="vc-primary" data-act="toast" data-arg="Opens /archive/view in a new tab">${icon("ext", "sm")} Open full manual</a>
        <button type="button" class="vc-sec-btn" data-act="toast" data-arg="MML copied" aria-label="Copy MML commands">${icon("copy")}</button></div>
      <p class="vc-muted small">${esc(insp.virtual_uri)} · read-only</p>`;
  }
  function nodeCard() {
    const n = DATA.graph.node;
    return `<div class="vc-node-h"><span class="vc-dotc" style="background:#199e70" aria-hidden="true"></span><div><h2 class="mono">${esc(n.label)}</h2><span class="vc-muted small">${esc(n.kind)} · 9 connections</span></div>
        <button type="button" class="vc-back" data-act="unselect" aria-label="Clear selection">${icon("x")}</button></div>
      <div class="vc-two"><button type="button" class="vc-primary" data-act="run" data-arg="${esc(n.label)}">${icon("search", "sm")} Search this</button><button type="button" class="vc-sec-btn wide" data-act="toast" data-arg="Expanded">${icon("plus", "sm")} Expand</button></div>
      ${n.conns.map(([k, list]) => `<h3 class="vc-h3">${esc(k.replace(/_/g, " ").toLowerCase())}</h3><div class="vc-chips">${list.map((x) => `<button type="button" class="vc-chip mono" data-act="toast" data-arg="Select ${esc(x)}">${esc(x)}</button>`).join("")}</div>`).join("")}`;
  }
  function opts() {
    return `<div class="vc-opts" role="dialog" aria-label="Map options">
      <div class="vc-seg" role="radiogroup" aria-label="Dimensions"><button type="button" role="radio" aria-checked="true">2D</button><button type="button" role="radio" aria-checked="false">3D</button></div>
      <label class="vc-row"><span>Edges</span><span class="vc-switch"><input type="checkbox" role="switch" checked aria-label="Edges" /><span></span></span></label>
      <label class="vc-row"><span>Clearance</span><select class="vc-sel"><option>Restricted</option><option>Confidential</option><option>Internal</option><option>Public</option></select></label>
      <div class="vc-legend">${DATA.graph.legend[S.layer].map(([c, l, n]) => `<button type="button" class="vc-leg" aria-pressed="true"><span class="vc-dotc" style="background:${c}"></span>${esc(l)}<small>${fmt(n)}</small></button>`).join("")}</div>
    </div>`;
  }
  function drawer() {
    const back = `<button type="button" class="vc-back" data-act="dview" data-arg="" aria-label="Back">${icon("chev-l")}</button>`;
    let body;
    if (S.dview === "dirs") {
      body = `<div class="vc-dh">${back}<h2 id="vc-d-t">Monitored directories</h2></div>` + DATA.sources.map((s, i) => `<div class="vc-dir"><span class="mono">${esc(s.path)}</span><small>${esc(s.domain)} · ${fmt(s.indexed_records)} records · synced ${esc(s.last_sync)}</small>
        <div class="vc-two"><button type="button" class="vc-sec-btn wide" data-act="toast" data-arg="Re-sync started">${icon("refresh", "sm")} Re-sync</button><button type="button" class="vc-danger" data-act="confirm" data-arg="${i}">${icon("trash", "sm")} Remove…</button></div></div>`).join("") +
        `<button type="button" class="vc-sec-btn wide block" data-act="toast" data-arg="Add directory form">${icon("plus", "sm")} Add directory</button>`;
    } else if (S.dview === "license") {
      const l = DATA.license;
      body = `<div class="vc-dh">${back}<h2 id="vc-d-t">License</h2></div><p class="vc-lic">${icon("shield")} <b>${esc(l.tier)}</b> · verified · expires ${esc(l.expires_at)}</p>
        <dl class="vc-dl"><dt>Customer</dt><dd class="mono">${esc(l.customer_id)}</dd><dt>Key</dt><dd class="mono">${esc(l.public_key_fingerprint)}</dd><dt>Hardware</dt><dd class="mono">${esc(l.hardware_fingerprint)}</dd></dl>
        <button type="button" class="vc-sec-btn wide block" data-act="toast" data-arg="Token form">${icon("key", "sm")} Replace token…</button>`;
    } else if (S.dview === "tools") {
      body = `<div class="vc-dh">${back}<h2 id="vc-d-t">AI tool connections</h2></div><label class="sr-only" for="vc-h">Tool</label><select id="vc-h" class="vc-sel block">${DATA.harnesses.map(([k, n]) => `<option>${esc(n)}</option>`).join("")}</select>
        <pre class="vc-pre">${esc(DATA.snippet)}</pre><button type="button" class="vc-primary block" data-act="toast" data-arg="Snippet copied">${icon("copy", "sm")} Copy snippet</button>`;
    } else {
      const row = (v, ic, t, d) => `<li><button type="button" class="vc-drow" data-act="dview" data-arg="${v}">${icon(ic)}<span>${t}<small>${d}</small></span>${icon("chev-r", "sm")}</button></li>`;
      body = `<div class="vc-dh"><span class="vc-mark" aria-hidden="true">Æ</span><h2 id="vc-d-t">Aegis Sovereign</h2></div>
        <p class="vc-muted small pad">${fmt(DATA.status.records)} records · ${fmt(DATA.status.entities)} entities · online, read-only</p>
        <ul class="vc-dlist">
          <li><label class="vc-drow">${icon("cpu")}<span>Local LLM<small>${S.llm ? "Running" : "Standby"}</small></span><span class="vc-switch"><input type="checkbox" role="switch" data-act="llm" ${S.llm ? "checked" : ""} aria-label="Local LLM" /><span></span></span></label></li>
          ${row("dirs", "folder", "Monitored directories", `${DATA.sources.length} · ${fmt(DATA.sources.reduce((a, s) => a + s.indexed_records, 0))} records`)}
          ${row("license", "key", "License", `${DATA.license.tier} · verified`)}
          ${row("tools", "plug", "AI tool connections", "MCP v2")}
        </ul>
        <p class="vc-muted small pad">${esc(DATA.status.host)} · v${esc(DATA.status.version)}</p>`;
    }
    return `<div class="vc-scrim" data-act="drawer"></div><nav class="vc-drawer" aria-labelledby="vc-d-t" tabindex="-1">${body}</nav>`;
  }
  function confirmDlg() {
    const s = DATA.sources[S.confirm];
    return `<div class="vc-scrim top" data-act="cancel"></div><section class="vc-confirm" role="alertdialog" aria-modal="true" aria-labelledby="vc-c-t" tabindex="-1">
      <h2 id="vc-c-t">Remove from index?</h2><p>Deletes <b>${fmt(s.indexed_records)} records</b> and graph edges for <span class="mono">${esc(s.path)}</span>. Files on disk stay.</p>
      <div class="vc-two"><button type="button" class="vc-sec-btn wide" data-act="cancel">Cancel</button><button type="button" class="vc-danger solid" data-act="toast" data-arg="Removed">Remove</button></div></section>`;
  }

  // ------------------------------------------------------------------------------------ behaviour
  function render(focus) {
    root.innerHTML = shell();
    placeRing(root.querySelector(".vc-stage"));
    const dlg = root.querySelector(".vc-confirm, .vc-drawer");
    if (focus) { const el = root.querySelector(focus); if (el) el.focus({ preventScroll: true }); } else if (dlg) dlg.focus({ preventScroll: true });
  }
  function run(q) { S.q = q; S.res = DATA.route(q); S.view = "results"; S.src = null; S.node = DATA.graph.node; S.layer = "entity"; S.snap = S.res.fast_summary ? "full" : "half"; render(); }
  function toast(m) { const t = root.querySelector(".vc-toast"); if (!t) return; t.textContent = m; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 1800); }
  function onClick(e) {
    const el = e.target.closest("[data-act]"); if (!el || el.tagName === "INPUT") return;
    const a = el.dataset.act, arg = el.dataset.arg;
    if (el.tagName === "A") e.preventDefault();
    if (a === "run") run(arg);
    else if (a === "open") { S.src = S.res.results[Number(arg)]; S.section = ""; S.view = "source"; S.snap = "full"; render(".vc-back"); }
    else if (a === "back") { S.view = "results"; S.snap = "half"; render(); }
    else if (a === "sec") { S.section = arg; render(`[data-act=sec][data-arg="${arg}"]`); }
    else if (a === "snap") { S.snap = { peek: "half", half: "full", full: "peek" }[S.snap]; render(".vc-grip"); }
    else if (a === "layer") { S.layer = arg; S.node = null; if (S.view === "node") S.view = "explore"; render(); }
    else if (a === "opts") { S.opts = !S.opts; render(); }
    else if (a === "drawer") { S.drawer = !S.drawer; S.dview = null; render(S.drawer ? null : ".vc-pill-btn"); }
    else if (a === "dview") { S.dview = arg || null; render(); }
    else if (a === "clear") { S.q = ""; S.res = null; S.view = "explore"; S.snap = "peek"; S.node = null; render("#vc-q"); }
    else if (a === "unselect") { S.node = null; S.view = S.res ? "results" : "explore"; S.snap = "peek"; render(); }
    else if (a === "confirm") { S.confirm = Number(arg); render(); }
    else if (a === "cancel") { S.confirm = null; render(); }
    else if (a === "toast") toast(arg);
  }
  function onChange(e) { if (e.target.dataset.act === "llm") { S.llm = e.target.checked; render(); } }
  function onSubmit(e) { e.preventDefault(); const v = root.querySelector("#vc-q").value.trim(); if (v) run(v); }

  PROTO.VARIANTS.C = {
    name: "Map model (graph + sheet)",
    mount(el, ctx) {
      root = el;
      root.addEventListener("click", onClick); root.addEventListener("change", onChange); root.addEventListener("submit", onSubmit);
      window.addEventListener("keydown", (e) => { if (e.key === "Escape") { S.drawer = false; S.confirm = null; S.opts = false; render(); } });
      const sc = ctx.screen;
      if (sc === "results" || sc === "source") { S.q = "ALM-20104"; S.res = DATA.route(S.q); S.view = "results"; S.snap = "half"; S.node = DATA.graph.node; }
      if (sc === "answer") { S.q = "Why did ALM-20104 trigger and how do we fix it?"; S.res = DATA.route(S.q); S.view = "results"; S.snap = "full"; S.node = DATA.graph.node; }
      if (sc === "source") { S.src = S.res.results[0]; S.section = "Possible Causes"; S.view = "source"; S.snap = "full"; }
      if (sc === "graph") { S.view = "node"; S.node = DATA.graph.node; S.snap = "half"; }
      if (sc === "graph-options") S.opts = true;
      if (sc === "settings") S.drawer = true;
      if (sc === "sources" || sc === "confirm") { S.drawer = true; S.dview = "dirs"; if (sc === "confirm") S.confirm = 2; }
      if (sc === "license" || sc === "tools") { S.drawer = true; S.dview = sc; }
      render();
    },
  };
})();
