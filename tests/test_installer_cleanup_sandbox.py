"""Run the uninstaller's canonical-cleanup PowerShell for real, in a sandbox.

``test_installer_cleanup_contract.py`` reads the program as text. This file
*executes* it: it decodes ``BF_CANONICAL_CLEANUP_PS`` out of
``app/build/installer.nsh``, points it at a throwaway ``%APPDATA%`` and invokes
it the way ``BfSafeDeleteCanonical`` does (one process per relative name, the
name in ``BF_UNINSTALL_TARGET``, ``-EncodedCommand``).

SAFETY. ``[Environment]::GetFolderPath(ApplicationData)`` is answered by the
Windows known-folder API and ignores ``$env:APPDATA``. Setting the environment
variable therefore does NOT redirect the program: run unmodified it would act
on the real ``%APPDATA%\\BetterFingers``. The harness swaps that one expression
for ``$env:BF_SANDBOX_APPDATA`` (asserting it occurs exactly once), refuses to
run unless the sandbox is under the temp directory and is not the real
``%APPDATA%``, and the ``_sandbox_root_gate`` fixture proves, before any
deleting test runs, that the rewritten program resolves the sandbox. Every
other byte of the program under test is the shipped one.
"""

import base64
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_INCLUDE = ROOT / "app/build/installer.nsh"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def _real_appdata():
    """The user's real Roaming folder from the known-folder API. Not
    ``os.environ["APPDATA"]``: tests/conftest.py repoints that at a temp dir, and
    the program under test does not read it either."""
    if sys.platform != "win32":
        return ""
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    CSIDL_APPDATA = 0x001A
    if ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_APPDATA, None, 0, buffer) != 0:
        return ""
    return buffer.value


_REAL_APPDATA = _real_appdata()

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not POWERSHELL.exists(),
    reason="the uninstaller cleanup program is Windows PowerShell 5.1",
)

_APPDATA_EXPRESSION = "[Environment]::GetFolderPath([Environment+SpecialFolder]::ApplicationData)"
_ROOT_NAME = "BetterFingers"

# Names the uninstaller treats as directories (everything else in the allowlist
# is a file); only used to seed realistic data.
_DIRECTORY_TARGETS = {
    "models", "wake_models", "tts", "runtimes", "recordings", "voices", "drafts",
    "exports", "profiles", "tmp", "cache", "logs",
    # Chromium's folders (the rest of its names are files).
    "Local Storage", "Session Storage", "IndexedDB", "WebStorage", "SharedStorage",
    "Service Worker", "File System", "databases", "blob_storage", "Network", "Cache",
    "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache", "Shared Dictionary",
    "InterestGroups", "PrivateAggregation",
}
# One of every shape the backend writes next to a store, plus the documented
# ``.corrupt-<tag>`` spelling.
_SIBLING_SUFFIXES = (
    ".bak-v1", ".bak-v12", ".corrupt", ".1760000000.corrupt",
    ".corrupt-20261004T120000Z", ".migrated",
)


def _installer_text():
    return INSTALLER_INCLUDE.read_text(encoding="utf-8")


def _shipped_program(define="BF_CANONICAL_CLEANUP_PS"):
    match = re.search(rf'^!define {define} "([A-Za-z0-9+/=]+)"$', _installer_text(), re.M)
    assert match, f"missing encoded cleanup program {define}"
    return base64.b64decode(match.group(1)).decode("utf-16-le")


def _allowlisted_targets():
    """The relative names the uninstaller macro really passes, in order."""
    targets = re.findall(r'^\s*!insertmacro BfSafeDeleteCanonical "([^"]+)"\s*$', _installer_text(), re.M)
    assert len(targets) == len(set(targets)) >= 30, targets
    assert {"personas.yaml", "draft_history.json", "contacts.json", "models"} <= set(targets)
    return targets


def _sandboxed_program(define="BF_CANONICAL_CLEANUP_PS"):
    program = _shipped_program(define)
    assert program.count(_APPDATA_EXPRESSION) == 1, "the root expression moved; update the harness"
    sandboxed = program.replace(_APPDATA_EXPRESSION, "$env:BF_SANDBOX_APPDATA")
    assert "GetFolderPath" not in sandboxed
    return sandboxed


def _encode(program):
    return base64.b64encode(program.encode("utf-16-le")).decode("ascii")


def _assert_is_sandbox(appdata):
    real_temp = os.path.realpath(tempfile.gettempdir())
    resolved = os.path.realpath(appdata)
    assert resolved.startswith(real_temp + os.sep), f"{appdata} is not under the temp directory"
    assert _REAL_APPDATA, "could not resolve the real %APPDATA%; refusing to run"
    real = os.path.normcase(os.path.realpath(_REAL_APPDATA))
    resolved = os.path.normcase(resolved)
    assert resolved != real and not resolved.startswith(real + os.sep) and not real.startswith(resolved + os.sep), (
        "sandbox overlaps the real %APPDATA%"
    )


def run_cleanup(appdata, relative, program=None):
    """Invoke the program once, like the NSIS macro. Returns the process result."""
    appdata = Path(appdata)
    _assert_is_sandbox(appdata)
    env = dict(os.environ)
    env.update({
        "BF_SANDBOX_APPDATA": str(appdata),
        "APPDATA": str(appdata),  # belt and braces; the program does not read it
        "BF_UNINSTALL_TARGET": relative,
    })
    return subprocess.run(
        [str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive",
         "-EncodedCommand", _encode(program or _sandboxed_program())],
        capture_output=True, text=True, env=env, timeout=60,
    )


@pytest.fixture(scope="module", autouse=True)
def _sandbox_root_gate():
    """Gate: nothing below runs unless the rewritten program resolves the sandbox."""
    with tempfile.TemporaryDirectory(prefix="bf-uninst-probe-") as probe:
        program = _sandboxed_program()
        # The program's first statements compute $root; print it instead of acting.
        head = "\n".join(program.splitlines()[:2]) + "\n[Console]::Out.Write($root)"
        env = dict(os.environ, BF_SANDBOX_APPDATA=probe, APPDATA=probe)
        result = subprocess.run(
            [str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", _encode(head)],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert os.path.normcase(result.stdout.strip()) == os.path.normcase(os.path.join(probe, _ROOT_NAME))
        assert _REAL_APPDATA
        assert os.path.normcase(os.path.realpath(_REAL_APPDATA)) not in os.path.normcase(result.stdout)
    yield


# --- sandbox helpers ---------------------------------------------------------


def _is_reparse(path):
    return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _snapshot(directory):
    """Every entry under ``directory`` as ``/``-joined relative names. A
    reparse point is listed but never descended into."""
    found = set()

    def walk(current, prefix):
        with os.scandir(current) as entries:
            for entry in entries:
                name = prefix + entry.name
                found.add(name)
                if entry.is_dir(follow_symlinks=False) and not _is_reparse(entry.path):
                    walk(entry.path, name + "/")

    walk(str(directory), "")
    return found


def _write(base, relative, text=None):
    path = Path(base) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else f"PRIVATE {relative}", encoding="utf-8")
    return path


def _junction(link, target):
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _is_reparse(link)


@pytest.fixture
def appdata(tmp_path):
    """A sandbox %APPDATA%."""
    base = tmp_path / "AppData"
    base.mkdir()
    _assert_is_sandbox(base)
    return base


@pytest.fixture
def make_junction(request):
    """Create a junction; unlink it (never follow it) before pytest removes the tree."""
    links = []

    def unlink_junctions():
        for link in links:
            if os.path.lexists(link) and _is_reparse(link):
                os.rmdir(link)

    request.addfinalizer(unlink_junctions)

    def make(link, target):
        _junction(link, target)
        links.append(str(link))

    return make


def _root(appdata):
    root = appdata / _ROOT_NAME
    root.mkdir(exist_ok=True)
    return root


# --- the bug: siblings next to an allowlisted store ---------------------------


def test_every_sibling_shape_is_deleted_and_every_decoy_survives(appdata):
    root = _root(appdata)
    stores = {"personas.yaml", "dictionary.json", "contacts.json"}
    for store in stores:
        _write(root, store)
        for suffix in _SIBLING_SUFFIXES:
            _write(root, store + suffix)
    # draft_history.json is renamed to .migrated once its rows are in history.db,
    # so the live file is gone and only the full pre-SQLite copy remains.
    _write(root, "draft_history.json.migrated", "PRIVATE old drafts")
    _write(root, "draft_history.json.bak-v1")

    decoys = [
        "personas.yaml.notes", "personas.yaml.bak-vX", "personas.yaml.bak-v", "personas.yaml.bak-v1x",
        "personas.yaml.bak-v1.notes", "personas.yaml.bak", "personas.yaml.backup", "personas.yaml.old",
        "personas.yaml.migrated.notes", "personas.yaml.corruptx", "personas.yaml.corrupt.notes",
        "personas.yaml.x1.corrupt", "personas.yaml..corrupt", "personas.yaml.1.corrupt.bak",
        "personas.yaml.1760000000.corrupt-extra.notes",
        "personasXyaml.bak-v1",            # the dot in the name is literal
        "xpersonas.yaml.bak-v1",           # prefix is anchored
        "personas.yaml2.bak-v1",
        "other.json", "other.json.bak-v1", "other.json.corrupt", "other.json.migrated",
        "dictionary.json.notes", "contacts.jsonl",
        "sub/personas.yaml.bak-v1",        # same name, different directory
        "sub/personas.yaml.corrupt",
    ]
    for decoy in decoys:
        _write(root, decoy)
    # A directory whose name matches a shape is not a file the backend wrote.
    _write(root, "personas.yaml.bak-v2/inside.txt")
    decoys += ["personas.yaml.bak-v2", "personas.yaml.bak-v2/inside.txt"]

    def run(target, gone):
        before = _snapshot(root)
        result = run_cleanup(appdata, target)
        assert result.returncode == 0, (target, result.stdout, result.stderr)
        after = _snapshot(root)
        assert before - after == gone, (target, sorted((before - after) ^ gone))
        assert not after - before

    # Target isolation: cleaning personas.yaml leaves the other stores' siblings alone.
    run("personas.yaml", {"personas.yaml"} | {"personas.yaml" + s for s in _SIBLING_SUFFIXES})
    assert (root / "dictionary.json.bak-v1").exists() and (root / "contacts.json.corrupt").exists()

    run("dictionary.json", {"dictionary.json"} | {"dictionary.json" + s for s in _SIBLING_SUFFIXES})
    run("contacts.json", {"contacts.json"} | {"contacts.json" + s for s in _SIBLING_SUFFIXES})
    # Main file already gone: its migration/backup debris must still be removed.
    run("draft_history.json", {"draft_history.json.migrated", "draft_history.json.bak-v1"})

    survivors = _snapshot(root)
    assert survivors == {"sub", *decoys}, sorted(survivors ^ {"sub", *decoys})
    # Decoys keep their content.
    assert (root / "personas.yaml.bak-v2/inside.txt").read_text(encoding="utf-8") == "PRIVATE personas.yaml.bak-v2/inside.txt"
    assert (root / "personas.yaml.notes").read_text(encoding="utf-8") == "PRIVATE personas.yaml.notes"


def test_second_run_is_a_clean_noop(appdata):
    root = _root(appdata)
    _write(root, "personas.yaml")
    _write(root, "personas.yaml.bak-v1")
    assert run_cleanup(appdata, "personas.yaml").returncode == 0
    assert _snapshot(root) == set()
    again = run_cleanup(appdata, "personas.yaml")
    assert again.returncode == 0, again.stderr
    assert _snapshot(root) == set()


@pytest.mark.slow  # one PowerShell process per allowlisted name, like the macro: ~12 s
def test_full_uninstall_sequence_removes_every_sibling_so_only_unknown_files_remain(appdata):
    """The reported bug end to end. Every name the macro passes, every sibling
    shape, plus files the uninstaller must not own. Afterwards only the
    unknown files remain, so once they are gone the macro's final
    non-recursive RMDir (which only removes an empty folder) succeeds."""
    root = _root(appdata)
    unknown = ["mine.txt", "personas.yaml.notes", "personas.yaml.bak-vX", "other.json.bak-v1"]
    for target in _allowlisted_targets():
        if target in _DIRECTORY_TARGETS:
            _write(root, f"{target}/nested/content.bin")
            continue
        _write(root, target)
        for suffix in _SIBLING_SUFFIXES:
            _write(root, target + suffix)
    for name in unknown:
        _write(root, name)
    assert len(_snapshot(root)) > 150

    for target in _allowlisted_targets():
        result = run_cleanup(appdata, target)
        assert result.returncode == 0, (target, result.stdout, result.stderr)

    assert _snapshot(root) == set(unknown), sorted(_snapshot(root) ^ set(unknown))
    with pytest.raises(OSError):
        os.rmdir(root)  # unknown files keep the folder alive by design
    for name in unknown:
        (root / name).unlink()
    os.rmdir(root)  # nothing the uninstaller owns is left behind


def test_directory_target_is_removed_but_does_not_sweep_name_siblings(appdata):
    """Sibling shapes belong to FILE stores. An existing directory target is
    removed exactly as before and nothing beside it is guessed at."""
    root = _root(appdata)
    _write(root, "models/m.gguf")
    _write(root, "models.corrupt")
    _write(root, "models.bak-v1")
    result = run_cleanup(appdata, "models")
    assert result.returncode == 0, result.stderr
    assert _snapshot(root) == {"models.corrupt", "models.bak-v1"}


# --- fail-closed paths -------------------------------------------------------


def test_junction_sibling_is_refused_and_nothing_is_deleted(appdata, make_junction):
    root = _root(appdata)
    outside = appdata / "outside"
    _write(outside, "secret.txt", "must survive")
    _write(root, "personas.yaml")
    _write(root, "personas.yaml.corrupt")
    _write(root, "personas.yaml.migrated")
    make_junction(root / "personas.yaml.bak-v1", outside)

    before = _snapshot(root)
    result = run_cleanup(appdata, "personas.yaml")
    assert result.returncode != 0
    assert "reparse point refused" in (result.stdout + result.stderr)
    assert _snapshot(root) == before, "fail closed: not even the safe files may be removed"
    assert _is_reparse(root / "personas.yaml.bak-v1")
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "must survive"


def test_junction_that_is_the_target_name_is_refused(appdata, make_junction):
    root = _root(appdata)
    outside = appdata / "outside"
    _write(outside, "secret.txt", "must survive")
    make_junction(root / "personas.yaml", outside)
    _write(root, "personas.yaml.bak-v1")
    result = run_cleanup(appdata, "personas.yaml")
    assert result.returncode != 0
    assert (root / "personas.yaml.bak-v1").exists()
    assert (outside / "secret.txt").exists() and _is_reparse(root / "personas.yaml")


def test_reparse_point_anywhere_under_the_root_still_refuses_the_whole_call(appdata, make_junction):
    """The pre-existing root-wide rule is unchanged: a reparse point anywhere
    below the canonical root fails every call closed."""
    root = _root(appdata)
    outside = appdata / "outside"
    _write(outside, "secret.txt")
    _write(root, "personas.yaml")
    _write(root, "personas.yaml.bak-v1")
    _write(root, "models/m.gguf")
    make_junction(root / "models" / "link", outside)
    before = _snapshot(root)
    result = run_cleanup(appdata, "personas.yaml")
    assert result.returncode != 0
    assert _snapshot(root) == before
    assert (outside / "secret.txt").exists()


def test_symlink_sibling_is_refused_when_symlinks_can_be_created(appdata):
    root = _root(appdata)
    outside = _write(appdata / "outside", "secret.txt", "must survive")
    _write(root, "personas.yaml")
    link = root / "personas.yaml.corrupt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError) as exc:  # needs Developer Mode or elevation
        pytest.skip(f"cannot create a file symlink here: {exc}")
    before = _snapshot(root)
    result = run_cleanup(appdata, "personas.yaml")
    assert result.returncode != 0
    assert _snapshot(root) == before
    assert outside.read_text(encoding="utf-8") == "must survive"


@pytest.mark.parametrize("relative", [
    r"..\outside\personas.yaml",
    r"..\BetterFingers-old\personas.yaml",
    r"sub\..\..\outside\personas.yaml",
    r"..",
    r".",
    r"",
    "\\",
    r"sub\..",
])
def test_targets_outside_the_root_are_refused_and_their_siblings_untouched(appdata, relative):
    root = _root(appdata)
    for outside in ("outside", "BetterFingers-old"):
        _write(appdata, f"{outside}/personas.yaml")
        _write(appdata, f"{outside}/personas.yaml.bak-v1")
    _write(root, "personas.yaml")
    _write(root, "personas.yaml.bak-v1")
    before_outside = _snapshot(appdata)
    result = run_cleanup(appdata, relative)
    assert result.returncode != 0, (relative, result.stdout, result.stderr)
    assert _snapshot(appdata) == before_outside, "refusal must not touch anything"


def test_a_locked_sibling_does_not_stop_the_rest_but_reports_failure(appdata):
    root = _root(appdata)
    _write(root, "personas.yaml")
    _write(root, "personas.yaml.bak-v1")
    locked = _write(root, "personas.yaml.corrupt")
    _write(root, "personas.yaml.migrated")
    with open(locked, "rb"):  # Python opens without FILE_SHARE_DELETE
        result = run_cleanup(appdata, "personas.yaml")
    assert result.returncode != 0
    assert _snapshot(root) == {"personas.yaml.corrupt"}


def test_missing_root_or_missing_target_is_a_clean_noop(appdata):
    result = run_cleanup(appdata, "personas.yaml")  # no BetterFingers folder at all
    assert result.returncode == 0, result.stderr
    assert not (appdata / _ROOT_NAME).exists(), "the cleanup must not create the folder"

    root = _root(appdata)
    _write(root, "contacts.json")
    result = run_cleanup(appdata, "personas.yaml")  # nothing named personas.yaml*
    assert result.returncode == 0, result.stderr
    assert _snapshot(root) == {"contacts.json"}


# --- Electron's userData folder (%APPDATA%\betterfingers-electron) ---------------------
#
# The packaged app's Electron userData is NOT the canonical folder (measured). Same
# program, one literal different; these run it for real against a sandbox with BOTH
# folders present, and prove it can reach Chromium's state without ever being a way
# into the canonical folder.

_ELECTRON_DEFINE = "BF_ELECTRON_CLEANUP_PS"
_ELECTRON_ROOT_NAME = "betterfingers-electron"


def _electron_targets():
    targets = re.findall(r'^\s*!insertmacro BfSafeDeleteElectron "([^"]+)"\s*$', _installer_text(), re.M)
    assert len(targets) == len(set(targets)) >= 30, targets
    assert {"Local Storage", "Cache", "Preferences", "sidecar_backend_raw.log"} <= set(targets)
    return targets


def run_electron_cleanup(appdata, relative):
    return run_cleanup(appdata, relative, program=_sandboxed_program(_ELECTRON_DEFINE))


def _electron_root(appdata):
    root = appdata / _ELECTRON_ROOT_NAME
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture(scope="module", autouse=True)
def _electron_sandbox_root_gate():
    """Gate: the Electron program, rewritten for the sandbox, resolves the sandbox's
    betterfingers-electron folder and nothing real."""
    with tempfile.TemporaryDirectory(prefix="bf-uninst-probe-") as probe:
        program = _sandboxed_program(_ELECTRON_DEFINE)
        head = "\n".join(program.splitlines()[:2]) + "\n[Console]::Out.Write($root)"
        env = dict(os.environ, BF_SANDBOX_APPDATA=probe, APPDATA=probe)
        result = subprocess.run(
            [str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", _encode(head)],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert os.path.normcase(result.stdout.strip()) == os.path.normcase(os.path.join(probe, _ELECTRON_ROOT_NAME))
        assert os.path.normcase(os.path.realpath(_REAL_APPDATA)) not in os.path.normcase(result.stdout)
    yield


def test_electron_cleanup_removes_chromium_state_and_leaves_the_canonical_folder_alone(appdata):
    canonical = _root(appdata)
    for name in ("onboarding.json", "personas.yaml", "history.db", "models/model.gguf"):
        _write(canonical, name)
    electron = _electron_root(appdata)
    chromium = [
        "Local Storage/leveldb/000003.log", "Local Storage/leveldb/CURRENT", "Session Storage/000003.log",
        "Cache/Cache_Data/data_0", "Code Cache/js/index", "GPUCache/data_0", "Network/Trust Tokens",
        "Preferences", "Local State", "lockfile", "DIPS", "DIPS-wal",
    ]
    ours = ["overlay-position.json", "overlay-appearance.json", "sidecar_backend_raw.log"]
    unknown = "somebody_elses_file.txt"
    for name in (*chromium, *ours, unknown):
        _write(electron, name)
    canonical_before = _snapshot(canonical)

    for target in ("Local Storage", "Session Storage", "Cache", "Code Cache", "GPUCache", "Network",
                   "Preferences", "Local State", "lockfile", "DIPS", "DIPS-wal", *ours):
        result = run_electron_cleanup(appdata, target)
        assert result.returncode == 0, (target, result.stdout, result.stderr)

    assert _snapshot(electron) == {unknown}, sorted(_snapshot(electron))
    assert _snapshot(canonical) == canonical_before, "the canonical folder must be untouched"
    with pytest.raises(OSError):
        os.rmdir(electron)  # an unknown file keeps Electron's folder alive, as it does for the canonical one


def test_electron_cleanup_is_not_a_way_into_the_canonical_folder(appdata):
    canonical = _root(appdata)
    _write(canonical, "onboarding.json")
    _write(canonical, "personas.yaml")
    electron = _electron_root(appdata)
    _write(electron, "Local Storage/leveldb/000003.log")
    before = _snapshot(appdata)

    for relative in (
        r"..\BetterFingers\onboarding.json",
        r"..\BetterFingers",
        r"..\betterfingers-electron\..\BetterFingers\personas.yaml",
        r"sub\..\..\BetterFingers\personas.yaml",
        r"..", r".", r"", "\\", r"sub\..",
    ):
        result = run_electron_cleanup(appdata, relative)
        assert result.returncode != 0, (relative, result.stdout, result.stderr)
        assert _snapshot(appdata) == before, f"{relative!r} must not delete anything"

    # And the converse: the canonical program cannot reach Electron's folder either.
    for relative in (r"..\betterfingers-electron\Local Storage", r"..\betterfingers-electron"):
        result = run_cleanup(appdata, relative)
        assert result.returncode != 0, (relative, result.stdout, result.stderr)
        assert _snapshot(appdata) == before


def test_electron_cleanup_refuses_a_junction_inside_its_folder(appdata, make_junction):
    electron = _electron_root(appdata)
    outside = appdata / "outside"
    _write(outside, "secret.txt", "must survive")
    _write(electron, "Local Storage/leveldb/000003.log")
    _write(electron, "Preferences")
    make_junction(electron / "Cache", outside)
    before = _snapshot(electron)

    result = run_electron_cleanup(appdata, "Local Storage")

    assert result.returncode != 0
    assert "reparse point refused" in (result.stdout + result.stderr)
    assert _snapshot(electron) == before, "fail closed: nothing at all is removed"
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "must survive"


def test_electron_cleanup_with_no_folder_is_a_clean_noop(appdata):
    result = run_electron_cleanup(appdata, "Local Storage")
    assert result.returncode == 0, result.stderr
    assert not (appdata / _ELECTRON_ROOT_NAME).exists(), "the cleanup must not create the folder"


@pytest.mark.slow  # one PowerShell process per allowlisted name, like the macro
def test_full_electron_uninstall_sequence_leaves_only_unknown_files(appdata):
    """Every name the macro passes, as the file or folder Chromium really makes
    it, plus a file the uninstaller must not own. The final non-recursive RMDir
    can then only succeed once the unknown file is gone."""
    electron = _electron_root(appdata)
    unknown = ["mine.txt", "Preferences.notes"]
    for target in _electron_targets():
        if target in _DIRECTORY_TARGETS:
            _write(electron, f"{target}/nested/content.bin")
        else:
            _write(electron, target)
    for name in unknown:
        _write(electron, name)
    assert len(_snapshot(electron)) > 40

    for target in _electron_targets():
        result = run_electron_cleanup(appdata, target)
        assert result.returncode == 0, (target, result.stdout, result.stderr)

    assert _snapshot(electron) == set(unknown), sorted(_snapshot(electron) ^ set(unknown))
    with pytest.raises(OSError):
        os.rmdir(electron)
    for name in unknown:
        (electron / name).unlink()
    os.rmdir(electron)
