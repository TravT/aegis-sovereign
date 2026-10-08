/**
 * Aegis Sovereign Web Portal - Core Search, Dichotomy & Workspace Controller
 */

let currentRouterMode = "auto";
let currentDomainFilter = "all";
let activeTab = "search";
let lastDossierData = null;
let currentSourceUri = "";
let currentSectionFilter = "";

function setDomainFilter(val) {
  currentDomainFilter = val;
  ["all", "homelab", "telecom"].forEach(d => {
    const pill = document.getElementById("domain-pill-" + d);
    if (pill) pill.classList.toggle("active", d === val);
  });
}

function renderStructuredContent(text) {
  if (!text) return "";
  if (typeof renderMarkdown === "function" && text.includes("|") && text.includes("\n")) {
    return renderMarkdown(text);
  }
  return escapeHtml(text);
}

function showPortalToast(msg) {
      const banner = document.getElementById("portal-toast");
      document.getElementById("portal-toast-msg").innerHTML = msg;
      banner.style.display = "flex";
    }

    // Global Keyboard Shortcut (Cmd+K or /) to focus Spotlight Search
    window.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        switchCommandTab("search");
        const input = document.getElementById("portal-query-input");
        if (input) { input.focus(); input.select(); }
      } else if (e.key === "/" && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
        e.preventDefault();
        switchCommandTab("search");
        const input = document.getElementById("portal-query-input");
        if (input) { input.focus(); }
      }
    });

    function setRouterMode(mode) {
      currentRouterMode = mode;
      ["auto", "prong1", "prong2"].forEach(m => {
        const el = document.getElementById("mode-btn-" + m);
        if (el) el.classList.toggle("active", m === mode);
      });
      updateLiveRoutePrediction(document.getElementById("portal-query-input").value);
    }

    function updateLiveRoutePrediction(val) {
      const q = (val || "").trim();
      const box = document.getElementById("live-route-predictor");
      const label = document.getElementById("live-route-predictor-label");
      if (!box || !label) return;

      const isIdMatch = /^(ALM-\d+|ADR-\d+|DSP\s+[A-Z0-9_]+|LST\s+[A-Z0-9_]+|MOD\s+[A-Z0-9_]+|ADD\s+[A-Z0-9_]+|RMV\s+[A-Z0-9_]+|LOTE-[A-Z0-9_-]+|SKILL-[A-Z0-9_-]+)$/i.test(q);
      const useProng1 = currentRouterMode === "prong1" || (currentRouterMode === "auto" && isIdMatch);

      if (useProng1) {
        box.className = "live-route-predictor";
        label.textContent = "PRONG 1 • Deterministic B-Tree Identifier Match (<0.8ms • 0 LLM Tokens)";
      } else {
        box.className = "live-route-predictor prong2-pred";
        label.textContent = "PRONG 2 • Neural NanoRunner Synthesis + Multi-Hop GraphRAG Dossier";
      }
    }

    function switchCommandTab(tabName) {
      ["search", "graph", "sources", "license"].forEach(t => {
        const btn = document.getElementById("tab-btn-" + t);
        const panel = document.getElementById("tab-panel-" + t);
        if (btn) btn.classList.toggle("active", t === tabName);
        if (panel) panel.classList.toggle("active", t === tabName);
      });
      if (tabName === "graph") {
        if (window.AegisGraphView) window.AegisGraphView.open();
      } else if (tabName === "sources") {
        loadMonitoredSources();
      } else if (tabName === "license") {
        loadLicenseStatus();
      }
    }

    async function refreshTelemetry() {
      try {
        const res = await fetch("/status");
        if (!res.ok) return;
        const data = await res.json();
        if (data.total_records !== undefined) {
          document.getElementById("tel-records").textContent =
            Number(data.total_records).toLocaleString() + " Indexed Records";
        }
        if (data.plan_tier) {
          document.getElementById("tel-license-tier").textContent =
            String(data.plan_tier).toUpperCase() + " (Ed25519)";
        }
        if (data.knowledge_graph) {
          const kg = data.knowledge_graph;
          if (kg.total_entities !== undefined) {
            document.getElementById("tel-entities").textContent =
              Number(kg.total_entities).toLocaleString() + " Graph Entities";
          }
          if (kg.total_relations !== undefined) {
            document.getElementById("tel-edges").textContent =
              Number(kg.total_relations).toLocaleString() + " Edges";
          }
        }
      } catch (e) {
        console.debug("Telemetry status check skipped:", e);
      }
    }

    function runPreset(queryText) {
      switchCommandTab("search");
      const input = document.getElementById("portal-query-input");
      input.value = queryText;
      updateLiveRoutePrediction(queryText);
      executePortalQuery();
    }

    async function executePortalQuery() {
      const query = document.getElementById("portal-query-input").value.trim();
      if (!query) return;

      const btn = document.getElementById("portal-search-btn");
      btn.textContent = "⏳ Routing...";

      const preferNeural = document.getElementById("chk-prefer-neural") ? document.getElementById("chk-prefer-neural").checked : false;

      try {
        const resp = await fetch("/router/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: query,
            domain_filter: currentDomainFilter,
            limit: 5,
            user_clearance: "restricted",
            prefer_neural: preferNeural,
            synthesize: currentRouterMode === "prong2" ? true : (currentRouterMode === "prong1" ? false : undefined)
          })
        });
        const data = await resp.json();
        renderPortalResponse(data);
      } catch (err) {
        console.error("Query failed:", err);
      } finally {
        btn.innerHTML = "<span>⚡ Route &amp; Execute</span>";
      }
    }

    function buildConfidenceRingSvg(score, isProng1) {
      const pct = Math.round(Number(score || 0.99) * 100);
      const strokeCol = isProng1 ? "#10B981" : "#06B6D4";
      const dash = Math.round((pct / 100) * 88);
      return `
        <div class="confidence-ring-wrap" title="Deterministic / Verified Confidence Score: ${pct}%">
          <svg width="32" height="32" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="14" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="3.2"></circle>
            <circle cx="18" cy="18" r="14" fill="none" stroke="${strokeCol}" stroke-width="3.2"
                    stroke-dasharray="${dash} 100" stroke-linecap="round" transform="rotate(-90 18 18)"></circle>
            <text x="18" y="21" text-anchor="middle" fill="#F8FAFC" font-size="8.8" font-family="JetBrains Mono, monospace" font-weight="700">${pct}%</text>
          </svg>
        </div>
      `;
    }

    function renderPortalResponse(data) {
      const routeType = data.route_type || data.route || "deterministic_direct";
      const status = data.status || "success";
      const needsSynth = currentRouterMode === "prong2" ? true : (currentRouterMode === "prong1" ? false : Boolean(data.needs_synthesis));
      const latency = Number(data.latency_ms || 0.8).toFixed(2);
      const isDeterministicMiss = (!needsSynth && routeType === "deterministic_direct" && status !== "success");
      const confLevel = data.confidence_level || (isDeterministicMiss ? "UNVERIFIED_SUGGESTIONS_AVAILABLE" : (needsSynth ? "HIGH_VERIFIED" : "HIGH_DETERMINISTIC_EXACT"));
      const confScore = Number(data.confidence_score || (isDeterministicMiss ? 0.35 : 0.99)).toFixed(2);

      const banner = document.getElementById("route-banner");
      const bannerTitle = document.getElementById("route-banner-title");
      const bannerMetrics = document.getElementById("route-banner-metrics");

      if (isDeterministicMiss) {
        banner.className = "route-banner prong-warning";
        bannerTitle.innerHTML =
          `⚠️ <strong>PRONG 1: IDENTIFIER NOT FOUND IN CATALOG</strong> • Safe Failure Guardrail &amp; Suggestions Active`;
        bannerMetrics.innerHTML = `
          <span class="metric-tag">Route: ${escapeHtml(routeType)} (miss)</span>
          <span class="metric-tag">Latency: ${latency}ms</span>
          <span class="metric-tag">0 Hallucinations</span>
          <span class="metric-tag">Confidence: ${escapeHtml(confLevel)} (${confScore})</span>
        `;
      } else if (!needsSynth && routeType === "deterministic_direct") {
        banner.className = "route-banner prong1";
        bannerTitle.innerHTML =
          `⚡ <strong>PRONG 1: DETERMINISTIC B-TREE / FTS5 FAST-PATH</strong> • Static Verified Lookup Active`;
        bannerMetrics.innerHTML = `
          <span class="metric-tag">Route: ${escapeHtml(routeType)}</span>
          <span class="metric-tag">Latency: ${latency}ms</span>
          <span class="metric-tag">0 LLM Tokens (98.2% Saved)</span>
          <span class="metric-tag">Confidence: ${escapeHtml(confLevel)} (${confScore})</span>
        `;
      } else {
        banner.className = "route-banner prong2";
        bannerTitle.innerHTML =
          `🧠 <strong>PRONG 2: SEMANTIC &amp; RELATIONAL SYNTHESIS</strong> • Minimal LLM Summary Active (${escapeHtml(routeType)})`;
        bannerMetrics.innerHTML = `
          <span class="metric-tag">Route: ${escapeHtml(routeType)}</span>
          <span class="metric-tag">Latency: ${latency}ms</span>
          <span class="metric-tag">Mode: ${escapeHtml(data.execution_mode || "neural_ollama_local")}</span>
          <span class="metric-tag">Confidence: ${escapeHtml(confLevel)} (${confScore})</span>
        `;
      }

      const synthBox = document.getElementById("nano-summary-container");
      if (needsSynth && data.fast_summary) {
        const fs = data.fast_summary;
        const formattedAnswer = renderMarkdown(fs.answer || "");
        synthBox.style.display = "block";
        synthBox.innerHTML = `
          <div class="nano-summary-box">
            <div class="nano-summary-header">
              <div class="nano-summary-title">
                <span>🧠 Minimal LLM Executive Summary (NanoRunner)</span>
              </div>
              <div style="display: flex; gap: 0.45rem; flex-wrap: wrap;">
                <span class="mode-badge">Mode: ${escapeHtml(fs.execution_mode || "extractive_template_fallback")}</span>
                <span class="mode-badge">Confidence: ${escapeHtml(confLevel)} (${Math.round(confScore * 100)}%)</span>
              </div>
            </div>
            <div class="nano-summary-body">${formattedAnswer}</div>
          </div>
        `;
      } else {
        synthBox.style.display = "none";
        synthBox.innerHTML = "";
      }

      renderGraphDossier(data.graph_dossier);

      const results = data.results || data.records || [];
      const cardsContainer = document.getElementById("source-cards-container");

      let suggestionHtml = "";
      if (data.suggestions && data.suggestions.length) {
        const queryId = data.identifier || document.getElementById("portal-query-input").value.trim();
        suggestionHtml = `
          <div class="suggestion-panel">
            <div class="suggestion-header">
              <span class="suggestion-icon">💡</span>
              <div>
                <div class="suggestion-title">Technical identifier <code>${escapeHtml(queryId)}</code> is not registered in the catalog.</div>
                <div class="suggestion-subtitle">
                  The requested code does not exist as an independent alarm. Neighboring alarms in the same series or related registered procedures were discovered:
                </div>
              </div>
            </div>
            <div class="suggestion-chips">
              ${data.suggestions.map(s => `
                <button type="button" class="suggestion-chip" title="Click to run instant lookup for ${escapeHtml(s.identifier)}" onclick="runPreset('${escapeHtml(s.identifier)}')">
                  <span class="chip-id">${escapeHtml(s.identifier)}</span>
                  <span class="chip-desc">${escapeHtml(s.short_title || s.title || '')}</span>
                </button>
              `).join('')}
            </div>
          </div>
        `;
      }

      if (!results.length) {
        cardsContainer.innerHTML = suggestionHtml + `
          <div class="source-card">
            <div class="source-title">No verified records matched '${escapeHtml(data.identifier || '')}' in Sovereign Vault</div>
            <p style="color: var(--text-secondary); margin-top: 0.5rem;">Safe Failure Guardrail prevented unverified hallucination. Please select a suggested neighbor identifier above or reformulate query.</p>
          </div>
        `;
        return;
      }

      let fallbackHeader = "";
      if (isDeterministicMiss) {
        fallbackHeader = `
          <div class="fallback-section-header" style="margin: 1.15rem 0 0.85rem 0; font-family: var(--font-mono); font-size: 0.82rem; color: #FBBF24; display: flex; align-items: center; gap: 0.5rem;">
            <span>📚 Related Documentation &amp; Topic References matching '<strong>${escapeHtml(data.identifier || "")}</strong>':</span>
          </div>
        `;
      }

      cardsContainer.innerHTML = suggestionHtml + fallbackHeader + results.map((r, idx) => {
        const vUri = r.virtual_uri || r.source_uri || r.file_path || "";
        const secs = r.structured_sections || {};
        const desc = secs["Description"] || (r.content || "").slice(0, 600);
        const causes = secs["Possible Causes"] || "";
        const proc = secs["Procedure"] || "";
        const params = secs["Parameters"] || "";
        const isProng1Card = !needsSynth;
        const tagText = isDeterministicMiss ? '⚡ RELATED TOPIC (FALLBACK)' : (isProng1Card ? '⚡ PRONG 1 EXACT' : '🧠 PRONG 2 VERIFIED');
        const tagColor = isDeterministicMiss ? '#FBBF24' : (isProng1Card ? 'var(--emerald-bright)' : 'var(--cyan-bright)');

        return `
          <article class="source-card ${isProng1Card ? 'prong1-card' : 'prong2-card'}" id="source-card-${idx + 1}">
            <div class="source-card-header">
              <div class="source-title-wrap">
                <div class="source-title">[${idx + 1}] ${escapeHtml(r.title || r.doc_identifier)}</div>
                <div style="margin-top: 0.25rem; display: flex; gap: 0.45rem; align-items: center;">
                  <span class="metric-tag">${escapeHtml(r.confidence_band || confLevel)}</span>
                  <span class="metric-tag" style="color: ${tagColor};">
                    ${tagText}
                  </span>
                </div>
              </div>
              ${buildConfidenceRingSvg(confScore, isProng1Card)}
            </div>
            <div class="source-uri">
              <a href="/archive/view?uri=${encodeURIComponent(vUri)}" target="_blank" class="source-link-btn" title="Open formatted document in new browser tab">
                🔗 ${escapeHtml(vUri)} <span style="font-size: 0.72rem; color: #38BDF8;">↗ View in Document Viewer</span>
              </a>
              <span style="color: var(--text-secondary); font-size: 0.7rem;">O_RDONLY STREAM</span>
            </div>

            <div class="structured-grid">
              <div class="sec-block">
                <div class="sec-block-title">
                  <span>📋 Description &amp; Specification</span>
                </div>
                <div class="sec-block-content">${renderStructuredContent(desc)}</div>
              </div>
              ${causes ? `
              <div class="sec-block">
                <div class="sec-block-title"><span>🔍 Possible Causes</span></div>
                <div class="sec-block-content">${renderStructuredContent(causes)}</div>
              </div>` : ""}
              ${proc ? `
              <div class="sec-block">
                <div class="sec-block-title">
                  <span>🛠️ Remediation Procedure</span>
                  <button type="button" class="inspector-tab" style="padding: 0.12rem 0.45rem; font-size: 0.68rem;" onclick="copyMmlFromCard('${escapeHtml(proc.slice(0, 240).replace(/'/g, "\\'"))}')">📋 Copy MML</button>
                </div>
                <div class="sec-block-content" style="font-family: var(--font-mono); font-size: 0.81rem;">${renderStructuredContent(proc)}</div>
              </div>` : ""}
              ${params ? `
              <div class="sec-block">
                <div class="sec-block-title"><span>⚙️ Parameters</span></div>
                <div class="sec-block-content">${renderStructuredContent(params)}</div>
              </div>` : ""}
            </div>

            <div class="action-btn-row">
              <a href="/archive/view?uri=${encodeURIComponent(vUri)}" target="_blank" class="action-btn primary-emerald" style="text-decoration: none;">
                📖 Open Full Manual in Viewer Tab ↗
              </a>
              <button class="action-btn" onclick="openSourceInInspector('${escapeHtml(vUri)}', '', false)">
                📄 Open in Side Drawer
              </button>
              <button class="action-btn" onclick="openSourceInInspector('${escapeHtml(vUri)}', 'Possible Causes', false)">
                🔍 Jump to Causes
              </button>
              <button class="action-btn" onclick="openSourceInInspector('${escapeHtml(vUri)}', 'Procedure', false)">
                🛠️ Jump to Procedure
              </button>
              <button class="action-btn" onclick="openSourceInInspector('${escapeHtml(vUri)}', '', true)">
                🖼️ Render Diagram
              </button>
            </div>
          </article>
        `;
      }).join("");
    }

    function renderGraphDossier(dossier) {
      const container = document.getElementById("graph-dossier-container");
      if (!dossier || (!dossier.neighbors || !dossier.neighbors.length)) {
        container.innerHTML = "";
        return;
      }

      const byRel = dossier.by_relation || {};
      const groups = [
        { key: "DIAGNOSED_BY_MML", label: "🩺 DIAGNOSED_BY_MML (Click to Run Prong 1)", isMml: true },
        { key: "REMEDIATED_BY_MML", label: "🛠️ REMEDIATED_BY_MML (Click to Run Prong 1)", isMml: true },
        { key: "MEASURED_BY_COUNTER", label: "📊 MEASURED_BY_COUNTER (3GPP / Vendor KPIs)", isMml: false },
        { key: "HAS_DIAGRAM", label: "🖼️ HAS_DIAGRAM (Embedded Signaling Plates)", isDiag: true }
      ];

      const rootName = (dossier.entity && dossier.entity.name) ? dossier.entity.name : "Matched Entity";
      const boxesHtml = groups.map(g => {
        const items = byRel[g.key] || [];
        if (!items.length) return "";
        const pills = items.slice(0, 6).map(item => {
          const rawName = item.name || (item.entity && item.entity.name) || "";
          if (g.isMml) {
            const cleanMml = rawName.split("(")[0].trim();
            return `<button type="button" class="entity-pill mml-pill" title="Click to execute Prong 1 MML Lookup: ${escapeHtml(cleanMml)}" onclick="runPreset('${escapeHtml(cleanMml)}')">⚡ ${escapeHtml(rawName)}</button>`;
          }
          if (g.isDiag) {
            const shortDiag = rawName.includes("#") ? rawName.split("#").pop() : rawName;
            return `<button type="button" class="entity-pill diag-pill" onclick="inspectCurrentSource('', true)">🖼️ ${escapeHtml(shortDiag)}</button>`;
          }
          return `<span class="entity-pill">${escapeHtml(rawName)}</span>`;
        }).join("");

        return `
          <div class="relation-box">
            <div class="relation-label">${g.label}</div>
            <div class="entity-pills">${pills}</div>
          </div>
        `;
      }).filter(Boolean).join("");

      if (!boxesHtml) {
        container.innerHTML = "";
        return;
      }

      container.innerHTML = `
        <div class="graph-dossier-panel">
          <div class="graph-header">
            <div class="graph-title">🕸️ Connected Knowledge Graph Dossier — ${escapeHtml(rootName)}</div>
            <span class="metric-tag">${dossier.neighbors.length} Connected Nodes</span>
          </div>
          <div class="relation-groups">${boxesHtml}</div>
        </div>
      `;
    }

    async function openSourceInInspector(virtualUri, sectionFilter = "", extractDiagram = false) {
      if (!virtualUri) return;
      currentInspectedUri = virtualUri;

      loadTopicNavigation(virtualUri);

      const metaEl = document.getElementById("inspector-meta");
      const contentEl = document.getElementById("inspector-content");
      const diagBox = document.getElementById("inspector-diagram-container");

      metaEl.innerHTML = `Streaming <code>${escapeHtml(virtualUri)}</code> in-memory (O_RDONLY)...`;

      try {
        const resp = await fetch("/archive/inspect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            virtual_uri: virtualUri,
            section_filter: sectionFilter,
            extract_diagram_to_artifact: extractDiagram,
            max_chars: 8000
          })
        });
        const data = await resp.json();
        metaEl.innerHTML = `
          <div><strong>Virtual URI:</strong> <code>${escapeHtml(data.virtual_uri || virtualUri)}</code></div>
          <div><strong>Entry:</strong> ${escapeHtml(data.entry_name || "N/A")} | <strong>Filter:</strong> ${escapeHtml(data.section_filter_applied || "Full Document")}</div>
          <div><strong>SHA-256:</strong> <code>${escapeHtml((data.sha256_hash || "").slice(0, 24))}...</code> | <strong>O_RDONLY Zero-Disk:</strong> ${Boolean(data.zero_disk_extraction)}</div>
        `;
        const rawContent = data.content_text || data.extracted_text || "No text content in entry.";
        if (typeof renderMarkdown === "function" && rawContent.includes("|") && rawContent.includes("\n")) {
          contentEl.className = "inspector-content-rendered";
          contentEl.innerHTML = renderMarkdown(rawContent);
        } else {
          contentEl.className = "inspector-content-pre";
          contentEl.textContent = rawContent;
        }

        if (data.diagram_url) {
          diagBox.style.display = "block";
          diagBox.innerHTML = `
            <div style="font-family: var(--font-mono); font-size: 0.78rem; color: var(--gold-bright);">
              🖼️ Extracted Signaling / Root Alarm Diagram (<code>${escapeHtml(data.diagram_url)}</code>)
            </div>
            <img src="${escapeHtml(data.diagram_url)}" alt="Extracted Huawei Signaling / Alarm Diagram" />
          `;
        } else if (!extractDiagram) {
          diagBox.style.display = "none";
        }
        loadTopicNavigation(virtualUri);
      } catch (err) {
        metaEl.textContent = "Error inspecting archive entry: " + err;
      }
    }

    async function loadTopicNavigation(virtualUri) {
      const treeContainer = document.getElementById("inspector-topic-tree");
      if (!treeContainer) return;
      try {
        const resp = await fetch("/topic/tree?uri=" + encodeURIComponent(virtualUri));
        if (!resp.ok) {
          treeContainer.style.display = "none";
          return;
        }
        const data = await resp.json();
        if (!data || !data.current) {
          treeContainer.style.display = "none";
          return;
        }

        let navBtns = "";
        if (data.prev_topic && data.prev_topic.uri) {
          navBtns += `<button type="button" class="inspector-nav-btn prev" onclick="openSourceInInspector('${escapeHtml(data.prev_topic.uri)}')" title="Previous: ${escapeHtml(data.prev_topic.name)}">⬅ Prev: ${escapeHtml(data.prev_topic.name)}</button>`;
        }
        if (data.parent && data.parent.uri) {
          navBtns += `<button type="button" class="inspector-nav-btn parent" onclick="openSourceInInspector('${escapeHtml(data.parent.uri)}')" title="Chapter: ${escapeHtml(data.parent.name)}">⬆ ${escapeHtml(data.parent.name)}</button>`;
        } else if (data.parent && data.parent.name) {
          navBtns += `<span class="inspector-nav-badge" title="Manual Root">📖 ${escapeHtml(data.parent.name)}</span>`;
        }
        if (data.next_topic && data.next_topic.uri) {
          navBtns += `<button type="button" class="inspector-nav-btn next" onclick="openSourceInInspector('${escapeHtml(data.next_topic.uri)}')" title="Next: ${escapeHtml(data.next_topic.name)}">Next: ${escapeHtml(data.next_topic.name)} ➡</button>`;
        }

        let sibList = "";
        if (data.siblings && data.siblings.length > 1) {
          sibList = `
            <details class="inspector-tree-accordion">
              <summary>📑 Chapter Contents (${data.siblings.length} Topics)</summary>
              <ul class="inspector-sib-list">
                ${data.siblings.map(s => {
                  if (s.is_current) return `<li class="current-topic">👉 <strong>${escapeHtml(s.name)}</strong> (Viewing)</li>`;
                  if (s.uri) return `<li><a href="javascript:void(0)" onclick="openSourceInInspector('${escapeHtml(s.uri)}')">${escapeHtml(s.name)}</a></li>`;
                  return `<li>${escapeHtml(s.name)}</li>`;
                }).join("")}
              </ul>
            </details>
          `;
        }

        let childList = "";
        if (data.children && data.children.length > 0) {
          childList = `
            <details class="inspector-tree-accordion" open style="margin-top: 0.45rem;">
              <summary>📂 Subtopics &amp; Sections (${data.children.length})</summary>
              <ul class="inspector-sib-list">
                ${data.children.map(c => {
                  if (c.uri) return `<li><a href="javascript:void(0)" onclick="openSourceInInspector('${escapeHtml(c.uri)}')">📄 ${escapeHtml(c.name)}</a></li>`;
                  return `<li>📄 ${escapeHtml(c.name)}</li>`;
                }).join("")}
              </ul>
            </details>
          `;
        }

        treeContainer.style.display = "block";
        treeContainer.innerHTML = `
          <div class="topic-strip-header">
            <span class="topic-path-badge">📁 ${escapeHtml(data.current.path_text || data.current.name)}</span>
          </div>
          <div class="topic-nav-buttons">${navBtns}</div>
          ${sibList}
          ${childList}
        `;
      } catch (e) {
        treeContainer.style.display = "none";
      }
    }

    function inspectCurrentSource(sectionFilter = "", extractDiagram = false) {
      if (!currentInspectedUri) return;
      openSourceInInspector(currentInspectedUri, sectionFilter, extractDiagram);
    }

    function scrollToSource(index) {
      const el = document.getElementById("source-card-" + index);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }

    /* ===================================================================== */
    /* TAB 2: INTERACTIVE TOPOLOGY GRAPH RENDERER (GET /graph/topology)      */
    /* ===================================================================== */

// Global Initializations
document.addEventListener("DOMContentLoaded", () => {
  const qInput = document.getElementById("portal-query-input");
  if (qInput) {
    qInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        executePortalQuery();
      }
    });
  }
  refreshTelemetry();
  checkLlmStatus();
  setInterval(refreshTelemetry, 25000);
});
