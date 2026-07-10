"""Injection compatibility matrix (§7, M2): per-target/per-dimension schema,
overall-status rules, coverage, JSON round-trip, and capability-matrix rendering."""

import json
import os
import tempfile
import unittest

import injection_matrix as im


class TargetResultTests(unittest.TestCase):
    def test_defaults_all_untested(self):
        result = im.TargetResult(app="Notepad", platform="windows")
        self.assertEqual(set(result.dimensions), set(im.DIMENSIONS))
        self.assertTrue(all(v == im.UNTESTED for v in result.dimensions.values()))
        self.assertEqual(result.overall, im.UNTESTED)

    def test_set_validates_dimension_and_status(self):
        result = im.TargetResult(app="Notepad", platform="windows")
        result.set("plain_text", im.PASS)
        self.assertEqual(result.dimensions["plain_text"], im.PASS)
        with self.assertRaises(ValueError):
            result.set("bogus", im.PASS)
        with self.assertRaises(ValueError):
            result.set("plain_text", "maybe")

    def test_overall_pass_needs_core_dimensions(self):
        result = im.TargetResult(app="Notepad", platform="windows")
        result.set("plain_text", im.PASS)
        # plain_text alone isn't enough; clipboard_restore still untested -> partial
        self.assertEqual(result.overall, im.PARTIAL)
        result.set("clipboard_restore", im.PASS)
        self.assertEqual(result.overall, im.PASS)

    def test_overall_fail_if_any_dimension_fails(self):
        result = im.TargetResult(app="Chrome text input", platform="linux-wayland")
        result.set("plain_text", im.PASS)
        result.set("clipboard_restore", im.PASS)
        result.set("elevated", im.FAIL)
        self.assertEqual(result.overall, im.FAIL)

    def test_round_trip(self):
        result = im.TargetResult(app="VS Code", platform="linux-x11", injection_method="xdotool", latency_ms=42.0, notes="ok")
        result.set("plain_text", im.PASS)
        result.set("unicode", im.PARTIAL)
        restored = im.TargetResult.from_dict(result.to_dict())
        self.assertEqual(restored.app, "VS Code")
        self.assertEqual(restored.injection_method, "xdotool")
        self.assertEqual(restored.latency_ms, 42.0)
        self.assertEqual(restored.dimensions["plain_text"], im.PASS)
        self.assertEqual(restored.dimensions["unicode"], im.PARTIAL)

    def test_from_dict_drops_unknown_keys_and_bad_status(self):
        restored = im.TargetResult.from_dict(
            {"app": "X", "platform": "windows", "dimensions": {"plain_text": "pass", "bogus": "pass", "unicode": "weird"}}
        )
        self.assertEqual(restored.dimensions["plain_text"], im.PASS)
        self.assertNotIn("bogus", restored.dimensions)
        self.assertEqual(restored.dimensions["unicode"], im.UNTESTED)  # invalid value ignored


class MatrixAggregationTests(unittest.TestCase):
    def test_default_matrix_covers_target_list(self):
        matrix = im.default_matrix("windows")
        self.assertEqual([r.app for r in matrix], im.DEFAULT_TARGETS)
        self.assertTrue(all(r.platform == "windows" for r in matrix))

    def test_coverage(self):
        matrix = im.default_matrix("windows", targets=["A", "B"])
        matrix[0].set("plain_text", im.PASS)
        matrix[0].set("unicode", im.FAIL)
        cov = im.coverage(matrix)
        self.assertEqual(cov["targets"], 2)
        self.assertEqual(cov["cells"], 2 * len(im.DIMENSIONS))
        self.assertEqual(cov["tested"], 2)
        self.assertEqual(cov["passed"], 1)

    def test_json_round_trip_via_files(self):
        matrix = im.default_matrix("linux-x11", targets=["Terminal"])
        matrix[0].set("plain_text", im.PASS)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "matrix.json")
            im.dump(matrix, path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["version"], 1)
            loaded = im.load(path)
        self.assertEqual(loaded[0].app, "Terminal")
        self.assertEqual(loaded[0].dimensions["plain_text"], im.PASS)

    def test_capability_markdown(self):
        matrix = im.default_matrix("windows", targets=["Notepad"])
        matrix[0].injection_method = "pydirectinput"
        matrix[0].latency_ms = 12.0
        matrix[0].set("plain_text", im.PASS)
        matrix[0].set("elevated", im.FAIL)
        md = im.to_capability_markdown(matrix)
        self.assertIn("| App | Platform | Method |", md)
        self.assertIn("Notepad", md)
        self.assertIn("pydirectinput", md)
        self.assertIn("12ms", md)
        self.assertIn("✅", md)
        self.assertIn("❌", md)


if __name__ == "__main__":
    unittest.main()
