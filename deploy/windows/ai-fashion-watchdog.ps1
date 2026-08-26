param(
    [string]$ProjectPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$PythonExe = 'python.exe',
    [string]$CloudflaredExe = 'C:\Program Files (x86)\cloudflared\cloudflared.exe',
    [string]$TunnelTokenFile = (Join-Path $env:USERPROFILE '.cloudflared\ai-fashion-local.token'),
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 8000,
    [int]$CheckIntervalSeconds = 20
)

$ErrorActionPreference = 'Continue'
$logsPath = Join-Path $ProjectPath 'workspace\logs'
New-Item -ItemType Directory -Path $logsPath -Force | Out-Null

function Test-LocalPort([int]$Port) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $client.Connect('127.0.0.1', $Port)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Start-HiddenProcess {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$StdoutName,
        [string]$StderrName
    )

    Start-Process -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $ProjectPath `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logsPath $StdoutName) `
        -RedirectStandardError (Join-Path $logsPath $StderrName)
}

function Test-TunnelProcess {
    $escapedTokenPath = [Regex]::Escape($TunnelTokenFile)
    return [bool](Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $escapedTokenPath } |
        Select-Object -First 1)
}

while ($true) {
    try {
        if (-not (Test-LocalPort $BackendPort)) {
            Start-HiddenProcess -FilePath $PythonExe `
                -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$BackendPort") `
                -StdoutName 'startup-backend.stdout.log' `
                -StderrName 'startup-backend.stderr.log'
        }

        if (-not (Test-LocalPort $FrontendPort)) {
            Start-HiddenProcess -FilePath $PythonExe `
                -ArgumentList @('-m', 'http.server', "$FrontendPort", '--bind', '127.0.0.1', '--directory', 'frontend') `
                -StdoutName 'startup-frontend.stdout.log' `
                -StderrName 'startup-frontend.stderr.log'
        }

        if ((Test-Path -LiteralPath $CloudflaredExe) -and
            (Test-Path -LiteralPath $TunnelTokenFile) -and
            -not (Test-TunnelProcess)) {
            Start-HiddenProcess -FilePath $CloudflaredExe `
                -ArgumentList @('tunnel', 'run', '--token-file', $TunnelTokenFile) `
                -StdoutName 'startup-tunnel.stdout.log' `
                -StderrName 'startup-tunnel.stderr.log'
        }
    }
    catch {
        "$(Get-Date -Format o) $($_.Exception.Message)" |
            Add-Content -LiteralPath (Join-Path $logsPath 'startup-watchdog.errors.log')
    }

    Start-Sleep -Seconds ([Math]::Max(5, $CheckIntervalSeconds))
}
