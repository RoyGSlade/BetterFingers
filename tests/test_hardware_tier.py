import unittest

from hardware_report import classify_tier, get_hardware_tier


class ClassifyTierTests(unittest.TestCase):
    def test_no_gpu_is_cpu_only(self):
        result = classify_tier(ram_mb=16000, vram_mb=None, gpu_kind="none", cores=8)
        self.assertEqual(result["tier"], "cpu-only")
        self.assertIn("CPU", result["label"])

    def test_integrated_gpu_is_igpu(self):
        result = classify_tier(ram_mb=16000, vram_mb=None, gpu_kind="integrated", cores=4)
        self.assertEqual(result["tier"], "igpu")

    def test_discrete_8gb(self):
        result = classify_tier(ram_mb=32000, vram_mb=8192, gpu_kind="discrete", cores=8)
        self.assertEqual(result["tier"], "dgpu-8g")

    def test_discrete_12gb_plus(self):
        result = classify_tier(ram_mb=32000, vram_mb=16384, gpu_kind="discrete", cores=12)
        self.assertEqual(result["tier"], "dgpu-12g+")

    def test_discrete_unknown_vram_still_dedicated(self):
        result = classify_tier(ram_mb=16000, vram_mb=None, gpu_kind="discrete", cores=8)
        self.assertTrue(result["tier"].startswith("dgpu"))

    def test_low_ram_warns(self):
        result = classify_tier(ram_mb=4000, vram_mb=None, gpu_kind="none", cores=2)
        self.assertEqual(result["tier"], "cpu-only")
        self.assertTrue(any("RAM" in w for w in result["warnings"]))

    def test_missing_inputs_do_not_crash(self):
        result = classify_tier()
        self.assertEqual(result["tier"], "cpu-only")
        self.assertIn("guidance", result)

    def test_get_hardware_tier_returns_valid_tier(self):
        result = get_hardware_tier()
        self.assertIn(result["tier"], {"cpu-only", "igpu", "dgpu-8g", "dgpu-12g+"})
        self.assertIn("guidance", result)


if __name__ == "__main__":
    unittest.main()
