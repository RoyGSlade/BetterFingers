import os
import tempfile
import unittest

import macros
from macros import apply_macros


class ApplyMacrosTests(unittest.TestCase):
    DATA = [
        {"trigger": "my address", "expansion": "123 Main St, Springfield"},
        {"trigger": "sign off", "expansion": "Best regards, John"},
        {"trigger": "eta", "expansion": "estimated time of arrival"},
    ]

    def test_expands_multi_word_trigger(self):
        self.assertEqual(
            apply_macros("send it to my address today", self.DATA),
            "send it to 123 Main St, Springfield today",
        )

    def test_case_insensitive_trigger(self):
        self.assertEqual(apply_macros("My Address", self.DATA), "123 Main St, Springfield")

    def test_word_boundary_safe(self):
        # 'my addresses' must not expand; 'beta' must not trigger 'eta'.
        self.assertEqual(apply_macros("my addresses", self.DATA), "my addresses")
        self.assertEqual(apply_macros("the beta test", self.DATA), "the beta test")

    def test_standalone_word_trigger(self):
        self.assertEqual(
            apply_macros("what is the eta", self.DATA),
            "what is the estimated time of arrival",
        )

    def test_longest_trigger_wins(self):
        data = [
            {"trigger": "address", "expansion": "ADDR"},
            {"trigger": "my address", "expansion": "123 Main St"},
        ]
        self.assertEqual(apply_macros("my address", data), "123 Main St")

    def test_no_macros_or_empty(self):
        self.assertEqual(apply_macros("hello", []), "hello")
        self.assertEqual(apply_macros("", self.DATA), "")
        self.assertEqual(apply_macros(None, self.DATA), None)


class GetMacrosCorruptFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()

    def _path(self):
        return macros._macros_path()

    def test_missing_file_returns_empty_list_silently(self):
        self.assertEqual(macros.get_macros(), [])

    def test_save_then_get_round_trips_without_crashing(self):
        # Regression: _save() writes {"macros": [list-of-dicts]}; get_macros()'s
        # legacy-dict migration branch used to call .items() on that list
        # unconditionally, crashing with AttributeError on the very next read
        # after any macro was ever saved.
        macros.add_macro("my address", "123 Main St")
        self.assertEqual(macros.get_macros(), [{"trigger": "my address", "expansion": "123 Main St"}])
        # A second read (fresh file handle) must also succeed.
        self.assertEqual(macros.get_macros(), [{"trigger": "my address", "expansion": "123 Main St"}])

    def test_legacy_dict_format_still_migrates(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"macros": {"my address": "123 Main St", "eta": "estimated time of arrival"}}')

        result = {m["trigger"]: m["expansion"] for m in macros.get_macros()}
        self.assertEqual(result, {"my address": "123 Main St", "eta": "estimated time of arrival"})

    def test_corrupted_file_is_quarantined_and_logged(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not valid json,,,")

        with self.assertLogs(level="WARNING") as log_ctx:
            result = macros.get_macros()

        self.assertEqual(result, [])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(f"{path}.corrupt"))
        self.assertTrue(any("corrupted" in msg for msg in log_ctx.output))

    def test_recovers_after_quarantine_and_can_save_again(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json")

        with self.assertLogs(level="WARNING"):
            macros.get_macros()

        macros.add_macro("my address", "123 Main St")
        self.assertEqual(macros.get_macros(), [{"trigger": "my address", "expansion": "123 Main St"}])


if __name__ == "__main__":
    unittest.main()
