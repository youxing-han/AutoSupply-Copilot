param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8501,
    [ValidateRange(5, 120)]
    [int]$HealthTimeoutSeconds = 30,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appPath = Join-Path $projectRoot "app.py"
$runtimeDir = Join-Path $projectRoot ".runtime"
$pidFile = Join-Path $runtimeDir "autosupply-$Port.pid"
$stdoutLog = Join-Path $runtimeDir "streamlit-$Port.log"
$stderrLog = Join-Path $runtimeDir "streamlit-$Port-error.log"
$dashboardUrl = "http://127.0.0.1:$Port"

function Test-DashboardHealth {
    try {
        $response = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "$dashboardUrl/_stcore/health" `
            -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Test-OwnedStreamlitProcess([int]$ProcessId) {
    $processInfo = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $ProcessId" `
        -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        return $false
    }
    $commandLine = [string]$processInfo.CommandLine
    return (
        $commandLine.Contains($projectRoot) -and
        $commandLine.Contains("streamlit") -and
        $commandLine.Contains("app.py")
    )
}

function Get-OwnedListenerProcessId {
    $connections = Get-NetTCPConnection `
        -LocalAddress "127.0.0.1" `
        -LocalPort $Port `
        -State Listen `
        -ErrorAction SilentlyContinue
    foreach ($connection in @($connections)) {
        $candidatePid = [int]$connection.OwningProcess
        if (Test-OwnedStreamlitProcess $candidatePid) {
            return $candidatePid
        }
    }
    return 0
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if (Test-Path -LiteralPath $pidFile) {
    $savedPidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $savedPid = 0
    if ([int]::TryParse($savedPidText, [ref]$savedPid)) {
        if ((Test-OwnedStreamlitProcess $savedPid) -and (Test-DashboardHealth)) {
            if (-not $NoBrowser) {
                & (Join-Path $PSScriptRoot "open_dashboard.ps1") -Url $dashboardUrl
            }
            exit 0
        }
    }
    Remove-Item -LiteralPath $pidFile -Force
}

if (Test-DashboardHealth) {
    throw "Port $Port is already used by another Streamlit service. See $stderrLog."
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project virtual environment was not found: $pythonPath"
}
if (-not (Test-Path -LiteralPath $appPath)) {
    throw "Streamlit entry point was not found: $appPath"
}

$arguments = @(
    "-m", "streamlit", "run", $appPath,
    "--server.address", "127.0.0.1",
    "--server.port", $Port,
    "--server.headless", "true",
    "--browser.gatherUsageStats", "false"
)
$process = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList $arguments `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru
Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii

$deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-DashboardHealth) {
        $listenerPid = Get-OwnedListenerProcessId
        if ($listenerPid -le 0) {
            break
        }
        Set-Content -LiteralPath $pidFile -Value $listenerPid -Encoding ascii
        if (-not $NoBrowser) {
            & (Join-Path $PSScriptRoot "open_dashboard.ps1") -Url $dashboardUrl
        }
        exit 0
    }
    Start-Sleep -Milliseconds 500
}

if (-not $process.HasExited) {
    Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
}
if (Test-Path -LiteralPath $pidFile) {
    Remove-Item -LiteralPath $pidFile -Force
}
throw "AutoSupply Copilot failed to start. See logs: $stdoutLog and $stderrLog"
