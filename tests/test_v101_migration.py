"""Hermetic upgrade coverage for data written by the v1.0.1 application.

The v1.0.1 tag predates the current profile/app-state schema markers.  These
tests keep a small fixture copied from that tag's on-disk shape and verify that
current code preserves it in an isolated data root.  The failure case pins the
rollback boundary: a failed migration may create a backup, but must not change
the source file or expose a partially migrated file as the current store.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import store_migration
import utils


class V101MigrationTests(unittest.TestCase):
    def test_v101_config_and_app_state_preserve_user_values_in_isolated_root(self):
        """The v1.0.1 unversioned files survive current startup migration."""
        with tempfile.TemporaryDirectory(prefix="betterfingers-v101-") as root:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = root
            try:
                data_root = Path(root) / "BetterFingers"
                profiles = data_root / "profiles"
                profiles.mkdir(parents=True)

                # Exact fields and values from v1.0.1's tracked config.yaml;
                # current code merges them into the profile schema.
                legacy_config = {
                    "hotkey": "f8",
                    "max_inter_key_delay": 0.0012,
                    "max_key_hold": 0.015,
                    "min_inter_key_delay": 0.0008,
                    "min_key_hold": 0.005,
                    "model_size": "base.en",
                }
                config_path = data_root / "config.yaml"
                config_path.write_text(yaml.safe_dump(legacy_config, sort_keys=True), encoding="utf-8")
                config_before = config_path.read_bytes()

                # v1.0.1 wrote app_state.yaml without schema_version.
                state_path = data_root / "app_state.yaml"
                state_path.write_text(
                    yaml.safe_dump(
                        {
                            "launch_count": 7,
                            "donation_prompt_shown": True,
                            "last_active_profile": "Default",
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                state_before = state_path.read_bytes()

                profile = utils.load_profile("Default")
                state = utils.load_app_state()

                self.assertEqual(profile["hotkey"], "f8")
                self.assertEqual(profile["model_size"], "base.en")
                self.assertEqual(profile["min_inter_key_delay"], 0.0008)
                self.assertEqual(profile["max_inter_key_delay"], 0.0012)
                self.assertEqual(state["launch_count"], 7)
                self.assertTrue(state["donation_prompt_shown"])

                migrated_profile = profiles / "Default.yaml"
                self.assertTrue(migrated_profile.is_file())
                self.assertEqual(yaml.safe_load(migrated_profile.read_text(encoding="utf-8"))["schema_version"], 1)
                self.assertEqual(config_path.read_bytes(), config_before)
                self.assertEqual(state_path.read_bytes(), state_before)
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata

    def test_failed_v101_to_current_step_preserves_source_and_backup(self):
        """A migration exception cannot publish partial data over v1.0.1."""
        with tempfile.TemporaryDirectory(prefix="betterfingers-v101-rollback-") as root:
            path = Path(root) / "legacy-store.json"
            original = '{"schema_version": 1, "items": ["legacy"], "keep": "yes"}\n'
            path.write_text(original, encoding="utf-8")

            def failed_step(data):
                data["items"].append("partial")
                raise RuntimeError("simulated migration failure")

            with self.assertRaisesRegex(RuntimeError, "simulated migration failure"):
                store_migration.load_versioned_store(
                    path,
                    2,
                    {1: failed_step},
                    default_factory=lambda: {"items": []},
                )

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            backup = Path(f"{path}.bak-v1")
            self.assertEqual(backup.read_text(encoding="utf-8"), original)
            self.assertFalse(Path(f"{path}.tmp").exists())

    def test_current_write_failure_leaves_existing_profile_bytes_unchanged(self):
        """A rejected current write cannot replace the migrated profile."""
        with tempfile.TemporaryDirectory(prefix="betterfingers-v101-write-") as root:
            with patch.dict(os.environ, {"APPDATA": root}, clear=False):
                utils.save_profile("Default", {"hotkey": "f8", "model_size": "base.en"})
                path = Path(root) / "BetterFingers" / "profiles" / "Default.yaml"
                before = path.read_bytes()

                with patch.object(
                    utils,
                    "validate_profile_settings",
                    side_effect=ValueError("simulated validation failure"),
                ), self.assertRaisesRegex(ValueError, "simulated validation failure"):
                    utils.save_profile("Default", {"hotkey": "f8"})

                self.assertEqual(path.read_bytes(), before)
                self.assertFalse(Path(f"{path}.tmp").exists())


if __name__ == "__main__":
    unittest.main()
