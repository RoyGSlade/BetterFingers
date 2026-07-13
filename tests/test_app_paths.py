"""Unified data root + legacy migration (P2 unified paths).

One resolved base under which every subpath lives; the resolver honors an
explicit override / APPDATA / an existing legacy dir before falling back to the
platform default; migration consolidates a legacy/split root idempotently.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_paths


class ResolveBaseTests(unittest.TestCase):
    def test_env_override_wins(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.dict(os.environ, {"BETTERFINGERS_DATA_DIR": d}, clear=False):
            self.assertEqual(app_paths.resolve_base(), Path(d))

    def test_appdata_used_when_set(self):
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items()
                   if k not in ("BETTERFINGERS_DATA_DIR",)}
            env["APPDATA"] = d
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(app_paths.resolve_base(), Path(d) / "BetterFingers")

    def test_fresh_install_falls_back_to_platform_dir(self):
        with tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items()
                   if k not in ("BETTERFINGERS_DATA_DIR", "APPDATA", "XDG_DATA_HOME")}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(app_paths.Path, "home", staticmethod(lambda: Path(home))):
                # No APPDATA, no legacy data → platform (XDG) default.
                base = app_paths.resolve_base()
                self.assertIn("BetterFingers", str(base))
                self.assertIn(".local/share", str(base))

    def test_existing_legacy_dir_with_data_is_kept(self):
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / "BetterFingers"
            legacy.mkdir()
            (legacy / "profiles").mkdir()  # non-empty → existing install
            env = {k: v for k, v in os.environ.items()
                   if k not in ("BETTERFINGERS_DATA_DIR", "APPDATA")}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(app_paths.Path, "home", staticmethod(lambda: Path(home))):
                self.assertEqual(app_paths.resolve_base(), legacy)


class AppPathsShapeTests(unittest.TestCase):
    def test_all_subpaths_under_base(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.dict(os.environ, {"BETTERFINGERS_DATA_DIR": d}, clear=False):
            ap = app_paths.get_app_paths()
            base = Path(d)
            for p in (ap.data, ap.config, ap.cache, ap.logs, ap.recordings,
                      ap.models, ap.voices, ap.history_db, ap.drafts_json,
                      ap.temp, ap.exports):
                self.assertTrue(str(p).startswith(str(base)), f"{p} not under {base}")

    def test_apppaths_is_frozen(self):
        ap = app_paths.get_app_paths()
        with self.assertRaises(Exception):
            ap.data = Path("/tmp/elsewhere")


class MigrationTests(unittest.TestCase):
    def test_migrate_moves_legacy_entries_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            current = Path(root) / "current"
            legacy = Path(root) / "legacy"
            legacy.mkdir()
            (legacy / "voices").mkdir()
            (legacy / "voices" / "a.wav").write_text("x")
            (legacy / "graph.json").write_text("{}")

            with patch.object(app_paths, "resolve_base", return_value=current), \
                 patch.object(app_paths, "_known_legacy_roots", return_value=[legacy]):
                report = app_paths.migrate_legacy_data()
                self.assertIn("voices", report["moved"])
                self.assertIn("graph.json", report["moved"])
                self.assertTrue((current / "voices" / "a.wav").exists())
                # Re-running is a no-op (nothing left to move).
                report2 = app_paths.migrate_legacy_data()
                self.assertEqual(report2["moved"], [])

    def test_migrate_never_clobbers_existing_target(self):
        with tempfile.TemporaryDirectory() as root:
            current = Path(root) / "current"
            current.mkdir()
            (current / "graph.json").write_text("KEEP")
            legacy = Path(root) / "legacy"
            legacy.mkdir()
            (legacy / "graph.json").write_text("OLD")

            with patch.object(app_paths, "resolve_base", return_value=current), \
                 patch.object(app_paths, "_known_legacy_roots", return_value=[legacy]):
                report = app_paths.migrate_legacy_data()
            self.assertIn("graph.json", report["skipped"])
            self.assertEqual((current / "graph.json").read_text(), "KEEP")


class DescribeLocationsTests(unittest.TestCase):
    def test_describe_marks_current_and_lists_legacy(self):
        locs = app_paths.describe_locations()
        self.assertTrue(any(loc["current"] for loc in locs))
        # Exactly one current entry.
        self.assertEqual(sum(1 for loc in locs if loc["current"]), 1)


if __name__ == "__main__":
    unittest.main()
