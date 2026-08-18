"""Static fail-closed contract for the production Windows signing path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNER = ROOT / "tools" / "sign_windows_artifacts.ps1"
BUILD = ROOT / "tools" / "build_and_sign_windows.ps1"
HOOK = ROOT / "app" / "scripts" / "azure-artifact-signing.cjs"
CONFIG = ROOT / "app" / "electron-builder.config.cjs"
DOC = ROOT / "docs" / "release" / "WINDOWS_SIGNING.md"


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
        "['.exe', '.dll', '.msi', '.msix']",
        "signingHashAlgorithms: ['sha256']",
        "require('./scripts/azure-artifact-signing.cjs')",
    ):
        assert required in config
    assert "configuration.path" in hook
    assert "sign_windows_artifacts.ps1" in hook
    assert "BETTERFINGERS_SIGNING_HOOK_REPORT_DIR" in hook
    assert "result.status !== 0" in hook


def test_wrapper_rechecks_final_outputs_and_writes_a_common_signer_report():
    build = _read(BUILD)
    for required in (
        '$env:BETTERFINGERS_SIGNING_MODE = "azure-cli"',
        '"electron-builder", "--config", "electron-builder.config.cjs", "--win", "--x64"',
        '"-Path", $unpackedPath, $installerPath',
        '"-VerifyOnly"',
        '$subjects.Count -ne 1',
        'profileType = "Public Trust"',
        'BetterFingers-Windows-signing-report.json',
    ):
        assert required in build


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
