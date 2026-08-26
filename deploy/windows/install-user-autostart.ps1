param(
    [string]$ProjectPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$PythonExe = 'python.exe',
    [string]$CloudflaredExe = 'C:\Program Files (x86)\cloudflared\cloudflared.exe',
    [string]$TunnelTokenFile = (Join-Path $env:USERPROFILE '.cloudflared\ai-fashion-local.token')
)

$ErrorActionPreference = 'Stop'
$watchdog = Join-Path $ProjectPath 'deploy\windows\ai-fashion-watchdog.ps1'
if (-not (Test-Path -LiteralPath $watchdog)) {
    throw "Watchdog script not found: $watchdog"
}
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python runtime not found: $PythonExe"
}
if (-not (Test-Path -LiteralPath $CloudflaredExe)) {
    throw "cloudflared not found: $CloudflaredExe"
}
if (-not (Test-Path -LiteralPath $TunnelTokenFile)) {
    throw "Cloudflare Tunnel token file not found: $TunnelTokenFile"
}

function Quote-Argument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

$arguments = @(
    '-NoProfile',
    '-NonInteractive',
    '-WindowStyle', 'Hidden',
    '-ExecutionPolicy', 'Bypass',
    '-File', (Quote-Argument $watchdog),
    '-ProjectPath', (Quote-Argument $ProjectPath),
    '-PythonExe', (Quote-Argument $PythonExe),
    '-CloudflaredExe', (Quote-Argument $CloudflaredExe),
    '-TunnelTokenFile', (Quote-Argument $TunnelTokenFile)
) -join ' '

$runPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$command = "powershell.exe $arguments"
New-ItemProperty -LiteralPath $runPath -Name 'AI_Fashion_Watchdog' -Value $command -PropertyType String -Force | Out-Null
Remove-ItemProperty -LiteralPath $runPath -Name 'AI_Fashion_Tunnel' -ErrorAction SilentlyContinue
Remove-ItemProperty -LiteralPath $runPath -Name 'AI_Fashion_Local_Origin' -ErrorAction SilentlyContinue

$escapedWatchdog = [Regex]::Escape($watchdog)
$running = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match $escapedWatchdog } |
    Select-Object -First 1
if (-not $running) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden
}

[pscustomobject]@{
    installed = $true
    mode = 'current-user logon with continuous recovery'
    registry_value = 'HKCU\Software\Microsoft\Windows\CurrentVersion\Run\AI_Fashion_Watchdog'
    watchdog = $watchdog
}
