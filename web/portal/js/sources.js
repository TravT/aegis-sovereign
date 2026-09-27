/**
 * Aegis Sovereign Web Portal - Monitored Directories & Purge Manager
 */
async function loadMonitoredSources() {
      try {
        const resp = await fetch("/sources");
        const data = await resp.json();
        const tbody = document.getElementById("monitored-sources-tbody");
        const sources = data.sources || [];
        if (!sources.length) {
          tbody.innerHTML = `<tr><td colspan="5">No monitored directories configured.</td></tr>`;
          return;
        }
        const maxRecs = Math.max(1, ...sources.map(s => Number(s.indexed_records || 0)));
        tbody.innerHTML = sources.map(s => {
          const p = escapeHtml(s.path);
          const count = Number(s.indexed_records || 0);
          const pct = Math.min(100, Math.max(6, Math.round((count / maxRecs) * 100)));
          return `
            <tr>
              <td style="font-family: var(--font-mono); font-size: 0.8rem; color: var(--text-primary);">${p}</td>
              <td><span class="metric-tag">${escapeHtml(s.domain)}</span></td>
              <td style="font-family: var(--font-mono); font-weight: 700; color: var(--emerald-bright);">
                <div>${count.toLocaleString()} records</div>
                <div class="record-progress-track"><div class="record-progress-fill" style="width: ${pct}%;"></div></div>
              </td>
              <td>
                <span class="metric-tag" style="color: var(--gold-bright); border-color: rgba(212, 175, 55, 0.35);">
                  🛡️ ${escapeHtml(s.anti_loop_guard)}
                </span>
              </td>
              <td>
                <div style="display: flex; gap: 0.45rem; flex-wrap: wrap;">
                  <button type="button" class="action-btn primary-emerald" onclick="resyncSource('${p}', '${escapeHtml(s.domain)}')">
                    🔄 Re-Sync
                  </button>
                  <button type="button" class="action-btn danger-btn" onclick="purgeSourceFromDb('${p}')">
                    🗑️ Purge Data from DB
                  </button>
                </div>
              </td>
            </tr>
          `;
        }).join("");
      } catch (e) {
        console.error("Failed to load sources:", e);
      }
    }

    async function addMonitoredSource() {
      const pathVal = document.getElementById("new-source-path").value.trim();
      const domainVal = document.getElementById("new-source-domain").value.trim() || "Custom Server Corpus";
      if (!pathVal) return;
      await resyncSource(pathVal, domainVal);
      document.getElementById("new-source-path").value = "";
    }

    async function resyncSource(pathStr, domainStr) {
      try {
        const resp = await fetch("/sources/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: pathStr, domain: domainStr, ingest_now: true })
        });
        const data = await resp.json();
        if (!resp.ok) {
          showPortalToast(`⚠️ <strong>Blocked:</strong> ${escapeHtml(data.error || 'Could not index directory')}`);
          return;
        }
        showPortalToast(
          `✅ <strong>Synced Server Directory:</strong> <code>${escapeHtml(data.path)}</code> • Ingested <strong>${data.ingested_records}</strong> router records &amp; <strong>${data.ingested_graph_documents || 0}</strong> graph nodes.`
        );
        loadMonitoredSources();
        refreshTelemetry();
      } catch (e) {
        showPortalToast(`⚠️ Error syncing source: ${escapeHtml(e)}`);
      }
    }

    async function purgeSourceFromDb(pathStr) {
      try {
        const resp = await fetch("/sources/remove", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: pathStr })
        });
        const data = await resp.json();
        showPortalToast(
          `🗑️ <strong>Purged Source from Sovereign DB:</strong> <code>${escapeHtml(data.path)}</code> • Removed <strong>${data.deleted_router_records}</strong> B-Tree records, <strong>${data.deleted_fts_tokens}</strong> FTS5 tokens, and <strong>${data.deleted_graph_edges}</strong> GraphStore edges.`
        );
        loadMonitoredSources();
        refreshTelemetry();
      } catch (e) {
        showPortalToast(`⚠️ Error purging source: ${escapeHtml(e)}`);
      }
    }

    /* ===================================================================== */
    /* TAB 4: PLATFORM LICENSE & AI HARNESS INTEGRATIONS                     */
    /* ===================================================================== */