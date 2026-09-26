#!/usr/bin/env bash
# ==============================================================================
# Aegis Sovereign Desktop Edition — Workstation Service Installer (ADR-37)
# Installs and enables the zero-copy workstation background daemon
# for macOS (launchd) or Linux (systemd user service). No root/sudo required.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OS_TYPE="$(uname -s)"

echo "----------------------------------------------------------------------"
echo "  Aegis Sovereign Desktop — Service Installer (ADR-37)"
echo "  Target OS: ${OS_TYPE}"
echo "----------------------------------------------------------------------"

# Detect Python interpreter
PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
    echo "[-] Error: python3 not found in PATH." >&2
    exit 1
fi

echo "[+] Using Python interpreter: ${PYTHON_BIN}"

if [[ "${OS_TYPE}" == "Darwin" ]]; then
    TARGET_DIR="${HOME}/Library/LaunchAgents"
    PLIST_DEST="${TARGET_DIR}/com.aegis.sovereign.workstation.plist"

    mkdir -p "${TARGET_DIR}"
    mkdir -p "${HOME}/.cache/sovereign/logs"

    echo "[+] Installing macOS launchd Agent to ${PLIST_DEST}..."
    sed -e "s|@PYTHON_BIN@|${PYTHON_BIN}|g" \
        -e "s|@APP_ROOT@|${APP_ROOT}|g" \
        -e "s|/usr/bin/python3|${PYTHON_BIN}|g" \
        "${SCRIPT_DIR}/aegis-workstation.plist" > "${PLIST_DEST}"

    # Unload previous instance if active
    launchctl unload "${PLIST_DEST}" 2>/dev/null || true

    echo "[+] Loading launchd Agent..."
    launchctl load -w "${PLIST_DEST}"

    echo "[✓] Aegis Sovereign Desktop daemon loaded via launchctl."
    echo "[i] Logs available at: /tmp/aegis-workstation.log"

elif [[ "${OS_TYPE}" == "Linux" ]]; then
    TARGET_DIR="${HOME}/.config/systemd/user"
    SERVICE_DEST="${TARGET_DIR}/aegis-workstation.service"

    mkdir -p "${TARGET_DIR}"
    mkdir -p "${HOME}/.cache/sovereign/logs"

    echo "[+] Installing Linux systemd user service to ${SERVICE_DEST}..."
    sed -e "s|@PYTHON_BIN@|${PYTHON_BIN}|g" \
        -e "s|@APP_ROOT@|${APP_ROOT}|g" \
        -e "s|/usr/bin/python3|${PYTHON_BIN}|g" \
        "${SCRIPT_DIR}/aegis-workstation.service" > "${SERVICE_DEST}"

    echo "[+] Reloading systemd user daemon..."
    systemctl --user daemon-reload

    echo "[+] Enabling and starting aegis-workstation.service..."
    systemctl --user enable aegis-workstation.service
    systemctl --user restart aegis-workstation.service

    echo "[✓] Aegis Sovereign Desktop daemon started via systemd user service."
    echo "[i] Check status: systemctl --user status aegis-workstation.service"

else
    echo "[-] Unsupported operating system: ${OS_TYPE}" >&2
    echo "    For Windows, please run install_service.ps1 in PowerShell." >&2
    exit 1
fi

echo "----------------------------------------------------------------------"
echo "[✓] Installation complete! Health check available at: http://127.0.0.1:9876/health"
echo "----------------------------------------------------------------------"
