param(
    [Parameter(Mandatory=$true)][string]$Url,
    [switch]$ResolveOnly
)
$ErrorActionPreference = 'Stop'
if ($Url -notmatch '^http://127\.0\.0\.1:\d+/?$') {
    throw 'Only the local AutoSupply dashboard URL is supported.'
}
$candidates = @(
    (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
    (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
)
foreach ($key in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe')) {
    if (Test-Path -LiteralPath $key) {
        $candidates += (Get-Item -LiteralPath $key).GetValue('')
    }
}
$chrome = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if ($ResolveOnly) {
    if ($chrome) { Write-Output $chrome } else { Write-Output 'SYSTEM_DEFAULT' }
    exit 0
}
if ($chrome) {
    # Visible because the user explicitly wants to view the dashboard in Chrome.
    Start-Process -FilePath $chrome -ArgumentList @('--new-tab', $Url)
} else {
    Start-Process $Url
}
