"""Clone-runtime provisioning: the frozen-build-compatible mechanism for
voice cloning (DESIGN §10 M5/M6, U6). Download/verify/extract is fully
mocked/fixture-driven here — no real network, no real torch/kanade-tokenizer
install, matching tier3-orchestrator's "mock all downloads in tests" ask
(the real archive publishing is an integration dependency, not this
workstream's).
"""

import io
import json
import os
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import voice_clone_engine as vce


def _build_runtime_archive(path, python_relpath, extra_members=()):
    """A minimal valid clone-runtime tarball: the required python executable
    plus a nested site-packages file, to prove directory structure survives
    extraction (unlike model_manager.safe_extract_runtime_archive's flat
    extraction, which would destroy this)."""
    with tarfile.open(path, "w:gz") as tf:
        for relpath, content in [(python_relpath, b"#!/bin/sh\necho fake-python\n")] + list(extra_members):
            data = content if isinstance(content, bytes) else content.encode("utf-8")
            info = tarfile.TarInfo(name=relpath)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def _build_traversal_archive(path):
    with tarfile.open(path, "w:gz") as tf:
        data = b"evil"
        info = tarfile.TarInfo(name="../../etc/evil.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))


class PlatformKeyTests(unittest.TestCase):
    def test_linux_x86_64(self):
        with patch("voice_clone_engine.platform.system", return_value="Linux"), \
             patch("voice_clone_engine.platform.machine", return_value="x86_64"):
            self.assertEqual(vce._clone_runtime_platform_key(), "linux-x86_64")

    def test_windows_amd64(self):
        with patch("voice_clone_engine.platform.system", return_value="Windows"), \
             patch("voice_clone_engine.platform.machine", return_value="AMD64"):
            self.assertEqual(vce._clone_runtime_platform_key(), "windows-x86_64")

    def test_unsupported_platform_returns_none(self):
        with patch("voice_clone_engine.platform.system", return_value="Darwin"), \
             patch("voice_clone_engine.platform.machine", return_value="arm64"):
            self.assertIsNone(vce._clone_runtime_platform_key())


class ProvisionedStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest_dir = self._tmp.name
        self._patchers = [
            patch("voice_clone_engine.clone_runtime_dir", return_value=self.dest_dir),
            patch("voice_clone_engine._clone_runtime_platform_key", return_value="linux-x86_64"),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)

    def _python_path(self):
        return os.path.join(self.dest_dir, "bin", "python3")

    def test_false_when_nothing_provisioned(self):
        self.assertFalse(vce.is_clone_runtime_provisioned())

    def test_false_when_python_exists_but_no_state_file(self):
        os.makedirs(os.path.dirname(self._python_path()))
        open(self._python_path(), "w").close()
        self.assertFalse(vce.is_clone_runtime_provisioned())

    def test_false_when_state_says_not_ready(self):
        os.makedirs(os.path.dirname(self._python_path()))
        open(self._python_path(), "w").close()
        with open(os.path.join(self.dest_dir, vce.CLONE_RUNTIME_STATE_FILE), "w") as fh:
            json.dump({"ready": False}, fh)
        self.assertFalse(vce.is_clone_runtime_provisioned())

    def test_true_when_fully_provisioned(self):
        os.makedirs(os.path.dirname(self._python_path()))
        open(self._python_path(), "w").close()
        with open(os.path.join(self.dest_dir, vce.CLONE_RUNTIME_STATE_FILE), "w") as fh:
            json.dump({"ready": True}, fh)
        self.assertTrue(vce.is_clone_runtime_provisioned())


class ExtractArchiveSecurityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_preserves_nested_directory_structure(self):
        archive_path = os.path.join(self._tmp.name, "runtime.tar.gz")
        _build_runtime_archive(
            archive_path, "bin/python3",
            extra_members=[("lib/python3.12/site-packages/kanade_tokenizer/__init__.py", "# pkg")],
        )
        dest_dir = os.path.join(self._tmp.name, "dest")
        vce._extract_clone_runtime_archive(archive_path, dest_dir, required_members=("bin/python3",))

        self.assertTrue(os.path.exists(os.path.join(dest_dir, "bin", "python3")))
        self.assertTrue(os.path.exists(
            os.path.join(dest_dir, "lib", "python3.12", "site-packages", "kanade_tokenizer", "__init__.py")
        ))

    def test_missing_required_member_raises_and_leaves_no_partial_install(self):
        archive_path = os.path.join(self._tmp.name, "runtime.tar.gz")
        _build_runtime_archive(archive_path, "bin/python3")  # no python.exe
        dest_dir = os.path.join(self._tmp.name, "dest")
        with self.assertRaises(Exception):
            vce._extract_clone_runtime_archive(archive_path, dest_dir, required_members=("python.exe",))
        self.assertFalse(os.path.exists(os.path.join(dest_dir, "python.exe")))

    def test_path_traversal_member_rejected(self):
        archive_path = os.path.join(self._tmp.name, "evil.tar.gz")
        _build_traversal_archive(archive_path)
        dest_dir = os.path.join(self._tmp.name, "dest")
        with self.assertRaises(Exception):
            vce._extract_clone_runtime_archive(archive_path, dest_dir, required_members=())
        # Nothing escaped to the parent of dest_dir.
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "evil.txt")))

    def test_reprovision_backs_up_and_replaces_previous_install(self):
        dest_dir = os.path.join(self._tmp.name, "dest")
        os.makedirs(dest_dir)
        with open(os.path.join(dest_dir, "stale_marker"), "w") as fh:
            fh.write("old")

        archive_path = os.path.join(self._tmp.name, "runtime.tar.gz")
        _build_runtime_archive(archive_path, "bin/python3")
        vce._extract_clone_runtime_archive(archive_path, dest_dir, required_members=("bin/python3",))

        self.assertTrue(os.path.exists(os.path.join(dest_dir, "bin", "python3")))
        self.assertFalse(os.path.exists(os.path.join(dest_dir, "stale_marker")))
        # No leftover backup/staging directories after a successful promote.
        leftovers = [f for f in os.listdir(self._tmp.name) if f not in ("runtime.tar.gz", "dest")]
        self.assertEqual(leftovers, [])


class ProvisionClientRuntimeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest_dir = self._tmp.name
        self._patchers = [
            patch("voice_clone_engine.clone_runtime_dir", return_value=self.dest_dir),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)

    def _fake_catalog(self, published=True):
        return {
            "linux-x86_64": {
                "url": "https://example.invalid/clone-runtime-linux-x86_64.tar.gz",
                "archive_name": "clone-runtime-linux-x86_64.tar.gz",
                "sha256": "f" * 64 if published else None,
                "python_relpath": os.path.join("bin", "python3"),
            }
        }

    def test_unsupported_platform_refuses_cleanly(self):
        with patch("voice_clone_engine._clone_runtime_platform_key", return_value=None):
            result = vce.provision_clone_runtime()
        self.assertFalse(result["ok"])
        self.assertIn("not supported", result["message"])

    def test_unpublished_artifact_refuses_cleanly_without_downloading(self):
        with patch("voice_clone_engine._clone_runtime_platform_key", return_value="linux-x86_64"), \
             patch("voice_clone_engine.CLONE_RUNTIME_CATALOG", self._fake_catalog(published=False)), \
             patch("model_manager.download_file") as download_mock:
            result = vce.provision_clone_runtime()
        self.assertFalse(result["ok"])
        self.assertIn("not been published", result["message"])
        download_mock.assert_not_called()

    def test_already_provisioned_short_circuits(self):
        with patch("voice_clone_engine.is_clone_runtime_provisioned", return_value=True), \
             patch("model_manager.download_file") as download_mock:
            result = vce.provision_clone_runtime()
        self.assertTrue(result["ok"])
        self.assertTrue(result["already_provisioned"])
        download_mock.assert_not_called()

    def test_download_failure_surfaces_cleanly(self):
        with patch("voice_clone_engine._clone_runtime_platform_key", return_value="linux-x86_64"), \
             patch("voice_clone_engine.CLONE_RUNTIME_CATALOG", self._fake_catalog()), \
             patch("model_manager.download_file", side_effect=IOError("checksum mismatch")):
            result = vce.provision_clone_runtime()
        self.assertFalse(result["ok"])
        self.assertIn("Download failed", result["message"])

    def test_happy_path_provisions_runtime_and_pins_wavlm(self):
        def fake_download(url, dest_path, desc="", progress_callback=None, expected_sha256=None, **kwargs):
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            if desc == "Voice-cloning runtime":
                _build_runtime_archive(dest_path, os.path.join("bin", "python3"))
            else:
                with open(dest_path, "wb") as fh:
                    fh.write(b"fake-wavlm-weights")

        with patch("voice_clone_engine._clone_runtime_platform_key", return_value="linux-x86_64"), \
             patch("voice_clone_engine.CLONE_RUNTIME_CATALOG", self._fake_catalog()), \
             patch("voice_clone_engine.CLONE_WAVLM_PIN", {
                 "url": "https://example.invalid/wavlm_base_plus.pth",
                 "sha256": "a" * 64,
                 "cache_relpath": os.path.join("hub", "checkpoints", "wavlm_base_plus.pth"),
             }), \
             patch("model_manager.download_file", side_effect=fake_download):
            result = vce.provision_clone_runtime()

        self.assertTrue(result["ok"])
        self.assertFalse(result["already_provisioned"])
        self.assertTrue(os.path.exists(os.path.join(self.dest_dir, "bin", "python3")))
        self.assertTrue(os.path.exists(
            os.path.join(self.dest_dir, "torch-home", "hub", "checkpoints", "wavlm_base_plus.pth")
        ))
        self.assertTrue(os.path.exists(os.path.join(self.dest_dir, "clone_worker.py")))
        with open(os.path.join(self.dest_dir, vce.CLONE_RUNTIME_STATE_FILE)) as fh:
            state = json.load(fh)
        self.assertTrue(state["ready"])
        # The downloaded archive itself is cleaned up after extraction.
        self.assertFalse(os.path.exists(os.path.join(self.dest_dir, "clone-runtime-linux-x86_64.tar.gz")))

        with patch("voice_clone_engine._clone_runtime_platform_key", return_value="linux-x86_64"):
            self.assertTrue(vce.is_clone_runtime_provisioned())

    def test_unconfigured_wavlm_pin_refuses_without_marking_ready(self):
        def fake_download(url, dest_path, desc="", progress_callback=None, expected_sha256=None, **kwargs):
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            _build_runtime_archive(dest_path, os.path.join("bin", "python3"))

        with patch("voice_clone_engine._clone_runtime_platform_key", return_value="linux-x86_64"), \
             patch("voice_clone_engine.CLONE_RUNTIME_CATALOG", self._fake_catalog()), \
             patch("voice_clone_engine.CLONE_WAVLM_PIN", {"url": None, "sha256": None, "cache_relpath": "x"}), \
             patch("model_manager.download_file", side_effect=fake_download):
            result = vce.provision_clone_runtime()

        self.assertFalse(result["ok"])
        self.assertIn("WavLM", result["message"])
        self.assertFalse(os.path.exists(os.path.join(self.dest_dir, vce.CLONE_RUNTIME_STATE_FILE)))


class AvailabilitySideRuntimeTests(unittest.TestCase):
    """availability() must report the side-runtime mechanism honestly, and
    never claim available in a simulated-frozen context just because a dev
    venv elsewhere has torch (there is no 'elsewhere' once truly frozen —
    simulated here by making the in-process import fail regardless)."""

    def test_side_runtime_available_when_provisioned_and_in_process_missing(self):
        with patch("voice_clone_engine.is_clone_runtime_provisioned", return_value=True):
            import builtins
            real_import = builtins.__import__

            def no_kanade(name, *args, **kwargs):
                if name.startswith("kanade_tokenizer"):
                    raise ImportError(name=name)
                return real_import(name, *args, **kwargs)

            with patch.object(builtins, "__import__", side_effect=no_kanade):
                status = vce.availability()
        self.assertTrue(status["available"])
        self.assertEqual(status["mechanism"], "side-runtime")

    def test_neither_mechanism_available(self):
        import builtins
        real_import = builtins.__import__

        def no_kanade(name, *args, **kwargs):
            if name.startswith("kanade_tokenizer"):
                raise ImportError(name=name)
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=no_kanade), \
             patch("voice_clone_engine.is_clone_runtime_provisioned", return_value=False):
            status = vce.availability()
        self.assertFalse(status["available"])
        self.assertIsNone(status["mechanism"])
        self.assertIn("setup_voice_cloning", status["setup_hint"])

    def test_simulated_frozen_build_does_not_falsely_claim_available(self):
        # sys.frozen=True is how PyInstaller marks a frozen process; even
        # with that set, availability must still require one of the two real
        # mechanisms to actually work — it must not special-case "frozen" as
        # meaning something different than "in-process import failed".
        import sys
        import builtins
        real_import = builtins.__import__

        def no_kanade(name, *args, **kwargs):
            if name.startswith("kanade_tokenizer"):
                raise ImportError(name=name)
            return real_import(name, *args, **kwargs)

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(builtins, "__import__", side_effect=no_kanade), \
             patch("voice_clone_engine.is_clone_runtime_provisioned", return_value=False):
            status = vce.availability()
        self.assertFalse(status["available"])


if __name__ == "__main__":
    unittest.main()
