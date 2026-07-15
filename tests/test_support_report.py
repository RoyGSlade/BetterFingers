import unittest

import support_report


def _sample_data():
    return {
        "generated_at": "2026-07-15T12:00:00+00:00",
        "version": {"backend_version": "0.1.0", "profile_schema_version": 1, "config_version": 1},
        "platform": {"system": "Linux", "release": "6.17.0", "python": "3.12.3"},
        "hardware_tier": "workstation",
        "hardware": {
            "cpu": {"model": "Intel Core i7-1165G7", "physical_cores": 4, "logical_threads": 8},
            "memory": {"total_mb": 15360, "available_mb": 8200},
            "gpu": {"available": True, "name": "Intel Iris Xe", "backend": "vulkan",
                    "kind": "integrated", "vram_mb": 11726, "accelerated": True},
            "disk": {"free_mb": 120000},
        },
        "runtime": {
            "llm": {"runtime_status": "ready", "runtime_build": 4123,
                    "required_runtime_build": 3000, "last_error": ""},
            "stt": {"initialized": True, "loaded": True, "model_size": "base.en", "device": "cpu"},
            "tts": {"initialized": True, "loaded": True, "backend": "kokoro-onnx"},
        },
        "resources": {
            "ledger": {
                "llm": {"model_id": "gemma-4-e2b-q4", "estimated_mb": 1800, "pinned": True},
                "stt": {"model_id": "base.en", "estimated_mb": 500, "pinned": False},
                "tts": None,
            },
            "available_mb": 6000,
            "ram_floor_mb": 1500,
        },
        "recent_errors": [
            {"severity": "warning", "component": "stt", "message": "model load slow",
             "created_at": "2026-07-15T11:59:00+00:00"},
        ],
        "paths": {
            "app_data_dir": "/home/u/.local/share/BetterFingers",
            "config_dir": "/home/u/.config/BetterFingers",
            "models_dir": "/home/u/.local/share/BetterFingers/models",
            "debug_log_path": "/home/u/.local/share/BetterFingers/debug.log",
            "llama_server_path": "/opt/llama/llama-server", "llama_server_exists": True,
            "default_model_path": "/models/gemma.gguf", "default_model_exists": False,
        },
    }


class RenderSupportReportTests(unittest.TestCase):
    def test_renders_all_sections(self):
        md = support_report.render_support_report(_sample_data())
        for heading in ("# BetterFingers Support Report", "## Version", "## Platform",
                        "## Hardware", "## Runtime validation", "## Loaded models (resident)",
                        "## Recent errors (redacted)", "## Paths"):
            self.assertIn(heading, md)

    def test_privacy_note_present(self):
        md = support_report.render_support_report(_sample_data())
        self.assertIn("no transcription content", md.lower())

    def test_key_facts_present(self):
        md = support_report.render_support_report(_sample_data())
        self.assertIn("0.1.0", md)
        self.assertIn("Intel Core i7-1165G7", md)
        self.assertIn("vulkan", md)
        self.assertIn("gemma-4-e2b-q4", md)
        self.assertIn("base.en", md)
        self.assertIn("workstation", md)

    def test_missing_binary_marked(self):
        md = support_report.render_support_report(_sample_data())
        self.assertIn("✗ (missing)", md)   # default model does not exist
        self.assertIn("✓", md)             # llama-server does exist

    def test_empty_data_does_not_crash(self):
        md = support_report.render_support_report({})
        self.assertIn("# BetterFingers Support Report", md)
        self.assertIn("_(none)_", md)  # empty error section

    def test_no_resident_models_message(self):
        data = _sample_data()
        data["resources"]["ledger"] = {"llm": None, "stt": None, "tts": None}
        md = support_report.render_support_report(data)
        self.assertIn("no models resident", md.lower())


class RedactErrorMessageTests(unittest.TestCase):
    def test_collapses_newlines(self):
        out = support_report.redact_error_message("line one\nline two\ttabbed")
        self.assertNotIn("\n", out)
        self.assertNotIn("\t", out)
        self.assertEqual(out, "line one line two tabbed")

    def test_strips_control_chars(self):
        out = support_report.redact_error_message("bad\x00\x07char")
        self.assertNotIn("\x00", out)
        self.assertNotIn("\x07", out)

    def test_caps_length(self):
        out = support_report.redact_error_message("x" * 5000)
        self.assertLessEqual(len(out), 301)  # 300 + ellipsis
        self.assertTrue(out.endswith("…"))

    def test_none_is_empty(self):
        self.assertEqual(support_report.redact_error_message(None), "")


if __name__ == "__main__":
    unittest.main()
