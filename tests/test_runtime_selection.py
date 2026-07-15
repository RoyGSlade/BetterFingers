"""Windows CUDA-vs-Vulkan runtime selection (backlog item 2).

An AMD/Intel Windows PC must NOT be handed the CUDA-only llama.cpp build.
These tests lock the selection table, the operator override, and — critically
for the supply-chain gate (§11) — that every archive the selector can choose is
hash-pinned.
"""
import unittest
from unittest.mock import patch

import model_manager as mm


class SelectRuntimeSpecTests(unittest.TestCase):
    def test_windows_nvidia_gets_cuda(self):
        spec = mm._select_runtime_spec("win32", prefer_cuda=True)
        self.assertEqual(spec["backend"], "cuda")
        self.assertEqual(spec["bin_url"], mm.WIN_CUDA_BIN_URL)
        self.assertEqual(spec["cuda_lib_url"], mm.WIN_CUDA_LIB_URL)
        self.assertEqual(spec["filename"], "llama-server.exe")

    def test_windows_non_nvidia_gets_vulkan_no_cudart(self):
        spec = mm._select_runtime_spec("win32", prefer_cuda=False)
        self.assertEqual(spec["backend"], "vulkan")
        self.assertEqual(spec["bin_url"], mm.WIN_VULKAN_BIN_URL)
        self.assertIsNone(spec["cuda_lib_url"])
        self.assertIsNone(spec["cuda_archive_name"])
        self.assertEqual(spec["filename"], "llama-server.exe")

    def test_linux_always_vulkan(self):
        spec = mm._select_runtime_spec("linux", prefer_cuda=False)
        self.assertEqual(spec["backend"], "vulkan")
        self.assertEqual(spec["bin_url"], mm.LINUX_VULKAN_BIN_URL)
        self.assertIsNone(spec["cuda_lib_url"])
        self.assertEqual(spec["filename"], "llama-server")

    def test_every_selectable_archive_is_hash_pinned(self):
        specs = [
            mm._select_runtime_spec("win32", True),
            mm._select_runtime_spec("win32", False),
            mm._select_runtime_spec("linux", False),
        ]
        for spec in specs:
            for url in (spec["bin_url"], spec["cuda_lib_url"]):
                if url:
                    digest = mm.runtime_artifact_sha256(url)
                    self.assertRegex(digest or "", r"^[0-9a-f]{64}$", url)


class ResolveRuntimeSpecTests(unittest.TestCase):
    """resolve_runtime_spec() = platform + override + nvidia detection."""

    def _resolve_on_windows(self, override, has_nvidia):
        env = {"BETTERFINGERS_LLAMA_RUNTIME": override} if override is not None else {}
        with patch.object(mm.sys, "platform", "win32"), \
             patch.object(mm, "_windows_has_nvidia_gpu", return_value=has_nvidia), \
             patch.dict(mm.os.environ, env, clear=False):
            if override is None:
                mm.os.environ.pop("BETTERFINGERS_LLAMA_RUNTIME", None)
            return mm.resolve_runtime_spec()

    def test_auto_nvidia_present_picks_cuda(self):
        self.assertEqual(self._resolve_on_windows(None, has_nvidia=True)["backend"], "cuda")

    def test_auto_no_nvidia_picks_vulkan(self):
        self.assertEqual(self._resolve_on_windows(None, has_nvidia=False)["backend"], "vulkan")

    def test_override_cuda_forces_cuda_without_nvidia(self):
        self.assertEqual(self._resolve_on_windows("cuda", has_nvidia=False)["backend"], "cuda")

    def test_override_vulkan_forces_vulkan_with_nvidia(self):
        self.assertEqual(self._resolve_on_windows("vulkan", has_nvidia=True)["backend"], "vulkan")

    def test_override_cpu_forces_vulkan_build(self):
        # "cpu" maps to the Vulkan archive, which runs CPU-only with no device.
        self.assertEqual(self._resolve_on_windows("cpu", has_nvidia=True)["backend"], "vulkan")

    def test_non_windows_ignores_override(self):
        with patch.object(mm.sys, "platform", "linux"), \
             patch.dict(mm.os.environ, {"BETTERFINGERS_LLAMA_RUNTIME": "cuda"}):
            self.assertEqual(mm.resolve_runtime_spec()["backend"], "vulkan")


class NvidiaDetectionTests(unittest.TestCase):
    def test_no_nvidia_smi_binary_is_false(self):
        with patch.object(mm.shutil, "which", return_value=None):
            self.assertFalse(mm._windows_has_nvidia_gpu())

    def test_nvidia_smi_lists_gpu_is_true(self):
        class _R:
            returncode = 0
            stdout = "GPU 0: NVIDIA GeForce RTX 4070 (UUID: GPU-abc)"
        with patch.object(mm.shutil, "which", return_value="/usr/bin/nvidia-smi"), \
             patch.object(mm.subprocess, "run", return_value=_R()):
            self.assertTrue(mm._windows_has_nvidia_gpu())

    def test_nvidia_smi_failure_is_false(self):
        with patch.object(mm.shutil, "which", return_value="/usr/bin/nvidia-smi"), \
             patch.object(mm.subprocess, "run", side_effect=OSError("boom")):
            self.assertFalse(mm._windows_has_nvidia_gpu())


if __name__ == "__main__":
    unittest.main()
