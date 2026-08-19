[CmdletBinding()]
param(
    [string]$PythonPath = "",
    [string]$SignToolPath = "",
    [string]$DlibPath = "",
    [string]$ExpectedSignerSubject = "",
    [string]$CorrelationId = "",
    [switch]$SkipNodeInstall,
    [switch]$SkipUnitTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "The signed BetterFingers Windows build must run on Windows."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$appRoot = Join-Path $repoRoot "app"
$signingScript = Join-Path $PSScriptRoot "sign_windows_artifacts.ps1"
$releaseRoot = Join-Path $appRoot "release"
$hookReportRoot = Join-Path $releaseRoot ".artifact-signing-hook-reports"
$finalReportPath = Join-Path $hookReportRoot "final-output-verification.json"
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
        if (-not $SkipNodeInstall) {
            Invoke-CheckedCommand -Command "npm" -Arguments @("ci") -FailureMessage "npm dependency installation failed"
        }
        if (-not $SkipUnitTests) {
            Invoke-CheckedCommand -Command "npm" -Arguments @("run", "test:unit") -FailureMessage "app unit tests failed"
        }
        Invoke-CheckedCommand -Command "npm" -Arguments @("run", "build") -FailureMessage "renderer/main build failed"
        Invoke-CheckedCommand -Command "npm" -Arguments @("run", "build:backend") -FailureMessage "Windows backend build failed"
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
    $backendPath = Join-Path $unpackedPath "resources\backend\betterfingers-backend.exe"
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

    $hookReports = @(Get-ChildItem -LiteralPath $hookReportRoot -Filter "*.json" -File |
        Where-Object { $_.FullName -cne $finalReportPath } |
        Sort-Object Name |
        ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json })
    if ($hookReports.Count -eq 0) {
        throw "electron-builder produced no per-artifact signing verification reports."
    }
    $finalReport = Get-Content -Raw -LiteralPath $finalReportPath | ConvertFrom-Json
    $hookArtifacts = @($hookReports | ForEach-Object { $_.artifacts } | ForEach-Object { $_ })
    $finalArtifacts = @($finalReport.artifacts)
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

    $subjects = @($finalArtifacts |
        ForEach-Object { [string]$_.signerSubject } |
        Sort-Object -Unique)
    if ($subjects.Count -ne 1 -or [string]::IsNullOrWhiteSpace($subjects[0])) {
        throw "Expected one common signer subject across BetterFingers-owned final outputs; observed: $($subjects -join '; ')."
    }
    $buildTimeSignerSubjects = @($hookArtifacts |
        ForEach-Object { [string]$_.signerSubject } |
        Sort-Object -Unique)
    $vendorPresignedArtifacts = @($hookArtifacts |
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
