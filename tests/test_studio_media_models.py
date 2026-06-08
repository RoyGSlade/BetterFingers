import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import studio_media_models


class StudioMediaModelsTests(unittest.TestCase):
    def test_catalog_exposes_studio_media_roles(self):
        models = {row["key"]: row for row in studio_media_models.list_models()}

        self.assertEqual(models["chatterbox"]["kind"], "voice")
        self.assertEqual(models["ace-step-1-5"]["kind"], "music")
        self.assertEqual(models["stable-audio-open-small"]["kind"], "ambience")
        self.assertEqual(studio_media_models.DEFAULTS["voice"], "chatterbox")

    def test_partial_snapshot_is_resumable_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "chatterbox"
            dest.mkdir()
            (dest / "partial.bin").write_bytes(b"abc")

            with patch("studio_media_models._models_dir", return_value=Path(tmp)):
                self.assertFalse(studio_media_models.model_installed("chatterbox"))
                state = studio_media_models.download_state("chatterbox")

            self.assertEqual(state["status"], "partial")
            self.assertTrue(state["resumable"])
            self.assertEqual(state["partial_bytes"], 3)

    def test_complete_marker_is_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "chatterbox"
            dest.mkdir()
            (dest / ".betterfingers_download_complete").write_text("repo", encoding="utf-8")

            with patch("studio_media_models._models_dir", return_value=Path(tmp)):
                self.assertTrue(studio_media_models.model_installed("chatterbox"))
                state = studio_media_models.download_state("chatterbox")

            self.assertEqual(state["status"], "done")
            self.assertTrue(state["installed"])


if __name__ == "__main__":
    unittest.main()
