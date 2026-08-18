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


def test_tag_publication_is_an_approval_gated_draft_prerelease():
    block = _publish_block()
    assert "if: startsWith(github.ref, 'refs/tags/')" in block
    assert "environment: release" in block
    assert "name: BetterFingers ${{ github.ref_name }}" in block
    assert "body: |" in block
    assert "draft: true" in block
    assert "prerelease: true" in block
    assert "make_latest: false" in block
    assert "generate_release_notes: false" in block


def test_friend_alpha_release_body_is_explicit_about_unsigned_experimental_limits():
    block = _publish_block()
    for required in (
        "unsigned public alpha for invited friend testing",
        "not a broadly qualified stable release",
        "exact Windows signing mode for this tag is `${{ needs.windows-installer.outputs.signing_mode }}`",
        "An unsigned Windows build can trigger Microsoft SmartScreen",
        "Verify the SHA-256 sidecar before running it",
        "do not disable Windows security controls",
        "language model used for AI cleanup is optional and disabled on a fresh install",
        "Do not use this alpha for highly sensitive dictation",
        "Report reproducible problems at https://github.com/RoyGSlade/BetterFingers/issues",
    ):
        assert required in block

    workflow = _workflow_text()
    assert "signing_mode: ${{ steps.signing.outputs.mode }}" in workflow


def test_release_keeps_all_qualification_artifacts():
    block = _publish_block()
    for pattern in (
        "release-assets/windows/*.exe",
        "release-assets/windows/*.exe.sha256",
        "release-assets/windows/*.exe.signature.txt",
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
    assert "Stable Windows tags must be signed." in workflow
    assert "$precedenceVersion = ($releaseVersion -split '\\+', 2)[0]" in workflow
    assert "$precedenceVersion -notmatch '-'" in workflow


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
    assert 'tools/smoke_installer.ps1' in workflow


def test_publish_job_rehashes_downloaded_artifacts_and_redownloads_draft():
    block = _publish_block()
    assert '(cd release-assets/windows && sha256sum --check *.exe.sha256)' in block
    assert '(cd release-assets/linux && sha256sum --check *.AppImage.sha256)' in block
    assert 'Verify draft release download and checksum' in block
    assert 'gh release download "${GITHUB_REF_NAME}"' in block
    assert "--pattern 'BetterFingers-Setup-*-x64.exe'" in block
    assert 'sha256sum --check "$(basename "${checksums[0]}")"' in block


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
