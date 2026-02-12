param(
    [string]$InstallerPath = "dist\BetterFingers_Setup.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $InstallerPath)) {
    throw "Installer not found: $InstallerPath"
}

$installDir = Join-Path $env:LOCALAPPDATA "Programs\BetterFingers"
$exePath = Join-Path $installDir "BetterFingers.exe"
$uninstallerPath = Join-Path $installDir "Uninstall.exe"

Write-Host "Running installer smoke test: $InstallerPath"
Start-Process -FilePath $InstallerPath -ArgumentList "/S" -Wait -NoNewWindow

if (-not (Test-Path $exePath)) {
    throw "Installed executable not found: $exePath"
}

Write-Host "Starting installed executable for startup sanity check..."
$proc = Start-Process -FilePath $exePath -PassThru
Start-Sleep -Seconds 4
if ($proc -and -not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1

if (-not (Test-Path $uninstallerPath)) {
    throw "Uninstaller not found: $uninstallerPath"
}

Write-Host "Running silent uninstall smoke test..."
Start-Process -FilePath $uninstallerPath -ArgumentList "/S" -Wait -NoNewWindow
Start-Sleep -Seconds 2

if (Test-Path $exePath) {
    throw "Uninstall smoke failed: executable still present at $exePath"
}

Write-Host "Installer smoke test passed."
