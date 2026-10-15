param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $projectRoot ".runtime"
$pidFile = Join-Path $runtimeDir "autosupply-$Port.pid"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Output "No running AutoSupply Copilot process was recorded."
    exit 0
}

$savedPidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
$streamlitPid = 0
if (-not [int]::TryParse($savedPidText, [ref]$streamlitPid)) {
    throw "Invalid PID file; no process was stopped: $pidFile"
}

$processInfo = Get-CimInstance Win32_Process `
    -Filter "ProcessId = $streamlitPid" `
    -ErrorAction SilentlyContinue
if ($null -eq $processInfo) {
    Remove-Item -LiteralPath $pidFile -Force
    Write-Output "The process no longer exists; the stale PID file was removed."
    exit 0
}

$commandLine = [string]$processInfo.CommandLine
if (
    -not $commandLine.Contains($projectRoot) -or
    -not $commandLine.Contains("streamlit") -or
    -not $commandLine.Contains("app.py")
) {
    throw "PID $streamlitPid does not belong to this project; no process was stopped."
}

Stop-Process -Id $streamlitPid
Wait-Process -Id $streamlitPid -Timeout 10 -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pidFile -Force
Write-Output "AutoSupply Copilot stopped safely."
