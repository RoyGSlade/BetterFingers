"""Fail-closed publication contract for v1.1.0-alpha.1 and later tags."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/build-installer.yml"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"


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


def test_windows_python_suites_isolate_chunks_and_files_to_release_memory():
    installer = _workflow_text()
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    for workflow in (installer, ci):
        assert 'Get-ChildItem -Path tests -Filter "test_*.py" -File' in workflow
        assert "$chunkCount = 8" in workflow
        assert "chunk: [0, 1, 2, 3, 4, 5, 6, 7]" in workflow
        assert "$chunkIndex = ${{ matrix.chunk }}" in workflow
        assert "foreach ($testFile in $chunk)" in workflow
        assert "python -m pytest -q $testFile.FullName" in workflow


def test_ci_preserves_required_windows_check_as_chunk_aggregator():
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    block = ci.split("\n  python-tests-windows:\n", 1)[1].split("\n  node:\n", 1)[0]
    assert "name: python-tests (windows-latest / py3.13)" in block
    assert "if: always()" in block
    assert "needs: python-tests-windows-chunk" in block
    assert 'run: test "$CHUNK_RESULT" = "success"' in block
