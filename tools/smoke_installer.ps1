param(
    [string]$InstallerPath = "dist\BetterFingers_Setup.exe",
    # Optional: path to a previously-published installer .exe (e.g. downloaded
    # from the last GitHub Release) to install first, so this run also
    # exercises upgrade-over-an-existing-install rather than only clean
    # install. When omitted, the upgrade leg is skipped.
    [string]$PreviousInstallerPath = "",
    [string]$ExpectedVersion = "1.1.0-alpha.4",
    [ValidateSet("NotSigned", "Valid")]
    [string]$ExpectedSignatureStatus = "NotSigned",
    # Azure Artifact Signing must prove the exact certificate identity, not
    # merely that Windows trusts whichever certificate signed the file.
    [string]$ExpectedSignerSubject = "",
    [string]$NativePayloadReportPath = "",
    [switch]$ExerciseCleanupCategories
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
$uninstallRegRoot = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
$uninstallRegPath = $null
$healthUrl = "http://127.0.0.1:8000/health"
$runtimeStatusUrl = "http://127.0.0.1:8000/runtime/status"
$runtimeVersionUrl = "http://127.0.0.1:8000/runtime/version"
$whisperModelsUrl = "http://127.0.0.1:8000/models/whisper"
$wakeDownloadUrl = "http://127.0.0.1:8000/wake/models/melspectrogram/download"
$wakeDownloadStateUrl = "http://127.0.0.1:8000/wake/models/melspectrogram/download-state"
$packagedStartupBudgetSeconds = 90
$qaDataRoot = $null
$appProcess = $null
$uninstallerPath = $null
$previousDataDir = $env:BETTERFINGERS_DATA_DIR
$previousAuthToken = $env:BETTERFINGERS_AUTH_TOKEN
$canonicalDataRoot = Join-Path $env:APPDATA "BetterFingers"
$canonicalDataRootExistedBefore = Test-Path -LiteralPath $canonicalDataRoot
# Electron/Chromium renderer state lives in its own folder (the packaged app's
# userData), which "remove my data" must clean too.
$electronDataRoot = Join-Path $env:APPDATA "betterfingers-electron"
$electronDataRootExistedBefore = Test-Path -LiteralPath $electronDataRoot
$seedSettingsPath = $null
$seedModelPath = $null
$seedSettingsHash = $null
$seedModelHash = $null
$obsoleteProgramPath = $null

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
    } catch {
        # Windows PowerShell 5 reports HTTP failures as WebException, while
        # PowerShell 7 uses HttpResponseException. Both expose Response and
        # StatusCode, so inspect the common shape instead of the exception
        # class or a deliberate 401 will be mistaken for a transport failure.
        $response = $_.Exception.Response
        if ($response -and $response.StatusCode) {
            return [int]$response.StatusCode
        }
        return 0
    }
}

function Invoke-AuthenticatedJson {
    param(
        [string]$Uri,
        [string]$Token,
        [ValidateSet("Get", "Post")]
        [string]$Method = "Get"
    )

    Invoke-RestMethod -UseBasicParsing -Uri $Uri -Method $Method -TimeoutSec 15 -Headers @{
        Authorization = "Bearer $Token"
    }
}

function Assert-AuthenticodeStatus {
    param(
        [string]$Path,
        [string]$Expected,
        [string]$Label,
        [string]$ExpectedSubject = "",
        [switch]$RequireTimestamp
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    $signature = Get-AuthenticodeSignature -FilePath $Path
    $actual = $signature.Status.ToString()
    Write-Host "$Label Authenticode status: $actual"
    if ($actual -ne $Expected) {
        throw "$Label Authenticode status was $actual; expected exactly $Expected."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSubject)) {
        $actualSubject = [string]$signature.SignerCertificate.Subject
        Write-Host "$Label signer subject: $actualSubject"
        if ($actualSubject -cne $ExpectedSubject) {
            throw "$Label signer subject was '$actualSubject'; expected exactly '$ExpectedSubject'."
        }
    }
    if ($RequireTimestamp -and $null -eq $signature.TimeStamperCertificate) {
        throw "$Label lacked an RFC 3161 timestamp certificate."
    }
}

function Assert-NativePayloadSignatures {
    param(
        [string]$RootPath,
        [string]$ProductExecutablePath,
        [ValidateSet("NotSigned", "Valid")]
        [string]$ExpectedPublisherStatus,
        [string]$ExpectedPublisherSubject = ""
    )

    if (-not (Test-Path -LiteralPath $RootPath -PathType Container)) {
        throw "Installed application tree not found: $RootPath"
    }
    if (-not (Test-Path -LiteralPath $ProductExecutablePath -PathType Leaf)) {
        throw "Installed backend executable not found: $ProductExecutablePath"
    }

    $payloadFiles = @(Get-ChildItem -LiteralPath $RootPath -File -Recurse |
        Where-Object { @(".exe", ".dll", ".pyd", ".node") -contains $_.Extension.ToLowerInvariant() } |
        Sort-Object FullName)
    if ($payloadFiles.Count -eq 0) {
        throw "Installed application tree contained no EXE, DLL, PYD, or NODE payload files: $RootPath"
    }

    $resolvedProductPath = (Resolve-Path -LiteralPath $ProductExecutablePath).Path
    $sawProductExecutable = $false
    $records = New-Object System.Collections.Generic.List[object]
    foreach ($payloadFile in $payloadFiles) {
        $resolvedPayloadPath = $payloadFile.FullName
        $isProductExecutable = $resolvedPayloadPath.Equals(
            $resolvedProductPath,
            [StringComparison]::OrdinalIgnoreCase
        )
        if ($isProductExecutable) {
            $sawProductExecutable = $true
            Assert-AuthenticodeStatus `
                -Path $resolvedPayloadPath `
                -Expected $ExpectedPublisherStatus `
                -Label "Installed backend executable" `
                -ExpectedSubject $ExpectedPublisherSubject `
                -RequireTimestamp:($ExpectedPublisherStatus -eq "Valid")
        } elseif ($ExpectedPublisherStatus -eq "Valid") {
            Assert-AuthenticodeStatus `
                -Path $resolvedPayloadPath `
                -Expected "Valid" `
                -Label "Installed application native payload"
        } else {
            # Unsigned manual qualification builds may still contain valid
            # Microsoft/vendor binaries. Accept Valid or NotSigned here, but
            # reject every broken/untrusted status instead of pretending the
            # unsigned build has passed the production WDAC gate.
            $signature = Get-AuthenticodeSignature -FilePath $resolvedPayloadPath
            $actual = $signature.Status.ToString()
            Write-Host "Installed application native payload Authenticode status: $actual ($resolvedPayloadPath)"
            if ($actual -notin @("Valid", "NotSigned")) {
                throw "Installed application native payload '$resolvedPayloadPath' had invalid Authenticode status $actual."
            }
        }

        $verifiedSignature = Get-AuthenticodeSignature -FilePath $resolvedPayloadPath
        if ($verifiedSignature.Status -eq "Valid" -and
            $null -eq $verifiedSignature.SignerCertificate) {
            throw "Installed application native payload '$resolvedPayloadPath' lacked a signer certificate."
        }
        $records.Add([ordered]@{
            path = $resolvedPayloadPath
            sha256 = (Get-FileHash -LiteralPath $resolvedPayloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
            signatureStatus = $verifiedSignature.Status.ToString()
            signerSubject = if ($null -eq $verifiedSignature.SignerCertificate) { "" } else { [string]$verifiedSignature.SignerCertificate.Subject }
            signerThumbprint = if ($null -eq $verifiedSignature.SignerCertificate) { "" } else { [string]$verifiedSignature.SignerCertificate.Thumbprint }
            timestampSubject = if ($null -eq $verifiedSignature.TimeStamperCertificate) { "" } else { [string]$verifiedSignature.TimeStamperCertificate.Subject }
            timestampThumbprint = if ($null -eq $verifiedSignature.TimeStamperCertificate) { "" } else { [string]$verifiedSignature.TimeStamperCertificate.Thumbprint }
        })
    }

    if (-not $sawProductExecutable) {
        throw "Recursive installed-tree verification omitted the BetterFingers backend executable: $resolvedProductPath"
    }
    Write-Host "Verified $($payloadFiles.Count) installed-tree EXE/DLL/PYD signature(s)."
    return $records.ToArray()
}

function Get-InstalledMetadata {
    $matches = @(Get-ChildItem -Path $uninstallRegRoot -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ItemProperty -Path $_.PSPath } |
        Where-Object {
            $_.DisplayName -like "BetterFingers*" -and
            $_.UninstallString -and
            ([string]$_.UninstallString).IndexOf($installDir, [StringComparison]::OrdinalIgnoreCase) -ge 0
        })
    if ($matches.Count -ne 1) {
        throw "Expected exactly one BetterFingers uninstall entry for $installDir; found $($matches.Count)."
    }
    return $matches[0]
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

    Assert-AuthenticodeStatus `
        -Path $InstallerPath `
        -Expected $ExpectedSignatureStatus `
        -Label "Installer" `
        -ExpectedSubject $ExpectedSignerSubject `
        -RequireTimestamp:($ExpectedSignatureStatus -eq "Valid")

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
        $previousMetadata = Get-InstalledMetadata
        $previousVersion = [string]$previousMetadata.DisplayVersion
        Write-Host "Previous version installed: $previousVersion"

        # This is a continuity sentinel for the isolated data directory, not a
        # schema-migration claim. It must survive the current installer.
        $sentinelPath = Join-Path $qaDataRoot "installer-data-continuity-sentinel.txt"
        $sentinelContents = "BetterFingers installer data continuity sentinel"
        [IO.File]::WriteAllText($sentinelPath, $sentinelContents, [Text.Encoding]::UTF8)
        $seedSettingsPath = Join-Path $qaDataRoot "profiles\installer-smoke.yaml"
        $seedModelPath = Join-Path $qaDataRoot "models\installer-smoke-model.bin"
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $seedSettingsPath), (Split-Path -Parent $seedModelPath) | Out-Null
        [IO.File]::WriteAllText($seedSettingsPath, "profile: preserved", [Text.Encoding]::UTF8)
        [IO.File]::WriteAllBytes($seedModelPath, [byte[]](0..255))
        $seedSettingsHash = (Get-FileHash -LiteralPath $seedSettingsPath -Algorithm SHA256).Hash
        $seedModelHash = (Get-FileHash -LiteralPath $seedModelPath -Algorithm SHA256).Hash

        # A registered NSIS upgrade replaces the old program tree. This file is
        # deliberately outside the new payload and must not survive.
        $obsoleteProgramPath = Join-Path $installDir "obsolete-upgrade-sentinel.bin"
        [IO.File]::WriteAllBytes($obsoleteProgramPath, [byte[]](1, 3, 3, 7))
    }

    # ---- Install the installer under test ----
    Write-Host "Running installer smoke test: $InstallerPath"
    Install-Silently -Path $InstallerPath

    if (-not (Test-Path $exePath)) {
        throw "Installed executable not found: $exePath"
    }

    $backendBundlePath = Join-Path $installDir "resources\backend\betterfingers-backend"
    $backendExePath = Join-Path $backendBundlePath "betterfingers-backend.exe"
    Assert-AuthenticodeStatus `
        -Path $exePath `
        -Expected $ExpectedSignatureStatus `
        -Label "Installed application" `
        -ExpectedSubject $ExpectedSignerSubject `
        -RequireTimestamp:($ExpectedSignatureStatus -eq "Valid")
    $installedNativePayloadRecords = @(Assert-NativePayloadSignatures `
        -RootPath $installDir `
        -ProductExecutablePath $backendExePath `
        -ExpectedPublisherStatus $ExpectedSignatureStatus `
        -ExpectedPublisherSubject $ExpectedSignerSubject)
    if ([string]::IsNullOrWhiteSpace($NativePayloadReportPath)) {
        $NativePayloadReportPath = "$([IO.Path]::GetFullPath($InstallerPath)).installed-native-verification.json"
    }
    $nativePayloadReportFullPath = [IO.Path]::GetFullPath($NativePayloadReportPath)
    $nativePayloadReportDirectory = Split-Path -Parent $nativePayloadReportFullPath
    if (-not (Test-Path -LiteralPath $nativePayloadReportDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $nativePayloadReportDirectory -Force | Out-Null
    }
    $nativePayloadReport = [ordered]@{
        schemaVersion = 1
        installerPath = (Resolve-Path -LiteralPath $InstallerPath).Path
        installRoot = (Resolve-Path -LiteralPath $installDir).Path
        expectedPublisherStatus = $ExpectedSignatureStatus
        expectedPublisherSubject = $ExpectedSignerSubject
        verifiedAtUtc = [DateTime]::UtcNow.ToString("o")
        artifacts = $installedNativePayloadRecords
    }
    [IO.File]::WriteAllText(
        $nativePayloadReportFullPath,
        ($nativePayloadReport | ConvertTo-Json -Depth 6),
        (New-Object Text.UTF8Encoding($false))
    )
    Write-Host "Installed native-payload verification report: $nativePayloadReportFullPath"

    $installedMetadata = Get-InstalledMetadata
    $uninstallRegPath = $installedMetadata.PSPath
    if ([string]$installedMetadata.DisplayName -ne "BetterFingers $ExpectedVersion") {
        throw "Unexpected uninstall DisplayName '$($installedMetadata.DisplayName)'; expected 'BetterFingers $ExpectedVersion'."
    }
    if ([string]$installedMetadata.DisplayVersion -ne $ExpectedVersion) {
        throw "Unexpected uninstall DisplayVersion '$($installedMetadata.DisplayVersion)'; expected '$ExpectedVersion'."
    }
    if ([string]$installedMetadata.Publisher -ne "Donaven Crenshaw") {
        throw "Unexpected uninstall Publisher '$($installedMetadata.Publisher)'; expected 'Donaven Crenshaw'."
    }
    if (-not ([string]$installedMetadata.UninstallString -like "*Uninstall*BetterFingers*.exe*")) {
        throw "Unexpected uninstall command: $($installedMetadata.UninstallString)"
    }

    $versionInfo = (Get-Item -LiteralPath $exePath).VersionInfo
    if ($versionInfo.ProductName -ne "BetterFingers") {
        throw "Installed ProductName was '$($versionInfo.ProductName)'; expected BetterFingers."
    }
    if ($versionInfo.CompanyName -ne "Donaven Crenshaw") {
        throw "Installed CompanyName was '$($versionInfo.CompanyName)'; expected Donaven Crenshaw."
    }
    # electron-builder deliberately stamps the product name into the Windows
    # executable's FileDescription (the package description is used by
    # installer/Linux metadata instead). Assert the real Windows identity so
    # the smoke test still catches a generic Electron executable.
    if ($versionInfo.FileDescription -ne "BetterFingers") {
        throw "Installed FileDescription was '$($versionInfo.FileDescription)'; expected BetterFingers."
    }

    if ($PreviousInstallerPath -ne "") {
        $upgradedVersion = [string]$installedMetadata.DisplayVersion
        Write-Host "Post-upgrade version: $upgradedVersion"
        if ($upgradedVersion -eq $previousVersion) {
            throw "Upgrade did not change the installed version (still $upgradedVersion) - installer may have no-opped instead of upgrading"
        }
        if ((-not (Test-Path $sentinelPath)) -or ([IO.File]::ReadAllText($sentinelPath) -ne $sentinelContents)) {
            throw "Installer data-directory continuity failed: current install did not preserve the isolated sentinel"
        }
        if (Test-Path -LiteralPath $obsoleteProgramPath) {
            throw "Upgrade left an obsolete program file behind: $obsoleteProgramPath"
        }
        if ((Get-FileHash -LiteralPath $seedSettingsPath -Algorithm SHA256).Hash -ne $seedSettingsHash) {
            throw "Upgrade changed the seeded settings file."
        }
        if ((Get-FileHash -LiteralPath $seedModelPath -Algorithm SHA256).Hash -ne $seedModelHash) {
            throw "Upgrade changed the seeded model bytes."
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

    # A clean launch must be useful without a language model. The profile
    # default keeps cleanup off, and neither startup nor diagnostics may
    # construct/download llama-server or a GGUF behind the user's back.
    $runtimeStatus = Invoke-AuthenticatedJson -Uri $runtimeStatusUrl -Token $authToken
    if ($runtimeStatus.llm_enabled -ne $false) {
        throw "Fresh installed profile did not report llm_enabled=false."
    }
    if ($runtimeStatus.llm_initialized -ne $false) {
        throw "Fresh installed launch initialized the LLM even though AI cleanup is disabled."
    }
    $runtimeVersion = Invoke-AuthenticatedJson -Uri $runtimeVersionUrl -Token $authToken
    if ($runtimeVersion.backend_version -ne $ExpectedVersion -or $runtimeVersion.expected_electron_api_version -ne $ExpectedVersion) {
        throw "Installed backend version mismatch: backend=$($runtimeVersion.backend_version), electron API=$($runtimeVersion.expected_electron_api_version), expected=$ExpectedVersion."
    }
    $unexpectedLlmFiles = @(Get-ChildItem -Path $qaDataRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -ieq ".gguf" -or $_.Name -ieq "llama-server.exe" })
    if ($unexpectedLlmFiles) {
        throw "Fresh launch downloaded LLM/runtime files while AI cleanup was disabled: $($unexpectedLlmFiles.FullName -join ', ')"
    }
    Write-Host "Fresh installed launch passed without initializing or downloading an LLM."

    # The installer ships the pinned base.en speech model and its MIT notices,
    # so a fresh profile must report it installed (bundled) without any download.
    $bundledModelDir = Join-Path $backendBundlePath "_internal\bundled_models\base.en"
    foreach ($bundledFile in @("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")) {
        if (-not (Test-Path -LiteralPath (Join-Path $bundledModelDir $bundledFile) -PathType Leaf)) {
            throw "Installed backend is missing the bundled speech model file $bundledFile."
        }
    }
    $bundledNotice = Join-Path $backendBundlePath "_internal\bundled-base.en-NOTICE.txt"
    if (-not (Test-Path -LiteralPath $bundledNotice -PathType Leaf) -or
        -not (Select-String -LiteralPath $bundledNotice -SimpleMatch "Copyright (c) 2022 OpenAI" -Quiet) -or
        -not (Select-String -LiteralPath $bundledNotice -SimpleMatch "Copyright (c) 2023 SYSTRAN" -Quiet)) {
        throw "Installed backend is missing the bundled speech model's MIT notices."
    }
    $whisperModels = Invoke-AuthenticatedJson -Uri $whisperModelsUrl -Token $authToken
    $bundledRow = @($whisperModels.models | Where-Object { $_.model_size -eq "base.en" -and $_.installed -eq $true -and $_.bundled -eq $true })
    if ($bundledRow.Count -ne 1) {
        throw "Fresh installed profile did not report the bundled base.en speech model as installed."
    }
    Write-Host "Installed app ships the bundled base.en speech model and its notices; fresh profile reports it installed."

    # Prove the packaged backend can perform a real outbound HTTPS download,
    # persist it into the isolated Windows data root, verify its pinned SHA,
    # and load-check the ONNX payload. This ~1.1 MB wake backbone exercises the
    # exact download/atomic-promotion machinery without pulling a multi-GB LLM.
    $downloadStart = Invoke-AuthenticatedJson -Uri $wakeDownloadUrl -Token $authToken -Method Post
    if ($downloadStart.ok -ne $true -or $downloadStart.background -ne $true) {
        throw "Installed-app download did not start as a background job."
    }
    $downloadDeadline = (Get-Date).AddSeconds(120)
    do {
        Start-Sleep -Milliseconds 500
        $downloadState = Invoke-AuthenticatedJson -Uri $wakeDownloadStateUrl -Token $authToken
    } while ($downloadState.active -eq $true -and (Get-Date) -lt $downloadDeadline)
    if ($downloadState.active -eq $true) {
        throw "Installed-app download did not finish within 120 seconds."
    }
    if ($downloadState.downloaded -ne $true -or $downloadState.verified -ne $true -or $downloadState.loadable -ne $true -or $downloadState.error) {
        throw "Installed-app download failed verification/loadability: $($downloadState | ConvertTo-Json -Compress)"
    }
    $wakeModelPath = Join-Path $qaDataRoot "wake_models\melspectrogram.onnx"
    if (-not (Test-Path -LiteralPath $wakeModelPath -PathType Leaf)) {
        throw "Verified wake model was not persisted at $wakeModelPath."
    }
    $wakeModel = Get-Item -LiteralPath $wakeModelPath
    $wakeHash = (Get-FileHash -LiteralPath $wakeModelPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($wakeModel.Length -ne 1087958 -or $wakeHash -ne "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f") {
        throw "Installed-app download payload mismatch: bytes=$($wakeModel.Length), sha256=$wakeHash."
    }
    Write-Host "Installed backend downloaded, checksum-verified, and load-verified the 1,087,958-byte wake model."

    # The installed app and its backend must be gone before NSIS uninstall runs.
    Stop-BetterFingersProcesses -Process $appProcess
    Assert-NoRunningBetterFingers
    Assert-PortReleased

    $uninstaller = Get-ChildItem -Path $installDir -Filter "Uninstall*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $uninstaller) {
        throw "Uninstaller not found in ${installDir} (looked for Uninstall*.exe)"
    }
    $uninstallerPath = $uninstaller.FullName
    Assert-AuthenticodeStatus `
        -Path $uninstallerPath `
        -Expected $ExpectedSignatureStatus `
        -Label "Uninstaller" `
        -ExpectedSubject $ExpectedSignerSubject `
        -RequireTimestamp:($ExpectedSignatureStatus -eq "Valid")

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

    if ($uninstallRegPath -and (Test-Path $uninstallRegPath)) {
        throw "Uninstall left a registry entry behind: $uninstallRegPath"
    }

    # Default uninstall is deliberately conservative: program files go, user
    # data does not. This includes custom override roots, which the uninstaller
    # is forbidden to discover or follow.
    if (-not (Test-Path -LiteralPath $wakeModelPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $wakeModelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $wakeHash) {
        throw "Default uninstall removed or changed downloaded model data."
    }
    if ($PreviousInstallerPath -ne "") {
        if ((Get-FileHash -LiteralPath $seedSettingsPath -Algorithm SHA256).Hash -ne $seedSettingsHash -or
            (Get-FileHash -LiteralPath $seedModelPath -Algorithm SHA256).Hash -ne $seedModelHash) {
            throw "Default uninstall changed preserved settings or model data."
        }
    }

    if ($ExerciseCleanupCategories) {
        if ($canonicalDataRootExistedBefore) {
            throw "Refusing category cleanup smoke because canonical data already existed before this run: $canonicalDataRoot"
        }
        if ($electronDataRootExistedBefore) {
            throw "Refusing category cleanup smoke because Electron data already existed before this run: $electronDataRoot"
        }
        $categoryCases = @(
            @{ Flag = "/BF_DELETE_MODELS"; Selected = @("models\smoke.bin", "wake_models\smoke.bin", "tts\kokoro_onnx\smoke.bin"); ElectronSelected = @() },
            @{ Flag = "/BF_DELETE_RECORDINGS"; Selected = @("recordings\smoke.wav", "voices\smoke.wav"); ElectronSelected = @() },
            @{ Flag = "/BF_DELETE_HISTORY"; Selected = @("draft_history.json", "history.db", "exports\smoke.txt"); ElectronSelected = @() },
            @{ Flag = "/BF_DELETE_SETTINGS"; Selected = @("profiles\smoke.yaml", "contacts.json", "launcher_workflows.json", "persona_drafts.json"); ElectronSelected = @("Local Storage\leveldb\smoke.ldb", "overlay-position.json") },
            @{ Flag = "/BF_DELETE_LOGS"; Selected = @("tmp\smoke.tmp", "logs\smoke.log", "debug.log", "audio_privacy_journal.json"); ElectronSelected = @("Cache\smoke.bin", "sidecar_backend_raw.log") }
        )
        $allCategoryPaths = @($categoryCases | ForEach-Object { $_.Selected } | ForEach-Object { $_ })
        $allElectronPaths = @($categoryCases | ForEach-Object { $_.ElectronSelected } | ForEach-Object { $_ })
        foreach ($case in $categoryCases) {
            Install-Silently -Path $InstallerPath
            foreach ($relativePath in $allCategoryPaths) {
                $target = Join-Path $canonicalDataRoot $relativePath
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
                [IO.File]::WriteAllText($target, "owned installer cleanup smoke", [Text.Encoding]::UTF8)
            }
            foreach ($relativePath in $allElectronPaths) {
                $target = Join-Path $electronDataRoot $relativePath
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
                [IO.File]::WriteAllText($target, "owned installer cleanup smoke", [Text.Encoding]::UTF8)
            }
            $metadata = Get-InstalledMetadata
            $categoryUninstaller = Get-ChildItem -Path $installDir -Filter "Uninstall*.exe" | Select-Object -First 1
            if (-not $categoryUninstaller) { throw "Category cleanup uninstaller was not found." }
            $categoryProcess = Start-Process -FilePath $categoryUninstaller.FullName `
                -ArgumentList @("/S", $case.Flag) -Wait -NoNewWindow -PassThru
            if ($categoryProcess.ExitCode -ne 0) {
                throw "Category cleanup $($case.Flag) failed with exit code $($categoryProcess.ExitCode)."
            }
            foreach ($relativePath in $allCategoryPaths) {
                $exists = Test-Path -LiteralPath (Join-Path $canonicalDataRoot $relativePath)
                if ($case.Selected -contains $relativePath) {
                    if ($exists) { throw "$($case.Flag) left selected data behind: $relativePath" }
                } elseif (-not $exists) {
                    throw "$($case.Flag) removed an unselected category path: $relativePath"
                }
            }
            foreach ($relativePath in $allElectronPaths) {
                $exists = Test-Path -LiteralPath (Join-Path $electronDataRoot $relativePath)
                if ($case.ElectronSelected -contains $relativePath) {
                    if ($exists) { throw "$($case.Flag) left selected Electron data behind: $relativePath" }
                } elseif (-not $exists) {
                    throw "$($case.Flag) removed an unselected Electron path: $relativePath"
                }
            }
            if (Test-Path -LiteralPath $metadata.PSPath) {
                throw "$($case.Flag) left an uninstall registry entry behind."
            }
        }
        Write-Host "Every optional uninstall category removed only its selected canonical and Electron paths."
    }

    $legs = if ($PreviousInstallerPath -ne "") { "install + upgrade + uninstall" } else { "install + uninstall" }
    Write-Host "Installer smoke test passed ($legs, exact identity/signature/version metadata, no-LLM fresh launch, real verified download, authenticated backend health, and clean uninstall)."
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
    if (-not $canonicalDataRootExistedBefore -and (Test-Path -LiteralPath $canonicalDataRoot)) {
        # The test owned this previously-absent exact root. Never clean a root
        # that predated the run.
        Remove-Item -LiteralPath $canonicalDataRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not $electronDataRootExistedBefore -and (Test-Path -LiteralPath $electronDataRoot)) {
        # Same rule for the Electron folder: only a root this run created.
        Remove-Item -LiteralPath $electronDataRoot -Recurse -Force -ErrorAction SilentlyContinue
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
