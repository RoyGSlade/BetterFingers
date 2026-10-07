"""F1 -- Chromium's own files in Electron's userData and the factory reset.

Measured on the real packaged app (unpacked electron-builder output, throwaway
profile, driven over CDP; evidence under app/artifacts/f1/):

* electron-builder's ``productName`` never reaches ``app.asar/package.json``, so
  the packaged app's name is the package ``name`` and Electron's userData is
  ``%APPDATA%\\betterfingers-electron`` -- NOT the unified data root
  ``%APPDATA%\\BetterFingers``. Chromium's folders sit in that other directory,
  so a factory reset over the unified root verified clean (HTTP 200) while the
  renderer's Local Storage (first-run flags, the legacy consent flag) survived.
  The Electron side of that is fixed in ``app/src/main/rendererState.js``.
* The topology the review suspected -- Electron's userData IS the unified root --
  is not what ships, but it is one ``productName`` line away, and when forced
  (``--user-data-dir`` = the data root) the same reset answered HTTP 500,
  ``verified: false`` with 44 residual Chromium files. This module pins how the
  backend handles that layout: Chromium's runtime entries are declared
  (``data_paths.ELECTRON_RUNTIME_NAMES``) so the residual sweep neither fails on
  them nor goes blind to a real undeclared file.

The names below are the entries seen in the real run, not invented ones.
"""

import json
import pathlib
import re

import pytest

from backend.privacy import data_categories as dc
from backend.privacy import data_lifecycle as dl
from backend.privacy import data_paths

ROOT = pathlib.Path(__file__).resolve().parents[1]

# `ls` of %APPDATA%\betterfingers-electron after one launch of the packaged
# alpha.4 build (app/artifacts/f1/before-fresh/snap-2-before-reset.json), minus
# the three files BetterFingers itself writes there.
OBSERVED_CHROMIUM_ENTRIES = {
    "Cache/Cache_Data/data_0": None,
    "Code Cache/js/index": None,
    "DIPS": None,
    "DIPS-wal": None,
    "DawnGraphiteCache/data_0": None,
    "DawnWebGPUCache/data_0": None,
    "GPUCache/data_0": None,
    "Local State": None,
    "Local Storage/leveldb/000003.log": None,
    "Local Storage/leveldb/CURRENT": None,
    "Network/Network Persistent State": None,
    "Network/Trust Tokens": None,
    "Preferences": None,
    "Session Storage/000003.log": None,
    "Shared Dictionary/db": None,
    "blob_storage/placeholder": None,
    "lockfile": None,
    # Created after the first launch / once storage was cleared (later snapshots).
    "InterestGroups": None,
    "PrivateAggregation": None,
    "PrivateAggregation-journal": None,
    "SharedStorage": None,
    "SharedStorage-wal": None,
    "WebStorage/QuotaManager": None,
}


def _write(root, relative, text=None):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else f"chromium {relative}", encoding="utf-8")
    return path


def _top(relative):
    return relative.split("/", 1)[0]


@pytest.fixture
def shared_root(isolated_data_root, monkeypatch):
    """Electron's userData collapsed onto the data root: the layout the review
    suspected, forced in the real app and answered HTTP 500 there."""
    monkeypatch.setattr(data_paths, "electron_user_data_candidates",
                        lambda: [isolated_data_root])
    return isolated_data_root


@pytest.fixture
def separate_root(isolated_data_root, monkeypatch, tmp_path):
    """The layout that ships: userData is a sibling folder, not the data root."""
    electron = tmp_path / "AppData" / "betterfingers-electron"
    electron.mkdir(parents=True)
    monkeypatch.setattr(data_paths, "electron_user_data_candidates",
                        lambda: [electron, isolated_data_root.parent / "BetterFingers-other"])
    return isolated_data_root, electron


# --- the declaration ------------------------------------------------------------


def test_every_chromium_entry_seen_in_the_real_app_is_declared():
    declared = {name.lower() for name in data_paths.ELECTRON_RUNTIME_NAMES}
    missing = sorted({_top(r) for r in OBSERVED_CHROMIUM_ENTRIES if _top(r).lower() not in declared})
    assert missing == [], f"Chromium wrote these in the real app but data_paths does not declare them: {missing}"


def test_the_reset_marker_the_electron_main_process_writes_is_declared():
    source = (ROOT / "app/src/main/rendererState.js").read_text(encoding="utf-8")
    marker = re.search(r"RESET_PENDING_MARKER = '([^']+)'", source).group(1)
    assert marker == data_paths.ELECTRON_RESET_PENDING_MARKER
    assert marker in data_paths.ELECTRON_RUNTIME_NAMES


def test_the_main_process_purge_list_is_a_subset_of_the_declared_runtime_names():
    """rendererState.js deletes these at the next launch; the backend, the
    uninstaller and this test all have to agree they are Chromium's."""
    source = (ROOT / "app/src/main/rendererState.js").read_text(encoding="utf-8")
    block = re.search(r"CHROMIUM_STORAGE_ENTRIES = Object\.freeze\(\[(.*?)\]\)", source, re.S).group(1)
    purged = re.findall(r"'([^']+)'", block)
    assert len(purged) >= 10, purged
    assert set(purged) <= set(data_paths.ELECTRON_RUNTIME_NAMES), sorted(set(purged) - set(data_paths.ELECTRON_RUNTIME_NAMES))


def test_the_runtime_names_are_plain_top_level_names():
    for name in data_paths.ELECTRON_RUNTIME_NAMES:
        assert name and not re.search(r"[\\/*?]", name), name
        assert name not in {".", ".."}
    assert isinstance(data_paths.ELECTRON_RUNTIME_NAMES, frozenset)


def test_none_of_betterfingers_own_stores_is_hidden_behind_the_runtime_allowlist(isolated_data_root, monkeypatch):
    """The allowlist must stay Chromium-only: a BetterFingers store whose name
    ever joins it would silently drop out of the reset's residual sweep."""
    # Every name the inventory can declare, whether or not it exists on disk.
    monkeypatch.setattr(data_paths, "_existing", lambda *candidates: list(candidates))
    declared = {p.name.lower() for category in dc.build_registry().all() for p in category.paths()}
    runtime = {name.lower() for name in data_paths.ELECTRON_RUNTIME_NAMES}
    # `cache` is the one honest collision: temp_audio declares <root>/cache, and on a
    # case-insensitive filesystem that IS Chromium's `Cache` folder.
    assert (declared & runtime) <= {"cache"}, f"inventory names that are also 'Chromium runtime': {sorted(declared & runtime)}"


def test_the_packaged_app_name_is_one_of_the_userdata_candidates():
    """The measured fact behind all of this. Electron names userData after the
    package.json productName if present, else name. If someone adds a
    productName this still has to hold, and the shared-root tests below become
    the live path."""
    package = json.loads((ROOT / "app/package.json").read_text(encoding="utf-8"))
    expected = package.get("productName") or package["name"]
    names = {p.name for p in data_paths.electron_user_data_candidates()}
    assert expected in names, (expected, names)


# --- the shared-root layout (forced experiment: HTTP 500, 44 residual files) ----------


def test_a_factory_reset_over_chromiums_files_in_the_data_root_verifies(shared_root):
    for relative in OBSERVED_CHROMIUM_ENTRIES:
        _write(shared_root, relative)
    _write(shared_root, "personas.yaml")
    _write(shared_root, "profiles/Default.yaml")

    result = dl.factory_reset(dc.build_registry())

    assert result["residual_files"] == [], "Chromium's runtime files are not an undeclared store"
    assert result["ok"] is True, result
    assert not (shared_root / "personas.yaml").exists()
    assert dl.verify_factory_reset(dc.build_registry())["ok"] is True


def test_a_real_undeclared_file_is_still_a_residual_beside_chromiums_files(shared_root):
    for relative in OBSERVED_CHROMIUM_ENTRIES:
        _write(shared_root, relative)
    stray = _write(shared_root, "customer_notes.json")

    result = dl.factory_reset(dc.build_registry())

    assert result["ok"] is False
    assert result["residual_files"] == [str(stray.resolve())], "only the real undeclared file, none of Chromium's"


def test_chromium_named_folders_are_owned_wholesale(shared_root):
    """Chromium owns its directories wholesale (the sweep does not descend into
    them), so a file inside one is Chromium's. A BetterFingers store never lives
    in a folder with a Chromium name."""
    _write(shared_root, "Local Storage/leveldb/anything.txt")
    assert dl.unmapped_files(dc.build_registry()) == []


def test_runtime_names_match_case_insensitively_like_the_windows_filesystem(shared_root):
    for name in ("local storage", "GPUCACHE", "preferences"):
        _write(shared_root, f"{name}/x" if name != "preferences" else name)
    assert dl.unmapped_files(dc.build_registry()) == []


def test_only_top_level_entries_are_runtime_owned(shared_root):
    """`Preferences` at the top is Chromium's; the same name three folders down
    is not covered by the allowlist."""
    deep = _write(shared_root, "somewhere/else/Preferences")
    assert dl.unmapped_files(dc.build_registry()) == [str(deep.resolve())]


def test_the_reset_names_what_it_left_to_electron(shared_root):
    for relative in OBSERVED_CHROMIUM_ENTRIES:
        _write(shared_root, relative)
    result = dl.factory_reset(dc.build_registry())
    owned = result["electron_runtime"]
    assert owned["owner"] == "electron"
    present = {_top(r) for r in OBSERVED_CHROMIUM_ENTRIES}
    assert set(owned["in_data_root"]) == present
    assert "restart" in owned["note"].lower()


# --- the layout that ships: nothing changes, nothing is hidden ---------------------------


def test_with_a_separate_userdata_folder_chromiums_names_in_the_data_root_are_not_ignored(separate_root):
    """When userData is a sibling folder there is no reason for Chromium names
    to appear in the data root, so if one does it is an unknown file."""
    data_root, electron = separate_root
    _write(electron, "Local Storage/leveldb/000003.log")
    stray = _write(data_root, "Local Storage/leveldb/000003.log")
    assert dl.unmapped_files(dc.build_registry()) == [str(stray.resolve())]


def test_with_a_separate_userdata_folder_the_reset_never_reaches_into_it_beyond_its_declared_files(separate_root):
    data_root, electron = separate_root
    for relative in OBSERVED_CHROMIUM_ENTRIES:
        _write(electron, relative)
    _write(electron, "overlay-position.json")
    _write(electron, "sidecar_backend_raw.log")
    _write(data_root, "personas.yaml")

    result = dl.factory_reset(dc.build_registry())

    assert result["ok"] is True, result
    assert "electron_runtime" not in result or not result["electron_runtime"]["in_data_root"]
    assert not (electron / "overlay-position.json").exists(), "declared Electron-owned file: removed"
    assert not (electron / "sidecar_backend_raw.log").exists()
    for relative in OBSERVED_CHROMIUM_ENTRIES:
        assert (electron / relative).exists(), f"{relative}: Chromium holds it open; main clears it, not the backend"


def test_is_electron_user_data_compares_the_resolved_path(shared_root, tmp_path):
    assert data_paths.is_electron_user_data(shared_root) is True
    assert data_paths.is_electron_user_data(tmp_path / "somewhere-else") is False


# --- temp_audio's `cache` is Chromium's Cache when userData is the data root -----------


def test_in_a_shared_root_chromiums_cache_folder_is_not_a_temp_audio_store(shared_root):
    """AppPaths.cache is reserved and nothing writes it. When userData is the data
    root that name is Chromium's HTTP cache, which Chromium rebuilds the moment it
    is cleared, so the backend must not own, wipe or verify it (measured: it made
    the post-reset check fail on `temp_audio`)."""
    _write(shared_root, "Cache/Cache_Data/data_0")
    _write(shared_root, "tmp/take.wav")
    assert [p.name for p in data_paths.temp_audio()] == ["tmp"]
    assert dc.build_registry().get("temp_audio").verify().ok is False  # tmp is ours
    dl.factory_reset(dc.build_registry())
    assert (shared_root / "Cache" / "Cache_Data" / "data_0").exists()
    assert dc.build_registry().get("temp_audio").verify().ok is True
    assert dl.verify_factory_reset(dc.build_registry())["ok"] is True


def test_in_a_separate_layout_the_reserved_cache_folder_is_still_temp_audio(separate_root):
    data_root, _electron = separate_root
    _write(data_root, "cache/convert.tmp.wav")
    assert {p.name for p in data_paths.temp_audio()} == {"cache"}
