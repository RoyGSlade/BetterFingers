import os
import tempfile
import unittest
from unittest.mock import patch

import wake_models as wm


class CatalogIntegrityTests(unittest.TestCase):
    """Supply-chain + license gate (§11 / tier3-wake-word.md hard constraint
    #3): every catalog entry must be pinned, verifiable, and permissively
    licensed -- mirrors tests/test_supply_chain_existing_verify.py's
    ManifestCoverageTests pattern for model_manager.AVAILABLE_MODELS."""

    def test_every_entry_has_https_url(self):
        for model_id, info in wm.AVAILABLE_WAKE_MODELS.items():
            self.assertTrue(info["url"].startswith("https://"), model_id)

    def test_every_entry_has_valid_sha256(self):
        for model_id, info in wm.AVAILABLE_WAKE_MODELS.items():
            self.assertRegex(info["sha256"], r"^[0-9a-f]{64}$", model_id)

    def test_every_entry_has_positive_size(self):
        for model_id, info in wm.AVAILABLE_WAKE_MODELS.items():
            self.assertGreater(int(info["size_bytes"]), 0, model_id)

    def test_every_entry_license_is_allowlisted(self):
        for model_id, info in wm.AVAILABLE_WAKE_MODELS.items():
            self.assertIn(info["license"], wm.ALLOWED_LICENSES, model_id)

    def test_no_wake_phrase_classifier_shipped_by_default(self):
        # The whole point of the license finding: zero "kind": "classifier"
        # entries ship in the default catalog (only the Apache-2.0 backbone).
        kinds = {info["kind"] for info in wm.AVAILABLE_WAKE_MODELS.values()}
        self.assertEqual(kinds, {"backbone"})

    def test_user_provided_license_is_allowlisted_for_the_import_path(self):
        self.assertIn("user-provided", wm.ALLOWED_LICENSES)


class _IsolatedWakeModelsDirMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patch = patch("wake_models.get_user_data_path", return_value=self._tmp.name)
        self._patch.start()
        self.addCleanup(self._patch.stop)


class DownloadWakeModelTests(_IsolatedWakeModelsDirMixin, unittest.TestCase):
    def test_download_delegates_to_model_manager_with_pinned_digest(self):
        info = wm.AVAILABLE_WAKE_MODELS["melspectrogram"]
        with patch("model_manager.download_file") as mock_download:
            dest = wm.download_wake_model("melspectrogram")
        mock_download.assert_called_once()
        args, kwargs = mock_download.call_args
        self.assertEqual(args[0], info["url"])
        self.assertEqual(args[1], dest)
        self.assertEqual(kwargs["expected_sha256"], info["sha256"])

    def test_unknown_model_id_raises(self):
        with self.assertRaises(KeyError):
            wm.download_wake_model("not_a_real_model")

    def test_is_backbone_model_downloaded_reflects_file_presence(self):
        self.assertFalse(wm.is_backbone_model_downloaded("melspectrogram"))
        path = wm.get_wake_model_path("melspectrogram")
        with open(path, "wb") as handle:
            handle.write(b"stub bytes")
        self.assertTrue(wm.is_backbone_model_downloaded("melspectrogram"))


class VerifyWakeModelFileTests(_IsolatedWakeModelsDirMixin, unittest.TestCase):
    def _write(self, model_id, data: bytes):
        path = wm.get_wake_model_path(model_id)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_missing_file_is_not_ok(self):
        result = wm.verify_wake_model_file("melspectrogram")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "missing")

    def test_matching_digest_is_ok(self):
        payload = b"real backbone bytes " * 100
        import hashlib

        digest = hashlib.sha256(payload).hexdigest()
        info = dict(wm.AVAILABLE_WAKE_MODELS["melspectrogram"])
        info["sha256"] = digest
        self._write("melspectrogram", payload)
        with patch.dict(wm.AVAILABLE_WAKE_MODELS, {"melspectrogram": info}):
            result = wm.verify_wake_model_file("melspectrogram")
        self.assertTrue(result["ok"])
        self.assertEqual(result["reason"], "verified")

    def test_mismatched_digest_is_quarantined(self):
        path = self._write("melspectrogram", b"tampered bytes")
        result = wm.verify_wake_model_file("melspectrogram")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "digest_mismatch")
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(f"{path}.corrupt"))

    def test_quarantine_false_leaves_file_in_place(self):
        path = self._write("melspectrogram", b"tampered bytes")
        wm.verify_wake_model_file("melspectrogram", quarantine=False)
        self.assertTrue(os.path.exists(path))


class ImportWakeModelTests(_IsolatedWakeModelsDirMixin, unittest.TestCase):
    def _make_source(self, data=b"tiny classifier bytes"):
        fd, path = tempfile.mkstemp(dir=self._tmp.name, suffix=".onnx")
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        return path

    def test_import_records_manifest_entry_as_user_provided(self):
        source = self._make_source()
        entry = wm.import_wake_model("My Custom Model", source)
        self.assertEqual(entry["license"], "user-provided")
        self.assertEqual(entry["origin"], "user-imported")
        self.assertEqual(entry["kind"], "classifier")
        self.assertTrue(os.path.exists(os.path.join(wm.get_wake_models_dir(), entry["filename"])))
        manifest = wm.load_imported_models()
        self.assertIn(entry["id"], manifest)

    def test_import_missing_source_raises(self):
        with self.assertRaises(ValueError):
            wm.import_wake_model("Bad", os.path.join(self._tmp.name, "does_not_exist.onnx"))

    def test_import_empty_file_raises(self):
        source = self._make_source(data=b"")
        with self.assertRaises(ValueError):
            wm.import_wake_model("Empty", source)

    def test_import_oversized_file_raises(self):
        source = self._make_source(data=b"x" * (wm.MAX_IMPORT_BYTES + 1))
        with self.assertRaises(ValueError):
            wm.import_wake_model("Too Big", source)

    def test_verify_imported_model_catches_tampering(self):
        source = self._make_source()
        entry = wm.import_wake_model("Tamperable", source)
        installed_path = os.path.join(wm.get_wake_models_dir(), entry["filename"])
        with open(installed_path, "ab") as handle:
            handle.write(b"extra bytes appended after import")

        result = wm.verify_imported_model(entry["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "digest_mismatch")
        self.assertNotIn(entry["id"], wm.load_imported_models())

    def test_verify_imported_model_unknown_id(self):
        result = wm.verify_imported_model("does_not_exist")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "unknown_model")

    def test_remove_imported_model(self):
        entry = wm.import_wake_model("Removable", self._make_source())
        installed_path = os.path.join(wm.get_wake_models_dir(), entry["filename"])
        self.assertTrue(wm.remove_imported_model(entry["id"]))
        self.assertFalse(os.path.exists(installed_path))
        self.assertNotIn(entry["id"], wm.load_imported_models())

    def test_remove_unknown_model_returns_false(self):
        self.assertFalse(wm.remove_imported_model("does_not_exist"))


class ListWakeModelsTests(_IsolatedWakeModelsDirMixin, unittest.TestCase):
    def test_lists_backbone_entries_with_download_status(self):
        entries = {e["id"]: e for e in wm.list_wake_models()}
        self.assertIn("melspectrogram", entries)
        self.assertEqual(entries["melspectrogram"]["origin"], "bundled")
        self.assertFalse(entries["melspectrogram"]["downloaded"])

        path = wm.get_wake_model_path("melspectrogram")
        with open(path, "wb") as handle:
            handle.write(b"stub")
        entries = {e["id"]: e for e in wm.list_wake_models()}
        self.assertTrue(entries["melspectrogram"]["downloaded"])

    def test_lists_imported_classifiers(self):
        fd, source = tempfile.mkstemp(dir=self._tmp.name, suffix=".onnx")
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"a tiny classifier")
        entry = wm.import_wake_model("Imported", source)

        entries = {e["id"]: e for e in wm.list_wake_models()}
        self.assertIn(entry["id"], entries)
        self.assertEqual(entries[entry["id"]]["license"], "user-provided")
        self.assertTrue(entries[entry["id"]]["downloaded"])


if __name__ == "__main__":
    unittest.main()
