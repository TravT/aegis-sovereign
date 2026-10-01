/* PROTOTYPE (throwaway) - Variant A: "Search-first app shell".
   Phone: bottom tab bar (Search / Graph / Settings), sticky search field at the top, sheets for
   filters, source preview, result actions and graph options. Tablet/desktop: the tab bar becomes a
   left rail and Search becomes master-detail (results | source pane). */
(function () {
  "use strict";
  const { DATA, esc, icon, fmt, answerHtml, routeLine, predict, placeRing } = PROTO;

  const S = {
    tab: "search", sub: null, q: "", res: null, src: null, section: "",
    filters: { scope: "all", mode: "auto", deep: false }, sheet: null, sheetArg: null,
    layer: "entity", node: null, dims: "2d", edges: true, showAll: false, clearance: "restricted", colorBy: "theme",
    llm: DATA.llm.status === "running", toast: "",
  };
  let root, lastFocus = null;
  const wide = () => window.matchMedia("(min-width: 768px)").matches;

  // ------------------------------------------------------------------------------------ shell
  function shell() {
    return `
    <div class="va" data-tab="${S.tab}">
      <a class="va-skip" href="#va-main">Skip to content</a>
      <nav class="va-tabs" aria-label="Primary">
        <div class="va-brand" aria-hidden="true"><span class="va-mark">Æ</span><span class="va-brand-t">Aegis</span></div>
        ${tabBtn("search", "search", "Search")}${tabBtn("graph", "graph", "Graph")}${tabBtn("settings", "settings", "Settings")}
        <div class="va-rail-status" aria-hidden="true"><span class="va-dot"></span>Online</div>
      </nav>
      <main id="va-main" class="va-main" tabindex="-1">${screen()}</main>
      <div class="va-scrim" ${S.sheet ? "" : "hidden"} data-act="close-sheet"></div>
      ${S.sheet ? sheet() : ""}
      <div class="va-toast" role="status" aria-live="polite">${esc(S.toast)}</div>
    </div>`;
  }
  function tabBtn(id, ic, label) {
    const on = S.tab === id;
    return `<button type="button" class="va-tab${on ? " on" : ""}" data-act="tab" data-arg="${id}" ${on ? 'aria-current="page"' : ""}>${icon(ic, "lg")}<span>${label}</span></button>`;
  }
  function screen() {
    if (S.tab === "search") return searchScreen();
    if (S.tab === "graph") return graphScreen();
    return settingsScreen();
  }

  // ------------------------------------------------------------------------------------ search
  function activeFilterCount() { const f = S.filters; return (f.scope !== "all") + (f.mode !== "auto") + (f.deep ? 1 : 0); }
  function searchScreen() {
    const n = activeFilterCount();
    const hasRes = !!S.res;
    return `
    <div class="va-search ${hasRes ? "has-res" : ""} ${S.src ? "has-src" : ""}">
      <section class="va-col" aria-label="Search">
        <header class="va-head">
          <div class="va-head-row">
            <span class="va-mark sm" aria-hidden="true">Æ</span>
            <h1 class="va-h1">Search the vault</h1>
            <span class="va-online"><span class="va-dot"></span>Online</span>
          </div>
          <form class="va-form" role="search" data-form="search">
            <label class="sr-only" for="va-q">Identifier or question</label>
            <div class="va-field">
              ${icon("search")}
              <input id="va-q" type="search" enterkeyhint="search" autocomplete="off" spellcheck="false" placeholder="Identifier or question" value="${esc(S.q)}" />
              <button type="submit" class="va-go" aria-label="Search">${icon("arrow-up")}</button>
            </div>
            <button type="button" class="va-icon-btn" data-act="sheet" data-arg="filters" aria-label="Search options${n ? ", " + n + " active" : ""}">${icon("sliders")}${n ? `<span class="va-count">${n}</span>` : ""}</button>
          </form>
          <p class="va-predict" id="va-predict" aria-live="polite">${esc(predict(S.q))}</p>
        </header>
        ${hasRes ? results() : idle()}
      </section>
      ${wide() ? `<section class="va-pane" aria-label="Source preview">${S.src ? sourceBody(false) : paneEmpty()}</section>` : ""}
    </div>`;
  }
  function idle() {
    const ex = DATA.examples;
    return `
    <div class="va-idle">
      <h2 class="va-h2">${icon("clock", "sm")} Recent</h2>
      <ul class="va-list">${DATA.recent.map((r) => `<li><button type="button" class="va-row" data-act="run" data-arg="${esc(r)}"><span class="${DATA.ID_RE.test(r) ? "mono" : ""}">${esc(r)}</span>${icon("chev-r", "sm")}</button></li>`).join("")}</ul>
      <details class="va-examples">
        <summary><span>Examples</span><span class="va-muted">${ex.exact.length + ex.ask.length}</span>${icon("chev-d", "sm")}</summary>
        <h3 class="va-h3">${icon("zap", "sm")} Exact lookups</h3>
        <ul class="va-list">${ex.exact.map(([id, d]) => `<li><button type="button" class="va-row" data-act="run" data-arg="${esc(id)}"><span><span class="mono">${esc(id)}</span><small>${esc(d)}</small></span>${icon("chev-r", "sm")}</button></li>`).join("")}</ul>
        <h3 class="va-h3">${icon("sparkle", "sm")} Questions</h3>
        <ul class="va-list">${ex.ask.map((q) => `<li><button type="button" class="va-row" data-act="run" data-arg="${esc(q)}"><span>${esc(q)}</span>${icon("chev-r", "sm")}</button></li>`).join("")}</ul>
      </details>
      <p class="va-foot">${fmt(DATA.status.records)} records · ${fmt(DATA.status.entities)} graph entities · read-only vault</p>
    </div>`;
  }
  function results() {
    const r = S.res, rl = routeLine(r);
    let html = `<div class="va-results" aria-live="polite">
      <div class="va-route"><span class="badge ${rl.cls}">${icon(rl.icon, "sm")}${rl.label}</span><span class="va-muted">${esc(rl.meta)}</span></div>`;
    if (r.fast_summary) {
      html += `<article class="va-answer" aria-label="Answer">${answerHtml(r.fast_summary.answer)}<p class="va-muted small">Grounded in the sources below. Tap a [n] to open it.</p></article>`;
    }
    if (r.suggestions) {
      html += `<div class="va-miss"><p><b class="mono">${esc(r.identifier)}</b> is not a registered identifier. Did you mean:</p>
        <div class="va-chips">${r.suggestions.map((s) => `<button type="button" class="va-chip" data-act="run" data-arg="${esc(s.identifier)}"><span class="mono">${esc(s.identifier)}</span> ${esc(s.short_title)}</button>`).join("")}</div></div>`;
    }
    html += `<h2 class="va-h2">${r.results.length} source${r.results.length === 1 ? "" : "s"}</h2><ol class="va-cards">` +
      r.results.map((x, i) => `
        <li class="va-card${S.src && S.src.virtual_uri === x.virtual_uri ? " on" : ""}" id="src-${i + 1}">
          <button type="button" class="va-card-main" data-act="open" data-arg="${i}">
            <span class="va-card-n" aria-hidden="true">${i + 1}</span>
            <span class="va-card-body">
              <span class="va-card-t">${esc(x.title)}</span>
              <span class="va-card-m">${esc(x.kind)} · ${esc(x.package)}</span>
              <span class="va-card-d">${esc(x.structured_sections.Description || "")}</span>
              ${x.has_procedure || x.has_diagram ? `<span class="va-tags">${x.has_procedure ? `<span class="va-tag">${icon("check", "sm")}Procedure</span>` : ""}${x.has_diagram ? `<span class="va-tag">${icon("image", "sm")}Diagram</span>` : ""}</span>` : ""}
            </span>
          </button>
          <button type="button" class="va-icon-btn ghost" data-act="sheet" data-arg="actions" data-i="${i}" aria-label="More actions for ${esc(x.doc_identifier)}">${icon("more")}</button>
        </li>`).join("") + `</ol>`;
    const d = r.graph_dossier && r.graph_dossier.by_relation;
    if (d) {
      html += `<div class="va-related"><h2 class="va-h2">Related commands</h2>
        <div class="va-rel-row"><span class="va-rel-k">Diagnose</span>${d.DIAGNOSED_BY_MML.map(chipRun).join("")}</div>
        <div class="va-rel-row"><span class="va-rel-k">Fix</span>${d.REMEDIATED_BY_MML.map(chipRun).join("")}</div>
        <div class="va-rel-row"><span class="va-rel-k">Graph</span><button type="button" class="va-chip" data-act="graph-for" data-arg="${esc(r.graph_dossier.entity.name)}">${icon("graph", "sm")} Show ${esc(r.graph_dossier.entity.name)} in graph</button></div>
        <p class="va-muted small">KPIs: ${d.MEASURED_BY_COUNTER.map(esc).join(", ")}</p></div>`;
    }
    return html + `</div>`;
  }
  const chipRun = (m) => `<button type="button" class="va-chip mono" data-act="run" data-arg="${esc(m)}">${esc(m)}</button>`;
  function paneEmpty() {
    return `<div class="va-pane-empty">${icon("doc", "lg")}<p>Select a source to preview it here.</p><p class="va-muted small">Previews stream from the archive only when you ask for them.</p></div>`;
  }
  function sourceBody(inSheet) {
    const s = S.src, insp = DATA.inspect(s.virtual_uri, S.section === "__diagram" ? "" : S.section);
    const body = S.section === "__diagram"
      ? `<div class="va-diagram">${icon("image", "lg")}<p>Diagram extracted on request (fig_0412 signalling path).</p></div>`
      : `<pre class="va-pre">${esc(insp.content_text)}</pre>`;
    return `
      <div class="va-src">
        <div class="va-src-head">
          ${inSheet ? `<button type="button" class="va-icon-btn ghost" data-act="close-sheet" aria-label="Close preview">${icon("chev-d")}</button>` : ""}
          <div class="va-src-t"><h2 id="va-sheet-title">${esc(s.title)}</h2><span class="va-muted small">${esc(s.kind)} · ${esc(s.package)}</span></div>
          <button type="button" class="va-icon-btn ghost" data-act="sheet" data-arg="actions" data-i="${S.res.results.indexOf(s)}" aria-label="More actions">${icon("more")}</button>
        </div>
        <div class="va-seg wrap" role="tablist" aria-label="Section">
          ${DATA.sectionTabs.map(([k, l]) => `<button type="button" role="tab" aria-selected="${S.section === k}" class="${S.section === k ? "on" : ""}" data-act="section" data-arg="${esc(k)}">${l}</button>`).join("")}
        </div>
        <div class="va-src-body">${body}
          <details class="va-details"><summary>Source details</summary>
            <dl><dt>URI</dt><dd class="mono">${esc(insp.virtual_uri)}</dd><dt>Entry</dt><dd class="mono">${esc(insp.entry_name)}</dd><dt>SHA-256</dt><dd class="mono">${esc(insp.sha256_hash.slice(0, 24))}…</dd><dt>Read mode</dt><dd>O_RDONLY, zero-disk</dd></dl>
          </details>
        </div>
        <div class="va-src-foot"><a class="va-primary" href="#" data-act="toast" data-arg="Opens /archive/view in a new tab">${icon("ext", "sm")} Open full manual</a></div>
      </div>`;
  }

  // ------------------------------------------------------------------------------------ graph
  function graphScreen() {
    const img = DATA.graph.img[S.layer][wide() ? 1 : 0];
    const n = S.node;
    return `
    <div class="va-graph ${n ? "has-node" : ""}">
      <h1 class="sr-only">Knowledge graph</h1>
      <div class="va-stage">
        <img src="${img}" alt="Knowledge graph, ${esc(S.layer)} layer (static stand-in for the WebGL canvas)" />
        ${n ? `<span class="va-sel-ring" data-ring aria-hidden="true"></span>` : ""}
      </div>
      <div class="va-g-top">
        <form class="va-g-find" role="search" data-form="gfind">
          ${icon("search")}<label class="sr-only" for="va-gq">Find a node</label>
          <input id="va-gq" type="search" placeholder="Find a node" value="${n ? esc(n.label) : ""}" autocomplete="off" />
        </form>
        <button type="button" class="va-icon-btn solid" data-act="sheet" data-arg="gopts" aria-label="View options">${icon("sliders")}</button>
      </div>
      <div class="va-seg va-g-layers" role="radiogroup" aria-label="Layer">
        ${DATA.graph.layers.map(([id, l]) => `<button type="button" role="radio" aria-checked="${S.layer === id}" class="${S.layer === id ? "on" : ""}" data-act="layer" data-arg="${id}">${esc(l)}</button>`).join("")}
      </div>
      <div class="va-g-tools">
        <button type="button" class="va-icon-btn solid fine" data-act="toast" data-arg="Zoom in" aria-label="Zoom in">${icon("plus")}</button>
        <button type="button" class="va-icon-btn solid fine" data-act="toast" data-arg="Zoom out" aria-label="Zoom out">${icon("minus")}</button>
        <button type="button" class="va-icon-btn solid" data-act="toast" data-arg="Fit whole graph" aria-label="Fit whole graph">${icon("target")}</button>
      </div>
      ${n ? nodePanel(n) : `<p class="va-g-hint">Tap a node to inspect it · pinch to zoom · drag to pan</p>`}
    </div>`;
  }
  function nodePanel(n) {
    return `
      <section class="va-node" aria-labelledby="va-node-t">
        <div class="va-grip" aria-hidden="true"></div>
        <div class="va-node-head">
          <span class="va-dotc" style="background:#199e70" aria-hidden="true"></span>
          <div><h2 id="va-node-t" class="mono">${esc(n.label)}</h2><span class="va-muted small">${esc(n.kind)} · 9 connections</span></div>
          <button type="button" class="va-icon-btn ghost" data-act="node-close" aria-label="Clear selection">${icon("x")}</button>
        </div>
        <div class="va-node-actions">
          <button type="button" class="va-primary" data-act="run-tab" data-arg="${esc(n.label)}">${icon("search", "sm")} Search this</button>
          <button type="button" class="va-secondary" data-act="toast" data-arg="Centered">${icon("target", "sm")} Center</button>
        </div>
        <details class="va-details open-wide" ${wide() ? "open" : ""}><summary>Connections (9)</summary>
          ${n.conns.map(([k, list]) => `<div class="va-conn-k">${esc(k.replace(/_/g, " ").toLowerCase())}</div>${list.map((x) => `<button type="button" class="va-conn" data-act="toast" data-arg="Select ${esc(x)}">${esc(x)}</button>`).join("")}`).join("")}
          <div class="va-conn-k">described in the manuals</div>${n.described_in.map((x) => `<button type="button" class="va-conn" data-act="toast" data-arg="Open topic">${icon("doc", "sm")} ${esc(x)}</button>`).join("")}
        </details>
      </section>`;
  }

  // ------------------------------------------------------------------------------------ settings
  function settingsScreen() {
    const list = settingsList();
    if (wide()) return `<div class="va-settings two"><section class="va-set-list" aria-label="Settings">${list}</section><section class="va-set-detail">${S.sub ? subPage() : `<div class="va-pane-empty">${icon("settings", "lg")}<p>Choose a setting.</p></div>`}</section></div>`;
    return `<div class="va-settings">${S.sub ? subPage() : list}</div>`;
  }
  function settingsList() {
    const st = DATA.status, tot = DATA.sources.reduce((a, s) => a + s.indexed_records, 0);
    const row = (sub, ic, t, d) => `<li><button type="button" class="va-set-row${S.sub === sub ? " on" : ""}" data-act="sub" data-arg="${sub}">${icon(ic)}<span class="va-set-t">${t}<small>${d}</small></span>${icon("chev-r", "sm")}</button></li>`;
    return `
      <header class="va-head plain"><h1 class="va-h1">Settings</h1></header>
      <div class="va-status-card"><span class="va-dot"></span><div><b>Appliance online</b><small>${fmt(st.records)} records · ${fmt(st.entities)} entities · ${fmt(st.edges)} edges</small></div></div>
      <h2 class="va-group">Appliance</h2>
      <ul class="va-set">
        <li><div class="va-set-row static">${icon("cpu")}<span class="va-set-t">Local LLM<small>${S.llm ? "Running · " + DATA.llm.model : "Standby · uses no CPU or RAM"}</small></span>
          <label class="va-switch"><input type="checkbox" role="switch" data-act="llm" ${S.llm ? "checked" : ""} aria-label="Local LLM"><span></span></label></div></li>
      </ul>
      <h2 class="va-group">Knowledge</h2>
      <ul class="va-set">${row("sources", "folder", "Monitored directories", `${DATA.sources.length} directories · ${fmt(tot)} records`)}</ul>
      <h2 class="va-group">Platform</h2>
      <ul class="va-set">${row("license", "key", "License", `${DATA.license.tier} · signature verified`)}${row("tools", "plug", "AI tool connections", "MCP v2 · 6 harnesses")}</ul>
      <h2 class="va-group">About</h2>
      <dl class="va-about"><dt>Host</dt><dd class="mono">${esc(st.host)}</dd><dt>Vault</dt><dd class="mono">${esc(st.vault)}</dd><dt>Access</dt><dd>Read-only (O_RDONLY zero-copy)</dd><dt>Version</dt><dd class="mono">${esc(st.version)}</dd></dl>`;
  }
  function subHead(title, extra) {
    return `<header class="va-subhead">${wide() ? "" : `<button type="button" class="va-icon-btn ghost" data-act="sub" data-arg="" aria-label="Back to settings">${icon("chev-l")}</button>`}<h1 class="va-h1">${title}</h1>${extra || ""}</header>`;
  }
  function subPage() {
    if (S.sub === "sources") {
      return subHead("Monitored directories", `<button type="button" class="va-icon-btn ghost" data-act="sheet" data-arg="add" aria-label="Add directory">${icon("plus")}</button>`) +
        `<p class="va-muted small pad">Directories indexed into the router and graph. Folders with <code>.aegis-no-index</code> are skipped.</p>
        <ul class="va-set">${DATA.sources.map((s, i) => `<li><button type="button" class="va-set-row" data-act="sheet" data-arg="source" data-i="${i}">${icon("folder")}<span class="va-set-t"><span class="mono path">${esc(s.path)}</span><small>${esc(s.domain)} · ${fmt(s.indexed_records)} records · synced ${esc(s.last_sync)}</small></span>${icon("chev-r", "sm")}</button></li>`).join("")}</ul>`;
    }
    if (S.sub === "license") {
      const l = DATA.license;
      return subHead("License") + `
        <div class="va-status-card gold">${icon("shield")}<div><b>${esc(l.tier)}</b><small>Ed25519 signature verified · expires ${esc(l.expires_at)}</small></div></div>
        <dl class="va-about"><dt>Organisation</dt><dd>${esc(l.organization)}</dd><dt>Customer</dt><dd class="mono">${esc(l.customer_id)}</dd><dt>Key</dt><dd class="mono">${esc(l.public_key_fingerprint)}</dd><dt>Hardware</dt><dd class="mono">${esc(l.hardware_fingerprint)}</dd></dl>
        <h2 class="va-group">Included</h2><ul class="va-feats">${l.unlocked_features.map((f) => `<li>${icon("check", "sm")}${esc(f)}</li>`).join("")}</ul>
        <div class="pad"><button type="button" class="va-secondary block" data-act="sheet" data-arg="token">${icon("key", "sm")} Replace license token…</button></div>`;
    }
    const h = DATA.harnesses;
    return subHead("AI tool connections") + `
      <div class="pad">
        <label class="va-label" for="va-harness">Tool</label>
        <div class="va-select"><select id="va-harness">${h.map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join("")}</select>${icon("chev-d", "sm")}</div>
        <p class="va-muted small">Add this to <code>${esc(h[0][2])}</code></p>
        <pre class="va-pre code">${esc(DATA.snippet)}</pre>
        <button type="button" class="va-primary block" data-act="toast" data-arg="Snippet copied">${icon("copy", "sm")} Copy snippet</button>
      </div>`;
  }

  // ------------------------------------------------------------------------------------ sheets
  function sheet() {
    const k = S.sheet;
    let title = "", body = "", cls = "";
    if (k === "filters") {
      const f = S.filters;
      title = "Search options";
      body = `
        <fieldset class="va-fs"><legend>Search in</legend>${seg("scope", [["all", "All vaults"], ["telecom", "Telecom"], ["homelab", "Homelab"]], f.scope)}</fieldset>
        <fieldset class="va-fs"><legend>Answer</legend>${seg("mode", [["auto", "Automatic"], ["prong1", "Exact only"], ["prong2", "Summarise"]], f.mode)}
          <p class="va-muted small">Automatic: identifiers get an exact lookup, questions get a grounded summary.</p></fieldset>
        <div class="va-set-row static">${icon("cpu")}<span class="va-set-t">Deep synthesis<small>${S.llm ? "Uses the local LLM" : "Local LLM is on standby. Turn it on in Settings."}</small></span>
          <label class="va-switch"><input type="checkbox" role="switch" data-act="deep" ${f.deep ? "checked" : ""} ${S.llm ? "" : "disabled"} aria-label="Deep synthesis"><span></span></label></div>
        <button type="button" class="va-primary block" data-act="close-sheet">Done</button>`;
    } else if (k === "actions") {
      const x = S.res.results[S.sheetArg];
      title = x.doc_identifier;
      body = `<ul class="va-menu">
        <li><button type="button" data-act="toast" data-arg="Opens /archive/view in a new tab">${icon("ext")} Open full manual</button></li>
        <li><button type="button" data-act="graph-for" data-arg="${esc(x.doc_identifier)}">${icon("graph")} Show in graph</button></li>
        ${x.has_procedure ? `<li><button type="button" data-act="toast" data-arg="MML copied">${icon("copy")} Copy MML commands</button></li>` : ""}
        <li><button type="button" data-act="toast" data-arg="Link copied">${icon("link")} Copy source link</button></li></ul>`;
    } else if (k === "source") {
      const s = DATA.sources[S.sheetArg];
      title = "Directory";
      body = `<p class="mono path big">${esc(s.path)}</p><p class="va-muted small">${esc(s.domain)} · ${fmt(s.indexed_records)} records · last synced ${esc(s.last_sync)} · ${esc(s.guard)}</p>
        <button type="button" class="va-primary block" data-act="toast" data-arg="Re-sync started">${icon("refresh", "sm")} Re-sync now</button>
        <button type="button" class="va-danger block" data-act="sheet" data-arg="confirm" data-i="${S.sheetArg}">${icon("trash", "sm")} Remove from index…</button>`;
    } else if (k === "confirm") {
      const s = DATA.sources[S.sheetArg];
      title = "Remove from index?"; cls = "alert";
      body = `<p>This deletes <b>${fmt(s.indexed_records)} records</b>, their search tokens and graph edges for:</p><p class="mono path">${esc(s.path)}</p>
        <p class="va-muted small">Files on disk are not touched. You can re-add the directory later; indexing takes a few minutes.</p>
        <div class="va-row2"><button type="button" class="va-secondary" data-act="close-sheet">Cancel</button><button type="button" class="va-danger solid" data-act="toast" data-arg="Removed from index">Remove</button></div>`;
    } else if (k === "add") {
      title = "Add directory";
      body = `<label class="va-label" for="va-np">Path on the server</label><input id="va-np" class="va-input mono" placeholder="/home/tlima/Enterprise_Hub/docs/wiki/operations" />
        <label class="va-label" for="va-nd">Label</label><input id="va-nd" class="va-input" placeholder="Homelab runbooks" />
        <button type="button" class="va-primary block" data-act="toast" data-arg="Indexing started">${icon("plus", "sm")} Add and index</button>`;
    } else if (k === "token") {
      title = "Replace license token";
      body = `<label class="va-label" for="va-tok">Signed .aegis-license token</label><textarea id="va-tok" class="va-input mono" rows="5" placeholder="Paste the Base64 token"></textarea>
        <button type="button" class="va-primary block" data-act="toast" data-arg="Signature verified">${icon("shield", "sm")} Verify and attach</button>`;
    } else if (k === "gopts") {
      title = "View options";
      body = `
        <fieldset class="va-fs"><legend>View</legend>${seg("dims", [["2d", "2D"], ["3d", "3D"]], S.dims)}</fieldset>
        <label class="va-label" for="va-colour">Colour by</label><div class="va-select"><select id="va-colour"><option>Entity type</option></select>${icon("chev-d", "sm")}</div>
        <fieldset class="va-fs"><legend>Show categories</legend><div class="va-chips">${DATA.graph.legend[S.layer].map(([c, l, n]) => `<button type="button" class="va-chip" aria-pressed="true"><span class="va-dotc" style="background:${c}"></span>${esc(l)} <span class="va-muted">${fmt(n)}</span></button>`).join("")}</div></fieldset>
        <div class="va-set-row static"><span class="va-set-t">Edges</span><label class="va-switch"><input type="checkbox" role="switch" checked aria-label="Edges"><span></span></label></div>
        ${S.layer === "tree" ? `<div class="va-set-row static"><span class="va-set-t">All 45,425 nodes<small>Slower on phones</small></span><label class="va-switch"><input type="checkbox" role="switch" aria-label="Show all nodes"><span></span></label></div>` : ""}
        <label class="va-label" for="va-clr">Clearance</label><div class="va-select"><select id="va-clr"><option>Restricted (all)</option><option>Confidential</option><option>Internal</option><option>Public</option></select>${icon("chev-d", "sm")}</div>
        <button type="button" class="va-primary block" data-act="close-sheet">Done</button>`;
    } else if (k === "src") {
      cls = "full";
      return `<section class="va-sheet full" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="va-sheet-title">${sourceBody(true)}</section>`;
    }
    return `<section class="va-sheet ${cls}" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="va-sheet-title">
      <div class="va-grip" aria-hidden="true"></div>
      <div class="va-sheet-head"><h2 id="va-sheet-title">${esc(title)}</h2><button type="button" class="va-icon-btn ghost" data-act="close-sheet" aria-label="Close">${icon("x")}</button></div>
      <div class="va-sheet-body">${body}</div></section>`;
  }
  function seg(name, opts, cur) {
    return `<div class="va-seg" role="radiogroup">${opts.map(([v, l]) => `<button type="button" role="radio" aria-checked="${cur === v}" class="${cur === v ? "on" : ""}" data-act="seg" data-name="${name}" data-arg="${v}">${l}</button>`).join("")}</div>`;
  }

  // ------------------------------------------------------------------------------------ behaviour
  function render(focusSel) {
    root.innerHTML = shell();
    placeRing(root.querySelector(".va-stage"));
    if (S.sheet) {
      const sh = root.querySelector(".va-sheet");
      if (sh) sh.focus({ preventScroll: true });
    } else if (focusSel) { const el = root.querySelector(focusSel); if (el) el.focus({ preventScroll: true }); }
  }
  function run(q) {
    S.q = q; S.res = DATA.route(q, S.filters); S.src = null; S.section = ""; S.sheet = null; S.tab = "search";
    render();
  }
  function toast(msg) {
    S.toast = msg; const t = root.querySelector(".va-toast"); if (t) { t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 1800); }
  }
  function onClick(e) {
    const el = e.target.closest("[data-act]"); if (!el || el.tagName === "INPUT") return;
    const a = el.dataset.act, arg = el.dataset.arg;
    if (el.tagName === "A") e.preventDefault();
    switch (a) {
      case "tab": S.tab = arg; S.sheet = null; render(); break;
      case "run": run(arg); break;
      case "run-tab": run(arg); break;
      case "open": {
        lastFocus = el; S.src = S.res.results[Number(arg)]; S.section = "";
        if (!wide()) S.sheet = "src"; render(); break;
      }
      case "section": S.section = arg; render(`[data-act=section][data-arg="${arg}"]`); break;
      case "sheet": lastFocus = el; S.sheet = arg; if (el.dataset.i !== undefined) S.sheetArg = Number(el.dataset.i); render(); break;
      case "close-sheet": S.sheet = S.sheet === "confirm" ? "source" : null; if (S.sheet === "src") S.sheet = null; render(); if (lastFocus && document.body.contains(lastFocus)) lastFocus.focus(); break;
      case "seg": {
        const n = el.dataset.name;
        if (n === "dims") S.dims = arg; else S.filters[n] = arg;
        render(`[data-name=${n}][data-arg=${arg}]`); break;
      }
      case "layer": S.layer = arg; S.node = null; render(); break;
      case "node-close": S.node = null; render(); break;
      case "graph-for": S.tab = "graph"; S.layer = "entity"; S.node = DATA.graph.node; S.sheet = null; render(); break;
      case "sub": S.sub = arg || null; render(); break;
      case "toast": toast(arg); break;
    }
  }
  function onChange(e) {
    const el = e.target;
    if (el.dataset.act === "llm") { S.llm = el.checked; toast(S.llm ? "Local LLM starting…" : "Local LLM stopping…"); render(); }
    if (el.dataset.act === "deep") S.filters.deep = el.checked;
  }
  function onSubmit(e) {
    e.preventDefault();
    const f = e.target.dataset.form;
    if (f === "search") { const q = root.querySelector("#va-q").value.trim(); if (q) run(q); }
    if (f === "gfind") { S.node = DATA.graph.node; S.layer = "entity"; render(); }
  }
  function onInput(e) { if (e.target.id === "va-q") { S.q = e.target.value; const p = root.querySelector("#va-predict"); if (p) p.textContent = predict(S.q); } }

  PROTO.VARIANTS.A = {
    name: "Search-first app shell",
    mount(el, ctx) {
      root = el;
      root.addEventListener("click", onClick); root.addEventListener("change", onChange);
      root.addEventListener("submit", onSubmit); root.addEventListener("input", onInput);
      window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && S.sheet) { S.sheet = null; render(); }
        if ((e.key === "/" || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k")) && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); S.tab = "search"; render("#va-q"); }
      });
      let wasWide = wide(); window.addEventListener("resize", () => { if (wide() !== wasWide) { wasWide = wide(); render(); } }); // only on breakpoint change: the phone keyboard also fires resize
      const sc = ctx.screen;
      if (sc === "results" || sc === "source") { S.q = "ALM-20104"; S.res = DATA.route("ALM-20104"); }
      if (sc === "answer") { S.q = "Why did ALM-20104 trigger and how do we fix it?"; S.res = DATA.route(S.q); }
      if (sc === "source") { S.src = S.res.results[0]; S.section = "Possible Causes"; if (!wide()) S.sheet = "src"; }
      if (sc === "filters") S.sheet = "filters";
      if (sc === "graph" || sc === "graph-options") { S.tab = "graph"; S.node = DATA.graph.node; if (sc === "graph-options") { S.node = null; S.sheet = "gopts"; } }
      if (sc === "settings") { S.tab = "settings"; if (wide()) S.sub = "sources"; }
      if (["sources", "license", "tools"].includes(sc)) { S.tab = "settings"; S.sub = sc; }
      if (sc === "confirm") { S.tab = "settings"; S.sub = "sources"; S.sheet = "confirm"; S.sheetArg = 2; }
      render();
    },
  };
})();
