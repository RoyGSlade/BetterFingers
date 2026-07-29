"""Unified data root + legacy migration (P2 unified paths).

One resolved base under which every subpath lives; the resolver honors an
explicit override / APPDATA / an existing legacy dir before falling back to the
platform default; migration consolidates a legacy/split root idempotently.
"""

import contextlib
import os
import sys
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
                # No APPDATA, no legacy data → platform default. The expected
                # segment differs per OS (XDG on Linux, Application Support on
                # macOS, AppData on Windows) — this test runs on all three in CI.
                base = app_paths.resolve_base()
                self.assertIn("BetterFingers", str(base))
                if sys.platform.startswith("win"):
                    self.assertIn("AppData", str(base))
                elif sys.platform == "darwin":
                    self.assertIn(os.path.join("Library", "Application Support"), str(base))
                else:
                    self.assertIn(".local/share", str(base))

    def test_existing_legacy_dir_with_data_is_kept(self):
        with self._legacy_home() as (home, legacy):
            (legacy / "profiles").mkdir()
            (legacy / "profiles" / "Default.yaml").write_text("{}")
            self.assertEqual(self._resolve(home), legacy)

    # --- the data-root election defect (Wave 12A) ---------------------------
    #
    # resolve_base() used to elect the legacy root whenever it was merely
    # non-empty. The app writes debug.log into whatever root it resolves, so
    # one boot was enough for an empty ~/BetterFingers to nominate itself, and
    # from then on every read returned defaults (no profile, no personas, no
    # voices were there) and every write landed away from the real data.

    @contextlib.contextmanager
    def _legacy_home(self):
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / "BetterFingers"
            legacy.mkdir()
            yield Path(home), legacy

    def _resolve(self, home):
        env = {k: v for k, v in os.environ.items()
               if k not in ("BETTERFINGERS_DATA_DIR", "APPDATA", "XDG_DATA_HOME")}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(app_paths.Path, "home", staticmethod(lambda: Path(home))):
            return app_paths.resolve_base()

    def _report(self, home):
        env = {k: v for k, v in os.environ.items()
               if k not in ("BETTERFINGERS_DATA_DIR", "APPDATA", "XDG_DATA_HOME")}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(app_paths.Path, "home", staticmethod(lambda: Path(home))):
            return app_paths.resolve_base_report()

    def test_decoy_log_file_does_not_elect_the_legacy_root(self):
        """The exact user-reported failure: the app's own debug.log elected a
        root that held no data, so every setting read as its default."""
        with self._legacy_home() as (home, legacy):
            (legacy / "debug.log").write_text("2026-07-28 - INFO - App started.\n")
            self.assertNotEqual(self._resolve(home), legacy)

    def test_app_written_bootstrap_files_alone_do_not_elect(self):
        for name, body in (("debug.log", "log\n"),
                           (".first_run_complete", "Welcome to BetterFingers!"),
                           ("app_state.yaml", "launch_count: 3\n")):
            with self.subTest(name=name), self._legacy_home() as (home, legacy):
                (legacy / name).write_text(body)
                self.assertNotEqual(self._resolve(home), legacy)

    def test_unreadable_leftover_directory_does_not_elect(self):
        """A root-owned leftover the app cannot even read is not data."""
        with self._legacy_home() as (home, legacy):
            stray = legacy / "backup"
            stray.mkdir()
            (stray / "x").write_text("x")
            os.chmod(stray, 0o000)
            try:
                self.assertNotEqual(self._resolve(home), legacy)
            finally:
                os.chmod(stray, 0o700)

    def test_empty_marker_directory_does_not_elect(self):
        """An empty voices/ is a directory the app made, not a cloned voice."""
        with self._legacy_home() as (home, legacy):
            (legacy / "voices").mkdir()
            self.assertNotEqual(self._resolve(home), legacy)

    def test_genuine_legacy_install_is_still_found(self):
        """The case the heuristic exists for must keep working — for every
        marker on its own, not just the one the fix was written against."""
        cases = {
            "personas.yaml": lambda p: (p / "personas.yaml").write_text("a: {}\n"),
            "history.db": lambda p: (p / "history.db").write_bytes(b"SQLite"),
            "config.yaml": lambda p: (p / "config.yaml").write_text("model: x\n"),
            "voice_presets.json": lambda p: (p / "voice_presets.json").write_text("{}"),
            "contacts.json": lambda p: (p / "contacts.json").write_text("{}"),
            "voices/": lambda p: ((p / "voices").mkdir(),
                                  (p / "voices" / "me.wav").write_bytes(b"RIFF")),
            "models/": lambda p: ((p / "models").mkdir(),
                                  (p / "models" / "m.gguf").write_bytes(b"GGUF")),
        }
        for label, populate in cases.items():
            with self.subTest(marker=label), self._legacy_home() as (home, legacy):
                populate(legacy)
                self.assertEqual(self._resolve(home), legacy)

    def test_real_data_still_wins_when_a_decoy_log_sits_beside_it(self):
        with self._legacy_home() as (home, legacy):
            (legacy / "debug.log").write_text("log\n")
            (legacy / "personas.yaml").write_text("a: {}\n")
            self.assertEqual(self._resolve(home), legacy)


class AppdataIsolationTests(unittest.TestCase):
    """APPDATA is how the suite and callers pin the data root somewhere safe.

    The whole test suite's isolation rests on this: tests/conftest.py points
    APPDATA at a temp dir, and destructive coverage (privacy wipe, factory
    reset, migration) then deletes whatever the resolver returns. A resolver
    that read APPDATA as a boolean rather than as a VALUE would send all of
    that at the developer's own ~/BetterFingers while every test still passed.
    """

    def test_appdata_value_is_honoured_not_just_its_presence(self):
        with tempfile.TemporaryDirectory() as tmp:
            appdata = Path(tmp) / "isolated"
            appdata.mkdir()
            # A populated real-looking install at HOME, to be sure the resolver
            # prefers the pinned location over data it can see elsewhere.
            home = Path(tmp) / "home"
            (home / "BetterFingers" / "profiles").mkdir(parents=True)
            (home / "BetterFingers" / "profiles" / "Default.yaml").write_text("{}")
            (home / "BetterFingers" / "personas.yaml").write_text("a: {}\n")

            env = {k: v for k, v in os.environ.items()
                   if k not in ("BETTERFINGERS_DATA_DIR",)}
            env["APPDATA"] = str(appdata)
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(app_paths.Path, "home", staticmethod(lambda: home)):
                base = app_paths.resolve_base()

            self.assertTrue(
                str(base).startswith(str(appdata)),
                f"APPDATA={appdata} must decide the root, got {base}")
            self.assertFalse(
                str(base).startswith(str(home)),
                f"resolved onto HOME ({home}) despite APPDATA being pinned: {base}")

    def test_env_override_outranks_appdata(self):
        """conftest pins BETTERFINGERS_DATA_DIR as the belt-and-braces rule, so
        it has to win even when APPDATA points somewhere else."""
        with tempfile.TemporaryDirectory() as tmp:
            pinned = Path(tmp) / "pinned"
            pinned.mkdir()
            env = dict(os.environ)
            env["APPDATA"] = str(Path(tmp) / "elsewhere")
            env["BETTERFINGERS_DATA_DIR"] = str(pinned)
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(app_paths.resolve_base(), pinned)

    def test_no_env_var_can_be_read_as_a_bare_boolean(self):
        """Each of the two pinning vars must move the answer to where it points.

        Written as a loop over both so that adding a third pinning rule that
        forgets to read its own value fails here.
        """
        for var in ("BETTERFINGERS_DATA_DIR", "APPDATA"):
            with self.subTest(var=var), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "target"
                target.mkdir()
                env = {k: v for k, v in os.environ.items()
                       if k not in ("BETTERFINGERS_DATA_DIR", "APPDATA")}
                env[var] = str(target)
                with patch.dict(os.environ, env, clear=True):
                    base = app_paths.resolve_base()
                self.assertTrue(
                    str(base).startswith(str(target)),
                    f"{var}={target} did not decide the root; got {base}")


class ResolutionReportTests(unittest.TestCase):
    """The decision must be reportable — a user seeing empty settings has to be
    able to find out which root was chosen and why."""

    def _report(self, home):
        env = {k: v for k, v in os.environ.items()
               if k not in ("BETTERFINGERS_DATA_DIR", "APPDATA", "XDG_DATA_HOME")}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(app_paths.Path, "home", staticmethod(lambda: Path(home))):
            return app_paths.resolve_base_report()

    def test_reason_codes_and_evidence(self):
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / "BetterFingers"
            legacy.mkdir()
            (legacy / "debug.log").write_text("log\n")

            rejected = self._report(Path(home))
            self.assertEqual(rejected.reason, "platform_default")
            self.assertNotEqual(rejected.base, legacy)
            # The rejected root is still reported, with no markers, so the
            # user can see it was considered and why it lost.
            legacy_row = [c for c in rejected.candidates
                          if c["path"] == str(legacy)][0]
            self.assertTrue(legacy_row["exists"])
            self.assertEqual(legacy_row["markers"], [])
            self.assertFalse(legacy_row["chosen"])

            (legacy / "personas.yaml").write_text("a: {}\n")
            kept = self._report(Path(home))
            self.assertEqual(kept.reason, "legacy_install")
            self.assertEqual(kept.base, legacy)
            self.assertIn("personas.yaml", kept.detail)
            self.assertEqual([c for c in kept.candidates if c["chosen"]][0]["markers"],
                             ["personas.yaml"])

    def test_env_override_reports_itself(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.dict(os.environ, {"BETTERFINGERS_DATA_DIR": d}, clear=False):
            report = app_paths.resolve_base_report()
            self.assertEqual(report.reason, "env_override")
            self.assertEqual(report.base, Path(d))

    def test_describe_locations_carries_the_reason_and_markers(self):
        locs = app_paths.describe_locations()
        current = [loc for loc in locs if loc["current"]][0]
        self.assertIn(current["reason"], ("env_override", "appdata",
                                          "legacy_install", "platform_default"))
        self.assertTrue(current["detail"])
        for loc in locs:
            self.assertIsInstance(loc["markers"], list)


class DataMarkerTests(unittest.TestCase):
    def test_markers_never_raise_on_an_unreadable_root(self):
        with tempfile.TemporaryDirectory() as root:
            locked = Path(root) / "locked"
            locked.mkdir()
            os.chmod(locked, 0o000)
            try:
                self.assertEqual(app_paths.data_markers(locked), [])
            finally:
                os.chmod(locked, 0o700)

    def test_markers_on_a_missing_or_non_directory_path(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(app_paths.data_markers(Path(root) / "nope"), [])
            afile = Path(root) / "afile"
            afile.write_text("x")
            self.assertEqual(app_paths.data_markers(afile), [])

    def test_bootstrap_names_are_deliberately_not_markers(self):
        for name in ("debug.log", ".first_run_complete", "app_state.yaml"):
            self.assertNotIn(name, app_paths._MARKER_FILES)
        for name in ("tmp", "cache", "exports"):
            self.assertNotIn(name, app_paths._MARKER_DIRS)


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


def _resolution(base, reason="platform_default"):
    """A BaseResolution standing in for a real election of ``base``.

    Migration now reads the *reason* a root was chosen, not just the path, so
    these tests hand it a full resolution rather than patching ``resolve_base``.
    """
    return app_paths.BaseResolution(base=base, reason=reason, detail="test", candidates=[])


class MigrationTests(unittest.TestCase):
    def test_migrate_moves_legacy_entries_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            current = Path(root) / "current"
            legacy = Path(root) / "legacy"
            legacy.mkdir()
            (legacy / "voices").mkdir()
            (legacy / "voices" / "a.wav").write_text("x")
            (legacy / "graph.json").write_text("{}")

            with patch.object(app_paths, "resolve_base_report",
                              return_value=_resolution(current)), \
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

            with patch.object(app_paths, "resolve_base_report",
                              return_value=_resolution(current)), \
                 patch.object(app_paths, "_known_legacy_roots", return_value=[legacy]):
                report = app_paths.migrate_legacy_data()
            self.assertIn("graph.json", report["skipped"])
            self.assertEqual((current / "graph.json").read_text(), "KEEP")

    # --- P0 (2026-07-29): an explicit root is a destination, never a magnet ---
    #
    # BETTERFINGERS_DATA_DIR is how every test, probe and agent in this project
    # isolates a boot. Migration used to run regardless of *why* the base was
    # chosen, and _known_legacy_roots always includes ~/BetterFingers on POSIX
    # (APPDATA is Windows-only, so _legacy_home_base always falls back to the
    # home directory). So setting the override to a scratch directory moved the
    # user's REAL install into the scratch directory -- and shutil.move across
    # filesystems deletes the source. These tests pin the repair.

    def test_env_override_never_pulls_the_real_install_into_itself(self):
        with tempfile.TemporaryDirectory() as root:
            scratch = Path(root) / "scratch"
            real = Path(root) / "home" / "BetterFingers"
            (real / "voices").mkdir(parents=True)
            (real / "voices" / "cloned.wav").write_text("irreplaceable")
            (real / "history.db").write_text("real history")

            env = dict(os.environ)
            env["BETTERFINGERS_DATA_DIR"] = str(scratch)
            env.pop("APPDATA", None)
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(app_paths.Path, "home",
                              staticmethod(lambda: Path(root) / "home")):
                report = app_paths.migrate_legacy_data()

            # Nothing moved, and the real install is untouched.
            self.assertEqual(report["moved"], [])
            self.assertEqual(report["skipped_reason"], "env_override")
            self.assertTrue((real / "voices" / "cloned.wav").exists())
            self.assertEqual((real / "voices" / "cloned.wav").read_text(),
                             "irreplaceable")
            self.assertEqual((real / "history.db").read_text(), "real history")
            self.assertFalse((scratch / "voices").exists())

    def test_appdata_on_posix_does_not_pull_the_real_install_in(self):
        # On POSIX an APPDATA value is always something a caller set, so it is
        # a pin, not the platform location. Only Windows treats it as native.
        with tempfile.TemporaryDirectory() as root:
            pinned = Path(root) / "pinned"
            real = Path(root) / "home" / "BetterFingers"
            (real / "profiles").mkdir(parents=True)
            (real / "profiles" / "me.json").write_text("{}")

            env = dict(os.environ)
            env.pop("BETTERFINGERS_DATA_DIR", None)
            env["APPDATA"] = str(pinned)
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(app_paths.Path, "home",
                              staticmethod(lambda: Path(root) / "home")), \
                 patch.object(app_paths.os, "name", "posix"):
                report = app_paths.migrate_legacy_data()

            self.assertEqual(report["moved"], [])
            self.assertEqual(report["skipped_reason"], "appdata")
            self.assertTrue((real / "profiles" / "me.json").exists())

    def test_windows_appdata_still_consolidates(self):
        # The guard must not break the genuine Windows upgrade path, where the
        # OS itself sets APPDATA and it really is the platform location.
        with tempfile.TemporaryDirectory() as root:
            appdata = Path(root) / "AppData"
            legacy = Path(root) / "legacy"
            legacy.mkdir()
            (legacy / "graph.json").write_text("{}")

            with patch.object(app_paths, "resolve_base_report",
                              return_value=_resolution(appdata / "BetterFingers",
                                                       reason="appdata")), \
                 patch.object(app_paths, "_known_legacy_roots", return_value=[legacy]), \
                 patch.object(app_paths.os, "name", "nt"):
                report = app_paths.migrate_legacy_data()

            self.assertIn("graph.json", report["moved"])

    def test_only_app_chosen_roots_are_migration_targets(self):
        allowed = {"platform_default", "legacy_install"}
        for reason in ("platform_default", "legacy_install", "env_override", "appdata"):
            with patch.object(app_paths.os, "name", "posix"):
                may = app_paths._may_migrate_into(_resolution(Path("/tmp/x"), reason))
            self.assertEqual(may, reason in allowed,
                             "reason {!r} changed migration eligibility".format(reason))

    # Both directions, under the repaired election rule: whichever root the
    # resolver picks must be the migration *target*, never the source. Getting
    # this backwards would move a real install into a decoy root — the failure
    # the election fix exists to prevent, arriving by another door.

    def _migrate_with_real_resolution(self, home):
        env = {k: v for k, v in os.environ.items()
               if k not in ("BETTERFINGERS_DATA_DIR", "APPDATA", "XDG_DATA_HOME")}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(app_paths.Path, "home", staticmethod(lambda: Path(home))):
            base = app_paths.resolve_base()
            return base, app_paths.migrate_legacy_data()

    def test_migration_pulls_platform_data_into_a_genuine_legacy_install(self):
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / "BetterFingers"
            (legacy / "profiles").mkdir(parents=True)
            (legacy / "profiles" / "Default.yaml").write_text("real")
            platform = Path(home) / ".local" / "share" / "BetterFingers"
            (platform / "voices").mkdir(parents=True)
            (platform / "voices" / "me.wav").write_bytes(b"RIFF")

            with patch.object(app_paths, "_platform_base", return_value=platform):
                base, report = self._migrate_with_real_resolution(Path(home))

            self.assertEqual(base, legacy)
            self.assertIn("voices", report["moved"])
            self.assertTrue((legacy / "voices" / "me.wav").exists())
            self.assertTrue((legacy / "profiles" / "Default.yaml").exists())

    def test_migration_does_not_drag_a_real_install_into_a_decoy_root(self):
        """Legacy holds only the app's own log; the real data is at the
        platform root. Nothing may move out of the platform root."""
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / "BetterFingers"
            legacy.mkdir(parents=True)
            (legacy / "debug.log").write_text("log\n")
            platform = Path(home) / ".local" / "share" / "BetterFingers"
            (platform / "profiles").mkdir(parents=True)
            (platform / "profiles" / "Default.yaml").write_text("real")
            (platform / "personas.yaml").write_text("a: {}\n")

            with patch.object(app_paths, "_platform_base", return_value=platform):
                base, report = self._migrate_with_real_resolution(Path(home))

            self.assertEqual(base, platform)
            self.assertTrue((platform / "profiles" / "Default.yaml").exists())
            self.assertTrue((platform / "personas.yaml").exists())
            self.assertFalse((legacy / "profiles").exists())

    def test_migration_is_stable_across_a_second_run(self):
        """Resolution must not oscillate: migrating once moves markers into the
        chosen root, and re-resolving must pick that same root again."""
        with tempfile.TemporaryDirectory() as home:
            legacy = Path(home) / "BetterFingers"
            legacy.mkdir(parents=True)
            (legacy / "debug.log").write_text("log\n")
            platform = Path(home) / ".local" / "share" / "BetterFingers"
            (platform / "personas.yaml").parent.mkdir(parents=True)
            (platform / "personas.yaml").write_text("a: {}\n")

            with patch.object(app_paths, "_platform_base", return_value=platform):
                first, _ = self._migrate_with_real_resolution(Path(home))
                second, report2 = self._migrate_with_real_resolution(Path(home))

            self.assertEqual(first, platform)
            self.assertEqual(second, platform)
            self.assertEqual(report2["moved"], [])


class DescribeLocationsTests(unittest.TestCase):
    def test_describe_marks_current_and_lists_legacy(self):
        locs = app_paths.describe_locations()
        self.assertTrue(any(loc["current"] for loc in locs))
        # Exactly one current entry.
        self.assertEqual(sum(1 for loc in locs if loc["current"]), 1)


if __name__ == "__main__":
    unittest.main()
