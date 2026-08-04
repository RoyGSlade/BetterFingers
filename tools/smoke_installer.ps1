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
# The uninstaller name is resolved dynamically after install: electron-builder's
# NSIS names it "Uninstall <ProductName>.exe" (e.g. "Uninstall BetterFingers.exe"),
# not a fixed "Uninstall.exe", so a hardcoded name breaks the smoke test.
$uninstallRegKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\BetterFingers"
$healthUrl = "http://127.0.0.1:8000/health"
$packagedStartupBudgetSeconds = 90
$qaDataRoot = $null
$appProcess = $null
$uninstallerPath = $null
$previousDataDir = $env:BETTERFINGERS_DATA_DIR
$previousAuthToken = $env:BETTERFINGERS_AUTH_TOKEN

function Get-BetterFingersProcesses {
    @(Get-Process -Name "BetterFingers", "betterfingers-backend" -ErrorAction SilentlyContinue)
}

function Assert-NoRunningBetterFingers {
    $running = @(Get-BetterFingersProcesses)
    if ($running) {
        throw "BetterFingers process still running (PID $($running.Id -join ', ')) - uninstall must not proceed with a live process, or teardown was incomplete"
    }
}

function Stop-BetterFingersProcesses {
    param([System.Diagnostics.Process]$Process)

    if ($Process) {
        try {
            if (-not $Process.HasExited) {
                # Let Electron's shutdown handler stop its backend cleanly
                # first. If it does not exit, /T guarantees an already-started
                # packaged child is not orphaned before uninstall begins.
                $null = $Process.CloseMainWindow()
                $gracefulDeadline = (Get-Date).AddSeconds(10)
                while (-not $Process.HasExited -and (Get-Date) -lt $gracefulDeadline) {
                    Start-Sleep -Milliseconds 250
                }
                if (-not $Process.HasExited) {
                    $taskkill = Start-Process -FilePath "taskkill.exe" `
                        -ArgumentList @("/PID", [string]$Process.Id, "/T", "/F") `
                        -Wait -PassThru -WindowStyle Hidden
                    $null = $taskkill
                }
            }
        } catch {
            # The process may have exited between the check and taskkill. The
            # named-process sweep below still handles an orphaned backend.
        }
    }

    $deadline = (Get-Date).AddSeconds(15)
    do {
        foreach ($running in @(Get-BetterFingersProcesses)) {
            try { Stop-Process -Id $running.Id -Force -ErrorAction SilentlyContinue } catch { }
        }
        if (-not @(Get-BetterFingersProcesses)) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
}

function Test-TcpPortOpen {
    param([int]$Port, [int]$TimeoutMilliseconds = 500)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.ConnectAsync("127.0.0.1", $Port)
        if (-not $connect.Wait($TimeoutMilliseconds)) {
            return $false
        }
        return $client.Connected
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Assert-PortReleased {
    param([int]$Port = 8000, [int]$TimeoutSeconds = 15)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-TcpPortOpen -Port $Port)) {
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Port $Port remained open after BetterFingers teardown"
}

function Get-HttpStatus {
    param(
        [string]$Uri,
        [string]$Token = ""
    )

    $headers = @{}
    if ($Token) {
        $headers["Authorization"] = "Bearer $Token"
    }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -Headers $headers -Method Get -TimeoutSec 3
        return [int]$response.StatusCode
    } catch [System.Net.WebException] {
        $response = $_.Exception.Response
        if ($response -and $response.StatusCode) {
            return [int]$response.StatusCode
        }
        return 0
    } catch {
        return 0
    }
}

function Install-Silently {
    param([string]$Path)

    $installerProcess = Start-Process -FilePath $Path -ArgumentList "/S" -Wait -NoNewWindow -PassThru
    if ($installerProcess.ExitCode -ne 0) {
        throw "Silent installer failed with exit code $($installerProcess.ExitCode): $Path"
    }
}

try {
    if (-not $env:RUNNER_TEMP) {
        throw "RUNNER_TEMP is required so installer QA data is isolated from the runner user's real data."
    }

    if (@(Get-BetterFingersProcesses)) {
        throw "A BetterFingers process was already running before installer QA; refusing to test against an unowned backend."
    }
    if (Test-TcpPortOpen -Port 8000) {
        throw "Port 8000 was already in use before installer QA; refusing to test against an unowned backend."
    }

    # This token is generated per run and inherited by Electron and its backend
    # through the environment. It is intentionally never printed or put in an
    # installer argument list.
    $authToken = [guid]::NewGuid().ToString("N")
    $qaDataRoot = Join-Path $env:RUNNER_TEMP ("betterfingers-installer-smoke-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $qaDataRoot | Out-Null
    $env:BETTERFINGERS_DATA_DIR = $qaDataRoot
    $env:BETTERFINGERS_AUTH_TOKEN = $authToken

    # ---- Optional leg: install a previous version first, to exercise upgrade ----
    if ($PreviousInstallerPath -ne "") {
        if (-not (Test-Path $PreviousInstallerPath)) {
            throw "Previous installer not found: $PreviousInstallerPath"
        }

        Write-Host "Installing previous version for upgrade test: $PreviousInstallerPath"
        Install-Silently -Path $PreviousInstallerPath

        if (-not (Test-Path $exePath)) {
            throw "Previous-version executable not found after install: $exePath"
        }
        $previousVersion = (Get-Item $exePath).VersionInfo.FileVersion
        Write-Host "Previous version installed: $previousVersion"

        # This is a continuity sentinel for the isolated data directory, not a
        # schema-migration claim. It must survive the current installer.
        $sentinelPath = Join-Path $qaDataRoot "installer-data-continuity-sentinel.txt"
        $sentinelContents = "BetterFingers installer data continuity sentinel"
        [IO.File]::WriteAllText($sentinelPath, $sentinelContents, [Text.Encoding]::UTF8)
    }

    # ---- Install the installer under test ----
    Write-Host "Running installer smoke test: $InstallerPath"
    Install-Silently -Path $InstallerPath

    if (-not (Test-Path $exePath)) {
        throw "Installed executable not found: $exePath"
    }

    if ($PreviousInstallerPath -ne "") {
        $upgradedVersion = (Get-Item $exePath).VersionInfo.FileVersion
        Write-Host "Post-upgrade version: $upgradedVersion"
        if ($upgradedVersion -eq $previousVersion) {
            throw "Upgrade did not change the installed version (still $upgradedVersion) - installer may have no-opped instead of upgrading"
        }
        if ((-not (Test-Path $sentinelPath)) -or ([IO.File]::ReadAllText($sentinelPath) -ne $sentinelContents)) {
            throw "Installer data-directory continuity failed: current install did not preserve the isolated sentinel"
        }
        Write-Host "Installer data-directory continuity sentinel survived current install."
    }

    # ---- Authenticated installed-app/backend health smoke ----
    Write-Host "Starting installed executable and waiting up to $packagedStartupBudgetSeconds seconds for authenticated backend health..."
    $appProcess = Start-Process -FilePath $exePath -PassThru
    $healthDeadline = (Get-Date).AddSeconds($packagedStartupBudgetSeconds)
    $authenticated = $false
    while ((Get-Date) -lt $healthDeadline) {
        if ($appProcess.HasExited) {
            throw "Installed BetterFingers.exe exited before authenticated backend health became ready."
        }
        $status = Get-HttpStatus -Uri $healthUrl -Token $authToken
        if ($status -eq 200) {
            $authenticated = $true
            break
        }
        if ($status -eq 401) {
            throw "Installed backend rejected its inherited authentication token."
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $authenticated) {
        throw "Installed backend did not return HTTP 200 from authenticated /health within $packagedStartupBudgetSeconds seconds."
    }
    Write-Host "Authenticated backend /health returned HTTP 200."

    $unauthenticatedStatus = Get-HttpStatus -Uri $healthUrl
    if ($unauthenticatedStatus -ne 401) {
        throw "Unauthenticated /health request was not rejected with HTTP 401 (received $unauthenticatedStatus)."
    }
    Write-Host "Unauthenticated backend /health request was rejected with HTTP 401."

    # The installed app and its backend must be gone before NSIS uninstall runs.
    Stop-BetterFingersProcesses -Process $appProcess
    Assert-NoRunningBetterFingers
    Assert-PortReleased

    $uninstaller = Get-ChildItem -Path $installDir -Filter "Uninstall*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $uninstaller) {
        throw "Uninstaller not found in ${installDir} (looked for Uninstall*.exe)"
    }
    $uninstallerPath = $uninstaller.FullName

    Write-Host "Running silent uninstall smoke test: $uninstallerPath"
    $uninstallerProcess = Start-Process -FilePath $uninstallerPath -ArgumentList "/S" -Wait -NoNewWindow -PassThru
    if ($uninstallerProcess.ExitCode -ne 0) {
        throw "Silent uninstaller failed with exit code $($uninstallerProcess.ExitCode): $uninstallerPath"
    }
    Start-Sleep -Seconds 2

    Assert-NoRunningBetterFingers
    Assert-PortReleased

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
    Write-Host "Installer smoke test passed ($legs, authenticated backend health + unauthenticated rejection + file + registry checks clean)."
} finally {
    # QA cleanup also runs when install, startup, health, or uninstall fails.
    Stop-BetterFingersProcesses -Process $appProcess
    try {
        Assert-PortReleased -TimeoutSeconds 5
    } catch {
        Write-Warning $_.Exception.Message
    }
    if ($qaDataRoot -and (Test-Path $qaDataRoot)) {
        Remove-Item -LiteralPath $qaDataRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($null -eq $previousDataDir) {
        Remove-Item Env:BETTERFINGERS_DATA_DIR -ErrorAction SilentlyContinue
    } else {
        $env:BETTERFINGERS_DATA_DIR = $previousDataDir
    }
    if ($null -eq $previousAuthToken) {
        Remove-Item Env:BETTERFINGERS_AUTH_TOKEN -ErrorAction SilentlyContinue
    } else {
        $env:BETTERFINGERS_AUTH_TOKEN = $previousAuthToken
    }
}
