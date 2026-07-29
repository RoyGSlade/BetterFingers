"""data_paths.py had no dedicated test file: its Electron-owned-root resolution
(electron_user_data_candidates) and its "only existing paths, no side effects"
invariant (_existing) were only ever exercised indirectly through
test_wipe_modes.py / test_privacy_report_agreement.py. Both matter specifically
for the packaged Linux AppImage: Electron's app.getPath('userData') resolves to
$XDG_CONFIG_HOME/<name> (or ~/.config/<name>) on Linux, never something inside
the read-only AppImage mount, and the privacy report must never manufacture a
directory just by asking where data lives.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import data_paths


class ElectronUserDataCandidatesLinuxTests(unittest.TestCase):
    def test_uses_xdg_config_home_when_set(self):
        with tempfile.TemporaryDirectory() as xdg_config:
            with patch.object(sys, "platform", "linux"), patch.dict(
                os.environ, {"XDG_CONFIG_HOME": xdg_config}, clear=False
            ):
                candidates = data_paths.electron_user_data_candidates()
                self.assertIn(Path(xdg_config) / "BetterFingers", candidates)
                self.assertIn(Path(xdg_config) / "betterfingers-electron", candidates)

    def test_falls_back_to_dot_config_when_xdg_unset(self):
        with tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
            with patch.object(sys, "platform", "linux"), patch.dict(
                os.environ, env, clear=True
            ), patch.object(Path, "home", return_value=Path(home)):
                candidates = data_paths.electron_user_data_candidates()
                self.assertIn(Path(home) / ".config" / "BetterFingers", candidates)

    def test_never_resolves_under_a_path_relative_to_this_file(self):
        # A packaged AppImage runs from a read-only, per-launch squashfs mount;
        # if this ever resolved relative to __file__/cwd instead of Path.home(),
        # the privacy report and factory reset would silently point at that
        # mount instead of real user data.
        with tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
            with patch.object(sys, "platform", "linux"), patch.dict(
                os.environ, env, clear=True
            ), patch.object(Path, "home", return_value=Path(home)):
                candidates = data_paths.electron_user_data_candidates()
                repo_root = Path(__file__).resolve().parent.parent
                for candidate in candidates:
                    self.assertFalse(
                        str(candidate.resolve()).startswith(str(repo_root)),
                        f"{candidate} resolves inside the repo checkout, not a real home directory",
                    )


class ExistingHasNoSideEffectsTests(unittest.TestCase):
    def test_existing_never_creates_a_directory(self):
        with tempfile.TemporaryDirectory() as root:
            missing = Path(root) / "not-there-yet" / "recordings"
            self.assertFalse(missing.exists())
            result = data_paths._existing(missing)
            self.assertEqual(result, [])
            self.assertFalse(missing.exists(), "_existing() must never create the path it is checking")

    def test_existing_only_returns_paths_that_are_really_on_disk(self):
        with tempfile.TemporaryDirectory() as root:
            present = Path(root) / "present.json"
            present.write_text("{}")
            absent = Path(root) / "absent.json"
            result = data_paths._existing(present, absent)
            self.assertEqual(result, [present])

    def test_existing_deduplicates_in_order(self):
        with tempfile.TemporaryDirectory() as root:
            present = Path(root) / "present.json"
            present.write_text("{}")
            result = data_paths._existing(present, present)
            self.assertEqual(result, [present])

    def test_existing_tolerates_an_unreadable_candidate_without_raising(self):
        # candidate.exists() can raise OSError on a broken/unreadable mount;
        # a privacy report must degrade to "not found", never crash.
        class ExplodingPath:
            def exists(self):
                raise OSError("simulated unreadable path")

        result = data_paths._existing(ExplodingPath())
        self.assertEqual(result, [])


class BaseUsesAppPathsResolveBaseTests(unittest.TestCase):
    def test_base_delegates_to_app_paths_resolve_base(self):
        # data_paths must never resolve its own root independently of
        # app_paths.resolve_base() (the P0-hardened single source of truth) —
        # a second resolver here would let the privacy report and the real
        # data root drift apart.
        with tempfile.TemporaryDirectory() as override:
            with patch.dict(os.environ, {"BETTERFINGERS_DATA_DIR": override}, clear=False):
                self.assertEqual(data_paths.base(), Path(override))


if __name__ == "__main__":
    unittest.main()
