import unittest

from hardware_report import _parse_vulkan_devices


class ParseVulkanDevicesTests(unittest.TestCase):
    """Pure parsing of `llama-server --list-devices` output — the basis for
    recognizing Vulkan (Intel/AMD) GPU acceleration in Diagnostics."""

    def test_intel_iris_xe_is_integrated(self):
        # Real output from the shipped Vulkan binary on the target laptop.
        text = (
            "Available devices:\n"
            "  Vulkan0: Intel(R) Iris(R) Xe Graphics (TGL GT2) (11726 MiB, 9746 MiB free)"
        )
        devices = _parse_vulkan_devices(text)
        self.assertEqual(len(devices), 1)
        # Name contains parentheses of its own — must not be truncated at "(R)".
        self.assertEqual(devices[0]["name"], "Intel(R) Iris(R) Xe Graphics (TGL GT2)")
        self.assertEqual(devices[0]["vram_mb"], 11726)
        self.assertEqual(devices[0]["kind"], "integrated")

    def test_discrete_card_classified_discrete(self):
        text = "  Vulkan0: NVIDIA GeForce RTX 4090 (24564 MiB, 24000 MiB free)"
        devices = _parse_vulkan_devices(text)
        self.assertEqual(devices[0]["kind"], "discrete")

    def test_amd_discrete_classified_discrete(self):
        text = "  Vulkan0: AMD Radeon RX 7900 XTX (24560 MiB, 24000 MiB free)"
        devices = _parse_vulkan_devices(text)
        self.assertEqual(devices[0]["kind"], "discrete")

    def test_llvmpipe_software_rasterizer_excluded(self):
        # llvmpipe is CPU software rendering — not real acceleration.
        text = "  Vulkan0: llvmpipe (LLVM 20.1.2, 256 bits) (16000 MiB, 8000 MiB free)"
        self.assertEqual(_parse_vulkan_devices(text), [])

    def test_unknown_vendor_defaults_to_integrated(self):
        # Conservative: an unrecognized string must not be promoted to a
        # dedicated-GPU tier.
        text = "  Vulkan0: SomeNewGPU 9000 (8000 MiB, 8000 MiB free)"
        self.assertEqual(_parse_vulkan_devices(text)[0]["kind"], "integrated")

    def test_no_devices_returns_empty(self):
        self.assertEqual(_parse_vulkan_devices("Available devices:\n  (none)"), [])
        self.assertEqual(_parse_vulkan_devices(""), [])

    def test_first_real_device_wins_over_llvmpipe(self):
        text = (
            "  Vulkan0: Intel(R) Iris(R) Xe Graphics (11726 MiB, 9746 MiB free)\n"
            "  Vulkan1: llvmpipe (LLVM 20) (16000 MiB, 8000 MiB free)"
        )
        devices = _parse_vulkan_devices(text)
        self.assertEqual(len(devices), 1)
        self.assertIn("Iris", devices[0]["name"])


if __name__ == "__main__":
    unittest.main()
