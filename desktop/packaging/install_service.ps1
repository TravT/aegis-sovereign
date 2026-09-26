<#
.SYNOPSIS
    Aegis Sovereign Desktop Edition — Windows Service & Startup Installer (ADR-37).
.DESCRIPTION
    Installs and registers the background workstation daemon on Windows.
    Runs under the current unprivileged user account (Zero Admin / DLP Safe).
#>

[CmdletBinding()]
param (
    [string]$Port = "9876",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  Aegis Sovereign Desktop — Windows Workstation Installer (ADR-37)" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Locate Python Interpreter
$PythonPath = $null
$Candidates = @("pythonw.exe", "python.exe")
foreach ($cmd in $Candidates) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $PythonPath = $found.Source
        break
    }
}

if (-not $PythonPath) {
    Write-Error "Python interpreter (pythonw.exe / python.exe) was not found in PATH. Please install Python 3.10+."
    exit 1
}

Write-Host "[+] Detected Python runtime: $PythonPath" -ForegroundColor Green

# 2. Prepare Storage Directory
$StorageDir = "$env:LOCALAPPDATA\Sovereign"
$LogsDir = "$StorageDir\logs"
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
    Write-Host "[+] Created dedicated cache directory: $StorageDir" -ForegroundColor Green
}

# 3. Resolve Project Root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppRoot = Resolve-Path "$ScriptDir\..\.."
Write-Host "[+] Aegis Appliance Root: $AppRoot" -ForegroundColor Green

# 4. Register Scheduled Task for Current User at Logon
$TaskName = "AegisSovereignWorkstation"
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument "-m desktop.daemon.daemon --port $Port" -WorkingDirectory $AppRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0

try {
    # Unregister existing task if present
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Aegis Sovereign Desktop In-Place Workstation Daemon (ADR-37)" | Out-Null
    Write-Host "[✓] Successfully registered Windows Scheduled Task '$TaskName' (Runs at user logon)." -ForegroundColor Green
    
    # Start task immediately
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "[+] Started background task '$TaskName'." -ForegroundColor Green
}
catch {
    Write-Warning "Could not register Scheduled Task. Falling back to Startup folder launcher..."
    $StartupFolder = [Environment]::GetFolderPath("Startup")
    $CmdPath = Join-Path $StartupFolder "AegisSovereignDesktop.cmd"
    $CmdContent = "@echo off`r`nstart `"`" `"$PythonPath`" -m desktop.daemon.daemon --port $Port`r`n"
    Set-Content -Path $CmdPath -Value $CmdContent -Encoding ASCII
    Write-Host "[✓] Created startup launcher: $CmdPath" -ForegroundColor Green
}

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "[✓] Windows Workstation installation complete!" -ForegroundColor Green
Write-Host "    Loopback HUD: http://127.0.0.1:$Port/" -ForegroundColor White
Write-Host "    Health check: http://127.0.0.1:$Port/health" -ForegroundColor White
Write-Host "======================================================================" -ForegroundColor Cyan
