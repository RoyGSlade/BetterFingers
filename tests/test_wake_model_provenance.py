"""Wave 8A package G: the wake provenance manifest cannot drift from the code.

docs/release/WAKE_MODEL_PROVENANCE.md is only worth anything if a new catalog
entry, or a model binary quietly added to the tree, makes it fail.
"""

import json
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(REPO_ROOT, "docs", "release", "wake_model_provenance.json")
DOC_PATH = os.path.join(REPO_ROOT, "docs", "release", "WAKE_MODEL_PROVENANCE.md")

# Extensions that would indicate a model artifact checked into the tree.
MODEL_SUFFIXES = (".onnx", ".tflite", ".npz", ".pth", ".pt", ".safetensors", ".h5", ".pb", ".gguf")
# Directories that are not this repository's shipped source.
PRUNED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "out", "dist", "release", "build", ".mypy_cache", ".ruff_cache",
}


def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


class ManifestShapeTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest()

    def test_manifest_and_document_both_exist(self):
        self.assertTrue(os.path.isfile(MANIFEST_PATH))
        self.assertTrue(os.path.isfile(DOC_PATH))

    def test_manifest_points_at_its_document(self):
        self.assertEqual(self.manifest["document"], "docs/release/WAKE_MODEL_PROVENANCE.md")

    def test_every_artifact_records_the_fields_a_release_audit_needs(self):
        required = {
            "id", "name", "filename", "kind", "origin", "license", "source",
            "source_url", "sha256", "size_bytes", "distribution",
            "redistributed_by_project", "shippable",
        }
        for entry in self.manifest["artifacts"]:
            self.assertTrue(required.issubset(entry), f"{entry.get('id')} is missing {required - set(entry)}")

    def test_nothing_in_the_manifest_is_redistributed_by_this_project(self):
        for entry in self.manifest["artifacts"]:
            self.assertFalse(entry["redistributed_by_project"], entry["id"])

    def test_excluded_models_are_recorded_as_not_shippable(self):
        self.assertTrue(self.manifest["excluded"], "the CC-BY-NC-SA finding must stay recorded")
        for entry in self.manifest["excluded"]:
            self.assertFalse(entry["shippable"], entry["ids"])

    def test_the_openwakeword_classifier_exclusion_is_still_recorded(self):
        excluded_ids = {i for entry in self.manifest["excluded"] for i in entry["ids"]}
        for model_id in ("alexa", "hey_mycroft", "hey_jarvis", "hey_rhasspy", "timer", "weather"):
            self.assertIn(model_id, excluded_ids)

    def test_user_supplied_classes_show_provenance(self):
        classes = {entry["class"]: entry for entry in self.manifest["user_supplied"]}
        self.assertEqual(set(classes), {"user-imported", "trained"})
        for entry in classes.values():
            self.assertTrue(entry["provenance_shown_to_user"])
            self.assertFalse(entry["redistributed_by_project"])


class CatalogSyncTests(unittest.TestCase):
    """The manifest is generated from, and must agree with, the code catalog."""

    def setUp(self):
        import wake_models

        self.wake_models = wake_models
        self.manifest = load_manifest()
        self.by_id = {entry["id"]: entry for entry in self.manifest["artifacts"]}

    def test_the_two_sets_of_ids_match_exactly(self):
        self.assertEqual(set(self.by_id), set(self.wake_models.AVAILABLE_WAKE_MODELS))

    def test_every_catalog_entry_matches_its_manifest_record(self):
        for model_id, info in self.wake_models.AVAILABLE_WAKE_MODELS.items():
            entry = self.by_id[model_id]
            self.assertEqual(entry["sha256"], info["sha256"], model_id)
            self.assertEqual(entry["size_bytes"], info["size_bytes"], model_id)
            self.assertEqual(entry["license"], info["license"], model_id)
            self.assertEqual(entry["source_url"], info["url"], model_id)
            self.assertEqual(entry["filename"], info["filename"], model_id)
            self.assertEqual(entry["kind"], info["kind"], model_id)

    def test_every_manifest_license_is_inside_the_gate(self):
        allowed = set(self.manifest["license_gate"]["allowed"])
        self.assertEqual(allowed, set(self.wake_models.ALLOWED_LICENSES))
        for entry in self.manifest["artifacts"]:
            self.assertIn(entry["license"], allowed, entry["id"])

    def test_no_wake_phrase_classifier_is_in_the_catalog(self):
        # The license gate's whole point: the backbone ships, phrases do not.
        kinds = {info["kind"] for info in self.wake_models.AVAILABLE_WAKE_MODELS.values()}
        self.assertEqual(kinds, {"backbone"})


class NoBundledBinariesTests(unittest.TestCase):
    def test_no_model_artifact_is_checked_into_the_tree(self):
        found = []
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
            dirnames[:] = [d for d in dirnames if d not in PRUNED_DIRS]
            for name in filenames:
                if name.lower().endswith(MODEL_SUFFIXES):
                    found.append(os.path.relpath(os.path.join(dirpath, name), REPO_ROOT))
        self.assertEqual(
            found, [],
            "A model artifact appeared in the tree. Record its provenance in "
            "docs/release/WAKE_MODEL_PROVENANCE.md before shipping it.",
        )

    def test_the_manifest_still_claims_zero_bundled_binaries(self):
        self.assertEqual(load_manifest()["repository_bundled_binaries"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
