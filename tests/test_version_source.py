"""One build version source, enforced (D-0008, Wave 11 / Gate 11).

Before Wave 11 three files invented their own version and disagreed. These
tests make the repo-root ``VERSION`` file authoritative: every other place a
version appears must equal it, and a stale copy fails here rather than
shipping a wrong number into a user's support report.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import version  # noqa: E402

TARGET_VERSION = "0.2.0-alpha.1"


def test_version_file_holds_the_release_target():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == TARGET_VERSION
    assert version.APP_VERSION == TARGET_VERSION
    assert version.RELEASE_TAG == f"v{TARGET_VERSION}"


def test_backend_version_equals_app_version():
    assert version.BACKEND_VERSION == version.APP_VERSION


def test_electron_package_version_matches():
    """app/package.json is a copy, not a second source — keep it equal."""
    package = json.loads((ROOT / "app/package.json").read_text(encoding="utf-8"))
    assert package["version"] == version.APP_VERSION, (
        "app/package.json version drifted from VERSION; electron-builder names "
        "release artifacts from this field, so a stale value ships a mislabelled installer"
    )


def test_runtime_version_endpoint_reports_the_single_source():
    """/runtime/version must not re-hardcode a literal."""
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    match = re.search(
        r"@app\.get\(\"/runtime/version\"\).*?\n\n", source, re.DOTALL
    )
    assert match, "could not locate the /runtime/version handler in server.py"
    handler = match.group(0)
    assert "version.BACKEND_VERSION" in handler or "BACKEND_VERSION" in handler, (
        "/runtime/version still hard-codes a version literal instead of reading version.py"
    )
    assert not re.search(r'"backend_version":\s*"\d', handler), (
        "/runtime/version hard-codes a numeric version literal (D-0008)"
    )


def test_support_report_version_block_reports_the_single_source():
    source = (ROOT / "server.py").read_text(encoding="utf-8")
    block = re.search(r'version_block = \{[^}]*\}', source)
    assert block, "could not locate the support-report version block in server.py"
    assert not re.search(r'"backend_version":\s*"\d', block.group(0)), (
        "the support report hard-codes a version literal (D-0008)"
    )


def test_no_stray_version_literals_in_shipping_pages():
    """The preview's dead marketing v1.2.0 must not come back anywhere."""
    offenders = []
    for path in (ROOT / "app/src/renderer").rglob("*.html"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"\bv\d+\.\d+\.\d+[\w.\-]*", text):
            offenders.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
    assert not offenders, (
        "renderer pages must render the version from the app:get-version bridge, "
        f"never a literal: {offenders}"
    )


@pytest.mark.parametrize("literal", ["0.1.0", "1.2.0"])
def test_retired_versions_are_gone_from_the_version_chain(literal):
    """The exact pre-Wave-11 conflicting numbers, in the files that carried them."""
    watched = [
        ROOT / "app/package.json",
        ROOT / "app/src/renderer/signal-desk.html",
        ROOT / "app/src/renderer/signal-desk-preview.html",
    ]
    offenders = [
        str(path.relative_to(ROOT))
        for path in watched
        if path.exists() and literal in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, f"retired version {literal} still present in {offenders}"
