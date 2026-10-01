/**
 * Aegis Sovereign Web Portal - Ed25519 Cryptographic License & AI Harnesses
 */
async function loadLicenseStatus() {
      try {
        const resp = await fetch("/license");
        const data = await resp.json();
        renderLicenseCard(data);
      } catch (e) {
        console.error("Failed to load license status:", e);
      }
    }

    function renderLicenseCard(data) {
      document.getElementById("tel-license-tier").textContent = `${data.tier || 'ENTERPRISE'} (Ed25519)`;
      document.getElementById("lic-card-badge").textContent =
        data.signature_verified ? `✓ Ed25519 VERIFIED (${data.tier})` : "UNVERIFIED";

      document.getElementById("lic-summary-box").innerHTML = `
        <div><strong>Active Plan Tier:</strong> <span style="color: var(--gold-bright); font-weight: 800;">${escapeHtml(data.tier)}</span> | <strong>Customer ID:</strong> <code>${escapeHtml(data.customer_id)}</code></div>
        <div><strong>Organization:</strong> ${escapeHtml(data.organization)}</div>
        <div><strong>Algorithm:</strong> <code>${escapeHtml(data.algorithm)}</code> | <strong>Public Key Fingerprint:</strong> <code>${escapeHtml(data.public_key_fingerprint)}</code></div>
        <div><strong>Hardware Fingerprint:</strong> <code>${escapeHtml(data.hardware_fingerprint)}</code> | <strong>Expires:</strong> ${escapeHtml(data.expires_at)}</div>
      `;

      const feats = data.unlocked_features || [];
      document.getElementById("lic-features-list").innerHTML = feats.map(f =>
        `<span class="preset-chip" style="border-color: var(--border-emerald); color: #A7F3D0;">✓ ${escapeHtml(f)}</span>`
      ).join("");

      document.getElementById("lic-token-textarea").value = data.license_token || "";
      cachedHarnesses = data.ai_harnesses || {};
      selectHarnessTab(currentHarnessKey);
    }

    async function provisionTierLicense(tierStr) {
      try {
        const resp = await fetch("/license/attach", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tier: tierStr,
            organization: "Enterprise Hub Homelab (Dell Latitude 7390)",
            customer_id: `LIC-AEGIS-${tierStr.toUpperCase()}-2026`
          })
        });
        const data = await resp.json();
        renderLicenseCard(data);
        refreshTelemetry();
        showPortalToast(`🔐 <strong>Ed25519 Cryptographic License Signed &amp; Attached:</strong> Tier updated to <strong>${escapeHtml(data.tier)}</strong> (${escapeHtml(data.public_key_fingerprint)}).`);
      } catch (e) {
        showPortalToast(`⚠️ License attach failed: ${escapeHtml(e)}`);
      }
    }

    async function attachCustomLicenseToken() {
      const tok = document.getElementById("lic-token-textarea").value.trim();
      if (!tok) return;
      try {
        const resp = await fetch("/license/attach", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ license_token: tok })
        });
        const data = await resp.json();
        if (!resp.ok) {
          showPortalToast(`⚠️ <strong>Signature Verification Failed:</strong> ${escapeHtml(data.error)}`);
          return;
        }
        renderLicenseCard(data);
        refreshTelemetry();
        showPortalToast(`🔐 <strong>Verified Ed25519 Token Attached:</strong> Active tier is now <strong>${escapeHtml(data.tier)}</strong>.`);
      } catch (e) {
        showPortalToast(`⚠️ Error verifying token: ${escapeHtml(e)}`);
      }
    }

    function selectHarnessTab(hKey) {
      currentHarnessKey = hKey;
      const hObj = cachedHarnesses[hKey];
      if (!hObj) return;
      document.getElementById("harness-meta-box").innerHTML = `
        <strong>Harness:</strong> ${escapeHtml(hObj.name)} (<span style="color: var(--gold-bright);">${escapeHtml(hObj.badge)}</span>) •
        <strong>Config Path:</strong> <code>${escapeHtml(hObj.config_path)}</code>
      `;
      document.getElementById("harness-snippet-pre").textContent = hObj.snippet || "";
    }

    async function checkLlmStatus() {
      const textEl = document.getElementById("llm-status-text");
      const btnEl = document.getElementById("btn-llm-toggle");
      if (!textEl || !btnEl) return;
      try {
        const res = await fetch("/llm/status");
        if (!res.ok) return;
        const data = await res.json();
        const isRunning = data.status === "running" && data.healthy;
        if (isRunning) {
          textEl.textContent = `Online (${data.current_model || "qwen2.5:1.5b"})`;
          textEl.style.color = "var(--emerald-bright)";
          btnEl.textContent = "Spin Down";
          btnEl.className = "action-btn danger-btn";
        } else if (data.status === "running" && !data.healthy) {
          textEl.textContent = "Starting up...";
          textEl.style.color = "var(--gold-bright)";
          btnEl.textContent = "Wait";
          btnEl.className = "action-btn";
        } else {
          textEl.textContent = "Standby (0 CPU/RAM)";
          textEl.style.color = "#94A3B8";
          btnEl.textContent = "Spin Up";
          btnEl.className = "action-btn primary-emerald";
        }
      } catch (e) {
        console.debug("LLM status check skipped:", e);
      }
    }

    async function toggleLlmPower() {
      const btnEl = document.getElementById("btn-llm-toggle");
      if (!btnEl) return;
      const isOnline = btnEl.textContent === "Spin Down";
      const action = isOnline ? "stop" : "start";
      btnEl.disabled = true;
      btnEl.textContent = isOnline ? "Stopping..." : "Spinning up...";
      showPortalToast(`🧠 Nomad API: Scaling local Ollama job (${action})...`);
      try {
        const res = await fetch("/llm/control", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: action })
        });
        const data = await res.json();
        showPortalToast(data.message || `Ollama is now ${data.status}`);
        setTimeout(checkLlmStatus, 1500);
      } catch (err) {
        showPortalToast(`Failed to control LLM: ${err}`);
      } finally {
        btnEl.disabled = false;
      }
    }

    function copyHarnessSnippet() {
      const txt = document.getElementById("harness-snippet-pre").textContent;
      if (navigator.clipboard) {
        navigator.clipboard.writeText(txt);
      }
      showPortalToast(`📋 Copied <strong>${escapeHtml(currentHarnessKey)}</strong> MCP configuration snippet to clipboard!`);
    }

    window.addEventListener("DOMContentLoaded", () => {
      updateLiveRoutePrediction(document.getElementById("portal-query-input").value);
      refreshTelemetry();
      checkLlmStatus();
      setInterval(checkLlmStatus, 10000);
    });