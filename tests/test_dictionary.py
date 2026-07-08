import logging
import os
import tempfile
import unittest

import dictionary


class _TempAppdataMixin:
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
        return dictionary._dictionary_path()


class GetTermsTests(_TempAppdataMixin, unittest.TestCase):
    def test_missing_file_returns_empty_list_silently(self):
        self.assertEqual(dictionary.get_terms(), [])

    def test_round_trips_added_terms(self):
        dictionary.add_term("Kubernetes")
        dictionary.add_term("kubernetes")  # case-insensitive dedupe
        self.assertEqual(dictionary.get_terms(), ["Kubernetes"])

    def test_corrupted_file_is_quarantined_and_logged(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not valid json,,,")

        with self.assertLogs(level="WARNING") as log_ctx:
            terms = dictionary.get_terms()

        self.assertEqual(terms, [])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(f"{path}.corrupt"))
        self.assertTrue(any("corrupted" in msg for msg in log_ctx.output))

    def test_recovers_after_quarantine_and_can_save_again(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json")

        with self.assertLogs(level="WARNING"):
            dictionary.get_terms()

        # The quarantined file must not block a fresh save.
        dictionary.add_term("Fresh")
        self.assertEqual(dictionary.get_terms(), ["Fresh"])


if __name__ == "__main__":
    unittest.main()
