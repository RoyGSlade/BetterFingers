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


# --- recovery siblings -------------------------------------------------------
#
# ``store_migration`` and the stores leave ``<store>.bak-v<N>``, ``<store>.corrupt``,
# ``<store>.<ts>.corrupt`` and ``draft_history.json.migrated`` beside the live
# file; they hold the same private text. ``data_paths._with_migration_siblings``
# is the authority for those shapes. The uninstaller's PowerShell must delete
# exactly the shapes declared there. test_installer_cleanup_sandbox.py runs the
# program for real; the tests below keep it in step with data_paths.

# Shapes data_paths documents and the backend writes (plus the documented but
# never-written ``.corrupt-<tag>`` spelling).
DECLARED_SIBLING_SUFFIXES = (
    ".bak-v1", ".bak-v12", ".corrupt", ".1760000000.corrupt",
    ".corrupt-20261004T120000Z", ".migrated",
)
# data_paths matches with ``startswith("bak-v")`` / ``startswith("corrupt")``,
# which is looser than anything it documents or the backend writes. The
# uninstaller deliberately stays exact and leaves these alone.
DATA_PATHS_LOOSER_THAN_DECLARED = (
    ".bak-vX", ".bak-v", ".bak-v1.notes", ".corruptx", ".corrupt.notes",
)
# Neither data_paths nor the uninstaller may claim these.
NEIGHBOURS = (
    ".notes", ".bak", ".backup", ".old", ".orig", "x", ".migrated.notes", ".1.corrupt.bak",
    ".x1.corrupt", "..corrupt", ".1.corrupt.notes",
)
# The literals _with_migration_siblings is built from (drift guard below).
EXPECTED_DATA_PATHS_SIBLING_LITERALS = {".*", "bak-v", "corrupt", "migrated"}


def _uninstaller_sibling_shape():
    program = _decoded_program("BF_CANONICAL_CLEANUP_PS")
    match = re.search(r"^\$shapes='([^']+)'$", program, re.M)
    assert match, "the cleanup program must declare its sibling shapes in one $shapes literal"
    return re.compile(match.group(1))


def _allowlisted_names():
    return set(re.findall(r'!insertmacro BfSafeDeleteCanonical "([^"]+)"', _installer_text()))


def test_cleanup_deletes_declared_sibling_shapes_by_exact_name_only():
    program = _decoded_program("BF_CANONICAL_CLEANUP_PS")
    # One anchored, escaped pattern built from the literal file name.
    assert "[regex]::Escape([IO.Path]::GetFileName($target))" in program
    assert r"$pattern='^'+" in program and r"+')$'" in program
    assert "$entry.Name -match $pattern" in program
    # Same directory only, no wildcard or recursive enumeration, no globbing.
    assert "Get-ChildItem -LiteralPath $parent -Force" in program
    for forbidden in ("-Filter", "-Include", "-Exclude", "-like", "*"):
        assert forbidden not in program, forbidden
    assert program.count("-Recurse") == 1, "only the existing target removal may recurse"
    # Every sibling gets the same root and reparse checks, all before any delete.
    assert "$entry.FullName.StartsWith($root.TrimEnd('\\')+'\\',[StringComparison]::OrdinalIgnoreCase)" in program
    assert "Assert-NoReparse $entry.FullName" in program
    first_delete = program.index("Remove-Item")
    for check in ("Assert-NoReparse $entry.FullName", "Assert-NoReparse $root"):
        assert program.index(check) < first_delete, f"{check} must run before anything is deleted"
    assert "Remove-Item -LiteralPath $sibling -Force" in program
    assert "Remove-Item -LiteralPath $target -Recurse -Force" in program
    # A directory that merely has a sibling-shaped name is not a store file.
    assert "if(-not $entry.PSIsContainer){$siblings+=$entry.FullName}" in program
    # An empty or root-equal target must never reach Remove-Item -Recurse.
    assert "if($target.TrimEnd('\\') -eq $root.TrimEnd('\\')){exit 20}" in program
    # Siblings are not skipped when the live file is already gone
    # (draft_history.json is renamed to .migrated once its rows are in history.db).
    assert "if(-not(Test-Path -LiteralPath $target) -and $siblings.Count -eq 0){exit 0}" in program


def test_uninstaller_sibling_shapes_cover_every_shape_data_paths_declares(tmp_path):
    from backend.privacy import data_paths

    shape = _uninstaller_sibling_shape()
    live = tmp_path / "store.json"
    live.write_text("{}", encoding="utf-8")

    def claimed_by_data_paths(suffix):
        sibling = tmp_path / ("store.json" + suffix)
        sibling.write_text("x", encoding="utf-8")
        try:
            return sibling in data_paths._with_migration_siblings(live)
        finally:
            sibling.unlink()

    for suffix in DECLARED_SIBLING_SUFFIXES:
        assert claimed_by_data_paths(suffix), f"data_paths no longer declares {suffix}; update this contract"
        assert shape.fullmatch(suffix[1:]), f"the uninstaller does not delete the declared sibling shape {suffix}"
    for suffix in DATA_PATHS_LOOSER_THAN_DECLARED:
        assert claimed_by_data_paths(suffix), (
            f"data_paths tightened and no longer claims {suffix}; drop it from DATA_PATHS_LOOSER_THAN_DECLARED"
        )
        assert not shape.fullmatch(suffix[1:]), f"the uninstaller must stay exact and leave {suffix} alone"
    for suffix in NEIGHBOURS:
        suffix = suffix if suffix.startswith(".") else "." + suffix
        assert not claimed_by_data_paths(suffix), f"data_paths now claims {suffix}; the uninstaller must handle it"
        assert not shape.fullmatch(suffix[1:]), f"the uninstaller claims {suffix}, which data_paths does not declare"


def test_a_new_data_paths_sibling_shape_fails_until_the_uninstaller_learns_it():
    """Drift guard. Probing known suffixes cannot notice a shape nobody thought
    to probe, so pin the literals ``_with_migration_siblings`` is made of. Add a
    shape there and this fails: teach ``$shapes`` in BF_CANONICAL_CLEANUP_PS
    (re-encode it into installer.nsh), extend DECLARED_SIBLING_SUFFIXES and the
    sandbox test, then update EXPECTED_DATA_PATHS_SIBLING_LITERALS."""
    import ast
    from backend.privacy import data_paths

    tree = ast.parse(Path(data_paths.__file__).read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_with_migration_siblings"
    )
    assert isinstance(function.body[0], ast.Expr) and isinstance(function.body[0].value, ast.Constant)
    literals, constants = set(), set()
    for statement in function.body[1:]:
        for node in ast.walk(statement):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
            elif isinstance(node, ast.Name) and node.id.startswith("_") and node.id.isupper():
                constants.add(node.id)
    assert literals == EXPECTED_DATA_PATHS_SIBLING_LITERALS, (
        f"data_paths._with_migration_siblings changed its sibling shapes: {sorted(literals)}"
    )
    assert constants == {"_TIMESTAMPED_QUARANTINE"}
    assert data_paths._TIMESTAMPED_QUARANTINE.pattern == r"[0-9]+\.corrupt"


def test_every_store_data_paths_declares_siblings_for_is_an_uninstaller_target():
    """A sibling is only swept with its live file's macro call, so a store that
    data_paths gives siblings but the allowlist omits would keep its backups."""
    from backend.privacy import data_paths

    source = Path(data_paths.__file__).read_text(encoding="utf-8")
    stores = set(re.findall(r'_with_migration_siblings\(\s*base\(\)\s*/\s*"([^"]+)"', source))
    assert len(stores) >= 14, stores
    missing = stores - _allowlisted_names()
    assert not missing, f"stores with declared siblings but no uninstaller target: {sorted(missing)}"


def test_encoded_cleanup_command_fits_the_nsis_string_limit():
    """electron-builder's makensis (v3.04) is built with NSIS_MAX_STRLEN=8192
    (read from ``makensis /HDRINFO``). The whole nsExec command line is one NSIS
    string, so the program must stay well inside it."""
    command = (
        r'"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" '
        r"-NoLogo -NoProfile -NonInteractive -EncodedCommand "
    )
    blob = re.search(r'^!define BF_CANONICAL_CLEANUP_PS "([A-Za-z0-9+/=]+)"$', _installer_text(), re.M).group(1)
    assert len(command) + len(blob) < 6000, len(command) + len(blob)

# --- inventory <-> uninstaller allowlist --------------------------------------
#
# "Remove my data" can only remove what BfSafeDeleteCanonical names, and the
# in-app factory reset can only remove what the privacy inventory declares. When
# the two lists drift the user gets two different answers to "what does this
# app keep?", and the uninstaller's final non-recursive RMDir silently leaves
# the data folder behind (D2: persona_drafts.json and tts/ were in neither).
# These tests tie the lists together from the inventory's side; the writer-side
# tie (everything the app can write is in both) is in
# test_privacy_inventory_completeness.py.

# Allowlisted names that no inventory category declares. They are reserved
# names inherited from the alpha.3 allowlist (AppPaths.exports / AppPaths.logs
# and an older ``drafts`` folder): the uninstaller still clears them if they
# exist, but nothing in the backend or the Electron main process writes them
# today. The set is compared EXACTLY, so a name cannot join or leave it silently:
# if one of these gains a writer it must be declared in the inventory (and drop
# out of here); if one is removed from the installer, drop it here too.
UNINSTALLER_ONLY = {
    "drafts": "older drafts folder; no current writer",
    "exports": "AppPaths.exports; no current writer (/privacy/export returns JSON, it writes no file)",
    "logs": "AppPaths.logs is the data root itself; nothing creates a logs folder",
}


def _inventory_top_level_names(tmp_path, monkeypatch):
    """``{name directly under the data root: {category ids}}`` for every path the
    inventory can declare, whether or not it exists.

    Runs the real ``paths()`` callables with the existence filter switched off,
    over a Windows-shaped tree (``%APPDATA%\\BetterFingers`` is both the unified
    root and Electron's packaged ``userData``). The unpackaged Electron root
    (``betterfingers-electron``) is skipped on purpose: the NSIS uninstaller only
    ever manages ``$APPDATA\\BetterFingers``.
    """
    import pathlib
    from backend.config import app_paths
    from backend.privacy import data_categories, data_paths

    appdata = tmp_path / "AppData"
    root = appdata / "BetterFingers"
    dev_root = appdata / "betterfingers-electron"
    root.mkdir(parents=True)
    monkeypatch.delenv("BETTERFINGERS_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(app_paths, "resolve_base", lambda: root)
    monkeypatch.setattr(data_paths, "electron_user_data_candidates", lambda: [root, dev_root])

    def every_candidate(*candidates):
        unique = []
        for candidate in candidates:
            if candidate not in unique:
                unique.append(candidate)
        return unique

    monkeypatch.setattr(data_paths, "_existing", every_candidate)

    names = {}
    for category in data_categories.build_registry().all():
        for path in category.paths():
            path = pathlib.Path(path)
            for base in (root, dev_root):
                try:
                    relative = path.relative_to(base)
                except ValueError:
                    continue
                if base is root:
                    names.setdefault(relative.parts[0], set()).add(category.id)
                break
            else:
                raise AssertionError(
                    f"{category.id} declares {path}, which is outside every root the uninstaller can reach"
                )
    return names


def _allowlist_by_checkbox():
    """``{relative name: the checkbox variable that guards it}``, from the macro."""
    cleanup = _installer_text().split("!macro customUnInstall", 1)[1]
    guarded = {}
    for variable, body in re.findall(
        r"\$\{If\} \$(BfDelete\w+) == \$\{BST_CHECKED\}\s*\n(.*?)\$\{EndIf\}", cleanup, re.S
    ):
        for name in re.findall(r'!insertmacro BfSafeDeleteCanonical "([^"]+)"', body):
            assert name not in guarded, f"{name} is guarded by two checkboxes"
            guarded[name] = variable
    return guarded


def test_the_inventory_extraction_sees_the_stores_this_contract_exists_for(tmp_path, monkeypatch):
    declared = _inventory_top_level_names(tmp_path, monkeypatch)
    assert len(declared) >= 35, sorted(declared)
    assert {
        "persona_drafts.json", "tts", "runtimes", "personas.yaml", "models", "voices",
        "history.db", "onboarding.json", "overlay-position.json", "sidecar_backend_raw.log",
        "user_profile.json", "audio_privacy_journal.json",
    } <= set(declared)
    assert declared["persona_drafts.json"] == {"personas"}
    assert declared["tts"] == {"downloaded_models"}


def test_every_top_level_name_the_inventory_declares_is_an_uninstaller_target(tmp_path, monkeypatch):
    declared = _inventory_top_level_names(tmp_path, monkeypatch)
    missing = {name: sorted(categories) for name, categories in declared.items()
               if name not in _allowlisted_names()}
    assert not missing, (
        "declared by the privacy inventory but not removable by 'remove my data' (add a "
        f"BfSafeDeleteCanonical line under the matching checkbox): {missing}"
    )


def test_uninstaller_only_names_are_exactly_the_documented_exceptions(tmp_path, monkeypatch):
    declared = _inventory_top_level_names(tmp_path, monkeypatch)
    extra = _allowlisted_names() - set(declared)
    assert extra == set(UNINSTALLER_ONLY), (
        f"allowlisted names the inventory does not declare: {sorted(extra)}; "
        f"documented exceptions: {sorted(UNINSTALLER_ONLY)}. Declare the artifact in "
        "backend/privacy/data_paths.py, or document why it is uninstaller-only."
    )


def test_a_category_is_never_split_across_uninstaller_checkboxes(tmp_path, monkeypatch):
    """Two names of one category under different checkboxes means ticking the
    box that matches the label leaves part of that data behind."""
    declared = _inventory_top_level_names(tmp_path, monkeypatch)
    guard = _allowlist_by_checkbox()
    per_category = {}
    for name, categories in declared.items():
        for category in categories:
            per_category.setdefault(category, {})[name] = guard.get(name)
    split = {category: names for category, names in per_category.items()
             if len(set(names.values())) > 1}
    assert not split, f"categories split across uninstaller checkboxes: {split}"


def test_downloaded_models_sit_under_the_models_checkbox_and_nothing_else_does(tmp_path, monkeypatch):
    """The Kokoro voice files and any GPU runtime are opt-in downloads. They must
    be removed by "Downloaded models and runtimes" and by nothing a user ticks
    for logs or settings, or an innocent tick deletes hundreds of megabytes."""
    declared = _inventory_top_level_names(tmp_path, monkeypatch)
    guard = _allowlist_by_checkbox()
    downloads = {name for name, categories in declared.items() if "downloaded_models" in categories}
    assert downloads == {"models", "tts", "runtimes"}
    assert {guard[name] for name in downloads} == {"BfDeleteModels"}
    assert guard["persona_drafts.json"] == guard["personas.yaml"] == "BfDeleteSettings"
