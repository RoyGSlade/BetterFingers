import importlib.util
import unittest
from pathlib import Path

# tools/ is not a package; load setup_venv.py directly so the pure decision
# logic can be unit-tested without importing the whole tools namespace.
_MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "setup_venv.py"
_spec = importlib.util.spec_from_file_location("setup_venv", _MODULE_PATH)
setup_venv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup_venv)

resolve_torch_channel = setup_venv.resolve_torch_channel


class ResolveTorchChannelTests(unittest.TestCase):
    """The core hardware-aware decision: which torch build to install."""

    def test_linux_no_gpu_auto_picks_cpu(self):
        # The whole point: a GPU-less Linux box must NOT pull the CUDA stack.
        self.assertEqual(
            resolve_torch_channel("Linux", "auto", cuda_present=False), "cpu"
        )

    def test_linux_with_gpu_auto_uses_default(self):
        self.assertEqual(
            resolve_torch_channel("Linux", "auto", cuda_present=True), "default"
        )

    def test_windows_auto_defers_to_default(self):
        # Default Windows/macOS torch wheels carry no nvidia-* payload, so auto
        # leaves them to normal requirements resolution regardless of GPU.
        self.assertEqual(
            resolve_torch_channel("Windows", "auto", cuda_present=False), "default"
        )

    def test_macos_auto_defers_to_default(self):
        self.assertEqual(
            resolve_torch_channel("Darwin", "auto", cuda_present=False), "default"
        )

    def test_explicit_cpu_forces_cpu_even_with_gpu(self):
        self.assertEqual(
            resolve_torch_channel("Linux", "cpu", cuda_present=True), "cpu"
        )

    def test_explicit_cpu_on_windows(self):
        self.assertEqual(
            resolve_torch_channel("Windows", "cpu", cuda_present=True), "cpu"
        )

    def test_explicit_cuda_forces_default_even_without_gpu(self):
        self.assertEqual(
            resolve_torch_channel("Linux", "cuda", cuda_present=False), "default"
        )


if __name__ == "__main__":
    unittest.main()
