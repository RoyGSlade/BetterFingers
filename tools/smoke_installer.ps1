param(
    [string]$InstallerPath = "dist\BetterFingers_Setup.exe",
    # Optional: path to a previously-published installer .exe (e.g. downloaded
    # from the last GitHub Release) to install first, so this run also
    # exercises upgrade-over-an-existing-install rather than only clean
    # install. When omitted, the upgrade leg is skipped.
    [string]$PreviousInstallerPath = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $InstallerPath)) {
    throw "Installer not found: $InstallerPath"
}

$installDir = Join-Path $env:LOCALAPPDATA "Programs\BetterFingers"
$exePath = Join-Path $installDir "BetterFingers.exe"
$uninstallerPath = Join-Path $installDir "Uninstall.exe"
$uninstallRegKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\BetterFingers"

function Start-AppAndWait {
    param([string]$Path, [int]$Seconds = 4)
    $proc = Start-Process -FilePath $Path -PassThru
    Start-Sleep -Seconds $Seconds
    if (-not $proc -or $proc.HasExited) {
        throw "Application exited unexpectedly within $Seconds s of launch: $Path"
    }
    return $proc
}

function Stop-AppAndVerify {
    param([System.Diagnostics.Process]$Proc, [int]$TimeoutSeconds = 10)
    Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Get-Process -Id $Proc.Id -ErrorAction SilentlyContinue) -eq $null) {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Process $($Proc.Id) did not exit within $TimeoutSeconds s"
}

function Assert-NoRunningBetterFingers {
    $running = Get-Process -Name "BetterFingers" -ErrorAction SilentlyContinue
    if ($running) {
        throw "BetterFingers process still running (PID $($running.Id -join ', ')) - uninstall must not proceed with a live process, or teardown was incomplete"
    }
}

# ---- Optional leg: install a previous version first, to exercise upgrade ----
if ($PreviousInstallerPath -ne "") {
    if (-not (Test-Path $PreviousInstallerPath)) {
        throw "Previous installer not found: $PreviousInstallerPath"
    }

    Write-Host "Installing previous version for upgrade test: $PreviousInstallerPath"
    Start-Process -FilePath $PreviousInstallerPath -ArgumentList "/S" -Wait -NoNewWindow

    if (-not (Test-Path $exePath)) {
        throw "Previous-version executable not found after install: $exePath"
    }
    $previousVersion = (Get-Item $exePath).VersionInfo.FileVersion
    Write-Host "Previous version installed: $previousVersion"
}

# ---- Clean/upgrade install with the installer under test ----
Write-Host "Running installer smoke test: $InstallerPath"
Start-Process -FilePath $InstallerPath -ArgumentList "/S" -Wait -NoNewWindow

if (-not (Test-Path $exePath)) {
    throw "Installed executable not found: $exePath"
}

if ($PreviousInstallerPath -ne "") {
    $upgradedVersion = (Get-Item $exePath).VersionInfo.FileVersion
    Write-Host "Post-upgrade version: $upgradedVersion"
    if ($upgradedVersion -eq $previousVersion) {
        throw "Upgrade did not change the installed version (still $upgradedVersion) - installer may have no-opped instead of upgrading"
    }
}

Write-Host "Starting installed executable for startup sanity check..."
$proc = Start-AppAndWait -Path $exePath
Stop-AppAndVerify -Proc $proc
Assert-NoRunningBetterFingers

if (-not (Test-Path $uninstallerPath)) {
    throw "Uninstaller not found: $uninstallerPath"
}

Write-Host "Running silent uninstall smoke test..."
Start-Process -FilePath $uninstallerPath -ArgumentList "/S" -Wait -NoNewWindow
Start-Sleep -Seconds 2

Assert-NoRunningBetterFingers

if (Test-Path $exePath) {
    throw "Uninstall smoke failed: executable still present at $exePath"
}

# Directory itself should be gone or empty - a leftover-but-empty install dir
# is the one thing NSIS may legitimately leave (e.g. user data mixed in);
# treat any leftover *files* as a failure, but tolerate an absent or empty dir.
if (Test-Path $installDir) {
    $leftovers = Get-ChildItem -Path $installDir -Recurse -File -ErrorAction SilentlyContinue
    if ($leftovers) {
        $names = ($leftovers | Select-Object -ExpandProperty FullName) -join ", "
        throw "Uninstall left files behind in ${installDir}: $names"
    }
}

if (Test-Path $uninstallRegKey) {
    throw "Uninstall left a registry entry behind: $uninstallRegKey"
}

$legs = if ($PreviousInstallerPath -ne "") { "install + upgrade + uninstall" } else { "install + uninstall" }
Write-Host "Installer smoke test passed ($legs, process + file + registry checks clean)."
