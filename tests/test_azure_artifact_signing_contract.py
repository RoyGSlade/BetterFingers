"""Static fail-closed contract for the production Windows signing path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNER = ROOT / "tools" / "sign_windows_artifacts.ps1"
BUILD = ROOT / "tools" / "build_and_sign_windows.ps1"
HOOK = ROOT / "app" / "scripts" / "azure-artifact-signing.cjs"
CONFIG = ROOT / "app" / "electron-builder.config.cjs"
DOC = ROOT / "docs" / "release" / "WINDOWS_SIGNING.md"
SIGNING_SCRIPT = ROOT / "tools" / "sign_windows_artifacts.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_signing_identity_endpoint_timestamp_and_formats_are_pinned():
    signer = _read(SIGNER)
    for required in (
        '[string]$AccountName = "better-fingers"',
        '[string]$CertificateProfileName = "better-fingers"',
        '[string]$Endpoint = "https://wus2.codesigning.azure.net"',
        '[string]$TimestampUrl = "http://timestamp.acs.microsoft.com/"',
        '$eligibleExtensions = @(".exe", ".dll", ".msi", ".msix")',
        '[Version]"10.0.2261.755"',
    ):
        assert required in signer


def test_signing_uses_sha256_rfc3161_dlib_and_verifies_every_target():
    signer = _read(SIGNER)
    for required in (
        '"/fd", "SHA256"',
        '"/tr", $TimestampUrl',
        '"/td", "SHA256"',
        '"/dlib", $resolvedDlib',
        '"/dmdf", $metadataPath',
        '"verify", "/v", "/debug", "/pa", "/all", $Target',
        'Get-AuthenticodeSignature -FilePath $Target',
        '$signature.Status -ne "Valid"',
        '$null -eq $signature.TimeStamperCertificate',
    ):
        assert required in signer


def test_only_azure_cli_credential_is_left_enabled_and_metadata_is_ephemeral():
    signer = _read(SIGNER)
    exclude_block = signer.split("ExcludeCredentials = @(", 1)[1].split("\n            )", 1)[0]
    assert '"AzureCliCredential"' not in exclude_block
    for excluded in (
        "EnvironmentCredential",
        "WorkloadIdentityCredential",
        "ManagedIdentityCredential",
        "SharedTokenCacheCredential",
        "VisualStudioCredential",
        "VisualStudioCodeCredential",
        "AzurePowerShellCredential",
        "AzureDeveloperCliCredential",
        "InteractiveBrowserCredential",
    ):
        assert f'"{excluded}"' in exclude_block
    assert "Get-Command az" in signer
    assert "account show --only-show-errors" in signer
    assert "GetTempPath" in signer
    assert "Remove-Item -LiteralPath $metadataRoot -Recurse -Force" in signer


def test_electron_builder_signs_payload_before_packaging_and_fails_closed():
    config = _read(CONFIG)
    hook = _read(HOOK)
    for required in (
        "signingMode === 'azure-cli'",
        "packageBuild.forceCodeSigning = true",
        "['!.dll']",
        "signingHashAlgorithms: ['sha256']",
        "require('./scripts/azure-artifact-signing.cjs')",
    ):
        assert required in config
    assert "configuration.path" in hook
    assert "sign_windows_artifacts.ps1" in hook
    assert "BETTERFINGERS_SIGNING_HOOK_REPORT_DIR" in hook
    assert "result.status !== 0" in hook


def test_wrapper_rechecks_product_owned_final_outputs_in_process_and_reports_vendor_signers():
    build = _read(BUILD)
    for required in (
        '$env:BETTERFINGERS_SIGNING_MODE = "azure-cli"',
        '"electron-builder", "--config", "electron-builder.config.cjs", "--win", "--x64"',
        '$applicationPath = Join-Path $unpackedPath "BetterFingers.exe"',
        '$backendPath = Join-Path $unpackedPath "resources\\backend\\betterfingers-backend.exe"',
        '$finalOutputPaths = @($installerPath, $applicationPath, $backendPath)',
        'Path = $finalOutputPaths',
        'VerifyOnly = $true',
        '& $signingScript @verifyParameters',
        '$subjects = @($finalArtifacts |',
        '$subjects.Count -ne 1',
        'buildTimeSignerSubjects = $buildTimeSignerSubjects',
        'vendorPresignedArtifacts = $vendorPresignedArtifacts',
        'profileType = "Public Trust"',
        'BetterFingers-Windows-signing-report.json',
    ):
        assert required in build
    assert '"-Path", $unpackedPath, $installerPath' not in build


def test_new_production_signing_files_contain_no_secret_auth_contract():
    combined = "\n".join(_read(path) for path in (SIGNER, BUILD, HOOK, DOC))
    for forbidden in (
        "AZURE_CLIENT_SECRET",
        "AZURE_CLIENT_ID",
        "AZURE_TENANT_ID",
        "WIN_CERTIFICATE_BASE64",
        "WIN_CERTIFICATE_PASSWORD",
        "clientSecret",
    ):
        assert forbidden not in combined


def test_runbook_names_the_repeatable_build_and_sign_command():
    doc = _read(DOC)
    assert "Microsoft.Azure.ArtifactSigningClientTools" in doc
    assert "az login" in doc
    assert ".\\tools\\build_and_sign_windows.ps1" in doc
    assert "BetterFingers-Windows-signing-report.json" in doc


def test_signtool_version_detection_does_not_depend_on_branding_fileversion_only():
    script = _read(SIGNING_SCRIPT)

    assert "$versionInfo.FileVersionRaw" in script
    assert "$versionInfo.ProductVersionRaw" in script
    assert "$versionInfo.ProductVersion" in script
    assert "(?<!\\d)(\\d+)\\.(\\d+)\\.(\\d+)\\.(\\d+)(?!\\d)" in script
    assert "Unable to read a valid SignTool SDK version" in script


def test_single_signing_target_remains_an_array_under_strict_mode():
    script = _read(SIGNING_SCRIPT)

    assert "$targets = @(Get-EligibleArtifacts -RequestedPaths $Path)" in script


def test_signtool_console_output_does_not_pollute_verification_records():
    script = _read(SIGNING_SCRIPT)

    assert (
        "& $ResolvedSignToolPath @Arguments | ForEach-Object { Write-Host $_ }"
        in script
    )
    assert "artifacts = $records.ToArray()" in script
