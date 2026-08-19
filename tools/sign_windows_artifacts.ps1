[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]]$Path,

    [string]$AccountName = "better-fingers",
    [string]$CertificateProfileName = "better-fingers",
    [string]$Endpoint = "https://wus2.codesigning.azure.net",
    [string]$TimestampUrl = "http://timestamp.acs.microsoft.com/",
    [string]$SignToolPath = "",
    [string]$DlibPath = "",
    [string]$ExpectedSignerSubject = "",
    [string]$CorrelationId = "",
    [string]$ReportPath = "",
    [switch]$VerifyOnly,
    [switch]$SkipAzureCliPreflight
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$minimumSignToolVersion = [Version]"10.0.2261.755"
$eligibleExtensions = @(".exe", ".dll", ".msi", ".msix")

function Resolve-ExistingFile {
    param(
        [string]$Candidate,
        [string]$Label
    )

    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        return $null
    }

    $resolved = Resolve-Path -LiteralPath $Candidate -ErrorAction SilentlyContinue
    if ($null -eq $resolved -or -not (Test-Path -LiteralPath $resolved.Path -PathType Leaf)) {
        throw "$Label was not found at '$Candidate'."
    }
    return $resolved.Path
}

function Get-SignToolFileVersion {
    param([string]$ResolvedSignToolPath)

    $versionInfo = (Get-Item -LiteralPath $ResolvedSignToolPath).VersionInfo
    $candidates = @(
        [string]$versionInfo.FileVersionRaw,
        [string]$versionInfo.ProductVersionRaw,
        [string]$versionInfo.FileVersion,
        [string]$versionInfo.ProductVersion
    )
    foreach ($candidate in $candidates) {
        $match = [regex]::Match($candidate, '(?<!\d)(\d+)\.(\d+)\.(\d+)\.(\d+)(?!\d)')
        if ($match.Success) {
            return [Version]$match.Value
        }
    }
    throw "Unable to read a valid SignTool SDK version from '$ResolvedSignToolPath' (FileVersion='$($versionInfo.FileVersion)', ProductVersion='$($versionInfo.ProductVersion)')."
}

function Resolve-SignTool {
    param([string]$RequestedPath)

    $explicit = Resolve-ExistingFile -Candidate $RequestedPath -Label "SignTool"
    if ($null -ne $explicit) {
        $resolved = $explicit
    } elseif (-not [string]::IsNullOrWhiteSpace($env:BETTERFINGERS_SIGNTOOL_PATH)) {
        $resolved = Resolve-ExistingFile -Candidate $env:BETTERFINGERS_SIGNTOOL_PATH -Label "SignTool"
    } else {
        $command = Get-Command signtool.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command) {
            $resolved = $command.Source
        } else {
            $resolved = $null
            $clientToolMatches = New-Object System.Collections.Generic.List[System.IO.FileInfo]
            foreach ($root in Get-ArtifactSigningInstallRoots) {
                Get-ChildItem -LiteralPath $root -Filter "signtool.exe" -File -Recurse -ErrorAction SilentlyContinue |
                    ForEach-Object { $clientToolMatches.Add($_) }
            }
            $clientTool = $clientToolMatches |
                Sort-Object @{ Expression = { $_.FullName -match "[\\/]x64[\\/]" }; Descending = $true },
                            @{ Expression = { $_.LastWriteTimeUtc }; Descending = $true } |
                Select-Object -First 1
            if ($null -ne $clientTool) {
                $resolved = $clientTool.FullName
            } elseif (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
                $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
                if (Test-Path -LiteralPath $kitsRoot -PathType Container) {
                    $resolved = Get-ChildItem -LiteralPath $kitsRoot -Directory |
                        ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" } |
                        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
                        Sort-Object -Descending |
                        Select-Object -First 1
                }
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($resolved)) {
        throw "SignTool.exe was not found. Install Microsoft Azure Artifact Signing Client Tools or the Windows SDK, or pass -SignToolPath."
    }

    $version = Get-SignToolFileVersion -ResolvedSignToolPath $resolved
    if ($version -lt $minimumSignToolVersion) {
        throw "SignTool $version is too old; Azure Artifact Signing requires $minimumSignToolVersion or later."
    }
    Write-Host "Using SignTool $version at $resolved"
    return $resolved
}

function Get-ArtifactSigningInstallRoots {
    $roots = New-Object System.Collections.Generic.List[string]
    $registryPatterns = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )

    foreach ($pattern in $registryPatterns) {
        Get-ItemProperty -Path $pattern -ErrorAction SilentlyContinue |
            Where-Object { [string]$_.DisplayName -match "Artifact Signing Client Tools" } |
            ForEach-Object {
                if (-not [string]::IsNullOrWhiteSpace([string]$_.InstallLocation)) {
                    $roots.Add([string]$_.InstallLocation)
                } elseif (-not [string]::IsNullOrWhiteSpace([string]$_.DisplayIcon)) {
                    $iconPath = ([string]$_.DisplayIcon).Trim('"').Split(',')[0]
                    $roots.Add((Split-Path -Parent $iconPath))
                }
            }
    }

    $programRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $relativeCandidates = @(
        "Artifact Signing Client Tools",
        "Azure Artifact Signing Client Tools",
        "Microsoft Artifact Signing Client Tools",
        "Microsoft\Artifact Signing Client Tools",
        "Microsoft\ArtifactSigningClientTools",
        "Microsoft\Azure Artifact Signing Client Tools"
    )
    foreach ($programRoot in $programRoots) {
        foreach ($relative in $relativeCandidates) {
            $candidate = Join-Path $programRoot $relative
            if (Test-Path -LiteralPath $candidate -PathType Container) {
                $roots.Add($candidate)
            }
        }
    }

    return @($roots | Sort-Object -Unique)
}

function Resolve-ArtifactSigningDlib {
    param([string]$RequestedPath)

    $explicit = Resolve-ExistingFile -Candidate $RequestedPath -Label "Azure Artifact Signing dlib"
    if ($null -ne $explicit) {
        return $explicit
    }
    if (-not [string]::IsNullOrWhiteSpace($env:BETTERFINGERS_ARTIFACT_SIGNING_DLIB_PATH)) {
        return Resolve-ExistingFile -Candidate $env:BETTERFINGERS_ARTIFACT_SIGNING_DLIB_PATH -Label "Azure Artifact Signing dlib"
    }

    $matches = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    foreach ($root in Get-ArtifactSigningInstallRoots) {
        Get-ChildItem -LiteralPath $root -Filter "Azure.CodeSigning.Dlib.dll" -File -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { $matches.Add($_) }
    }

    $selected = $matches |
        Sort-Object @{ Expression = { $_.FullName -match "[\\/]x64[\\/]" }; Descending = $true },
                    @{ Expression = { $_.LastWriteTimeUtc }; Descending = $true } |
        Select-Object -First 1
    if ($null -eq $selected) {
        throw "Azure.CodeSigning.Dlib.dll was not found. Install Microsoft.Azure.ArtifactSigningClientTools, or pass -DlibPath."
    }
    Write-Host "Using Azure Artifact Signing dlib at $($selected.FullName)"
    return $selected.FullName
}

function Get-EligibleArtifacts {
    param([string[]]$RequestedPaths)

    $targets = New-Object System.Collections.Generic.List[string]
    foreach ($requested in $RequestedPaths) {
        $resolved = Resolve-Path -LiteralPath $requested -ErrorAction SilentlyContinue
        if ($null -eq $resolved) {
            throw "Artifact path was not found: $requested"
        }

        foreach ($item in @($resolved)) {
            if (Test-Path -LiteralPath $item.Path -PathType Container) {
                Get-ChildItem -LiteralPath $item.Path -File -Recurse |
                    Where-Object { $eligibleExtensions -contains $_.Extension.ToLowerInvariant() } |
                    ForEach-Object { $targets.Add($_.FullName) }
            } else {
                $extension = [IO.Path]::GetExtension($item.Path).ToLowerInvariant()
                if ($eligibleExtensions -notcontains $extension) {
                    throw "Artifact '$($item.Path)' is not an EXE, DLL, MSI, or MSIX file."
                }
                $targets.Add($item.Path)
            }
        }
    }

    $uniqueTargets = @($targets | Sort-Object -Unique)
    if ($uniqueTargets.Count -eq 0) {
        throw "No distributable EXE, DLL, MSI, or MSIX artifacts were found under the requested path(s)."
    }
    return $uniqueTargets
}

function Invoke-SignTool {
    param(
        [string]$ResolvedSignToolPath,
        [string[]]$Arguments,
        [string]$Operation
    )

    & $ResolvedSignToolPath @Arguments | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool $Operation failed with exit code $LASTEXITCODE."
    }
}

function Assert-AzureCliSession {
    $az = Get-Command az -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $az) {
        throw "Azure CLI was not found. Install it and authenticate with 'az login' before signing."
    }
    & $az.Source account show --only-show-errors --query id --output tsv | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI has no usable signed-in account. Run 'az login' and select the subscription that owns the signing profile."
    }
}

function Get-VerifiedSignatureRecord {
    param(
        [string]$Target,
        [string]$ResolvedSignToolPath,
        [string]$RequiredSubject
    )

    Invoke-SignTool -ResolvedSignToolPath $ResolvedSignToolPath -Operation "verification for '$Target'" -Arguments @(
        "verify", "/v", "/debug", "/pa", "/all", $Target
    )

    $signature = Get-AuthenticodeSignature -FilePath $Target
    if ($signature.Status -ne "Valid") {
        throw "Authenticode verification for '$Target' returned $($signature.Status): $($signature.StatusMessage)"
    }
    if ($null -eq $signature.SignerCertificate) {
        throw "'$Target' has no signer certificate after SignTool reported success."
    }
    if ($null -eq $signature.TimeStamperCertificate) {
        throw "'$Target' has no RFC 3161 timestamp certificate; refusing a three-day Artifact Signing signature."
    }

    $subject = [string]$signature.SignerCertificate.Subject
    if (-not [string]::IsNullOrWhiteSpace($RequiredSubject) -and $subject -cne $RequiredSubject) {
        throw "Signer subject for '$Target' was '$subject'; expected exactly '$RequiredSubject'."
    }

    return [ordered]@{
        path = (Resolve-Path -LiteralPath $Target).Path
        sha256 = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant()
        signerSubject = $subject
        signerThumbprint = [string]$signature.SignerCertificate.Thumbprint
        timestampSubject = [string]$signature.TimeStamperCertificate.Subject
        timestampThumbprint = [string]$signature.TimeStamperCertificate.Thumbprint
    }
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Azure Artifact Signing with SignTool must run on Windows."
}
if ($Endpoint -cne "https://wus2.codesigning.azure.net") {
    throw "BetterFingers signing is pinned to the West US 2 endpoint https://wus2.codesigning.azure.net."
}
if ($AccountName -cne "better-fingers" -or $CertificateProfileName -cne "better-fingers") {
    throw "BetterFingers production signing requires account 'better-fingers' and certificate profile 'better-fingers'."
}
if ($TimestampUrl -cne "http://timestamp.acs.microsoft.com/") {
    throw "BetterFingers signing is pinned to the Artifact Signing timestamp service http://timestamp.acs.microsoft.com/."
}

$resolvedSignTool = Resolve-SignTool -RequestedPath $SignToolPath
$targets = @(Get-EligibleArtifacts -RequestedPaths $Path)
Write-Host "Discovered $($targets.Count) eligible Windows artifact(s):"
$targets | ForEach-Object { Write-Host "  $_" }

$metadataRoot = $null
$metadataPath = $null
try {
    if (-not $VerifyOnly) {
        if (-not $SkipAzureCliPreflight) {
            Assert-AzureCliSession
        }
        $resolvedDlib = Resolve-ArtifactSigningDlib -RequestedPath $DlibPath
        if ([string]::IsNullOrWhiteSpace($CorrelationId)) {
            $CorrelationId = "BetterFingers/$([Environment]::MachineName)/$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
        }

        $metadataRoot = Join-Path ([IO.Path]::GetTempPath()) ("betterfingers-artifact-signing-" + [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $metadataRoot | Out-Null
        $metadataPath = Join-Path $metadataRoot "metadata.json"
        $metadata = [ordered]@{
            Endpoint = $Endpoint
            CodeSigningAccountName = $AccountName
            CertificateProfileName = $CertificateProfileName
            CorrelationId = $CorrelationId
            ExcludeCredentials = @(
                "EnvironmentCredential",
                "WorkloadIdentityCredential",
                "ManagedIdentityCredential",
                "SharedTokenCacheCredential",
                "VisualStudioCredential",
                "VisualStudioCodeCredential",
                "AzurePowerShellCredential",
                "AzureDeveloperCliCredential",
                "InteractiveBrowserCredential"
            )
        }
        [IO.File]::WriteAllText(
            $metadataPath,
            ($metadata | ConvertTo-Json -Depth 4),
            (New-Object Text.UTF8Encoding($false))
        )

        foreach ($target in $targets) {
            Write-Host "Signing $target"
            Invoke-SignTool -ResolvedSignToolPath $resolvedSignTool -Operation "signing for '$target'" -Arguments @(
                "sign",
                "/v",
                "/debug",
                "/fd", "SHA256",
                "/tr", $TimestampUrl,
                "/td", "SHA256",
                "/dlib", $resolvedDlib,
                "/dmdf", $metadataPath,
                $target
            )
        }
    }

    $records = New-Object System.Collections.Generic.List[object]
    $observedSubject = ""
    foreach ($target in $targets) {
        $requiredSubject = if (-not [string]::IsNullOrWhiteSpace($ExpectedSignerSubject)) {
            $ExpectedSignerSubject
        } else {
            $observedSubject
        }
        $record = Get-VerifiedSignatureRecord -Target $target -ResolvedSignToolPath $resolvedSignTool -RequiredSubject $requiredSubject
        if ([string]::IsNullOrWhiteSpace($observedSubject)) {
            $observedSubject = [string]$record.signerSubject
        }
        $records.Add($record)
    }

    if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
        $reportDirectory = Split-Path -Parent ([IO.Path]::GetFullPath($ReportPath))
        if (-not (Test-Path -LiteralPath $reportDirectory -PathType Container)) {
            New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
        }
        $report = [ordered]@{
            accountName = $AccountName
            certificateProfileName = $CertificateProfileName
            endpoint = $Endpoint
            timestampUrl = $TimestampUrl
            signerSubject = $observedSubject
            verifiedAtUtc = [DateTime]::UtcNow.ToString("o")
            artifacts = $records.ToArray()
        }
        [IO.File]::WriteAllText(
            ([IO.Path]::GetFullPath($ReportPath)),
            ($report | ConvertTo-Json -Depth 6),
            (New-Object Text.UTF8Encoding($false))
        )
        Write-Host "Wrote signing verification report to $([IO.Path]::GetFullPath($ReportPath))"
    }

    Write-Host "Verified $($records.Count) Artifact Signing signature(s) with signer '$observedSubject'."
} finally {
    if ($null -ne $metadataRoot -and (Test-Path -LiteralPath $metadataRoot)) {
        Remove-Item -LiteralPath $metadataRoot -Recurse -Force
    }
}
