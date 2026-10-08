"""A factory reset must not report its own recreated settings as leftovers.

Once a reset succeeds, the still-running app recreates ``profiles/Default.yaml``
from defaults (``utils.load_profile`` -> ``save_profile``) the next time it
reads its settings. The ``profiles`` verifier used to count any file in
``profiles/`` as a survivor, so "Check what's left" contradicted the reset's
own "nothing remains".

The rule these tests pin: only the untouched recreated Default profile, and its
``.bak`` if the app wrote one and that copy is also untouched, may survive a
reset. A changed setting, any other file in ``profiles/``, an unreadable file,
or a legacy ``config.yaml`` must still fail the check. The deletion side of the
reset is pinned too, because the verifier is only allowed to change how the
result is judged.

Every test runs on a temp data root. ``isolated_data_root`` pins both
BETTERFINGERS_DATA_DIR and APPDATA (``data_paths.user_profile`` reads APPDATA
directly), and the Electron userData candidates are pointed at a temp dir, so a
reset here cannot reach a real install.
"""

import pytest
import yaml

from backend.config import utils
from backend.privacy import data_categories as dc
from backend.privacy import data_lifecycle as dl
from backend.privacy import data_paths


@pytest.fixture
def reset_root(isolated_data_root, tmp_path, monkeypatch):
    electron = tmp_path / "electron-userdata"
    electron.mkdir()
    monkeypatch.setattr(data_paths, "electron_user_data_candidates", lambda: [electron])
    return isolated_data_root


def _factory_reset():
    registry = dc.build_registry()
    result = dl.factory_reset(registry)
    assert result["ok"], result
    return registry


def _recreate_default(root):
    """What the running app does on its next settings read after a reset."""
    utils.load_profile("Default")
    live = root / "profiles" / "Default.yaml"
    assert live.is_file()
    return live


def _profiles_verdict(registry):
    verdict = dl.verify_factory_reset(registry)
    return verdict, verdict["categories"]["profiles"]


def _tree(root):
    """Every path under root with its bytes (None for directories)."""
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def test_recreated_default_profile_is_not_a_leftover(reset_root):
    registry = _factory_reset()
    _recreate_default(reset_root)

    verdict = dl.verify_factory_reset(registry)

    assert "profiles" not in verdict["failed"], verdict["categories"]["profiles"]
    assert verdict["ok"], verdict


def test_changed_setting_in_recreated_default_fails(reset_root):
    registry = _factory_reset()
    live = _recreate_default(reset_root)
    data = yaml.safe_load(live.read_text(encoding="utf-8"))
    data["hotkey"] = "f7"
    live.write_text(yaml.safe_dump(data), encoding="utf-8")

    verdict, profiles = _profiles_verdict(registry)

    assert not verdict["ok"]
    assert "profiles" in verdict["failed"]
    assert not profiles["ok"]
    assert str(live) in profiles["remaining"]
    # The detail names the setting that changed, never its value: values are
    # user settings and the verdict is shown on screen.
    assert "hotkey" in profiles["detail"]
    assert "f7" not in profiles["detail"]


def test_extra_profile_beside_recreated_default_fails(reset_root):
    registry = _factory_reset()
    _recreate_default(reset_root)
    work = reset_root / "profiles" / "Work.yaml"
    work.write_text("hotkey: f9\n", encoding="utf-8")

    verdict, profiles = _profiles_verdict(registry)

    assert not verdict["ok"]
    assert "profiles" in verdict["failed"]
    assert str(work) in profiles["remaining"]


def test_legacy_config_yaml_fails(reset_root):
    registry = _factory_reset()
    _recreate_default(reset_root)
    legacy = reset_root / "config.yaml"
    legacy.write_text("hotkey: f7\n", encoding="utf-8")

    verdict, profiles = _profiles_verdict(registry)

    assert "profiles" in verdict["failed"]
    assert str(legacy) in profiles["remaining"]


def test_unexpected_file_inside_profiles_fails(reset_root):
    registry = _factory_reset()
    _recreate_default(reset_root)
    stray = reset_root / "profiles" / "notes.txt"
    stray.write_text("scratch", encoding="utf-8")

    verdict, profiles = _profiles_verdict(registry)

    assert "profiles" in verdict["failed"]
    assert str(stray) in profiles["remaining"]


def test_no_profiles_directory_passes_and_is_not_created(reset_root):
    registry = _factory_reset()
    assert not (reset_root / "profiles").exists()

    verdict, profiles = _profiles_verdict(registry)

    assert profiles["ok"], profiles
    assert "profiles" not in verdict["failed"]
    assert not (reset_root / "profiles").exists(), "verification created profiles/"


def test_verification_writes_nothing_when_the_default_is_recreated(reset_root):
    registry = _factory_reset()
    _recreate_default(reset_root)
    before = _tree(reset_root)

    dl.verify_factory_reset(registry)

    assert _tree(reset_root) == before, "verify_factory_reset changed the data root"


def test_untouched_backup_of_the_recreated_default_is_accepted(reset_root):
    registry = _factory_reset()
    live = _recreate_default(reset_root)
    # save_profile writes a .bak when it overwrites an existing profile. Saving
    # the untouched defaults again is the ordinary way to get one.
    utils.save_profile("Default", utils.load_profile("Default"))
    bak = live.with_name(live.name + ".bak")
    assert bak.is_file()

    _, profiles = _profiles_verdict(registry)

    assert profiles["ok"], profiles


def test_changed_backup_fails(reset_root):
    registry = _factory_reset()
    live = _recreate_default(reset_root)
    utils.save_profile("Default", utils.load_profile("Default"))
    bak = live.with_name(live.name + ".bak")
    data = yaml.safe_load(bak.read_text(encoding="utf-8"))
    data["hotkey"] = "f7"
    bak.write_text(yaml.safe_dump(data), encoding="utf-8")

    verdict, profiles = _profiles_verdict(registry)

    assert "profiles" in verdict["failed"]
    assert str(bak) in profiles["remaining"]


def test_backup_without_its_live_profile_fails(reset_root):
    registry = _factory_reset()
    profiles_dir = reset_root / "profiles"
    profiles_dir.mkdir()
    orphan = profiles_dir / "Default.yaml.bak"
    orphan.write_text(yaml.safe_dump(dc._untouched_default_profile()), encoding="utf-8")

    verdict, profiles = _profiles_verdict(registry)

    assert "profiles" in verdict["failed"]
    assert str(orphan) in profiles["remaining"]


def test_unreadable_recreated_default_fails(reset_root):
    registry = _factory_reset()
    live = _recreate_default(reset_root)
    live.write_text("hotkey: [unclosed\n", encoding="utf-8")

    verdict, profiles = _profiles_verdict(registry)

    assert "profiles" in verdict["failed"]
    assert str(live) in profiles["remaining"]


def test_expected_default_matches_what_the_app_writes(reset_root):
    """The verifier's notion of "untouched" must be the file load_profile
    actually writes, or the pass above is a coincidence of two copies."""
    live = _recreate_default(reset_root)
    written = yaml.safe_load(live.read_text(encoding="utf-8"))

    assert written == dc._untouched_default_profile()


def test_reset_still_deletes_a_customised_profile_directory(reset_root):
    profiles = reset_root / "profiles"
    profiles.mkdir()
    (profiles / "Default.yaml").write_text("hotkey: f7\n", encoding="utf-8")
    (profiles / "Work.yaml").write_text("hotkey: f9\n", encoding="utf-8")
    (reset_root / "config.yaml").write_text("hotkey: f7\n", encoding="utf-8")

    result = dl.factory_reset(dc.build_registry())

    assert result["ok"], result
    assert not profiles.exists()
    assert not (reset_root / "config.yaml").exists()
