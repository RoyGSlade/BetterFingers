"""Hard disk-space gate before large model/runtime downloads.

hardware_report.py's assess_model_fit() only ever flags low disk as an
ADVISORY warning line — nothing there stops a multi-GB download from
starting, so a user could kick off a transfer that fails partway and leaves a
confusing half-written state. These tests cover the hard gate added in
model_manager.py:

* _ensure_disk_space() raises InsufficientDiskSpaceError with a needed-vs-
  available message (in human GB units) when free space is short, and is a
  no-op when space is sufficient or the required size is unknown (falsy).
* download_file() consults it once the response headers reveal the transfer
  size (the only place it can, for callers with no catalog size), BEFORE the
  destination file is opened for writing.
* check_and_download_resources() consults it up-front for the model download
  (whose size is always known from AVAILABLE_MODELS' size_bytes), refusing
  before ever calling download_file / opening a network connection.
"""

import os
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import model_manager as mm


def _fake_disk_usage(total, free):
    used = max(0, total - free)
    return types.SimpleNamespace(total=total, used=used, free=free)


def _fake_response(payload: bytes, status_code=200, extra_headers=None):
    response = MagicMock()
    response.status_code = status_code
    headers = {"content-length": str(len(payload))}
    if extra_headers:
        headers.update(extra_headers)
    response.headers = headers
    response.iter_content = lambda chunk_size: iter([payload])
    response.raise_for_status = lambda: None
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *a: False
    return response


class EnsureDiskSpaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_raises_with_needed_vs_available_message_when_short(self):
        one_gb = 1024 ** 3
        with patch.object(mm.shutil, "disk_usage", return_value=_fake_disk_usage(10 * one_gb, 3 * one_gb)):
            with self.assertRaises(mm.InsufficientDiskSpaceError) as ctx:
                mm._ensure_disk_space(self._tmp.name, required_bytes=6 * one_gb)
        message = str(ctx.exception)
        self.assertIn("6.6 GB", message)  # 6 GB * 1.1 headroom
        self.assertIn("3.0 GB", message)
        self.assertIn(self._tmp.name, message)
        self.assertEqual(ctx.exception.required_bytes, 6 * one_gb)
        self.assertEqual(ctx.exception.free_bytes, 3 * one_gb)

    def test_does_not_raise_when_space_is_sufficient(self):
        one_gb = 1024 ** 3
        with patch.object(mm.shutil, "disk_usage", return_value=_fake_disk_usage(100 * one_gb, 50 * one_gb)):
            mm._ensure_disk_space(self._tmp.name, required_bytes=6 * one_gb)  # must not raise

    def test_headroom_multiplier_is_applied(self):
        # Exactly the raw size is free, but headroom (1.1x) makes it insufficient.
        one_gb = 1024 ** 3
        with patch.object(mm.shutil, "disk_usage", return_value=_fake_disk_usage(10 * one_gb, 6 * one_gb)):
            with self.assertRaises(mm.InsufficientDiskSpaceError):
                mm._ensure_disk_space(self._tmp.name, required_bytes=6 * one_gb)

    def test_noop_when_required_bytes_falsy(self):
        with patch.object(mm.shutil, "disk_usage", side_effect=AssertionError("should not be called")):
            mm._ensure_disk_space(self._tmp.name, required_bytes=0)
            mm._ensure_disk_space(self._tmp.name, required_bytes=None)


class DownloadFileDiskGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = os.path.join(self._tmp.name, "artifact.bin")
        self.payload = b"x" * (1024 * 1024)

    def test_insufficient_space_refuses_before_writing_part_file(self):
        one_gb = 1024 ** 3
        with patch.object(mm.shutil, "disk_usage", return_value=_fake_disk_usage(one_gb, 0)), patch.object(
            mm.requests, "get", return_value=_fake_response(self.payload)
        ) as get:
            with self.assertRaises(mm.InsufficientDiskSpaceError) as ctx:
                mm.download_file(
                    "https://example.invalid/artifact.bin", self.dest, "Test artifact", resume=False,
                )
        self.assertIn("Not enough disk space", str(ctx.exception))
        # Headers were fetched (get() was called) but no chunk was ever written.
        get.assert_called_once()
        self.assertFalse(os.path.exists(self.dest))
        self.assertFalse(os.path.exists(self.dest + ".part"))

    def test_sufficient_space_proceeds_to_actual_download(self):
        one_gb = 1024 ** 3
        with patch.object(mm.shutil, "disk_usage", return_value=_fake_disk_usage(one_gb, one_gb)), patch.object(
            mm.requests, "get", return_value=_fake_response(self.payload)
        ):
            mm.download_file(
                "https://example.invalid/artifact.bin", self.dest, "Test artifact", resume=False,
            )
        self.assertTrue(os.path.exists(self.dest))
        with open(self.dest, "rb") as fh:
            self.assertEqual(fh.read(), self.payload)

    def test_unknown_size_skips_the_gate(self):
        # No content-length / content-range header at all -> remaining_bytes is
        # 0, so the gate is a no-op rather than a spurious refusal; the transfer
        # proceeds (disk_usage must not even be consulted).
        response = _fake_response(self.payload)
        del response.headers["content-length"]
        response.headers = {}
        with patch.object(mm.shutil, "disk_usage", side_effect=AssertionError("should not be called")), patch.object(
            mm.requests, "get", return_value=response
        ):
            mm.download_file(
                "https://example.invalid/artifact.bin", self.dest, "Test artifact", resume=False,
            )
        self.assertTrue(os.path.exists(self.dest))


class CheckAndDownloadResourcesDiskGateTests(unittest.TestCase):
    """check_and_download_resources() knows the model's exact size up-front
    (AVAILABLE_MODELS' size_bytes) and must refuse before ever calling
    download_file (i.e. before opening a network connection at all)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.model_id = mm.DEFAULT_MODEL
        self.model_path = os.path.join(self._tmp.name, mm.AVAILABLE_MODELS[self.model_id]["filename"])
        self._patches = [
            patch("model_manager.get_models_dir", return_value=self._tmp.name),
            patch("model_manager.get_model_path", return_value=self.model_path),
            patch("model_manager.get_server_path", return_value=os.path.join(self._tmp.name, "llama-server")),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_refuses_before_calling_download_file_when_disk_is_short(self):
        with patch.object(mm.shutil, "disk_usage", return_value=_fake_disk_usage(1024, 0)), patch(
            "model_manager.download_file"
        ) as download_file:
            result = mm.check_and_download_resources(model_id=self.model_id)

        download_file.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertIn("GB", result["message"])
        self.assertIn("Not enough disk space", result["message"])
        state = mm.get_download_state(self.model_id)
        self.assertEqual(state.get("status"), "error")
        self.assertIn("Not enough disk space", state.get("message", ""))

    def test_proceeds_to_download_when_disk_is_sufficient(self):
        one_gb = 1024 ** 3
        # A present, already-valid server runtime short-circuits the platform-
        # specific runtime download+extract (Windows .zip vs Linux .tar.gz), so
        # this test exercises ONLY the model-download disk gate and stays
        # cross-platform. (The prior version created a `#!/bin/sh` stub and
        # relied on get_server_filename() matching the patched get_server_path;
        # on Windows the stub can't execute and the names diverge (.exe), so the
        # runtime path ran and unzipped the 20-byte model stub -> BadZipFile.)
        server_path = mm.get_server_path()
        os.makedirs(os.path.dirname(server_path), exist_ok=True)
        with open(server_path, "w", encoding="utf-8") as fh:
            fh.write("stub")

        def fake_download_file(url, dest_path, *args, **kwargs):
            # Tiny stand-in file; BETTERFINGERS_ALLOW_TINY_MODELS makes
            # is_model_file_complete() accept it without a real multi-GB
            # download or digest match.
            with open(dest_path, "wb") as fh:
                fh.write(b"\0" * 20)

        with patch.dict(os.environ, {"BETTERFINGERS_ALLOW_TINY_MODELS": "1"}), patch.object(
            mm.shutil, "disk_usage", return_value=_fake_disk_usage(100 * one_gb, 100 * one_gb)
        ), patch(
            "model_manager.validate_llama_server_runtime",
            return_value={"ok": True, "build": 999999},
        ), patch("model_manager.download_file", side_effect=fake_download_file) as download_file:
            result = mm.check_and_download_resources(model_id=self.model_id)

        # Only the model is downloaded; the present+valid server skips runtime install.
        download_file.assert_called_once()
        self.assertTrue(result["ok"], result.get("message"))


if __name__ == "__main__":
    unittest.main()
