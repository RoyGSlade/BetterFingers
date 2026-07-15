"""Shared config-store persistence discipline (DESIGN §9.5, Tier-3 M4 B1).

Version ladder, idempotency, corrupt quarantine, backup-per-step, downgrade
refusal, and write atomicity — the guarantees every adopting store (personas,
voice presets, profiles, app_state) relies on.
"""

import json
import os
import tempfile
import unittest

import store_migration as sm


def _default_factory():
    return {"items": []}


class QuarantineTests(unittest.TestCase):
    def test_moves_file_to_corrupt_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            with open(path, "w") as fh:
                fh.write("not json{{{")
            dest = sm.quarantine_corrupt_file(path)
            self.assertEqual(dest, f"{path}.corrupt")
            self.assertFalse(os.path.exists(path))
            self.assertTrue(os.path.exists(dest))

    def test_collision_falls_back_to_timestamp_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            open(path, "w").close()
            open(f"{path}.corrupt", "w").close()  # pre-existing quarantine
            dest = sm.quarantine_corrupt_file(path)
            self.assertNotEqual(dest, f"{path}.corrupt")
            self.assertTrue(dest.endswith(".corrupt"))
            self.assertTrue(os.path.exists(dest))

    def test_missing_file_returns_empty_string(self):
        self.assertEqual(sm.quarantine_corrupt_file("/nonexistent/path/x.json"), "")


class WriteAtomicTests(unittest.TestCase):
    def test_writes_content_and_leaves_no_tmp_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            sm.write_atomic(path, '{"a": 1}')
            with open(path) as fh:
                self.assertEqual(fh.read(), '{"a": 1}')
            leftovers = [f for f in os.listdir(d) if f != "store.json"]
            self.assertEqual(leftovers, [])

    def test_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            sm.write_atomic(path, "first")
            sm.write_atomic(path, "second")
            with open(path) as fh:
                self.assertEqual(fh.read(), "second")

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nested", "dir", "store.json")
            sm.write_atomic(path, "x")
            self.assertTrue(os.path.exists(path))

    def test_no_tmp_file_left_behind_on_write_failure(self):
        with tempfile.TemporaryDirectory() as d:
            # A directory in place of the target path makes the open() fail.
            path = os.path.join(d, "store.json")
            os.makedirs(path)
            with self.assertRaises(Exception):
                sm.write_atomic(path, "x")
            leftovers = [f for f in os.listdir(d) if f != "store.json"]
            self.assertEqual(leftovers, [])


class BackupBeforeMigrationTests(unittest.TestCase):
    def test_writes_versioned_backup(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            with open(path, "w") as fh:
                fh.write('{"schema_version": 1}')
            backup_path = sm.backup_before_migration(path, 1)
            self.assertEqual(backup_path, f"{path}.bak-v1")
            with open(backup_path) as fh:
                self.assertEqual(fh.read(), '{"schema_version": 1}')

    def test_missing_source_returns_empty_string(self):
        self.assertEqual(sm.backup_before_migration("/nonexistent/x.json", 1), "")


class DegradedEventsTests(unittest.TestCase):
    def setUp(self):
        sm.clear_degraded_events()

    tearDown = setUp

    def test_quarantine_records_a_degraded_event(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            with open(path, "w") as fh:
                fh.write("{not valid")
            sm.load_versioned_store(path, 1, {}, default_factory=_default_factory)

        events = sm.get_degraded_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "quarantined")
        self.assertIn(path, events[0]["path"])

    def test_downgrade_refusal_records_a_degraded_event(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            with open(path, "w") as fh:
                json.dump({"schema_version": 99, "items": []}, fh)
            sm.load_versioned_store(path, 1, {}, default_factory=_default_factory)

        events = sm.get_degraded_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "downgrade_refused")

    def test_successful_load_records_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            with open(path, "w") as fh:
                json.dump({"schema_version": 1, "items": []}, fh)
            sm.load_versioned_store(path, 1, {}, default_factory=_default_factory)

        self.assertEqual(sm.get_degraded_events(), [])

    def test_ring_buffer_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(sm._MAX_DEGRADED_EVENTS + 10):
                path = os.path.join(d, f"store{i}.json")
                with open(path, "w") as fh:
                    fh.write("{not valid")
                sm.load_versioned_store(path, 1, {}, default_factory=_default_factory)

        self.assertEqual(len(sm.get_degraded_events()), sm._MAX_DEGRADED_EVENTS)


class LoadVersionedStoreTests(unittest.TestCase):
    def _write(self, d, payload):
        path = os.path.join(d, "store.json")
        with open(path, "w") as fh:
            json.dump(payload, fh)
        return path

    def test_missing_file_returns_defaults_at_current_version(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            data, report = sm.load_versioned_store(
                path, 3, {}, default_factory=_default_factory
            )
            self.assertEqual(data, {"items": [], "schema_version": 3})
            self.assertEqual(report["action"], "new")
            self.assertTrue(report["ok"])

    def test_already_current_version_loads_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, {"schema_version": 3, "items": [1, 2]})
            data, report = sm.load_versioned_store(
                path, 3, {}, default_factory=_default_factory
            )
            self.assertEqual(data, {"schema_version": 3, "items": [1, 2]})
            self.assertEqual(report["action"], "loaded")
            self.assertEqual(report["from_version"], 3)

    def test_missing_schema_version_defaults_to_1(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, {"items": ["legacy"]})
            data, report = sm.load_versioned_store(
                path, 1, {}, default_factory=_default_factory
            )
            self.assertEqual(report["from_version"], 1)
            self.assertEqual(report["action"], "loaded")

    def test_version_ladder_applies_migrations_in_order(self):
        def v1_to_v2(data):
            data["items"] = [x.upper() for x in data["items"]]
            return data

        def v2_to_v3(data):
            data["items"].append("added-in-v3")
            return data

        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, {"schema_version": 1, "items": ["a", "b"]})
            data, report = sm.load_versioned_store(
                path, 3, {1: v1_to_v2, 2: v2_to_v3}, default_factory=_default_factory
            )
            self.assertEqual(data["items"], ["A", "B", "added-in-v3"])
            self.assertEqual(data["schema_version"], 3)
            self.assertEqual(report["action"], "migrated")
            self.assertEqual(report["from_version"], 1)
            self.assertEqual(report["to_version"], 3)

    def test_backup_written_once_per_version_step(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, {"schema_version": 1, "items": []})
            _, report = sm.load_versioned_store(
                path, 3, {1: lambda d: d, 2: lambda d: d}, default_factory=_default_factory
            )
            self.assertEqual(len(report["backup_paths"]), 2)
            self.assertTrue(os.path.exists(f"{path}.bak-v1"))
            self.assertTrue(os.path.exists(f"{path}.bak-v2"))

    def test_backup_disabled_writes_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, {"schema_version": 1, "items": []})
            _, report = sm.load_versioned_store(
                path, 2, {1: lambda d: d}, default_factory=_default_factory, backup=False
            )
            self.assertEqual(report["backup_paths"], [])
            self.assertFalse(os.path.exists(f"{path}.bak-v1"))

    def test_missing_migration_step_stops_short_with_warning(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, {"schema_version": 1, "items": []})
            data, report = sm.load_versioned_store(
                path, 3, {1: lambda d: d}, default_factory=_default_factory  # no 2->3 step
            )
            self.assertEqual(data["schema_version"], 2)  # stopped after the only registered step
            self.assertTrue(any("no migration registered" in w for w in report["warnings"]))

    def test_repeated_load_after_migration_is_idempotent(self):
        def v1_to_v2(data):
            data["items"] = data["items"] + ["migrated"]
            return data

        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, {"schema_version": 1, "items": ["orig"]})
            data, report = sm.load_versioned_store(
                path, 2, {1: v1_to_v2}, default_factory=_default_factory
            )
            self.assertEqual(data["items"], ["orig", "migrated"])
            self.assertEqual(report["action"], "migrated")

            # Simulate the caller persisting the migrated data, then reload:
            # migration must NOT run again (would double the "migrated" tag).
            with open(path, "w") as fh:
                json.dump(data, fh)
            data2, report2 = sm.load_versioned_store(
                path, 2, {1: v1_to_v2}, default_factory=_default_factory
            )
            self.assertEqual(data2["items"], ["orig", "migrated"])
            self.assertEqual(report2["action"], "loaded")

    def test_corrupt_json_is_quarantined_and_returns_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.json")
            with open(path, "w") as fh:
                fh.write("{not valid json")
            data, report = sm.load_versioned_store(
                path, 1, {}, default_factory=_default_factory
            )
            self.assertEqual(data, {"items": [], "schema_version": 1})
            self.assertEqual(report["action"], "quarantined")
            self.assertTrue(report["ok"])
            self.assertFalse(os.path.exists(path))
            self.assertTrue(os.path.exists(f"{path}.corrupt"))

    def test_non_mapping_top_level_is_quarantined(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, [1, 2, 3])  # a list, not a dict
            data, report = sm.load_versioned_store(
                path, 1, {}, default_factory=_default_factory
            )
            self.assertEqual(report["action"], "quarantined")
            self.assertTrue(os.path.exists(f"{path}.corrupt"))

    def test_downgrade_refused_never_touches_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, {"schema_version": 99, "items": ["future data"]})
            data, report = sm.load_versioned_store(
                path, 3, {}, default_factory=_default_factory
            )
            self.assertEqual(data, {"items": []})  # bare defaults, no schema_version stamped
            self.assertEqual(report["action"], "downgrade_refused")
            self.assertFalse(report["ok"])
            self.assertTrue(report["warnings"])
            # The file on disk is completely untouched.
            with open(path) as fh:
                on_disk = json.load(fh)
            self.assertEqual(on_disk, {"schema_version": 99, "items": ["future data"]})
            self.assertFalse(os.path.exists(f"{path}.bak-v99"))
            self.assertFalse(os.path.exists(f"{path}.corrupt"))

    def test_empty_file_parsed_as_none_is_treated_as_empty_store_not_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.yaml")
            with open(path, "w") as fh:
                fh.write("")  # e.g. yaml.safe_load("") -> None
            data, report = sm.load_versioned_store(
                path, 1, {}, default_factory=_default_factory, parse=lambda text: None if not text.strip() else json.loads(text)
            )
            self.assertEqual(report["action"], "loaded")
            self.assertNotEqual(report["action"], "quarantined")
            self.assertEqual(data.get("schema_version", 1), 1)
            self.assertFalse(os.path.exists(f"{path}.corrupt"))

    def test_custom_parse_function(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.yaml")
            with open(path, "w") as fh:
                fh.write("schema_version: 1\nitems: [a, b]\n")

            def fake_yaml_parse(text):
                # Minimal stand-in so this test has no real yaml dependency
                # beyond exercising the `parse` injection point itself.
                result = {}
                for line in text.strip().splitlines():
                    key, _, value = line.partition(":")
                    result[key.strip()] = value.strip()
                return result

            data, report = sm.load_versioned_store(
                path, 1, {}, default_factory=_default_factory, parse=fake_yaml_parse
            )
            self.assertEqual(report["action"], "loaded")
            self.assertIn("items", data)


if __name__ == "__main__":
    unittest.main()
