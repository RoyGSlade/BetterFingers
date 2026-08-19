"""Fail-closed publication contract for v1.1.0-alpha.1 and later tags."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/build-installer.yml"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
INSTALLER_SMOKE = ROOT / "tools/smoke_installer.ps1"


def _workflow_text():
    return WORKFLOW.read_text(encoding="utf-8")


def _publish_block():
    text = _workflow_text()
    return text.split("\n  publish-release:\n", 1)[1]


def _draft_block():
    text = _workflow_text()
    return text.split("\n  draft-release:\n", 1)[1].split(
        "\n  publish-release:\n", 1
    )[0]


def test_tag_publication_qualifies_a_private_draft_before_approval():
    draft = _draft_block()
    publish = _publish_block()
    assert "if: startsWith(github.ref, 'refs/tags/')" in draft
    assert "environment: release" not in draft
    assert "name: BetterFingers ${{ github.ref_name }}" in draft
    assert "body: |" in draft
    assert "draft: true" in draft
    assert "prerelease: ${{ steps.release_kind.outputs.prerelease }}" in draft
    assert "make_latest: false" in draft
    assert "generate_release_notes: false" in draft
    assert "Verify every downloaded draft asset" in draft

    assert "needs: draft-release" in publish
    assert "environment: release" in publish
    assert "Reverify private draft before public promotion" in publish
    assert "gh release edit" in publish
    assert "--draft=false --prerelease=true --latest=false" in publish
    assert "--draft=false --prerelease=false --latest" in publish
    assert "draft: true" not in publish


def test_no_checkout_release_jobs_bind_gh_to_the_workflow_repository():
    for block in (_draft_block(), _publish_block()):
        assert "GH_REPO: ${{ github.repository }}" in block


def test_release_body_is_explicit_about_signed_experimental_limits():
    block = _draft_block()
    for required in (
        "code-signed release candidate",
        "update channel is `${{ steps.release_kind.outputs.channel }}`",
        "exact Windows signing mode for this tag is `${{ needs.windows-installer.outputs.signing_mode }}`",
        "Verify the installer signature and SHA-256 sidecar before running it",
        "do not disable Windows security controls",
        "language model used for AI cleanup is optional and disabled on a fresh install",
        "Do not use this alpha for highly sensitive dictation",
        "Report reproducible problems at https://github.com/RoyGSlade/BetterFingers/issues",
    ):
        assert required in block

    workflow = _workflow_text()
    assert "signing_mode: ${{ steps.signing.outputs.mode }}" in workflow


def test_release_keeps_all_qualification_artifacts():
    block = _draft_block()
    for pattern in (
        "release-assets/windows/*.exe",
        "release-assets/windows/*.exe.sha256",
        "release-assets/windows/*.exe.signature.txt",
        "release-assets/windows/*.exe.authenticode.json",
        "release-assets/windows/*.exe.blockmap",
        "release-assets/windows/${{ steps.release_kind.outputs.channel }}.yml",
        "release-assets/linux/*.AppImage",
        "release-assets/linux/*.AppImage.sha256",
        "release-assets/sbom/*.cdx.json",
    ):
        assert pattern in block


def test_linux_appimage_smoke_does_not_disable_electron_sandbox():
    assert "--no-sandbox" not in _workflow_text()


def test_linux_release_repairs_a_missing_locked_electron_binary_before_tests():
    workflow = _workflow_text()
    block = workflow.split("\n  linux-appimage:\n", 1)[1].split(
        "\n  sbom:\n", 1
    )[0]
    install = "run: npm ci"
    repair = "run: npm run fix:electron"
    unit_tests = "run: npm run test:unit"
    assert install in block
    assert repair in block
    assert unit_tests in block
    assert block.index(install) < block.index(repair) < block.index(unit_tests)


def test_windows_installer_creates_build_directory_before_smoke_log():
    workflow = _workflow_text()
    block = workflow.split("      - name: Run smoke suite\n", 1)[1].split(
        "\n      # Windows code signing", 1
    )[0]
    mkdir = "New-Item -ItemType Directory -Force -Path build | Out-Null"
    assert mkdir in block
    assert block.index(mkdir) < block.index("Tee-Object -FilePath build/pytest-smoke.log")


def test_first_release_history_is_parsed_without_expanding_a_null_tag():
    workflow = _workflow_text()
    block = workflow.split(
        "      - name: Download previous release installer (replacement continuity coverage)\n",
        1,
    )[1].split("\n      - name: Smoke check installer", 1)[0]
    assert '$prevTag = ""' in block
    assert "ForEach-Object { $_.tagName }" in block
    assert "Select-Object -ExpandProperty tagName" not in block
    assert 'Write-Host "No previous release found; skipping replacement/continuity coverage."' in block
    assert "--exclude-pre-releases" not in block
    assert 'Where-Object { $_.name -like "BetterFingers-Setup-*-x64.exe" }' in block


def test_release_identity_and_unsigned_policy_fail_closed():
    workflow = _workflow_text()
    assert "Package version '$version' does not match VERSION '$versionFile'." in workflow
    assert "Tag '${{ github.ref_name }}' does not match package version" in workflow
    assert 'expected exactly NotSigned' in workflow
    assert "Every Windows tag must be signed." in workflow
    assert 'if ("${{ github.ref_type }}" -eq "tag")' in workflow
    assert "Unsigned builds are allowed only for manual qualification runs." in workflow


def test_azure_signing_account_is_wired_conditionally_and_partial_config_fails():
    workflow = _workflow_text()
    for required in (
        'AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE',
        'AZURE_TRUSTED_SIGNING_PUBLISHER_NAME',
        'AZURE_TENANT_ID',
        'AZURE_CLIENT_ID',
        'AZURE_CLIENT_SECRET',
        'BETTERFINGERS_SIGNING_MODE: ${{ steps.signing.outputs.mode }}',
        'Azure signing is partially configured.',
        'Azure and PFX signing are both configured',
        'PFX signing is partially configured.',
        'mode=azure',
        'mode=pfx',
        'mode=unsigned',
    ):
        assert required in workflow

    configure = workflow.split("      - name: Configure Windows code signing\n", 1)[1].split(
        "\n      # Runs electron-vite build", 1
    )[0]
    build = workflow.split("      - name: Build installer (electron-builder)\n", 1)[1].split(
        "\n      - name: Clean up code-signing certificate", 1
    )[0]
    assert "GITHUB_ENV" not in configure
    assert "AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}" in build
    assert "CSC_LINK: ${{ steps.signing.outputs.cert_path }}" in build


def test_installer_artifact_name_and_installed_smoke_contract_are_exact():
    workflow = _workflow_text()
    assert 'BetterFingers-Setup-$version-x64.exe' in workflow
    assert '-ExpectedVersion' in workflow
    assert '-ExpectedSignatureStatus' in workflow
    assert '$args += "-ExerciseCleanupCategories"' in workflow
    assert 'tools/smoke_installer.ps1' in workflow


def test_updater_assets_are_validated_before_upload_and_before_promotion():
    workflow = _workflow_text()
    draft = _draft_block()
    publish = _publish_block()
    for required in (
        'Validate updater metadata and blockmap',
        r'$metadata = Join-Path "app\release" "$channel.yml"',
        '$blockmap = "$installer.blockmap"',
        '[Security.Cryptography.SHA512]::Create()',
        "Updater metadata SHA-512 does not match the signed installer.",
        '${{ steps.updater.outputs.blockmap }}',
        '${{ steps.updater.outputs.metadata }}',
    ):
        assert required in workflow
    for block in (draft, publish):
        assert ".exe.authenticode.json" in block
        assert ".exe.blockmap" in block
        assert "sha512" in block
        assert "Valid" in block


def test_channel_classification_keeps_alpha_and_stable_isolated():
    draft = _draft_block()
    publish = _publish_block()
    assert 'if [[ "$GITHUB_REF_NAME" == *-* ]]' in draft
    assert 'echo "channel=alpha"' in draft
    assert 'echo "channel=latest"' in draft
    assert 'echo "prerelease=true"' in draft
    assert 'echo "prerelease=false"' in draft
    assert "grep -Fxq 'alpha.yml'" in publish
    assert "grep -Fxq 'latest.yml'" in publish


def test_publish_job_rehashes_downloaded_artifacts_and_redownloads_draft():
    draft = _draft_block()
    publish = _publish_block()
    assert '(cd release-assets/windows && sha256sum --check *.exe.sha256)' in draft
    assert '(cd release-assets/linux && sha256sum --check *.AppImage.sha256)' in draft
    assert 'Verify every downloaded draft asset' in draft
    assert 'gh release download "${GITHUB_REF_NAME}"' in draft
    assert "--pattern 'BetterFingers-Setup-*-x64.exe'" in draft
    assert 'sha256sum --check "$(basename "${checksums[0]}")"' in draft
    assert 'gh release download "$GITHUB_REF_NAME" --dir "$download_dir"' in publish
    assert 'openssl dgst -sha512 -binary' in draft
    assert 'openssl dgst -sha512 -binary' in publish


def test_installed_app_smoke_proves_no_llm_and_a_real_verified_download():
    smoke = INSTALLER_SMOKE.read_text(encoding="utf-8")
    for required in (
        'llm_enabled -ne $false',
        'llm_initialized -ne $false',
        'wake/models/melspectrogram/download',
        'wake/models/melspectrogram/download-state',
        '1087958',
        'ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f',
        'Assert-AuthenticodeStatus -Path $exePath',
        'Assert-AuthenticodeStatus -Path $backendExePath',
        'Assert-AuthenticodeStatus -Path $uninstallerPath',
        'ExpectedSignerSubject',
        'SignerCertificate.Subject',
        'DisplayVersion',
        'Publisher',
        'if ($versionInfo.FileDescription -ne "BetterFingers")',
    ):
        assert required in smoke


def test_installer_smoke_reads_http_error_status_across_powershell_versions():
    smoke = INSTALLER_SMOKE.read_text(encoding="utf-8")
    helper = smoke.split("function Get-HttpStatus {", 1)[1].split(
        "function Invoke-AuthenticatedJson {", 1
    )[0]
    assert "catch [System.Net.WebException]" not in helper
    assert "$response = $_.Exception.Response" in helper
    assert "return [int]$response.StatusCode" in helper


def test_installer_smoke_proves_upgrade_preservation_and_selective_cleanup():
    smoke = INSTALLER_SMOKE.read_text(encoding="utf-8")
    for required in (
        'obsolete-upgrade-sentinel.bin',
        'Upgrade left an obsolete program file behind',
        '$seedSettingsHash',
        '$seedModelHash',
        'Expected exactly one BetterFingers uninstall entry',
        'Default uninstall removed or changed downloaded model data',
        '[switch]$ExerciseCleanupCategories',
        '/BF_DELETE_MODELS',
        '/BF_DELETE_RECORDINGS',
        '/BF_DELETE_HISTORY',
        '/BF_DELETE_SETTINGS',
        '/BF_DELETE_LOGS',
        'removed an unselected category path',
        '$canonicalDataRootExistedBefore',
    ):
        assert required in smoke


def test_azure_signer_subject_is_enforced_on_artifact_and_installed_payloads():
    workflow = _workflow_text()
    smoke = INSTALLER_SMOKE.read_text(encoding="utf-8")
    assert "$signature.SignerCertificate.Subject" in workflow
    assert "$signerSubject -cne $env:AZURE_EXPECTED_PUBLISHER" in workflow
    assert '$args += @("-ExpectedSignerSubject", $env:AZURE_EXPECTED_PUBLISHER)' in workflow
    assert '$actualSubject -cne $ExpectedSubject' in smoke
    assert smoke.count('-ExpectedSubject $ExpectedSignerSubject') == 4


def test_windows_python_suites_isolate_chunks_and_files_to_release_memory():
    installer = _workflow_text()
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    for workflow in (installer, ci):
        assert 'Get-ChildItem -Path tests -Filter "test_*.py" -File' in workflow
        assert "$chunkCount = 8" in workflow
        assert "$chunkIndex = ${{ matrix.chunk }}" in workflow
        assert "foreach ($testFile in $chunk)" in workflow
        assert "timeout-minutes: 45" in workflow
        assert "Start-Process -FilePath (Get-Command python).Source" in workflow
        assert "$process.WaitForExit(300000)" in workflow
        assert "$process.Kill($true)" in workflow
        assert "exceeded the 5-minute per-file timeout" in workflow

    for workflow in (installer, ci):
        assert "chunk: [0, 1, 2, 3, 4, 5, 6, 7]" in workflow


def test_ci_preserves_required_windows_check_as_chunk_aggregator():
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    block = ci.split("\n  python-tests-windows:\n", 1)[1].split("\n  node:\n", 1)[0]
    assert "name: python-tests (windows-latest / py3.13)" in block
    assert "if: always()" in block
    assert "needs: python-tests-windows-chunk" in block
    assert 'run: test "$CHUNK_RESULT" = "success"' in block
