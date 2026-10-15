param(
    [string]$DesktopPath = [Environment]::GetFolderPath("Desktop")
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$startScript = Join-Path $PSScriptRoot "start_autosupply.ps1"
$stopScript = Join-Path $PSScriptRoot "stop_autosupply.ps1"
$powershellPath = (Get-Command powershell.exe).Source

if (-not (Test-Path -LiteralPath $DesktopPath)) {
    throw "Desktop path does not exist: $DesktopPath"
}

$shell = New-Object -ComObject WScript.Shell

$startShortcutPath = Join-Path $DesktopPath "AutoSupply Copilot.lnk"
$startShortcut = $shell.CreateShortcut($startShortcutPath)
$startShortcut.TargetPath = $powershellPath
$startShortcut.Arguments = (
    "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`""
)
$startShortcut.WorkingDirectory = $projectRoot
$startShortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
$startShortcut.Description = "Start the local AutoSupply Copilot Dashboard"
$startShortcut.Save()

$stopShortcutPath = Join-Path $DesktopPath "Stop AutoSupply Copilot.lnk"
$stopShortcut = $shell.CreateShortcut($stopShortcutPath)
$stopShortcut.TargetPath = $powershellPath
$stopShortcut.Arguments = (
    "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$stopScript`""
)
$stopShortcut.WorkingDirectory = $projectRoot
$stopShortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,27"
$stopShortcut.Description = "Safely stop the local AutoSupply Copilot Dashboard"
$stopShortcut.Save()

Write-Output "Created: $startShortcutPath"
Write-Output "Created: $stopShortcutPath"
