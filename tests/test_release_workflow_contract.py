"""Fail-closed publication contract for v1.1.0-alpha.1 and later tags."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/build-installer.yml"


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
