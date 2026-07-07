import os
import tarfile
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

import model_manager
from model_manager import check_and_download_resources, get_model_server_args


class ModelManagerStatusTests(unittest.TestCase):
    def test_gemma_4_models_are_available(self):
        expected = {
            "gemma-4-e2b-q4",
            "gemma-4-e2b-q8",
            "gemma-4-e4b-q4",
            "gemma-4-e4b-q8",
            "gemma-4-12b-q4",
            "gemma-4-26b-a4b-q4",
            "gemma-4-31b-q4",
        }

        self.assertTrue(expected.issubset(set(model_manager.AVAILABLE_MODELS)))
        for model_id in expected:
            model = model_manager.AVAILABLE_MODELS[model_id]
            self.assertIn("gemma-4", model["url"])
            self.assertTrue(model["filename"].endswith(".gguf"))
            self.assertGreater(model["size_mb"], 0)

    def test_gemma_4_models_use_jinja_server_args(self):
        args = get_model_server_args("gemma-4-e4b-q4")

        self.assertIn("--jinja", args)
        self.assertIn("--chat-template-kwargs", args)

    def test_models_expose_studio_and_betterfingers_roles(self):
        dispatcher = model_manager.AVAILABLE_MODELS["gemma-4-e4b-q4"]
        writer = model_manager.AVAILABLE_MODELS["gemma-4-12b-q4"]
        rewrite = model_manager.AVAILABLE_MODELS["gemma-3-4b-q4"]

        self.assertEqual(dispatcher["group"], "studio")
        self.assertIn("dispatcher", dispatcher["roles"])
        self.assertEqual(dispatcher["lane"], "cpu")
        self.assertIn("writer", writer["roles"])
        self.assertEqual(writer["lane"], "gpu-transient")
        self.assertEqual(rewrite["group"], "betterfingers")
        self.assertIn("rewrite", rewrite["roles"])

    def test_download_file_resumes_partial_and_promotes_atomically(self):
        class FakeResponse:
            status_code = 206
            headers = {"content-length": "5", "content-range": "bytes 5-9/10"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=8192):
                yield b"fghij"

        progress = []
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "model.gguf")
            with open(f"{dest}.part", "wb") as handle:
                handle.write(b"abcde")

            with patch("model_manager.requests.get", return_value=FakeResponse()) as get:
                model_manager.download_file("https://example.test/model", dest, "Model", progress_callback=progress.append)

            self.assertTrue(os.path.exists(dest))
            self.assertFalse(os.path.exists(f"{dest}.part"))
            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), b"abcdefghij")
            self.assertEqual(get.call_args.kwargs["headers"], {"Range": "bytes=5-"})
            self.assertEqual(progress[-1]["status"], "complete")

    def test_download_file_keeps_partial_on_failure(self):
        class BrokenResponse:
            status_code = 200
            headers = {"content-length": "10"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=8192):
                yield b"abc"
                raise RuntimeError("connection dropped")

        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "model.gguf")
            with patch("model_manager.requests.get", return_value=BrokenResponse()):
                with self.assertRaises(RuntimeError):
                    model_manager.download_file("https://example.test/model", dest, "Model")

            self.assertFalse(os.path.exists(dest))
            self.assertTrue(os.path.exists(f"{dest}.part"))

    def test_incomplete_final_model_is_moved_to_part_for_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "bad.gguf")
            part_path = f"{model_path}.part"
            with open(model_path, "wb") as handle:
                handle.write(b"partial")

            with patch("model_manager.get_model_path", return_value=model_path), patch(
                "model_manager.get_partial_model_path", return_value=part_path
            ), patch("model_manager.is_model_file_complete", return_value=False):
                moved = model_manager._prepare_incomplete_model_for_resume("gemma-4-e4b-q4")

            self.assertEqual(moved, len(b"partial"))
            self.assertFalse(os.path.exists(model_path))
            self.assertTrue(os.path.exists(part_path))

    def test_linux_runtime_tar_symlinks_are_preserved_and_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = os.path.join(tmp, "runtime.tar.gz")
            extract_dir = os.path.join(tmp, "extract")
            os.makedirs(extract_dir, exist_ok=True)

            with tarfile.open(archive_path, "w:gz") as archive:
                for link_name, target_name in model_manager.LINUX_RUNTIME_LINKS.items():
                    data = b"library"
                    info = tarfile.TarInfo(f"bin/{target_name}")
                    info.size = len(data)
                    archive.addfile(info, BytesIO(data))
                    if link_name == "libmtmd.so.0":
                        symlink = tarfile.TarInfo(f"bin/{link_name}")
                        symlink.type = tarfile.SYMTYPE
                        symlink.linkname = target_name
                        archive.addfile(symlink)

            with patch("model_manager.sys.platform", "linux"):
                model_manager._extract_tar_flat(archive_path, extract_dir)
                self.assertTrue(os.path.islink(os.path.join(extract_dir, "libmtmd.so.0")))

                repair = model_manager.repair_linux_runtime_links(extract_dir)

            self.assertTrue(repair["ok"])
            for link_name, target_name in model_manager.LINUX_RUNTIME_LINKS.items():
                link_path = os.path.join(extract_dir, link_name)
                self.assertTrue(os.path.islink(link_path))
                self.assertEqual(os.readlink(link_path), target_name)

    def test_linux_runtime_extract_replaces_readonly_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = os.path.join(tmp, "runtime.tar.gz")
            extract_dir = os.path.join(tmp, "extract")
            os.makedirs(extract_dir, exist_ok=True)
            stale_path = os.path.join(extract_dir, "llama-server")
            with open(stale_path, "wb") as handle:
                handle.write(b"old")
            os.chmod(stale_path, 0o555)

            with tarfile.open(archive_path, "w:gz") as archive:
                data = b"new"
                info = tarfile.TarInfo("bin/llama-server")
                info.size = len(data)
                archive.addfile(info, BytesIO(data))

            model_manager._extract_tar_flat(archive_path, extract_dir)

            with open(stale_path, "rb") as handle:
                self.assertEqual(handle.read(), b"new")

    def test_linux_runtime_extract_allows_symlink_before_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = os.path.join(tmp, "runtime.tar.gz")
            extract_dir = os.path.join(tmp, "extract")
            os.makedirs(extract_dir, exist_ok=True)

            with tarfile.open(archive_path, "w:gz") as archive:
                symlink = tarfile.TarInfo("bin/libllama-common.so.0")
                symlink.type = tarfile.SYMTYPE
                symlink.linkname = "libllama-common.so.0.0.9548"
                archive.addfile(symlink)

                data = b"library"
                info = tarfile.TarInfo("bin/libllama-common.so.0.0.9548")
                info.size = len(data)
                archive.addfile(info, BytesIO(data))

            model_manager._extract_tar_flat(archive_path, extract_dir)

            link_path = os.path.join(extract_dir, "libllama-common.so.0")
            self.assertTrue(os.path.islink(link_path))
            self.assertEqual(os.readlink(link_path), "libllama-common.so.0.0.9548")
            self.assertTrue(os.path.exists(os.path.join(extract_dir, os.readlink(link_path))))

    def test_validate_runtime_failure_returns_loader_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_path = os.path.join(tmp, "llama-server")
            with open(server_path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\n")
                handle.write("echo 'error while loading shared libraries: libmtmd.so.0' >&2\n")
                handle.write("exit 127\n")
            os.chmod(server_path, 0o755)

            with patch("model_manager.sys.platform", "linux"), patch(
                "model_manager.repair_linux_runtime_links", return_value={"ok": True, "repaired": [], "missing": [], "errors": []}
            ):
                result = model_manager.validate_llama_server_runtime(server_path)

            self.assertFalse(result["ok"])
            self.assertIn("libmtmd.so.0", result["message"])

    def test_gemma4_updates_old_managed_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "gemma4.gguf")
            server_path = os.path.join(tmp, "llama-server")
            with open(model_path, "wb") as handle:
                handle.write(b"model")
            with open(server_path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\necho 'version: 7870'\n")
            os.chmod(server_path, 0o755)

            def fake_download(_url, dest_path, *_args, **_kwargs):
                with tarfile.open(dest_path, "w:gz") as archive:
                    data = b"#!/bin/sh\necho 'version: 9548'\n"
                    info = tarfile.TarInfo("bin/llama-server")
                    info.mode = 0o755
                    info.size = len(data)
                    archive.addfile(info, BytesIO(data))

            with patch.dict(os.environ, {}, clear=True), patch(
                "model_manager.sys.platform", "linux"
            ), patch("model_manager.get_models_dir", return_value=tmp), patch(
                "model_manager.get_model_path", return_value=model_path
            ), patch("model_manager.download_file", side_effect=fake_download) as download_file:
                result = check_and_download_resources(model_id="gemma-4-12b-q4")

            self.assertTrue(result["ok"])
            download_file.assert_called_once()
            validation = model_manager.validate_llama_server_runtime(server_path)
            self.assertEqual(validation["build"], 9548)

    def test_gemma4_is_not_ready_with_old_runtime_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "gemma4.gguf")
            server_path = os.path.join(tmp, "llama-server")
            with open(model_path, "wb") as handle:
                handle.write(b"model")
            with open(server_path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\necho 'version: 7870'\n")
            os.chmod(server_path, 0o755)

            with patch("model_manager.sys.platform", "linux"), patch(
                "model_manager.get_model_path", return_value=model_path
            ), patch("model_manager.get_server_path", return_value=server_path):
                self.assertFalse(model_manager.is_ready("gemma-4-12b-q4"))
                self.assertTrue(model_manager.is_ready("gemma-3-4b-q4"))

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

    def test_model_file_status_reports_non_writable_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "model.gguf")
            with open(model_path, "wb") as handle:
                handle.write(b"model")
            os.chmod(model_path, 0o444)

            try:
                with patch("model_manager.get_model_path", return_value=model_path):
                    status = model_manager.get_model_file_status("gemma-4-12b-q4")
            finally:
                os.chmod(model_path, 0o644)

            self.assertTrue(status["complete"])
            self.assertTrue(status["readable"])
            if not status["writable"]:
                self.assertIn("not_writable", status["attention"])

    def test_unreadable_model_is_not_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "model.gguf")
            with open(model_path, "wb") as handle:
                handle.write(b"model")
            os.chmod(model_path, 0)

            try:
                with patch("model_manager.get_model_path", return_value=model_path):
                    status = model_manager.get_model_file_status("gemma-4-12b-q4")
                    complete = model_manager.is_model_file_complete("gemma-4-12b-q4")
                    readable = os.access(model_path, os.R_OK)
            finally:
                os.chmod(model_path, 0o644)

            if not readable:
                self.assertFalse(status["readable"])
                self.assertFalse(complete)

    def test_linux_uses_llama_server_without_exe_and_downloads_linux_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "local.gguf")
            with open(model_path, "wb") as handle:
                handle.write(b"model")

            def fake_download(_url, dest_path, *_args, **_kwargs):
                with tarfile.open(dest_path, "w:gz") as archive:
                    data = b"#!/bin/sh\nexit 0\n"
                    info = tarfile.TarInfo("bin/llama-server")
                    info.mode = 0o755
                    info.size = len(data)
                    archive.addfile(info, BytesIO(data))

            with patch.dict(os.environ, {"BETTERFINGERS_MODEL_PATH": model_path}, clear=True), patch(
                "model_manager.sys.platform", "linux"
            ), patch("model_manager.get_models_dir", return_value=tmp), patch(
                "model_manager.get_repo_root", return_value=tmp
            ), patch(
                "model_manager.download_file", side_effect=fake_download
            ) as download_file:
                result = check_and_download_resources(model_id="gemma-3-4b-q4")
                server_path = model_manager.get_server_path()

            self.assertEqual(model_manager.get_server_filename(), "llama-server")
            self.assertTrue(server_path.endswith("llama-server"))
            self.assertFalse(server_path.endswith("llama-server.exe"))
            self.assertTrue(bool(result.get("ok", False)))
            download_file.assert_called_once()

    def test_repo_local_linux_llama_server_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "local.gguf")
            server_path = os.path.join(tmp, ".betterfingers", "llama-server", "bin", "llama-server")
            os.makedirs(os.path.dirname(server_path), exist_ok=True)
            with open(model_path, "wb") as handle:
                handle.write(b"model")
            with open(server_path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\nexit 0\n")
            os.chmod(server_path, 0o755)

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
