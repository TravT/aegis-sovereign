/**
 * Aegis Sovereign Web Portal - interactive knowledge graph explorer (Task 14.1).
 *
 * Data comes from /graph/v2/{meta,slice,find}: clearance-aware, level-of-detail slices of the manual
 * trees, the alarm/MML/KPI entity graph and the homelab wiki. Rendering is graph_gl.js (WebGL,
 * 2D + 3D); small layers are laid out by graph_force.js, the tree layer by the server.
 * No third-party code: the page works air-gapped.
 */
(function () {
  "use strict";

  const API = "/graph/v2";
  // Categorical colours on the portal's dark surface. Nodes of any two categories can sit side by
  // side, so only the first three palette slots are used: they are the ones that pass the data-viz
  // all-pairs gate (colour-blind separation and contrast) on this surface. Every other category is
  // folded into a neutral "other"; the legend chips isolate any category.
  const SLOTS = ["#3987e5", "#d95926", "#199e70"];
  const OTHER = "#7d8794", PACKAGE_COLOR = "#e8edf5", OTHER_KEY = "\u0000other";
  const KNOWN = {
    "tree.package": ["USC", "UPCF", "REL"],
    "tree.theme": ["om_mml", "engineering", "mml_machine"],
    "entity.theme": ["telecom_alarm", "mml_command", "telecom_kpi"],
    "wiki.kind": ["decision", "documentation", "chapter"],
  };
  const LAYERS = [
    { id: "tree", label: "Manual trees", modes: [["package", "Package"], ["theme", "Console (theme)"], ["depth", "Depth"]] },
    { id: "entity", label: "Alarms · MML · KPIs", modes: [["theme", "Entity type"]] },
    { id: "wiki", label: "Homelab wiki", modes: [["kind", "Note type"], ["theme", "Domain"]] },
  ];
  const NODE_COLUMNS = ["label", "kind", "group", "depth", "theme", "n_desc", "degree", "see_also", "uri", "x", "y", "x3", "y3", "z3"];

  const $ = (id) => document.getElementById(id);
  const esc = (s) => (typeof escapeHtml === "function" ? escapeHtml(String(s)) : String(s).replace(/[&<>"']/g, (c) => "&#" + c.charCodeAt(0) + ";"));
  const hex = (h) => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255];
  const fmt = (n) => Number(n).toLocaleString();

  /** All nodes and edges loaded so far, merged across slices (expanding a node adds to them). */
  class Store {
    constructor() { this.clear(); }
    clear() {
      this.ids = []; this.idx = new Map(); this.edges = []; this.edgeKeys = new Set();
      this.col = {}; NODE_COLUMNS.forEach((c) => { this.col[c] = []; });
      this.childCount = [];
    }
    get size() { return this.ids.length; }
    merge(slice) {
      const n = slice.nodes, remap = new Array(n.id.length);
      for (let k = 0; k < n.id.length; k++) {
        let i = this.idx.get(n.id[k]);
        if (i === undefined) {
          i = this.ids.length; this.ids.push(n.id[k]); this.idx.set(n.id[k], i); this.childCount.push(0);
          NODE_COLUMNS.forEach((c) => this.col[c].push(n[c] ? n[c][k] : (c === "see_also" ? [] : (c === "uri" ? "" : 0))));
        }
        remap[k] = i;
      }
      const e = slice.edges;
      for (let k = 0; k < e.s.length; k++) {
        const s = remap[e.s[k]], t = remap[e.t[k]], key = s + "|" + t + "|" + e.k[k];
        if (this.edgeKeys.has(key)) continue;
        this.edgeKeys.add(key); this.edges.push([s, t, e.k[k]]);
        if (e.k[k] === "CHILD_OF") this.childCount[t]++;
      }
    }
  }

  class GraphView {
    constructor() {
      this.store = new Store(); this.layer = "tree"; this.dims = "2d"; this.colorBy = "package";
      this.clearance = "restricted"; this.showAll = true; this.meta = null;
      this.selected = -1; this.hover = -1; this.only = null; this.hits = new Set();
      this.ready = false; this.busy = 0; this.force = null;
    }

    // ---- lifecycle -----------------------------------------------------------------------------
    async open() {
      if (!this.ready) { if (!this.init()) return; this.ready = true; await this.loadMeta(); await this.load(); }
      else this.gl._resize(), this.gl.requestRender();
    }

    init() {
      const canvas = $("gv-canvas");
      if (!canvas) return false;
      try {
        this.gl = new AegisGraphGL(canvas, {
          onHover: (i, e) => this.onHover(i, e), onClick: (i) => this.select(i),
          onDblClick: (i) => this.onDouble(i), onView: () => this.updateLabels(),
        });
      } catch (err) { this.status("The graph viewer needs WebGL2: " + err.message, true); return false; }
      $("gv-layers").addEventListener("click", (e) => { const b = e.target.closest("[data-layer]"); if (b) this.setLayer(b.dataset.layer); });
      $("gv-dim2").onclick = () => this.setDims("2d"); $("gv-dim3").onclick = () => this.setDims("3d");
      $("gv-colorby").onchange = (e) => { this.colorBy = e.target.value; this.recolor(); };
      $("gv-showall").onchange = (e) => { this.showAll = e.target.checked; this.load(); };
      $("gv-edges").onchange = (e) => { this.edgesOn = e.target.checked; this.gl.edgesOn = this.edgesOn; this.gl.edgeAlpha = this.edgesOn ? this.autoEdgeAlpha() : 0; this.gl.requestRender(); };
      const ecoBox = $("gv-edges-ecosystem"); if (ecoBox) ecoBox.onchange = (e) => { this.gl.ecosystemOn = e.target.checked; this.gl.requestRender(); };
      const relBox = $("gv-edges-relational"); if (relBox) relBox.onchange = (e) => { this.gl.relationalOn = e.target.checked; this.gl.requestRender(); };
      $("gv-clearance").onchange = async (e) => { this.clearance = e.target.value; await this.loadMeta(); await this.load(); };
      $("gv-zoom-in").onclick = () => this.gl.zoomBy(1.4); $("gv-zoom-out").onclick = () => this.gl.zoomBy(1 / 1.4);
      $("gv-fit").onclick = () => this.gl.fit();
      const box = $("gv-search"); let timer = null;
      box.oninput = () => { clearTimeout(timer); timer = setTimeout(() => this.search(box.value), 180); };
      box.onkeydown = (e) => { if (e.key === "Enter") { const first = $("gv-results").querySelector("[data-id]"); if (first) first.click(); } if (e.key === "Escape") this.clearSearch(); };
      $("gv-legend").addEventListener("click", (e) => { const b = e.target.closest("[data-cat]"); if (b) this.toggleCategory(b.dataset.cat, e.shiftKey); });
      this.edgesOn = true;
      return true;
    }

    status(text, error) { const el = $("gv-status"); if (el) { el.textContent = text; el.className = "gv-status" + (error ? " gv-error" : ""); } }
    async api(op, params) {
      const q = new URLSearchParams(Object.assign({ user_clearance: this.clearance }, params));
      const resp = await fetch(`${API}/${op}?${q}`);
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || resp.statusText);
      return body;
    }

    async loadMeta() {
      try { this.meta = await this.api("meta", {}); } catch (e) { this.status("Graph API unavailable: " + e.message, true); return; }
      const available = new Set(this.meta.layers.map((l) => l.id));
      $("gv-layers").innerHTML = LAYERS.filter((l) => available.has(l.id)).map((l) => {
        const info = this.meta.layers.find((m) => m.id === l.id);
        return `<button type="button" class="gv-layer${l.id === this.layer ? " active" : ""}" data-layer="${l.id}">${esc(l.label)} <span class="gv-count">${fmt(info.nodes)}</span></button>`;
      }).join("");
    }

    // ---- loading -------------------------------------------------------------------------------
    async load() {
      const token = ++this.busy;
      this.cancelForce(); this.selected = -1; this.hover = -1; this.hits.clear();
      this.status("Loading…");
      try {
        const params = { layer: this.layer };
        if (this.layer === "tree") params.mode = this.showAll ? "all" : "clustered";
        const t0 = performance.now(), slice = await this.api("slice", params);
        if (token !== this.busy) return;
        this.store.clear(); this.store.merge(slice);
        this.applyLayerUi(); this.rebuild(true);
        this.status(`${fmt(this.store.size)} nodes · ${fmt(this.store.edges.length)} edges · ${Math.round(performance.now() - t0)} ms`);
        this.renderInspector(-1);
      } catch (e) { this.status("Could not load the graph: " + e.message, true); }
    }

    applyLayerUi() {
      const def = LAYERS.find((l) => l.id === this.layer);
      if (!def.modes.some((m) => m[0] === this.colorBy)) this.colorBy = def.modes[0][0];
      $("gv-colorby").innerHTML = def.modes.map((m) => `<option value="${m[0]}"${m[0] === this.colorBy ? " selected" : ""}>${esc(m[1])}</option>`).join("");
      $("gv-showall-wrap").style.display = this.layer === "tree" ? "" : "none";
      document.querySelectorAll("#gv-layers .gv-layer").forEach((b) => b.classList.toggle("active", b.dataset.layer === this.layer));
    }

    async setLayer(layer) { if (layer === this.layer) return; this.layer = layer; this.colorBy = ""; this.only = null; this.clearSearch(); await this.load(); }
    setDims(d) {
      this.dims = d; $("gv-dim2").classList.toggle("active", d === "2d"); $("gv-dim3").classList.toggle("active", d === "3d");
      this.gl.mode = d; this.rebuild(true);
    }

    // ---- building GL data ----------------------------------------------------------------------
    positions() {
      const c = this.store.col, n = this.store.size, pos = new Float32Array(n * 3), three = this.dims === "3d";
      for (let i = 0; i < n; i++) {
        pos[i * 3] = three ? c.x3[i] : c.x[i]; pos[i * 3 + 1] = three ? c.y3[i] : c.y[i]; pos[i * 3 + 2] = three ? c.z3[i] : 0;
      }
      return pos;
    }

    /** The category value of node i for the current colouring (release packages and ADRs are merged). */
    category(i) {
      const c = this.store.col;
      if (this.colorBy === "package") return String(c.group[i]).startsWith("REL_") ? "REL" : c.group[i];
      if (this.colorBy === "kind") return c.kind[i] === "adr" ? "decision" : c.kind[i];
      return c.theme[i];
    }
    isPackageNode(i) { return this.layer === "tree" && this.store.col.kind[i] === "package"; }

    makeScale() {
      const n = this.store.size, key = `${this.layer}.${this.colorBy}`;
      if (this.colorBy === "depth") {
        let max = 1; for (let i = 0; i < n; i++) max = Math.max(max, this.store.col.depth[i]);
        const at = (d) => { const t = Math.min(1, Math.max(0, (d - 1) / Math.max(1, max - 1))); return [0.30 + 0.62 * (1 - t), 0.62 + 0.30 * (1 - t), 0.98 - 0.15 * t]; };
        return { depth: true, max, rgb: (i) => at(this.store.col.depth[i]), bucketOf: () => "", legend: [] };
      }
      const counts = new Map();
      for (let i = 0; i < n; i++) { if (this.isPackageNode(i)) continue; const v = this.category(i); counts.set(v, (counts.get(v) || 0) + 1); }
      const slot = new Map(); (KNOWN[key] || []).forEach((v, k) => slot.set(v, k));
      let next = slot.size;                              // unknown categories: the most common ones take the free slots
      [...counts.entries()].sort((a, b) => b[1] - a[1]).forEach(([v]) => { if (v !== "" && !slot.has(v) && next < SLOTS.length) slot.set(v, next++); });
      const bucketOf = (i) => (this.isPackageNode(i) ? "" : slot.has(this.category(i)) ? this.category(i) : OTHER_KEY);
      const hexOf = (i) => (this.isPackageNode(i) ? PACKAGE_COLOR : slot.has(this.category(i)) ? SLOTS[slot.get(this.category(i))] : OTHER);
      const legend = [...slot.entries()].filter(([v]) => counts.has(v)).sort((a, b) => a[1] - b[1]).map(([v, k]) => ({ value: v, color: SLOTS[k], count: counts.get(v) }));
      const rest = [...counts.entries()].filter(([v]) => !slot.has(v)).reduce((a, [, c]) => a + c, 0);
      if (rest) legend.push({ value: OTHER_KEY, color: OTHER, count: rest, label: this.colorBy === "theme" && this.layer === "tree" ? "other / no console tag" : "other" });
      return { depth: false, legend, bucketOf, hexOf, rgb: (i) => hex(hexOf(i)) };
    }

    autoEdgeAlpha() { const m = this.store.edges.length; return m > 20000 ? 0.05 : m > 3000 ? 0.10 : 0.26; }

    /** (Re)upload everything: positions, colours, sizes, edges. keepView=false keeps the camera. */
    rebuild(fit) {
      const s = this.store, n = s.size, c = s.col;
      this.stopForceOnly();
      const pos = this.layer === "tree" ? this.positions() : new Float32Array(n * 3);
      const color = new Float32Array(n * 3), size = new Float32Array(n);
      this.scale = this.makeScale();
      for (let i = 0; i < n; i++) {
        color.set(this.scale.rgb(i), i * 3);
        const isPkg = this.layer === "tree" && c.kind[i] === "package";
        size[i] = isPkg ? 11 : this.layer === "tree" ? 2.4 + Math.log2(1 + c.n_desc[i]) * 0.6 : 3.4 + Math.min(11, Math.sqrt(c.degree[i]) * 1.1);
      }
      const hierEdges = [];
      const ecoEdges = [];
      const relEdges = [];
      this.adj = Array.from({ length: n }, () => []);
      s.edges.forEach((e, k) => {
        const sIdx = e[0], tIdx = e[1], kind = e[2];
        this.adj[sIdx].push(k);
        this.adj[tIdx].push(k);
        if (kind === "COMPANION_PACKAGE" || kind === "CORE_NETWORK_PEER") {
          ecoEdges.push(sIdx, tIdx);
        } else if (kind === "SHARED_ALARM" || kind === "SHARED_MML" || kind === "FUNCTIONAL_BRIDGE" || kind === "SHARES_ENTITY") {
          relEdges.push(sIdx, tIdx);
        } else {
          hierEdges.push(sIdx, tIdx);
        }
      });
      const edges = new Uint32Array(hierEdges);
      const ecosystemEdges = new Uint32Array(ecoEdges);
      const relationalEdges = new Uint32Array(relEdges);
      this.order = Array.from({ length: n }, (_, i) => i).sort((a, b) => size[b] - size[a]).slice(0, 4000);
      this.gl.mode = this.dims; this.gl.pos = pos;
      this.gl.edgeAlpha = this.edgesOn ? this.autoEdgeAlpha() : 0;
      this.gl.setData({ pos, color, size, edges, ecosystemEdges, relationalEdges });
      this.applyFlags();
      this.renderLegend();
      if (this.layer !== "tree") this.startForce();
      else if (fit) this.gl.fit();
    }

    /** A new colouring only re-uploads the colour buffer (a running layout is not disturbed). */
    recolor() {
      const n = this.store.size, color = new Float32Array(n * 3);
      this.scale = this.makeScale();
      for (let i = 0; i < n; i++) color.set(this.scale.rgb(i), i * 3);
      this.gl.setColors(color); this.renderLegend(); this.applyFlags();
      if (this.selected >= 0) this.renderInspector(this.selected);
    }

    // ---- force layout for the flat layers ------------------------------------------------------
    startForce() {
      const n = this.store.size; if (!n) return;
      const edges = new Uint32Array(this.store.edges.length * 2);
      this.store.edges.forEach((e, k) => { edges[k * 2] = e[0]; edges[k * 2 + 1] = e[1]; });
      const pos = this.gl.pos, dims = this.dims === "3d" ? 3 : 2;
      this.force = new AegisGraphForce(pos, edges, dims);
      const force = this.force;
      this.status(`Laying out ${fmt(n)} nodes…`);
      const tick = () => {
        if (this.force !== force) return;
        const t0 = performance.now();                    // as many steps as fit a 30 ms frame budget
        do { force.step(); } while (!force.done && performance.now() - t0 < 30);
        this.gl.updatePositions();
        if (force.tick <= 3 || force.tick % 25 === 0 || force.done) this.gl.fit(true);
        if (force.done) { this.status(`${fmt(n)} nodes · ${fmt(this.store.edges.length)} edges`); this.force = null; }
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
    stopForceOnly() { this.force = null; }
    cancelForce() { this.force = null; }

    // ---- flags, legend, filtering --------------------------------------------------------------
    applyFlags() {
      const n = this.store.size, flags = new Uint8Array(n);
      if (this.only && !this.scale.depth) {
        for (let i = 0; i < n; i++) { const b = this.scale.bucketOf(i); if (b !== "" && !this.only.has(b)) flags[i] = 1; }
      }
      this.hits.forEach((i) => { if (flags[i] !== 1) flags[i] = 2; });
      if (this.selected >= 0 && this.adj && this.adj[this.selected]) {
        this.adj[this.selected].forEach((k) => { const e = this.store.edges[k]; const o = e[0] === this.selected ? e[1] : e[0]; if (flags[o] !== 1) flags[o] = 2; });
        flags[this.selected] = 3;
      }
      this.gl.setFlags(flags);
      this.updateLabels();
    }

    renderLegend() {
      const el = $("gv-legend");
      if (this.scale.depth) {
        el.innerHTML = `<span class="gv-legend-note">Depth</span><span class="gv-depth-bar"></span><span class="gv-legend-note">1 → ${this.scale.max}</span>`;
        return;
      }
      el.innerHTML = this.scale.legend.map((l) => `
        <button type="button" class="gv-chip${this.only && !this.only.has(l.value) ? " off" : ""}" data-cat="${esc(l.value)}" title="Click to isolate this category; click again to show all (Shift-click adds or removes one)">
          <span class="gv-dot" style="background:${l.color}"></span>${esc(l.label || l.value)} <span class="gv-count">${fmt(l.count)}</span>
        </button>`).join("") || `<span class="gv-legend-note">No categories</span>`;
    }
    /** Click isolates a category (click again: show all); Shift-click adds or removes one from the shown set. */
    toggleCategory(v, additive) {
      if (additive) {
        const all = new Set(this.scale.legend.map((l) => l.value)), cur = this.only ? new Set(this.only) : all;
        if (cur.has(v)) cur.delete(v); else cur.add(v);
        this.only = cur.size === 0 || cur.size === all.size ? null : cur;
      } else this.only = this.only && this.only.size === 1 && this.only.has(v) ? null : new Set([v]);
      this.renderLegend(); this.applyFlags();
    }

    // ---- interaction ---------------------------------------------------------------------------
    onHover(i, e) {
      this.hover = i;
      const tip = $("gv-tooltip");
      if (i < 0) { tip.style.display = "none"; this.updateLabels(); return; }
      const c = this.store.col, r = $("gv-stage").getBoundingClientRect();
      tip.innerHTML = `<b>${esc(c.label[i])}</b><br>${esc(c.kind[i])}${c.theme[i] ? " · " + esc(c.theme[i]) : ""}` +
        (this.layer === "tree" ? `<br>${fmt(c.n_desc[i])} descendants` : `<br>${fmt(c.degree[i])} connections`);
      tip.style.left = Math.min(r.width - 250, e.clientX - r.left + 14) + "px"; tip.style.top = (e.clientY - r.top + 14) + "px"; tip.style.display = "block";
      this.updateLabels();
    }

    isExpandable(i) { return this.layer === "tree" && this.store.col.n_desc[i] > 0 && this.store.childCount[i] === 0; }

    onDouble(i) { if (this.isExpandable(i)) this.expand(i); else this.gl.focusOn(i); }

    select(i) {
      this.selected = i;
      const hot = (i >= 0 && this.adj && this.adj[i]) ? this.adj[i].flatMap((k) => [this.store.edges[k][0], this.store.edges[k][1]]) : [];
      this.gl.setHotEdges(new Uint32Array(hot));
      this.applyFlags(); this.renderInspector(i);
    }

    async expand(i) {
      if (!this.isExpandable(i)) return;
      this.status("Expanding…");
      try {
        const slice = await this.api("slice", { layer: "tree", focus: this.store.ids[i], levels: 1 });
        this.store.merge(slice); const keep = this.store.ids[this.selected];
        this.rebuild(false); if (keep) this.select(this.store.idx.get(keep));
        this.status(`${fmt(this.store.size)} nodes · ${fmt(this.store.edges.length)} edges`);
      } catch (e) { this.status("Could not expand: " + e.message, true); }
    }

    /** Load every ancestor of a tree node along its path (one level each), then select it. */
    async reveal(path) {
      const target = path[path.length - 1];
      if (this.layer !== this.currentHitLayer && this.currentHitLayer) { this.layer = this.currentHitLayer; this.colorBy = ""; await this.load(); }
      for (let k = 0; k < path.length - 1; k++) {
        const i = this.store.idx.get(path[k]); if (i === undefined) break;
        if (this.isExpandable(i)) { const slice = await this.api("slice", { layer: "tree", focus: path[k], levels: 1 }); this.store.merge(slice); }
      }
      if (this.layer === "tree") this.rebuild(false);      // flat layers have nothing new to load, and a rebuild would restart their layout
      const i = this.store.idx.get(target); if (i === undefined) { this.status("Node not loaded", true); return; }
      this.select(i); this.gl.focusOn(i); this.gl.zoomBy(this.gl.mode === "2d" ? 3.5 : 2.5);
    }

    // ---- search --------------------------------------------------------------------------------
    async search(text) {
      const box = $("gv-results"); this.hits.clear();
      if (text.trim().length < 2) { box.innerHTML = ""; this.applyFlags(); return; }
      try {
        const hits = await this.api("find", { q: text, layer: this.layer, limit: 12 });
        this.currentHitLayer = this.layer;
        box.innerHTML = hits.map((h) => `<div class="gv-result" data-id="${esc(h.id)}"><b>${esc(h.label)}</b><small>${esc(h.kind)} · ${esc(h.path.length - 1)} levels deep</small></div>`).join("") || `<div class="gv-result none">No matches at this clearance</div>`;
        box.querySelectorAll("[data-id]").forEach((el, k) => { el.onclick = () => { this.reveal(hits[k].path); box.innerHTML = ""; }; });
        hits.forEach((h) => { const i = this.store.idx.get(h.id); if (i !== undefined) this.hits.add(i); });
        this.applyFlags();
      } catch (e) { box.innerHTML = `<div class="gv-result none">${esc(e.message)}</div>`; }
    }
    clearSearch() { $("gv-search").value = ""; $("gv-results").innerHTML = ""; this.hits.clear(); if (this.gl) this.applyFlags(); }

    /** Jump to a manual topic from another layer (an alarm's "described in" links). */
    async openTopic(id) {
      const hit = await this.api("find", { id, layer: "tree" });
      if (!hit.length) { this.status("That topic is not visible at this clearance", true); return; }
      this.currentHitLayer = "tree"; await this.reveal(hit[0].path);
    }

    // ---- labels --------------------------------------------------------------------------------
    updateLabels() {
      const host = $("gv-labels"); if (!host || !this.gl || !this.order) return;
      const gl = this.gl, out = { x: 0, y: 0, w: 0 }, taken = [], wanted = [];
      const place = (i, cls) => {
        if (i < 0 || !gl.project(i, out)) return;
        if (out.x < 4 || out.y < 4 || out.x > gl.w - 4 || out.y > gl.h - 4) return;
        const text = String(this.store.col.label[i]).slice(0, 28), w = text.length * 6.4 + 10;
        const box = [out.x + 6, out.y - 9, out.x + 6 + w, out.y + 9];
        if (cls === "gv-label" && taken.some((t) => box[0] < t[2] && box[2] > t[0] && box[1] < t[3] && box[3] > t[1])) return;
        taken.push(box); wanted.push([text, out.x, out.y, cls]);
      };
      place(this.selected, "gv-label gv-sel"); place(this.hover, "gv-label gv-sel");
      this.hits.forEach((i) => { if (wanted.length < 14) place(i, "gv-label gv-hit"); });
      const budget = this.layer === "tree" ? 26 : 40;
      for (let k = 0; k < this.order.length && wanted.length < budget; k++) { if (gl.flags[this.order[k]] !== 1) place(this.order[k], "gv-label"); }
      while (host.childNodes.length < wanted.length) host.appendChild(document.createElement("div"));
      for (let k = 0; k < host.childNodes.length; k++) {
        const el = host.childNodes[k], w = wanted[k];
        if (!w) { el.style.display = "none"; continue; }
        el.style.display = ""; el.className = w[3]; el.textContent = w[0]; el.style.transform = `translate(${w[1] + 7}px, ${w[2] - 8}px)`;
      }
    }

    // ---- inspector -----------------------------------------------------------------------------
    renderInspector(i) {
      const box = $("graph-node-details"), tag = $("graph-node-category");
      if (i < 0) { tag.textContent = this.layer; box.innerHTML = `<p class="gv-hint">Click a node to see its connections. Double-click a node with <b>+</b> descendants to expand it. Drag to ${this.dims === "3d" ? "orbit (Shift-drag to pan)" : "pan"}, scroll to zoom.</p>`; return; }
      const c = this.store.col, color = this.scale.depth ? "#3987e5" : this.scale.hexOf(i);
      tag.textContent = c.kind[i];
      const rows = this.layer === "tree"
        ? [["Package", c.group[i]], ["Depth", c.depth[i]], ["Descendants", fmt(c.n_desc[i])], ["Console", c.theme[i] || "—"]]
        : [["Type", c.theme[i] || c.kind[i]], ["Connections", fmt(c.degree[i])]];
      const byKind = new Map();
      if (this.adj && this.adj[i]) {
        this.adj[i].forEach((k) => { const e = this.store.edges[k], out = e[0] === i, peer = out ? e[1] : e[0]; const g = byKind.get(e[2]) || []; g.push({ peer, out }); byKind.set(e[2], g); });
      }
      const KIND_LABELS = {
        "COMPANION_PACKAGE": "📦 Product Family (Companion Release)",
        "CORE_NETWORK_PEER": "🌐 5G Core Network Peer",
        "FUNCTIONAL_BRIDGE": "🌉 Functional Bridge (Release ↔ HedEx)",
        "SHARED_ALARM": "🚨 Shared Alarm Handling",
        "SHARED_MML": "⌨️ Shared MML Command",
        "SHARES_ENTITY": "🧬 Shared Telecom Entity",
        "CHILD_OF": "📁 Sub-chapter / Section",
        "NEXT_TOPIC": "📄 Next Sequential Topic",
        "SECOND_PARENT": "🔀 Cross-Reference Parent",
      };
      const connections = [...byKind.entries()].map(([kind, list]) => `
        <div class="gv-conn-kind">${esc(KIND_LABELS[kind] || kind)} <span class="gv-count">${list.length}</span></div>
        ${list.slice(0, 25).map((p) => `<a href="javascript:void(0)" class="gv-conn" data-peer="${p.peer}">${p.out ? "→" : "←"} ${esc(c.label[p.peer])}</a>`).join("")}
        ${list.length > 25 ? `<div class="gv-more">+ ${list.length - 25} more</div>` : ""}`).join("");
      const seeAlso = (c.see_also && c.see_also[i]) || [];
      const uri = (c.uri && c.uri[i]) ? c.uri[i] : "";
      const viewerUrl = uri ? ("/archive/view?uri=" + encodeURIComponent(uri)) : "";
      box.innerHTML = `
        <div class="gv-node-title" style="color:${color}">${esc(c.label[i])}</div>
        <table class="gv-facts">${rows.map((r) => `<tr><td>${esc(r[0])}</td><td>${esc(r[1])}</td></tr>`).join("")}</table>
        <div class="gv-actions">
          ${viewerUrl ? `<a href="${viewerUrl}" target="_blank" class="action-btn primary-gold" style="text-decoration:none; display:inline-flex; align-items:center; justify-content:center; gap:0.4rem; font-weight:700;" id="gv-view-doc">📖 Open Article in Viewer ↗</a>` : ""}
          ${this.isExpandable(i) ? `<button type="button" class="action-btn" id="gv-expand">➕ Expand ${fmt(c.n_desc[i])} descendants</button>` : ""}
          <button type="button" class="action-btn" id="gv-center">⛶ Center Node</button>
          <button type="button" class="action-btn primary-emerald" id="gv-search-node">🔍 Run Search on Node</button>
        </div>
        ${seeAlso.length ? `<div class="sec-block-title">📖 Described in the manuals (${seeAlso.length})</div><div class="gv-topics" id="gv-topics"></div>` : ""}
        <div class="sec-block-title">🔗 Connections (${this.adj[i].length})</div>
        <div class="gv-conns">${connections || '<div class="gv-hint">No connections in the loaded view.</div>'}</div>`;
      const q = (id) => box.querySelector("#" + id);
      if (q("gv-expand")) q("gv-expand").onclick = () => this.expand(i);
      q("gv-center").onclick = () => this.gl.focusOn(i);
      q("gv-search-node").onclick = () => { if (typeof runPreset === "function") runPreset(String(c.label[i])); };
      box.querySelectorAll("[data-peer]").forEach((a) => { a.onclick = () => { const p = Number(a.dataset.peer); this.select(p); this.gl.focusOn(p); }; });
      if (seeAlso.length) this.renderTopics(seeAlso.slice(0, 8), box.querySelector("#gv-topics"));
    }

    async renderTopics(ids, host) {
      for (const id of ids) {
        try {
          const hit = await this.api("find", { id, layer: "tree" });
          if (!hit.length) continue;
          const a = document.createElement("a"); a.href = "javascript:void(0)"; a.className = "gv-conn";
          a.textContent = "📄 " + hit[0].label.slice(0, 60) + "  (" + hit[0].path[0].replace("pkg:", "") + ")";
          a.onclick = () => this.openTopic(id); host.appendChild(a);
        } catch (e) { /* a topic that vanished is simply not listed */ }
      }
    }
  }

  window.AegisGraphView = new GraphView();
})();
