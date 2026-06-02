import os
import tempfile
import unittest
from unittest.mock import patch

import model_manager
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

    def test_linux_uses_llama_server_without_exe_and_skips_windows_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "local.gguf")
            with open(model_path, "wb") as handle:
                handle.write(b"model")

            with patch.dict(os.environ, {"BETTERFINGERS_MODEL_PATH": model_path}, clear=True), patch(
                "model_manager.sys.platform", "linux"
            ), patch("model_manager.get_models_dir", return_value=tmp), patch(
                "model_manager.download_file"
            ) as download_file:
                result = check_and_download_resources(model_id="gemma-3-4b-q4")
                server_path = model_manager.get_server_path()

            self.assertEqual(model_manager.get_server_filename(), "llama-server")
            self.assertTrue(server_path.endswith("llama-server"))
            self.assertFalse(server_path.endswith("llama-server.exe"))
            self.assertFalse(bool(result.get("ok", True)))
            self.assertIn("BETTERFINGERS_LLAMA_SERVER", result.get("message", ""))
            download_file.assert_not_called()

    def test_repo_local_linux_llama_server_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "local.gguf")
            server_path = os.path.join(tmp, ".betterfingers", "llama-server", "bin", "llama-server")
            os.makedirs(os.path.dirname(server_path), exist_ok=True)
            with open(model_path, "wb") as handle:
                handle.write(b"model")
            with open(server_path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\n")

            with patch.dict(os.environ, {"BETTERFINGERS_MODEL_PATH": model_path}, clear=True), patch(
                "model_manager.sys.platform", "linux"
            ), patch("model_manager.get_repo_root", return_value=tmp), patch(
                "model_manager.get_models_dir", return_value=os.path.join(tmp, "models")
            ), patch("model_manager.download_file") as download_file:
                self.assertEqual(model_manager.get_server_path(), server_path)
                result = check_and_download_resources(model_id="gemma-3-4b-q4")

            self.assertTrue(bool(result.get("ok", False)))
            download_file.assert_not_called()

    def test_llama_server_env_override_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_path = os.path.join(tmp, "custom-llama-server")
            with open(server_path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\n")

            with patch.dict(os.environ, {"BETTERFINGERS_LLAMA_SERVER": server_path}, clear=True), patch(
                "model_manager.sys.platform", "linux"
            ):
                self.assertEqual(model_manager.get_server_path(), server_path)


if __name__ == "__main__":
    unittest.main()
