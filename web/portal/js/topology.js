/**
 * Aegis Sovereign Web Portal - Interactive Knowledge Graph Topology Engine
 */
function zoomGraph(factor) {
      currentGraphScale = Math.min(2.2, Math.max(0.6, currentGraphScale * factor));
      const g = document.getElementById("topology-zoom-group");
      if (g) {
        g.setAttribute("transform", `translate(460, 290) scale(${currentGraphScale}) translate(-460, -290)`);
      }
    }

    function resetGraphZoom() {
      currentGraphScale = 1.0;
      const g = document.getElementById("topology-zoom-group");
      if (g) {
        g.setAttribute("transform", "translate(0, 0) scale(1)");
      }
    }

    async function loadGraphTopology(filterTerm = "") {
      try {
        const url = filterTerm
          ? `/graph/topology?filter=${encodeURIComponent(filterTerm)}`
          : "/graph/topology";
        const resp = await fetch(url);
        const data = await resp.json();
        cachedTopology = data;
        renderRadialTopologySvg(data);
        if (data.nodes && data.nodes.length) {
          selectGraphNode(data.nodes[0].id);
        }
      } catch (e) {
        console.error("Failed to load topology:", e);
      }
    }

    function renderRadialTopologySvg(data) {
      const svg = document.getElementById("topology-svg");
      const nodes = data.nodes || [];
      const edges = data.edges || [];
      const cx = 460;
      const cy = 290;
      const ringRadii = { 0: 0, 1: 118, 2: 208, 3: 268 };

      const byRing = { 0: [], 1: [], 2: [], 3: [] };
      nodes.forEach(n => {
        const r = n.ring !== undefined ? n.ring : 2;
        (byRing[r] = byRing[r] || []).push(n);
      });

      const coords = {};
      Object.keys(byRing).forEach(rk => {
        const list = byRing[rk];
        const radius = ringRadii[rk] || 200;
        list.forEach((n, idx) => {
          if (Number(rk) === 0 && list.length === 1) {
            coords[n.id] = { x: cx, y: cy, node: n };
          } else {
            const angle = (2 * Math.PI * idx) / Math.max(1, list.length) - Math.PI / 2;
            coords[n.id] = {
              x: Math.round(cx + radius * Math.cos(angle)),
              y: Math.round(cy + radius * Math.sin(angle)),
              node: n
            };
          }
        });
      });

      let html = `<g id="topology-zoom-group">`;
      // Ambient radial guide rings
      [118, 208, 268].forEach(rad => {
        html += `<circle cx="${cx}" cy="${cy}" r="${rad}" fill="none" stroke="rgba(148, 163, 184, 0.14)" stroke-dasharray="4 6" stroke-width="1" />`;
      });

      // Curved Cubic-Bezier Directed Edges with Animated Data Flow
      edges.forEach(e => {
        const s = coords[e.source];
        const t = coords[e.target];
        if (!s || !t) return;
        const mx = (s.x + t.x) / 2 + (cy - (s.y + t.y) / 2) * 0.14;
        const my = (s.y + t.y) / 2 + ((s.x + t.x) / 2 - cx) * 0.14;
        const dPath = `M ${s.x} ${s.y} Q ${mx} ${my} ${t.x} ${t.y}`;
        html += `
          <path d="${dPath}" fill="none" stroke="rgba(148, 163, 184, 0.24)" stroke-width="1.5" />
          <path d="${dPath}" fill="none" stroke="rgba(212, 175, 55, 0.55)" stroke-width="1.3" class="animated-edge" />
        `;
      });

      // Multi-Halo Glowing Nodes
      Object.values(coords).forEach(({ x, y, node }) => {
        const col = node.color || "#D4AF37";
        const rSize = node.ring === 0 ? 19 : (node.ring === 1 ? 13.5 : 10.5);
        const shortLabel = (node.label || node.id).slice(0, 26);
        const safeId = escapeHtml(node.id);
        html += `
          <g style="cursor: pointer;" onclick="selectGraphNode('${safeId}')">
            <circle cx="${x}" cy="${y}" r="${rSize + 8}" fill="${col}" fill-opacity="0.1" />
            <circle cx="${x}" cy="${y}" r="${rSize + 3.5}" fill="${col}" fill-opacity="0.22" />
            <circle cx="${x}" cy="${y}" r="${rSize}" fill="${col}" stroke="#05070B" stroke-width="2.2" />
            <text x="${x}" y="${y + rSize + 15}" text-anchor="middle"
                  fill="#F8FAFC" font-size="10.5" font-family="JetBrains Mono, monospace" font-weight="700">
              ${escapeHtml(shortLabel)}
            </text>
          </g>
        `;
      });

      html += `</g>`;
      svg.innerHTML = html;
    }

    function selectGraphNode(nodeId) {
      if (!cachedTopology) return;
      const node = (cachedTopology.nodes || []).find(n => n.id === nodeId);
      if (!node) return;

      document.getElementById("graph-node-category").textContent = node.category || "entity";
      const connectedEdges = (cachedTopology.edges || []).filter(
        e => e.source === nodeId || e.target === nodeId
      );

      const relListHtml = connectedEdges.map(e => {
        const isOut = e.source === nodeId;
        const peer = isOut ? e.target : e.source;
        const dirArrow = isOut ? "→" : "←";
        return `
          <div style="padding: 0.45rem 0.65rem; background: rgba(5, 7, 11, 0.85); border: 1px solid var(--border-subtle); border-radius: 7px; margin-bottom: 0.42rem; font-family: var(--font-mono); font-size: 0.75rem;">
            <span style="color: var(--gold-bright);">${escapeHtml(e.relation)}</span> ${dirArrow}
            <a href="javascript:void(0)" style="color: var(--cyan-bright); text-decoration: none; font-weight: 600;" onclick="selectGraphNode('${escapeHtml(peer)}')">${escapeHtml(peer)}</a>
          </div>
        `;
      }).join("");

      const presetQuery = node.query_preset || node.id;
      document.getElementById("graph-node-details").innerHTML = `
        <div style="margin-bottom: 0.9rem;">
          <div style="font-size: 1.06rem; font-weight: 800; color: ${escapeHtml(node.color || '#D4AF37')}; margin-bottom: 0.3rem;">
            ${escapeHtml(node.label || node.id)}
          </div>
          <p style="font-size: 0.85rem; color: var(--text-secondary);">
            ${escapeHtml(node.description || "")}
          </p>
        </div>
        <div style="margin-bottom: 0.95rem;">
          <button type="button" class="action-btn primary-emerald" style="width: 100%; justify-content: center;"
                  onclick="runPreset('${escapeHtml(presetQuery)}')">
            🔍 Run Prong 1/2 Search on Node (${escapeHtml(presetQuery.slice(0, 28))})
          </button>
        </div>
        <div class="sec-block-title">🔗 Connected Server &amp; Corpus Edges (${connectedEdges.length})</div>
        <div style="max-height: 310px; overflow-y: auto; margin-top: 0.45rem;">
          ${relListHtml || '<div style="color: var(--text-muted); font-size: 0.8rem;">No direct edges in current filter view.</div>'}
        </div>
      `;
    }

    /* ===================================================================== */
    /* TAB 3: MONITORED DIRECTORIES & 1-CLICK DB PURGE MANAGER               */
    /* ===================================================================== */