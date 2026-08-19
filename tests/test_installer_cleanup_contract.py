"""Safety contract for the assisted BetterFingers NSIS uninstaller."""

import base64
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_INCLUDE = ROOT / "app/build/installer.nsh"
PACKAGE_JSON = ROOT / "app/package.json"


def _installer_text():
    return INSTALLER_INCLUDE.read_text(encoding="utf-8")


def _decoded_program(name):
    match = re.search(rf'^!define {name} "([A-Za-z0-9+/=]+)"$', _installer_text(), re.M)
    assert match, f"missing encoded cleanup program {name}"
    return base64.b64decode(match.group(1)).decode("utf-16-le")


def test_nsis_cleanup_is_wired_and_new_installs_have_a_fixed_location():
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    nsis = package["build"]["nsis"]
    assert nsis["include"] == "build/installer.nsh"
    assert nsis["allowToChangeInstallationDirectory"] is False
    installer = _installer_text()
    assert "!ifdef BUILD_UNINSTALLER" in installer
    assert installer.rstrip().endswith("!endif")


def test_every_user_data_category_is_visible_and_unchecked():
    installer = _installer_text()
    for label in (
        "Downloaded models and runtimes",
        "Recordings and custom voices",
        "History, drafts, and exports",
        "Settings, profiles, personas, dictionary, contacts, and workflows",
        "Logs and temporary data",
    ):
        assert label in installer
    assert installer.count("${NSD_CreateCheckbox}") == 5
    assert installer.count("${NSD_Uncheck}") == 5
    assert r"Canonical data folder: $APPDATA\BetterFingers" in installer
    assert "This cannot be undone." in installer
    assert "MB_YESNO|MB_DEFBUTTON2" in installer


def test_cleanup_only_runs_for_explicit_uninstall_not_upgrade():
    installer = _installer_text()
    cleanup = installer.split("!macro customUnInstall", 1)[1]
    assert "${IfNot} ${isUpdated}" in cleanup
    assert cleanup.index("${IfNot} ${isUpdated}") < cleanup.index(
        '!insertmacro BfSafeDeleteUpdaterCache'
    )
    assert "${GetParameters}" in installer
    for flag in (
        "/BF_DELETE_MODELS",
        "/BF_DELETE_RECORDINGS",
        "/BF_DELETE_HISTORY",
        "/BF_DELETE_SETTINGS",
        "/BF_DELETE_LOGS",
    ):
        assert flag in installer


def test_cleanup_recomputes_canonical_root_and_refuses_escape_or_reparse_points():
    installer = _installer_text()
    safe_delete = _decoded_program("BF_CANONICAL_CLEANUP_PS")
    assert "[Environment+SpecialFolder]::ApplicationData" in safe_delete
    assert "$env:BF_UNINSTALL_TARGET" in safe_delete
    assert "Join-Path $root $relative" in safe_delete
    assert "StartsWith" in safe_delete
    assert "OrdinalIgnoreCase" in safe_delete
    assert "ReparsePoint" in safe_delete
    assert "Assert-NoReparse $root" in safe_delete
    assert "Remove-Item -LiteralPath $target" in safe_delete
    assert "BETTERFINGERS_DATA_DIR" not in safe_delete
    assert "GetEnvironmentVariable" not in installer
    assert "-EncodedCommand ${BF_CANONICAL_CLEANUP_PS}" in installer
    assert 'SetEnvironmentVariable(t, t)i ("BF_UNINSTALL_TARGET", "${RelativePath}")' in installer
    assert r'RMDir /r "$APPDATA\BetterFingers"' not in installer


def test_categories_delete_only_allowlisted_relative_paths():
    installer = _installer_text()
    for relative_path in (
        "models",
        "wake_models",
        "recordings",
        "voices",
        "draft_history.json",
        "history.db",
        "drafts",
        "exports",
        "profiles",
        "config.yaml",
        "personas.yaml",
        "dictionary.json",
        "contacts.json",
        "launcher_workflows.json",
        "tmp",
        "cache",
        "logs",
        "debug.log",
    ):
        assert f'!insertmacro BfSafeDeleteCanonical "{relative_path}"' in installer
    assert '!insertmacro BfSafeDeleteCanonical "$' not in installer
    assert '!insertmacro BfSafeDeleteCanonical "..' not in installer


def test_only_known_completed_updater_staging_roots_are_always_removed():
    installer = _installer_text()
    assert '!insertmacro BfSafeDeleteUpdaterCache "betterfingers-electron-updater"' in installer
    assert '!insertmacro BfSafeDeleteUpdaterCache "BetterFingers-updater"' in installer
    updater_program = _decoded_program("BF_UPDATER_CLEANUP_PS")
    assert "[Environment+SpecialFolder]::LocalApplicationData" in updater_program
    assert "$env:BF_UNINSTALL_CACHE" in updater_program
    assert "Assert-NoReparse $target" in updater_program
    assert "ReparsePoint" in updater_program
    assert "-EncodedCommand ${BF_UPDATER_CLEANUP_PS}" in installer
