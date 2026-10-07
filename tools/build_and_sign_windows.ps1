[CmdletBinding()]
param(
    [string]$PythonPath = "",
    [string]$SignToolPath = "",
    [string]$DlibPath = "",
    [string]$ExpectedSignerSubject = "CN=Donaven Crenshaw, O=Donaven Crenshaw, L=Kingfisher, S=ok, C=US",
    [string]$CorrelationId = "",
    [switch]$SkipNodeInstall,
    [switch]$SkipUnitTests,
    [switch]$UsePreparedPayload
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "The signed BetterFingers Windows build must run on Windows."
}
if ([string]::IsNullOrWhiteSpace($ExpectedSignerSubject)) {
    throw "ExpectedSignerSubject must name the exact verified certificate subject."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$appRoot = Join-Path $repoRoot "app"
$signingScript = Join-Path $PSScriptRoot "sign_windows_artifacts.ps1"
$releaseRoot = Join-Path $appRoot "release"
$hookReportRoot = Join-Path $releaseRoot ".artifact-signing-hook-reports"
$finalReportPath = Join-Path $hookReportRoot "final-output-verification.json"
$backendBuildPayloadReportPath = Join-Path $hookReportRoot "backend-build-payload-verification.json"
$packagedNativePayloadReportPath = Join-Path $hookReportRoot "packaged-native-payload-verification.json"
$combinedReportPath = Join-Path $releaseRoot "BetterFingers-Windows-signing-report.json"

function Invoke-CheckedCommand {
    param(
        [string]$Command,
        [string[]]$Arguments,
        [string]$FailureMessage
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Get-EnvironmentSnapshot {
    param([string[]]$Names)

    $snapshot = @{}
    foreach ($name in $Names) {
        $item = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        $snapshot[$name] = if ($null -eq $item) { $null } else { [string]$item.Value }
    }
    return $snapshot
}

function Restore-EnvironmentSnapshot {
    param([hashtable]$Snapshot)

    foreach ($name in $Snapshot.Keys) {
        if ($null -eq $Snapshot[$name]) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        } else {
            Set-Item -LiteralPath "Env:$name" -Value $Snapshot[$name]
        }
    }
}

function Get-NativePayloadPaths {
    param(
        [string]$RootPath,
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $RootPath -PathType Container)) {
        throw "$Label root was not found: $RootPath"
    }
    $paths = @(Get-ChildItem -LiteralPath $RootPath -File -Recurse |
        Where-Object { @(".exe", ".dll", ".pyd", ".node") -contains $_.Extension.ToLowerInvariant() } |
        ForEach-Object { $_.FullName } |
        Sort-Object -Unique)
    if ($paths.Count -eq 0) {
        throw "$Label contained no EXE, DLL, PYD, or NODE payload files: $RootPath"
    }
    return $paths
}

function Get-RelativeArtifactMap {
    param(
        [string]$RootPath,
        [object[]]$Artifacts,
        [string]$Label
    )

    $resolvedRoot = (Resolve-Path -LiteralPath $RootPath).Path
    $rootPrefix = $resolvedRoot.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) +
        [IO.Path]::DirectorySeparatorChar
    $recordsByRelativePath = @{}
    foreach ($artifact in $Artifacts) {
        $artifactPath = [string]$artifact.path
        $resolvedArtifactPath = (Resolve-Path -LiteralPath $artifactPath).Path
        if (-not $resolvedArtifactPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "$Label report contained an artifact outside '$resolvedRoot': $resolvedArtifactPath"
        }
        $relativePath = $resolvedArtifactPath.Substring($rootPrefix.Length).Replace('\', '/')
        if ($recordsByRelativePath.ContainsKey($relativePath)) {
            throw "$Label report contained duplicate relative path '$relativePath'."
        }
        $recordsByRelativePath[$relativePath] = $artifact
    }
    return $recordsByRelativePath
}

function Assert-IdenticalArtifactMaps {
    param(
        [hashtable]$BuildArtifacts,
        [hashtable]$PackagedArtifacts
    )

    if ($BuildArtifacts.Count -ne $PackagedArtifacts.Count) {
        throw "Backend native payload changed during packaging: build count $($BuildArtifacts.Count), packaged count $($PackagedArtifacts.Count)."
    }
    $identityFields = @(
        "sha256",
        "signerSubject",
        "signerThumbprint",
        "timestampSubject",
        "timestampThumbprint"
    )
    foreach ($relativePath in $BuildArtifacts.Keys) {
        if (-not $PackagedArtifacts.ContainsKey($relativePath)) {
            throw "Backend native payload '$relativePath' was omitted during packaging."
        }
        foreach ($field in $identityFields) {
            $buildProperty = $BuildArtifacts[$relativePath].PSObject.Properties[$field]
            $packagedProperty = $PackagedArtifacts[$relativePath].PSObject.Properties[$field]
            if ($null -eq $buildProperty -or $null -eq $packagedProperty) {
                throw "Backend payload reports omitted required identity field '$field' for '$relativePath'."
            }
            $buildValue = [string]$buildProperty.Value
            $packagedValue = [string]$packagedProperty.Value
            if ($buildValue -cne $packagedValue) {
                throw "Backend native payload '$relativePath' changed '$field' during packaging."
            }
        }
    }
}

$requiredCommands = @("az", "node", "npm", "powershell.exe")
foreach ($commandName in $requiredCommands) {
    if ($null -eq (Get-Command $commandName -ErrorAction SilentlyContinue | Select-Object -First 1)) {
        throw "Required command '$commandName' was not found. See docs/release/WINDOWS_SIGNING.md."
    }
}
if (-not (Test-Path -LiteralPath $signingScript -PathType Leaf)) {
    throw "Signing script not found at $signingScript."
}

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
$resolvedPython = Resolve-Path -LiteralPath $PythonPath -ErrorAction SilentlyContinue
if ($null -eq $resolvedPython -or -not (Test-Path -LiteralPath $resolvedPython.Path -PathType Leaf)) {
    throw "Release Python was not found at '$PythonPath'. Create the repo .venv and install the locked Windows requirements first."
}
$PythonPath = $resolvedPython.Path

Invoke-CheckedCommand -Command "az" -Arguments @(
    "account", "show", "--only-show-errors", "--output", "none"
) -FailureMessage "Azure CLI has no usable signed-in account; run 'az login' first"
Invoke-CheckedCommand -Command $PythonPath -Arguments @(
    "-c", "import PyInstaller, fastapi"
) -FailureMessage "The release Python environment is missing PyInstaller or BetterFingers runtime dependencies"

if ([string]::IsNullOrWhiteSpace($CorrelationId)) {
    $CorrelationId = "BetterFingers/$([Environment]::MachineName)/$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
}

$environmentNames = @(
    "BETTERFINGERS_PYTHON",
    "BETTERFINGERS_SIGNING_MODE",
    "BETTERFINGERS_SIGNTOOL_PATH",
    "BETTERFINGERS_ARTIFACT_SIGNING_DLIB_PATH",
    "BETTERFINGERS_EXPECTED_SIGNER_SUBJECT",
    "BETTERFINGERS_SIGNING_CORRELATION_ID",
    "BETTERFINGERS_SIGNING_HOOK_REPORT_DIR",
    "BETTERFINGERS_SKIP_AZURE_CLI_PREFLIGHT"
)
$environmentSnapshot = Get-EnvironmentSnapshot -Names $environmentNames

try {
    $env:BETTERFINGERS_PYTHON = $PythonPath
    $env:BETTERFINGERS_SIGNING_MODE = "azure-cli"
    $env:BETTERFINGERS_SIGNING_CORRELATION_ID = $CorrelationId
    $env:BETTERFINGERS_SIGNING_HOOK_REPORT_DIR = $hookReportRoot
    $env:BETTERFINGERS_SKIP_AZURE_CLI_PREFLIGHT = "1"

    foreach ($entry in @(
        @{ Name = "BETTERFINGERS_SIGNTOOL_PATH"; Value = $SignToolPath },
        @{ Name = "BETTERFINGERS_ARTIFACT_SIGNING_DLIB_PATH"; Value = $DlibPath },
        @{ Name = "BETTERFINGERS_EXPECTED_SIGNER_SUBJECT"; Value = $ExpectedSignerSubject }
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$entry.Value)) {
            Remove-Item -LiteralPath "Env:$($entry.Name)" -ErrorAction SilentlyContinue
        } else {
            Set-Item -LiteralPath "Env:$($entry.Name)" -Value ([string]$entry.Value)
        }
    }

    if (Test-Path -LiteralPath $hookReportRoot) {
        Remove-Item -LiteralPath $hookReportRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $hookReportRoot -Force | Out-Null

    Push-Location $appRoot
    try {
        if (-not $UsePreparedPayload -and -not $SkipNodeInstall) {
            Invoke-CheckedCommand -Command "npm" -Arguments @("ci") -FailureMessage "npm dependency installation failed"
        }
        if (-not $UsePreparedPayload -and -not $SkipUnitTests) {
            Invoke-CheckedCommand -Command "npm" -Arguments @("run", "test:unit") -FailureMessage "app unit tests failed"
        }
        if (-not $UsePreparedPayload) {
            Invoke-CheckedCommand -Command "npm" -Arguments @("run", "build") -FailureMessage "renderer/main build failed"
            Invoke-CheckedCommand -Command "npm" -Arguments @("run", "build:backend") -FailureMessage "Windows backend build failed"
        }

        $backendBuildBundlePath = Join-Path $appRoot "resources\backend\betterfingers-backend"
        $backendBuildExecutablePath = Join-Path $backendBuildBundlePath "betterfingers-backend.exe"
        if (-not (Test-Path -LiteralPath $backendBuildBundlePath -PathType Container) -or
            -not (Test-Path -LiteralPath $backendBuildExecutablePath -PathType Leaf)) {
            throw "Expected PyInstaller onedir backend was not produced at $backendBuildExecutablePath."
        }
        $backendBuildNativePayloadPaths = @(Get-NativePayloadPaths `
            -RootPath $backendBuildBundlePath `
            -Label "Backend build bundle")

        # PyInstaller onedir keeps native modules visible. Sign every unsigned
        # EXE/DLL/PYD before electron-builder copies the payload, while keeping
        # already-valid Microsoft/vendor signatures intact.
        $backendSignParameters = @{
            Path = $backendBuildNativePayloadPaths
            ReportPath = $backendBuildPayloadReportPath
            CorrelationId = "$CorrelationId/backend-build-payload"
            PreserveValidSignatures = $true
            SkipAzureCliPreflight = $true
        }
        if (-not [string]::IsNullOrWhiteSpace($SignToolPath)) {
            $backendSignParameters.SignToolPath = $SignToolPath
        }
        if (-not [string]::IsNullOrWhiteSpace($DlibPath)) {
            $backendSignParameters.DlibPath = $DlibPath
        }
        if (-not [string]::IsNullOrWhiteSpace($ExpectedSignerSubject)) {
            $backendSignParameters.ExpectedSignerSubject = $ExpectedSignerSubject
        }
        try {
            & $signingScript @backendSignParameters
        } catch {
            throw "backend native-payload signing failed: $($_.Exception.Message)"
        }

        Invoke-CheckedCommand -Command "npx" -Arguments @(
            "electron-builder", "--config", "electron-builder.config.cjs", "--win", "--x64", "--publish", "never"
        ) -FailureMessage "signed Windows packaging failed"
    } finally {
        Pop-Location
    }

    $packageVersion = (Get-Content -Raw (Join-Path $appRoot "package.json") | ConvertFrom-Json).version
    $installerPath = Join-Path $releaseRoot "BetterFingers-Setup-$packageVersion-x64.exe"
    $releaseChannel = if ($packageVersion -match "-") { "alpha" } else { "latest" }
    $updateMetadataPath = Join-Path $releaseRoot "$releaseChannel.yml"
    $blockmapPath = "$installerPath.blockmap"
    $updaterConfigPath = Join-Path $releaseRoot "win-unpacked\resources\app-update.yml"
    $publisherIdentity = "CN=Donaven Crenshaw, O=Donaven Crenshaw, C=US"
    $updaterConfig = Get-Content -Raw -LiteralPath $updaterConfigPath
    $publisherPattern = '(?m)^publisherName:\s*\r?\n\s+-\s*[''"]?{0}[''"]?\s*$' -f [regex]::Escape($publisherIdentity)
    if ($updaterConfig -notmatch $publisherPattern) {
        throw "Packaged app-update.yml is missing the exact approved publisherName pin."
    }
    $checksumPath = "$installerPath.sha256"
    $unpackedPath = Join-Path $releaseRoot "win-unpacked"
    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
        throw "Expected signed installer was not produced at $installerPath."
    }
    if (-not (Test-Path -LiteralPath $unpackedPath -PathType Container)) {
        throw "Expected unpacked Windows application was not produced at $unpackedPath."
    }
    foreach ($updateAsset in @($updateMetadataPath, $blockmapPath)) {
        if (-not (Test-Path -LiteralPath $updateAsset -PathType Leaf)) {
            throw "Expected updater asset was not produced at $updateAsset."
        }
    }

    $installerName = Split-Path -Leaf $installerPath
    $metadata = Get-Content -Raw -LiteralPath $updateMetadataPath
    $escapedInstallerName = [regex]::Escape($installerName)
    $metadataPathPattern = '(?m)^path:\s*[''"]?{0}[''"]?\s*$' -f $escapedInstallerName
    if ($metadata -notmatch $metadataPathPattern) {
        throw "Updater metadata '$updateMetadataPath' does not name the exact signed installer '$installerName'."
    }
    $sha512Provider = [Security.Cryptography.SHA512]::Create()
    try {
        $installerSha512 = [Convert]::ToBase64String(
            $sha512Provider.ComputeHash([IO.File]::ReadAllBytes($installerPath))
        )
    } finally {
        $sha512Provider.Dispose()
    }
    $escapedSha512 = [regex]::Escape($installerSha512)
    $metadataShaPattern = '(?m)^sha512:\s*[''"]?{0}[''"]?\s*$' -f $escapedSha512
    if ($metadata -notmatch $metadataShaPattern) {
        throw "Updater metadata SHA-512 does not match the signed installer."
    }
    $installerSha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$installerSha256  $installerName" | Out-File -LiteralPath $checksumPath -Encoding ascii

    $applicationPath = Join-Path $unpackedPath "BetterFingers.exe"
    $packagedBackendBundlePath = Join-Path $unpackedPath "resources\backend\betterfingers-backend"
    $backendPath = Join-Path $packagedBackendBundlePath "betterfingers-backend.exe"
    $finalOutputPaths = @($installerPath, $applicationPath, $backendPath)
    foreach ($finalOutputPath in $finalOutputPaths) {
        if (-not (Test-Path -LiteralPath $finalOutputPath -PathType Leaf)) {
            throw "Expected BetterFingers final output was not produced at $finalOutputPath."
        }
    }

    # Invoke the verifier in-process so PowerShell receives an actual string
    # array. powershell.exe -File cannot bind multiple values to a script array
    # parameter reliably and instead binds the second path positionally.
    $verifyParameters = @{
        Path = $finalOutputPaths
        ReportPath = $finalReportPath
        VerifyOnly = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($SignToolPath)) {
        $verifyParameters.SignToolPath = $SignToolPath
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSignerSubject)) {
        $verifyParameters.ExpectedSignerSubject = $ExpectedSignerSubject
    }
    try {
        & $signingScript @verifyParameters
    } catch {
        throw "final SignTool verification failed: $($_.Exception.Message)"
    }

    $packagedNativePayloadPaths = @(Get-NativePayloadPaths `
        -RootPath $unpackedPath `
        -Label "Packaged application tree")
    $packagedVerifyParameters = @{
        Path = $packagedNativePayloadPaths
        ReportPath = $packagedNativePayloadReportPath
        VerifyOnly = $true
        PreserveValidSignatures = $true
    }
    if (-not [string]::IsNullOrWhiteSpace($SignToolPath)) {
        $packagedVerifyParameters.SignToolPath = $SignToolPath
    }
    try {
        & $signingScript @packagedVerifyParameters
    } catch {
        throw "packaged application native-payload verification failed: $($_.Exception.Message)"
    }

    $excludedVerificationReports = @(
        $finalReportPath,
        $backendBuildPayloadReportPath,
        $packagedNativePayloadReportPath
    )
    $hookReports = @(Get-ChildItem -LiteralPath $hookReportRoot -Filter "*.json" -File |
        Where-Object { $excludedVerificationReports -notcontains $_.FullName } |
        Sort-Object Name |
        ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json })
    if ($hookReports.Count -eq 0) {
        throw "electron-builder produced no per-artifact signing verification reports."
    }
    $finalReport = Get-Content -Raw -LiteralPath $finalReportPath | ConvertFrom-Json
    $backendBuildPayloadReport = Get-Content -Raw -LiteralPath $backendBuildPayloadReportPath | ConvertFrom-Json
    $packagedNativePayloadReport = Get-Content -Raw -LiteralPath $packagedNativePayloadReportPath | ConvertFrom-Json
    $hookArtifacts = @($hookReports | ForEach-Object { $_.artifacts } | ForEach-Object { $_ })
    foreach ($requiredName in @("BetterFingers.exe", (Split-Path -Leaf $installerPath), "*.__uninstaller.exe")) {
        $matchingHooks = @($hookArtifacts | Where-Object {
            (Split-Path -Leaf ([string]$_.path)) -like $requiredName -and
            [string]$_.verificationDisposition -eq "signed" -and
            [string]$_.signerSubject -ceq $ExpectedSignerSubject -and
            -not [string]::IsNullOrWhiteSpace([string]$_.timestampSubject)
        })
        if ($matchingHooks.Count -eq 0) {
            throw "Missing signed, timestamped hook verification for '$requiredName'."
        }
    }
    $finalArtifacts = @($finalReport.artifacts)
    $backendBuildPayloadArtifacts = @($backendBuildPayloadReport.artifacts)
    $packagedNativePayloadArtifacts = @($packagedNativePayloadReport.artifacts)
    if ($finalArtifacts.Count -ne $finalOutputPaths.Count) {
        throw "Expected $($finalOutputPaths.Count) BetterFingers final-output verification records; observed $($finalArtifacts.Count)."
    }
    $reportedFinalPaths = @($finalArtifacts | ForEach-Object { [string]$_.path })
    foreach ($finalOutputPath in $finalOutputPaths) {
        $resolvedFinalOutputPath = (Resolve-Path -LiteralPath $finalOutputPath).Path
        if ($reportedFinalPaths -cnotcontains $resolvedFinalOutputPath) {
            throw "Final-output verification report omitted '$resolvedFinalOutputPath'."
        }
    }

    if ([string]$backendBuildPayloadReport.operation -cne "sign-and-verify" -or
        $backendBuildPayloadReport.classificationComplete -ne $true) {
        throw "Backend build verification report did not contain a complete signing/preservation classification."
    }
    if ([string]$packagedNativePayloadReport.operation -cne "verify-only" -or
        $packagedNativePayloadReport.classificationComplete -ne $false) {
        throw "Packaged native-payload report did not identify itself as verify-only evidence."
    }
    if ($packagedNativePayloadArtifacts.Count -ne $packagedNativePayloadPaths.Count) {
        throw "Expected $($packagedNativePayloadPaths.Count) packaged application native signature records; observed $($packagedNativePayloadArtifacts.Count)."
    }
    $reportedPackagedPayloadPaths = @($packagedNativePayloadArtifacts | ForEach-Object { [string]$_.path })
    foreach ($payloadPath in $packagedNativePayloadPaths) {
        $resolvedPayloadPath = (Resolve-Path -LiteralPath $payloadPath).Path
        if ($reportedPackagedPayloadPaths -cnotcontains $resolvedPayloadPath) {
            throw "Packaged application verification report omitted '$resolvedPayloadPath'."
        }
    }

    $packagedBackendRoot = (Resolve-Path -LiteralPath $packagedBackendBundlePath).Path
    $packagedBackendPrefix = $packagedBackendRoot.TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    ) + [IO.Path]::DirectorySeparatorChar
    $backendPackagedPayloadArtifacts = @($packagedNativePayloadArtifacts |
        Where-Object {
            ([string]$_.path).StartsWith($packagedBackendPrefix, [StringComparison]::OrdinalIgnoreCase)
        })
    $backendBuildArtifactMap = Get-RelativeArtifactMap `
        -RootPath $backendBuildBundlePath `
        -Artifacts $backendBuildPayloadArtifacts `
        -Label "Backend build"
    $backendPackagedArtifactMap = Get-RelativeArtifactMap `
        -RootPath $packagedBackendBundlePath `
        -Artifacts $backendPackagedPayloadArtifacts `
        -Label "Packaged backend"
    Assert-IdenticalArtifactMaps `
        -BuildArtifacts $backendBuildArtifactMap `
        -PackagedArtifacts $backendPackagedArtifactMap

    $subjects = @($finalArtifacts |
        ForEach-Object { [string]$_.signerSubject } |
        Sort-Object -Unique)
    if ($subjects.Count -ne 1 -or [string]::IsNullOrWhiteSpace($subjects[0])) {
        throw "Expected one common signer subject across BetterFingers-owned final outputs; observed: $($subjects -join '; ')."
    }
    $buildTimeArtifacts = @($hookArtifacts + $backendBuildPayloadArtifacts)
    $buildTimeSignerSubjects = @($buildTimeArtifacts |
        ForEach-Object { [string]$_.signerSubject } |
        Sort-Object -Unique)
    $vendorPresignedArtifacts = @($buildTimeArtifacts |
        Where-Object { [string]$_.signerSubject -cne $subjects[0] })

    $combinedReport = [ordered]@{
        schemaVersion = 1
        packageVersion = $packageVersion
        accountName = "better-fingers"
        certificateProfileName = "better-fingers"
        profileType = "Public Trust"
        endpoint = "https://wus2.codesigning.azure.net"
        timestampUrl = "http://timestamp.acs.microsoft.com/"
        correlationId = $CorrelationId
        signerSubject = $subjects[0]
        verifiedAtUtc = [DateTime]::UtcNow.ToString("o")
        buildTimeVerifications = $hookArtifacts
        backendBuildPayloadVerifications = $backendBuildPayloadArtifacts
        backendPackagedPayloadVerifications = $backendPackagedPayloadArtifacts
        packagedNativePayloadVerifications = $packagedNativePayloadArtifacts
        buildTimeSignerSubjects = $buildTimeSignerSubjects
        vendorPresignedArtifacts = $vendorPresignedArtifacts
        finalOutputVerifications = $finalArtifacts
    }
    [IO.File]::WriteAllText(
        $combinedReportPath,
        ($combinedReport | ConvertTo-Json -Depth 8),
        (New-Object Text.UTF8Encoding($false))
    )

    Write-Host ""
    Write-Host "SIGNED BUILD COMPLETE"
    Write-Host "Installer: $installerPath"
    Write-Host "Updater metadata: $updateMetadataPath"
    Write-Host "Updater blockmap: $blockmapPath"
    Write-Host "SHA-256 sidecar: $checksumPath"
    Write-Host "Verification report: $combinedReportPath"
    Write-Host "Signer: $($subjects[0])"
} finally {
    Restore-EnvironmentSnapshot -Snapshot $environmentSnapshot
}
