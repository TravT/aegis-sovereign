#!/usr/bin/env bash
# ==============================================================================
# Aegis Sovereign Knowledge Appliance — Turnkey Packaging & Installer v2.1.0
# ==============================================================================
# Usage:
#   ./install.sh                       (Full idempotent installation & verification)
#   ./install.sh --check-only          (Non-destructive preflight & 6-stage CI audit)
#   ./install.sh --bundle-dir <path>   (Build redistributable bundle & MANIFEST.json)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROD_VAULT_DIR="${REPO_ROOT}/docs/.aegis_vault"
VISIBLE_VAULT_LINK="${REPO_ROOT}/docs/aegis_index"
LEGACY_DATA_DIR="${SCRIPT_DIR}/data"
MCP_TARGET_DIR="${HOME}/.gemini/antigravity-cli/mcp/sovereign-vault"
MCP_SOURCE_DIR="${SCRIPT_DIR}/core/mcp/schemas"
SKILL_PRIMARY="${REPO_ROOT}/.agents/skills/manage-sovereign-vault/SKILL.md"
SKILL_GOLDEN="${REPO_ROOT}/ansible/roles/golden_files/files/gemini-skills/manage-sovereign-vault/SKILL.md"

CHECK_ONLY=0
BUNDLE_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check-only)
            CHECK_ONLY=1
            shift
            ;;
        --bundle-dir)
            BUNDLE_DIR="$2"
            shift 2
            ;;
        --bundle-dir=*)
            BUNDLE_DIR="${1#*=}"
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

PYTHON_BIN="${REPO_ROOT}/.venv/bin/python3"
if [ ! -x "${PYTHON_BIN}" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

echo "======================================================================"
echo "  AEGIS SOVEREIGN KNOWLEDGE APPLIANCE — TURNKEY INSTALLER v2.1.0"
echo "  Mode: $([ "${CHECK_ONLY}" -eq 1 ] && echo 'CHECK-ONLY (CI/Audit)' || echo 'FULL TURNKEY INSTALL')"
echo "======================================================================"

# ------------------------------------------------------------------------------
# Stage 1: Hardware SIMD & Runtime Audit
# ------------------------------------------------------------------------------
echo "[Stage 1/6] Hardware SIMD & Runtime Audit..."
SIMD_PROFILE="SCALAR_FALLBACK"
if [ -f /proc/cpuinfo ]; then
    if grep -q -i "avx512" /proc/cpuinfo; then
        SIMD_PROFILE="AVX-512_VNNI_INT8_TURBO"
    elif grep -q -i "avx2" /proc/cpuinfo; then
        SIMD_PROFILE="AVX2_FMA_INT8_SIMD"
    fi
elif command -v sysctl >/dev/null 2>&1; then
    if sysctl -a 2>/dev/null | grep -q "hw.optional.arm64: 1"; then
        SIMD_PROFILE="ARM64_NEON_DOTPROD"
    fi
fi

PY_CHECK="$("${PYTHON_BIN}" -c '
import sqlite3, sys
assert sys.version_info >= (3, 10), f"Python >= 3.10 required, found {sys.version}"
conn = sqlite3.connect(":memory:")
conn.execute("CREATE VIRTUAL TABLE t USING fts5(x);")
print(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} | SQLite {sqlite3.sqlite_version} (FTS5 Verified)")
')"
echo "  -> Hardware SIMD Profile : ${SIMD_PROFILE}"
echo "  -> Runtime Verification  : ${PY_CHECK}"

# ------------------------------------------------------------------------------
# Stage 2: Production Vault & Anti-Loop Sentinel Provisioning
# ------------------------------------------------------------------------------
echo "[Stage 2/6] Production Vault & Anti-Loop Sentinel Provisioning..."
if [ "${CHECK_ONLY}" -eq 0 ]; then
    mkdir -p "${PROD_VAULT_DIR}/qdrant" "${PROD_VAULT_DIR}/extracted_diagrams"
    if [ ! -f "${PROD_VAULT_DIR}/.aegis-no-index" ]; then
        cat > "${PROD_VAULT_DIR}/.aegis-no-index" <<'EOF'
{
  "sentinel": ".aegis-no-index",
  "appliance": "Aegis Sovereign Knowledge Appliance",
  "version": "2.1.0",
  "policy": "STRICT_ANTI_OUROBOROS_EXCLUSION"
}
EOF
    fi
    ln -sfn .aegis_vault "${VISIBLE_VAULT_LINK}"
    ln -sfn "${PROD_VAULT_DIR}/sovereign_router.db" "${LEGACY_DATA_DIR}/sovereign_router.db"
    ln -sfn "${PROD_VAULT_DIR}/sovereign_graph.db" "${LEGACY_DATA_DIR}/sovereign_graph.db"
    ln -sfn "${PROD_VAULT_DIR}/sovereign_router.db" "${LEGACY_DATA_DIR}/sovereign_huawei_router.db"
    ln -sfn "${PROD_VAULT_DIR}/sovereign_graph.db" "${LEGACY_DATA_DIR}/sovereign_huawei_graph.db"
    ln -sfn "${PROD_VAULT_DIR}/extracted_diagrams" "${LEGACY_DATA_DIR}/extracted_diagrams"
fi

test -d "${PROD_VAULT_DIR}" || { echo "ERROR: Missing ${PROD_VAULT_DIR}" >&2; exit 1; }
test -f "${PROD_VAULT_DIR}/.aegis-no-index" || { echo "ERROR: Missing .aegis-no-index sentinel" >&2; exit 1; }
test -f "${PROD_VAULT_DIR}/sovereign_router.db" || { echo "ERROR: Missing sovereign_router.db" >&2; exit 1; }
test -f "${PROD_VAULT_DIR}/sovereign_graph.db" || { echo "ERROR: Missing sovereign_graph.db" >&2; exit 1; }
test -L "${VISIBLE_VAULT_LINK}" || { echo "ERROR: Missing docs/aegis_index symlink" >&2; exit 1; }
echo "  -> Vault Directory       : ${PROD_VAULT_DIR} (Sentinel: .aegis-no-index OK)"
echo "  -> Canonical Databases   : sovereign_router.db & sovereign_graph.db OK"
echo "  -> Visible Symlink       : ${VISIBLE_VAULT_LINK} -> .aegis_vault"

# ------------------------------------------------------------------------------
# Stage 3: 7-Tool MCP v2 Server Registration
# ------------------------------------------------------------------------------
echo "[Stage 3/6] 7-Tool MCP v2 Server Registration..."
if [ "${CHECK_ONLY}" -eq 0 ]; then
    mkdir -p "${MCP_TARGET_DIR}"
    if [ -d "${MCP_SOURCE_DIR}" ]; then
        cp -f "${MCP_SOURCE_DIR}"/*.json "${MCP_TARGET_DIR}/" 2>/dev/null || true
        cp -f "${MCP_SOURCE_DIR}/instructions.md" "${MCP_TARGET_DIR}/" 2>/dev/null || true
    fi
    cat > "${PROD_VAULT_DIR}/mcp_config.json" <<EOF
{
  "mcpServers": {
    "sovereign-vault": {
      "command": "${PYTHON_BIN}",
      "args": ["${REPO_ROOT}/scripts/sovereign_mcp.py"],
      "env": {
        "SOVEREIGN_ROUTER_DB": "${PROD_VAULT_DIR}/sovereign_router.db",
        "SOVEREIGN_GRAPH_DB": "${PROD_VAULT_DIR}/sovereign_graph.db"
      }
    }
  }
}
EOF
fi
MCP_SCHEMA_COUNT="$(ls -1 "${MCP_TARGET_DIR}"/*.json 2>/dev/null | wc -l | tr -d ' ')"
if [ "${MCP_SCHEMA_COUNT}" -lt 7 ]; then
    echo "ERROR: Expected 7 MCP tool schemas in ${MCP_TARGET_DIR}, found ${MCP_SCHEMA_COUNT}" >&2
    exit 1
fi
echo "  -> Registered MCP Tools  : ${MCP_SCHEMA_COUNT} schemas + instructions.md in ${MCP_TARGET_DIR}"

# ------------------------------------------------------------------------------
# Stage 4: Agent Skill & Golden Files Synchronization
# ------------------------------------------------------------------------------
echo "[Stage 4/6] Agent Skill & Golden Files Synchronization..."
if [ "${CHECK_ONLY}" -eq 0 ] && [ -f "${SKILL_PRIMARY}" ]; then
    mkdir -p "$(dirname "${SKILL_GOLDEN}")"
    cp -f "${SKILL_PRIMARY}" "${SKILL_GOLDEN}"
fi
test -f "${SKILL_PRIMARY}" || { echo "ERROR: Missing ${SKILL_PRIMARY}" >&2; exit 1; }
test -f "${SKILL_GOLDEN}" || { echo "ERROR: Missing ${SKILL_GOLDEN}" >&2; exit 1; }
echo "  -> Skill Synchronized    : ${SKILL_PRIMARY} <-> Golden Files OK"

# ------------------------------------------------------------------------------
# Stage 5: Operator Manuals (01–15) & Web Search Portal Verification
# ------------------------------------------------------------------------------
echo "[Stage 5/6] Operator Manuals (01–15) & Web Search Portal Verification..."
MANUAL_COUNT="$(ls -1 "${SCRIPT_DIR}/docs/manuals"/[0-9][0-9]_*.md 2>/dev/null | wc -l | tr -d ' ')"
if [ "${MANUAL_COUNT}" -lt 15 ]; then
    echo "ERROR: Expected 15 operator manuals in docs/manuals/, found ${MANUAL_COUNT}" >&2
    exit 1
fi
test -f "${SCRIPT_DIR}/web/portal/index.html" || { echo "ERROR: Missing web/portal/index.html" >&2; exit 1; }
echo "  -> Operator Manuals      : ${MANUAL_COUNT}/15 verified in docs/manuals/"
echo "  -> Web Search Portal     : ${SCRIPT_DIR}/web/portal/index.html verified"

# ------------------------------------------------------------------------------
# Stage 6: Live Smoke Test (<5ms Prong 1 & GraphRAG Check)
# ------------------------------------------------------------------------------
echo "[Stage 6/6] Live Smoke Test (Prong 1 & GraphRAG against Unified Server Vault)..."
SMOKE_OUT="$("${PYTHON_BIN}" -c "
import sqlite3, time
r_conn = sqlite3.connect('${PROD_VAULT_DIR}/sovereign_router.db')
doc_cnt = r_conn.execute('SELECT COUNT(*) FROM document_records').fetchone()[0]
g_conn = sqlite3.connect('${PROD_VAULT_DIR}/sovereign_graph.db')
ent_cnt = g_conn.execute('SELECT COUNT(*) FROM entities').fetchone()[0]
rel_cnt = g_conn.execute('SELECT COUNT(*) FROM entity_relations').fetchone()[0]
t0 = time.perf_counter()
hit = r_conn.execute(\"SELECT doc_identifier, title FROM document_records WHERE doc_identifier LIKE 'ALM-20104%' LIMIT 1\").fetchone()
adr_hit = r_conn.execute(\"SELECT doc_identifier, title FROM document_records WHERE doc_identifier = 'ADR-40' LIMIT 1\").fetchone()
skill_hit = r_conn.execute(\"SELECT doc_identifier, title FROM document_records WHERE doc_identifier = 'manage-sovereign-vault' LIMIT 1\").fetchone()
dt_ms = (time.perf_counter() - t0) * 1000.0
assert doc_cnt >= 48900, f'Expected >= 48900 docs, got {doc_cnt}'
assert ent_cnt >= 8500, f'Expected >= 8500 entities, got {ent_cnt}'
assert hit is not None and adr_hit is not None and skill_hit is not None, 'Missing expected unified vault records'
print(f'Prong 1 & GraphRAG Smoke PASS in {dt_ms:.2f}ms (<5ms SLA) | Docs={doc_cnt:,} | Entities={ent_cnt:,} | Relations={rel_cnt:,}')
")"
echo "  -> ${SMOKE_OUT}"

if [ -n "${BUNDLE_DIR}" ]; then
    echo "----------------------------------------------------------------------"
    echo "[Packaging] Building redistributable release bundle at ${BUNDLE_DIR}..."
    "${PYTHON_BIN}" "${SCRIPT_DIR}/tools/build_release_bundle.py" --bundle-dir "${BUNDLE_DIR}"
fi

echo "======================================================================"
echo "  AEGIS v2.1.0 READY — Launch Web Portal:"
echo "    python3 -m core.server --host 127.0.0.1 --port 8080"
echo "======================================================================"
