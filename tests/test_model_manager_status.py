import os
import tempfile
import unittest
from unittest.mock import patch

from model_manager import check_and_download_resources


class ModelManagerStatusTests(unittest.TestCase):
    def test_check_and_download_resources_reports_error_when_model_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "missing.gguf")
            server_path = os.path.join(tmp, "llama-server.exe")

            with patch("model_manager.get_models_dir", return_value=tmp), patch(
                "model_manager.get_model_path", return_value=model_path
            ), patch("model_manager.get_server_path", return_value=server_path), patch(
                "model_manager.download_file", side_effect=RuntimeError("offline")
            ) as download_file:
                result = check_and_download_resources(model_id="gemma-3-4b-q4")

            self.assertFalse(bool(result.get("ok", True)))
            self.assertIn("unavailable", str(result.get("message", "")).lower())
            self.assertEqual(download_file.call_count, 1)


if __name__ == "__main__":
    unittest.main()
