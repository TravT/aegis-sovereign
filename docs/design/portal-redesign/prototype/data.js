/* PROTOTYPE (throwaway) - mock data + tiny helpers shared by the three variants.
   Shapes mirror the real API (POST /router/query, POST /archive/inspect, GET /sources, GET /license,
   GET /llm/status, /graph/v2/*) so a winning variant can be wired to the real endpoints unchanged.
   Nothing here talks to a server. */
(function () {
  "use strict";
  const ID_RE = /^(ALM-\d+|ADR-\d+|DSP\s+[A-Z0-9_]+|LST\s+[A-Z0-9_]+|MOD\s+[A-Z0-9_]+|ADD\s+[A-Z0-9_]+|RMV\s+[A-Z0-9_]+|RST\s+[A-Z0-9_]+|LOTE-[A-Z0-9_-]+|SKILL-[A-Z0-9_-]+)$/i;

  const SECTIONS = {
    "Description": "This alarm is reported when the packet loss or delay on an M3UA/SCTP link bearer exceeds the configured threshold for 3 consecutive measurement periods. Services carried on the link may experience retransmissions and increased set-up latency.",
    "Possible Causes": "1. Transmission quality between the local and the peer SCTP endpoint degraded (packet loss > 1%).\n2. The peer signalling point is overloaded and drops DATA chunks.\n3. SCTP retransmission parameters (RTO.min / RTO.max) are inconsistent between the two ends.",
    "Procedure": "1. Run DSP LINKSTAT: LINKNO=12; to check the link state.\n2. Run LST M3LNK: LNKNAME=\"STP_A\"; to verify the SCTP parameters.\n3. If the retransmission rate is above 1%, check the transport network (VLAN, MTU, QoS marking).\n4. If the alarm persists, run RST M3LNK: LNKNAME=\"STP_A\"; during a maintenance window.",
    "Impact on the System": "Signalling messages on the affected link are delayed; if all links in the link set degrade, the route to the peer becomes unavailable (see ALM-20333).",
  };
  const FULL_TEXT = "ALM-20104 Link Bearer Quality Drop\n\nAlarm ID 20104 · Severity Major · Type Communication\n\n" +
    Object.entries(SECTIONS).map(([k, v]) => k + "\n" + v).join("\n\n");

  const P1 = {
    "ALM-20104": {
      status: "success", route_type: "deterministic_direct", needs_synthesis: false, latency_ms: 0.74,
      confidence_level: "HIGH_DETERMINISTIC_EXACT", confidence_score: 0.99, identifier: "ALM-20104",
      graph_dossier: { entity: { name: "ALM-20104" }, by_relation: {
        DIAGNOSED_BY_MML: ["DSP LINKSTAT", "LST M3LNK"], REMEDIATED_BY_MML: ["RST M3LNK", "MOD M3LNK"],
        MEASURED_BY_COUNTER: ["VS.M3UA.LinkUnavail.Dur", "VS.SCTP.RetransRate"], HAS_DIAGRAM: ["fig_0412 signalling path"] } },
      results: [
        { title: "ALM-20104 Link Bearer Quality Drop", doc_identifier: "ALM-20104", package: "USC 26.1.0", kind: "Alarm reference",
          virtual_uri: "archive://USC/alarm_ref.zip#ALM-20104.html", has_procedure: true, has_diagram: true, structured_sections: SECTIONS },
        { title: "ALM-20333 STP Link Bearer Quality", doc_identifier: "ALM-20333", package: "USC 26.1.0", kind: "Alarm reference",
          virtual_uri: "archive://USC/alarm_ref.zip#ALM-20333.html", structured_sections: { Description: "Reported when the quality of all bearers of an STP link set drops below the threshold; the route to the peer becomes unavailable." } },
      ],
    },
  };
  const P2 = {
    status: "success", route_type: "hybrid_needle", needs_synthesis: true, latency_ms: 412, execution_mode: "extractive_template_fallback",
    confidence_level: "HIGH_VERIFIED", confidence_score: 0.86,
    fast_summary: { grounded: true, answer:
      "ALM-20104 fires when an M3UA/SCTP link bearer loses packets or adds delay above threshold for three periods [1].\n" +
      "Diagnose: run DSP LINKSTAT, then LST M3LNK to compare SCTP timers with the peer [1][2].\n" +
      "Fix: repair the transport path (VLAN, MTU, QoS); reset the link with RST M3LNK only in a maintenance window [1]." },
    graph_dossier: P1["ALM-20104"].graph_dossier,
    results: [
      P1["ALM-20104"].results[0],
      { title: "SCTP link troubleshooting (USC O&M guide, 7.4)", doc_identifier: "USC-OM-7.4", package: "USC 26.1.0", kind: "O&M guide",
        virtual_uri: "archive://USC/om_guide.zip#7.4.html", structured_sections: { Description: "How to compare RTO timers, heartbeat intervals and path MTU between the two ends of an SCTP association." } },
      { title: "VS.SCTP.RetransRate (KPI)", doc_identifier: "VS.SCTP.RetransRate", package: "USC 26.1.0", kind: "KPI",
        virtual_uri: "archive://USC/kpi_ref.zip#VS.SCTP.RetransRate.html", structured_sections: { Description: "Ratio of retransmitted DATA chunks to all DATA chunks on an SCTP association, per 15-minute period." } },
    ],
  };
  const MISS = {
    status: "not_found", route_type: "deterministic_direct", needs_synthesis: false, latency_ms: 0.9, identifier: "",
    confidence_level: "UNVERIFIED_SUGGESTIONS_AVAILABLE", confidence_score: 0.35,
    suggestions: [{ identifier: "ALM-20104", short_title: "Link Bearer Quality Drop" }, { identifier: "ALM-20105", short_title: "Link Bearer Congestion" }, { identifier: "ALM-20101", short_title: "M3UA Link Down" }],
    results: [],
  };

  function route(query, opts) {
    opts = opts || {};
    const q = String(query || "").trim();
    const isId = ID_RE.test(q);
    const mode = opts.mode || "auto";
    if (mode === "prong2" || (mode === "auto" && !isId)) return clone(P2, { query: q });
    const hit = P1[q.toUpperCase()];
    if (hit) return clone(hit, { query: q });
    return clone(MISS, { query: q, identifier: q.toUpperCase() });
  }
  function clone(o, extra) { return Object.assign(JSON.parse(JSON.stringify(o)), extra || {}); }

  function inspect(uri, section) {
    const text = section ? (SECTIONS[section] || "This entry has no “" + section + "” section.") : FULL_TEXT;
    return { virtual_uri: uri, entry_name: uri.split("#").pop(), section_filter_applied: section || "Full document",
      sha256_hash: "9f2c6d1ab3e45f0c7d8e9a1b2c3d4e5f60718293", zero_disk_extraction: true, content_text: text,
      diagram_url: null };
  }

  const DATA = {
    ID_RE, route, inspect, SECTIONS,
    sectionTabs: [["", "Full"], ["Description", "Description"], ["Possible Causes", "Causes"], ["Procedure", "Procedure"], ["Impact on the System", "Impact"], ["__diagram", "Diagram"]],
    status: { online: true, records: 49001, entities: 9117, edges: 20297, tier: "ENTERPRISE", host: "homelab (192.168.0.48)", vault: "Enterprise_Hub/docs/.aegis_vault", version: "2.2.1" },
    llm: { status: "standby", model: "qwen2.5:1.5b" },
    examples: {
      exact: [["ALM-20104", "Link bearer quality drop"], ["DSP OPTMODULE", "MML optical module spec"], ["ALM-1003", "Module fault + root diagram"], ["ADR-40", "Two-pronged architecture"]],
      ask: ["Why did ALM-20104 trigger and how do we fix it?", "How are the PODs of the USC organised?", "What are the first steps when commissioning the PCF?"],
    },
    recent: ["ALM-20104", "How is Traefik ingress routed in the homelab?", "DSP OPTMODULE"],
    sources: [
      { path: "/data/vendor/huawei/USC_V100R023", domain: "Telecom vendor catalog", indexed_records: 41022, last_sync: "2026-09-29 03:10", guard: ".aegis-no-index respected" },
      { path: "/data/vendor/huawei/UPCF_V100R021", domain: "Telecom vendor catalog", indexed_records: 6136, last_sync: "2026-09-29 03:14", guard: ".aegis-no-index respected" },
      { path: "/home/tlima/Enterprise_Hub/docs/wiki", domain: "Homelab wiki", indexed_records: 1843, last_sync: "2026-09-30 07:02", guard: ".aegis-no-index respected" },
    ],
    license: { tier: "ENTERPRISE", signature_verified: true, organization: "Enterprise Hub Homelab", customer_id: "LIC-AEGIS-ENTERPRISE-2026",
      algorithm: "Ed25519", public_key_fingerprint: "ed25519:7c:1f:9a:42", hardware_fingerprint: "hw:dell-7390:4b1e", expires_at: "2027-09-30",
      unlocked_features: ["Two-pronged router", "GraphRAG dossier", "RAPTOR hierarchical tree", "Archive inspector", "MCP v2 (7 tools)"] },
    harnesses: [
      ["claude_code", "Claude Code CLI", "~/.claude.json"], ["antigravity", "Google Antigravity (agy)", "~/.gemini/antigravity-cli/mcp/sovereign-vault/mcp_config.json"],
      ["claude_desktop", "Claude Desktop", "claude_desktop_config.json"], ["cursor", "Cursor IDE", "~/.cursor/mcp.json"],
      ["windsurf", "Windsurf", "~/.codeium/windsurf/mcp_config.json"], ["cline", "Continue / Cline", "cline_mcp_settings.json"],
    ],
    snippet: '{\n  "mcpServers": {\n    "sovereign-vault": {\n      "command": "python3",\n      "args": ["-m", "core.mcp"],\n      "env": { "AEGIS_URL": "http://rag.home.arpa" }\n    }\n  }\n}',
    graph: {
      layers: [["tree", "Manuals", 45425, "Manuals"], ["entity", "Alarms · MML · KPIs", 3622, "Alarms"], ["wiki", "Wiki", 126, "Wiki"]],
      legend: {
        tree: [["#3987e5", "USC", 265], ["#d95926", "UPCF", 1762], ["#199e70", "REL", 26]],
        entity: [["#3987e5", "telecom_alarm", 1865], ["#d95926", "mml_command", 1213], ["#199e70", "telecom_kpi", 308], ["#7d8794", "other", 236]],
        wiki: [["#3987e5", "decision", 33], ["#d95926", "documentation", 41], ["#199e70", "chapter", 22], ["#7d8794", "other", 30]],
      },
      img: { tree: ["img/graph_tree_phone.jpg", "img/graph_tree_wide.jpg"], entity: ["img/graph_entity_phone.jpg", "img/graph_entity_wide.jpg"], wiki: ["img/graph_entity_phone.jpg", "img/graph_entity_wide.jpg"] },
      node: { label: "ALM-20104", kind: "telecom_alarm", layer: "entity", facts: [["Type", "telecom_alarm"], ["Connections", "9"], ["Package", "USC 26.1.0"]],
        conns: [["DIAGNOSED_BY_MML", ["DSP LINKSTAT", "LST M3LNK"]], ["REMEDIATED_BY_MML", ["RST M3LNK", "MOD M3LNK"]], ["MEASURED_BY_COUNTER", ["VS.M3UA.LinkUnavail.Dur", "VS.SCTP.RetransRate"]], ["CANONICAL_ALARM_SPEC", ["ALM-20104 (Link Bear Quality)"]]],
        described_in: ["Alarm reference › ALM-20104 (USC)", "O&M guide › 7.4 SCTP links (USC)"] },
    },
  };

  // ---- helpers -------------------------------------------------------------------------------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name, cls) => `<svg class="ico ${cls || ""}" aria-hidden="true" focusable="false"><use href="#i-${name}"></use></svg>`;
  const fmt = (n) => Number(n).toLocaleString("en-US");
  /** Answer text with [n] citations rendered as small links. */
  const answerHtml = (text) => esc(text).split("\n").map((line) => `<p>${line.replace(/\[(\d)\]/g, '<a href="#src-$1" class="cite" data-cite="$1">[$1]</a>')}</p>`).join("");
  /** One-line, human description of the route taken (replaces the route banner + predictor + legend). */
  function routeLine(res) {
    if (res.status === "not_found") return { cls: "miss", icon: "alert", label: "Not in catalog", meta: "Exact lookup · no match · suggestions below" };
    if (!res.needs_synthesis) return { cls: "exact", icon: "zap", label: "Exact match", meta: `${res.latency_ms} ms · 0 LLM tokens · confidence ${Math.round(res.confidence_score * 100)}%` };
    return { cls: "synth", icon: "sparkle", label: "Synthesised answer", meta: `${res.results.length} sources · grounded · ${Math.round(res.latency_ms)} ms` };
  }
  function predict(q) { q = String(q || "").trim(); if (!q) return ""; return ID_RE.test(q) ? "Exact lookup (identifier)" : "Question: answer will be synthesised from sources"; }
  const params = new URLSearchParams(location.search);
  /** Node position (fraction of the static graph image) of ALM-20104, used to draw the selection ring. */
  const NODE_POS = { phone: [0.583, 0.546], wide: [0.550, 0.5625] };
  /** Position a selection ring over a point of an object-fit:cover image inside `stage`. */
  function placeRing(stage) {
    if (!stage) return;
    const img = stage.querySelector("img"), ring = stage.querySelector("[data-ring]");
    if (!img || !ring) return;
    const go = () => {
      const cw = stage.clientWidth, ch = stage.clientHeight, iw = img.naturalWidth, ih = img.naturalHeight;
      if (!iw) return;
      const k = Math.max(cw / iw, ch / ih), dx = (cw - iw * k) / 2, dy = (ch - ih * k) / 2;
      const pos = NODE_POS[img.src.includes("wide") ? "wide" : "phone"];
      ring.style.left = (dx + pos[0] * iw * k) + "px"; ring.style.top = (dy + pos[1] * ih * k) + "px"; ring.style.display = "block";
    };
    if (img.complete) go(); else img.addEventListener("load", go, { once: true });
  }

  window.PROTO = { DATA, esc, icon, fmt, answerHtml, routeLine, predict, params, placeRing, VARIANTS: {} };
})();
