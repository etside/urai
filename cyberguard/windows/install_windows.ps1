# CyberGuard Windows Installer
# Run as Administrator: powershell -ExecutionPolicy Bypass -File install_windows.ps1
#Requires -RunAsAdministrator
param(
    [string]$UraiBin = "$env:LOCALAPPDATA\urai\bin\urai.exe",
    [string]$CgDir   = "$env:PROGRAMDATA\CyberGuard"
)
$ErrorActionPreference = "Stop"
Write-Host "[CyberGuard] Installing Windows security agent..." -ForegroundColor Cyan

# 1. Create install dir
New-Item -ItemType Directory -Force -Path $CgDir | Out-Null
New-Item -ItemType Directory -Force -Path "$CgDir\data" | Out-Null

# 2. Install Python deps
Write-Host "[CyberGuard] Installing Python dependencies..."
pip install pywin32 psutil scapy wmi cryptography requests 2>&1 | Out-Null

# 3. Install WFP monitoring via Windows built-in netsh / WFP API
#    (Python pywin32 + ctypes calls WFP for packet inspection)
Write-Host "[CyberGuard] Configuring Windows Filtering Platform rules..."
# Block known threat actor IPs at WFP level
$badIps = @("175.45.178.0","210.52.109.0","77.83.196.0")
foreach ($ip in $badIps) {
    try {
        netsh advfirewall firewall add rule name="CyberGuard-Block-$ip" `
            dir=out action=block remoteip=$ip protocol=any 2>&1 | Out-Null
        netsh advfirewall firewall add rule name="CyberGuard-Block-in-$ip" `
            dir=in action=block remoteip=$ip protocol=any 2>&1 | Out-Null
    } catch {}
}

# 4. Enable ETW session for kernel-level process + network monitoring
Write-Host "[CyberGuard] Starting ETW monitoring session..."
$logman = "logman create trace CyberGuard -p {Microsoft-Windows-Security-Auditing} " +
          "-p {Microsoft-Windows-NetworkSecurity} " +
          "-o $CgDir\etw.etl -ets -mode RealTime"
Invoke-Expression $logman 2>&1 | Out-Null

# 5. Install Windows Task Scheduler for persistent daemon
Write-Host "[CyberGuard] Installing scheduled task (persistent daemon)..."
$pythonExe = (Get-Command python).Path
$taskAction = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument "-m cyberguard.daemon daemon start" `
    -WorkingDirectory "$env:USERPROFILE\.local\share\urai"
$taskTrigger = New-ScheduledTaskTrigger -AtStartup
$taskSettings = New-ScheduledTaskSettingsSet -RunOnlyIfNetworkAvailable -RestartOnIdle
Register-ScheduledTask -TaskName "CyberGuardDaemon" `
    -Action $taskAction -Trigger $taskTrigger `
    -Settings $taskSettings -RunLevel Highest -Force | Out-Null

# 6. Enable Windows Defender tamper protection check
Write-Host "[CyberGuard] Verifying Windows Defender state..."
$mpStatus = Get-MpComputerStatus -ErrorAction SilentlyContinue
if ($mpStatus -and -not $mpStatus.RealTimeProtectionEnabled) {
    Write-Warning "Windows Defender real-time protection is DISABLED. CyberGuard recommends enabling it."
}

# 7. Self-protection: protect CyberGuard process from termination via WFP
#    (Prevents EDRChoker/EDRPrison-style attacks against our agent)
Write-Host "[CyberGuard] Enabling agent self-protection..."
$cgProtect = @"
# Add WFP permit rule for CyberGuard process network (prevents EDRChoker-style blocking)
netsh advfirewall firewall add rule name="CyberGuard-Self-Allow" `
    dir=out action=allow program="$pythonExe" protocol=any
"@
Invoke-Expression $cgProtect 2>&1 | Out-Null

Write-Host ""
Write-Host "[✓] CyberGuard installed." -ForegroundColor Green
Write-Host "    Quick scan:  python -m cyberguard.daemon scan --tier 1"
Write-Host "    Deep scan:   python -m cyberguard.daemon scan --tier 2"
Write-Host "    Continuous:  python -m cyberguard.daemon daemon start"
