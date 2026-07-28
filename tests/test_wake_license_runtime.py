"""Runtime enforcement of the wake-model license gate — closes WMP-3.

Before Wave 8B the gate existed only as a test over the checked-in catalog
(``tests/test_wake_models.py``), so a catalog entry added without running the
suite would have been downloaded and loaded regardless. These tests assert the
*code* refuses it, and that the refusal is honest rather than a mystery load
failure.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import wake_models  # noqa: E402
import wake_word  # noqa: E402


class LicenseGateTests(unittest.TestCase):
    def test_every_redistributable_license_is_allowed_at_runtime(self):
        for name in wake_models.ALLOWED_LICENSES:
            self.assertTrue(wake_models.license_allowed(name), name)

    def test_a_self_trained_model_is_allowed_but_is_not_in_the_catalog_gate(self):
        # Nothing is redistributed, so it is not part of the redistribution
        # set — but it must still be a known value, not an unknown one.
        self.assertTrue(wake_models.license_allowed("self-trained"))
        self.assertNotIn("self-trained", wake_models.ALLOWED_LICENSES)

    def test_the_noncommercial_license_the_audit_found_is_refused(self):
        # openWakeWord's own pre-trained phrase classifiers are CC-BY-NC-SA-4.0
        # and are deliberately not listed; the runtime must refuse one even if
        # it somehow appeared in a catalog.
        self.assertFalse(wake_models.license_allowed("CC-BY-NC-SA-4.0"))

    def test_a_blank_or_missing_license_is_refused_not_defaulted(self):
        for value in (None, "", "   "):
            self.assertFalse(wake_models.license_allowed(value), repr(value))

    def test_assert_raises_with_a_message_naming_the_model_and_the_license(self):
        with self.assertRaises(wake_models.WakeModelLicenseRefused) as caught:
            wake_models.assert_license_allowed("phrase_x", "CC-BY-NC-SA-4.0")
        message = str(caught.exception)
        self.assertIn("phrase_x", message)
        self.assertIn("CC-BY-NC-SA-4.0", message)

    def test_assert_returns_the_license_when_allowed(self):
        self.assertEqual(wake_models.assert_license_allowed("melspectrogram", "Apache-2.0"), "Apache-2.0")

    def test_a_missing_license_names_the_absence_rather_than_an_empty_string(self):
        with self.assertRaises(wake_models.WakeModelLicenseRefused) as caught:
            wake_models.assert_license_allowed("phrase_x", None)
        self.assertIn("(none recorded)", str(caught.exception))


class ModelLicenseLookupTests(unittest.TestCase):
    def test_a_catalog_model_reports_its_license(self):
        self.assertEqual(wake_models.model_license("melspectrogram"), "Apache-2.0")

    def test_an_unknown_id_is_none_not_blank(self):
        # None means "no such model" (a lookup failure); "" would mean "a known
        # model with no license recorded" (a policy failure). They must not be
        # confused, or a typo would be reported as a licensing problem.
        with mock.patch.object(wake_models, "load_imported_models", return_value={}):
            self.assertIsNone(wake_models.model_license("no_such_model"))

    def test_an_imported_model_reports_its_manifest_license(self):
        manifest = {"user_1": {"license": "user-provided", "filename": "imported_user_1.onnx"}}
        with mock.patch.object(wake_models, "load_imported_models", return_value=manifest):
            self.assertEqual(wake_models.model_license("user_1"), "user-provided")


class DownloadPathTests(unittest.TestCase):
    def test_a_disallowed_catalog_entry_is_never_downloaded(self):
        poisoned = dict(wake_models.AVAILABLE_WAKE_MODELS)
        poisoned["bad_phrase"] = {
            "name": "Bad", "filename": "bad.onnx", "url": "https://example.invalid/bad.onnx",
            "sha256": "0" * 64, "size_bytes": 1, "kind": "classifier",
            "license": "CC-BY-NC-SA-4.0", "source": "test",
        }
        with mock.patch.object(wake_models, "AVAILABLE_WAKE_MODELS", poisoned), \
                mock.patch("model_manager.download_file") as download:
            with self.assertRaises(wake_models.WakeModelLicenseRefused):
                wake_models.download_wake_model("bad_phrase")
        download.assert_not_called()

    def test_an_allowed_entry_still_downloads(self):
        with mock.patch("model_manager.download_file") as download, \
                mock.patch.object(wake_models, "get_wake_model_path", return_value="/tmp/x.onnx"):
            wake_models.download_wake_model("melspectrogram")
        download.assert_called_once()


class DetectorBuildTests(unittest.TestCase):
    """The load path is where the gate has to bite."""

    def test_a_disallowed_backbone_refuses_before_anything_is_hashed_or_loaded(self):
        poisoned = {
            "melspectrogram": dict(wake_models.AVAILABLE_WAKE_MODELS["melspectrogram"],
                                   license="CC-BY-NC-SA-4.0"),
            "embedding_model": wake_models.AVAILABLE_WAKE_MODELS["embedding_model"],
        }
        with mock.patch.object(wake_models, "AVAILABLE_WAKE_MODELS", poisoned), \
                mock.patch.object(wake_models, "is_backbone_model_downloaded") as downloaded, \
                mock.patch.object(wake_models, "build_onnx_session") as build:
            detector, available, reason = wake_word.build_openwakeword_detector()

        self.assertIsNone(detector)
        self.assertFalse(available)
        self.assertIn("CC-BY-NC-SA-4.0", reason)
        self.assertTrue(reason.startswith("unavailable:"))
        downloaded.assert_not_called()
        build.assert_not_called()

    def test_a_disallowed_classifier_refuses(self):
        manifest = {"user_1": {"license": "CC-BY-NC-SA-4.0", "filename": "imported_user_1.onnx"}}
        with mock.patch.object(wake_models, "load_imported_models", return_value=manifest), \
                mock.patch.object(wake_models, "build_onnx_session") as build:
            detector, available, reason = wake_word.build_openwakeword_detector(
                classifier_id="user_1", classifier_origin="user-imported"
            )
        self.assertIsNone(detector)
        self.assertFalse(available)
        self.assertIn("user_1", reason)
        build.assert_not_called()

    def test_an_unknown_classifier_id_is_reported_as_unknown_not_as_a_license_problem(self):
        with mock.patch.object(wake_models, "load_imported_models", return_value={}), \
                mock.patch.object(wake_models, "is_backbone_model_downloaded", return_value=False):
            _detector, available, reason = wake_word.build_openwakeword_detector(
                classifier_id="typo_id", classifier_origin="user-imported"
            )
        self.assertFalse(available)
        self.assertNotIn("license", reason.lower())

    def test_the_shipped_catalog_passes_its_own_runtime_gate(self):
        # The regression that matters day to day: enforcement must not refuse
        # the artifacts this build actually ships.
        for model_id, info in wake_models.AVAILABLE_WAKE_MODELS.items():
            self.assertTrue(wake_models.license_allowed(info["license"]), model_id)


if __name__ == "__main__":
    unittest.main()
