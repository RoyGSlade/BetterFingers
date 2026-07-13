"""Per-app injection pacing policy + best-effort active-app detection."""

import subprocess
import unittest
from unittest.mock import patch

import injection_pacing as ip


class NormalizeAppTests(unittest.TestCase):
    def test_empty_and_blank(self):
        self.assertEqual(ip.normalize_app(None), "")
        self.assertEqual(ip.normalize_app(""), "")
        self.assertEqual(ip.normalize_app("   "), "")

    def test_libreoffice_variants(self):
        for raw in ("soffice", "soffice.bin", "libreoffice-writer", "LibreOffice Calc"):
            self.assertEqual(ip.normalize_app(raw), "libreoffice", raw)

    def test_terminals_collapse(self):
        for raw in ("gnome-terminal-server", "konsole", "xterm", "Alacritty", "kitty"):
            self.assertEqual(ip.normalize_app(raw), "terminal", raw)

    def test_browsers_and_editors(self):
        self.assertEqual(ip.normalize_app("Google-chrome"), "chrome")
        self.assertEqual(ip.normalize_app("chromium"), "chrome")
        self.assertEqual(ip.normalize_app("Navigator.Firefox"), "firefox")
        self.assertEqual(ip.normalize_app("Code"), "vscode")

    def test_unknown_uses_last_dotted_segment(self):
        self.assertEqual(ip.normalize_app("org.gnome.Gedit"), "gedit")
        self.assertEqual(ip.normalize_app("SomeApp"), "someapp")


class ResolvePacingTests(unittest.TestCase):
    def test_default_app_types_at_tool_default(self):
        self.assertEqual(
            ip.resolve_pacing("gedit", {}),
            {"strategy": ip.TYPE, "key_delay_ms": ip.XDOTOOL_DEFAULT_DELAY_MS},
        )

    def test_libreoffice_pastes_by_default(self):
        pacing = ip.resolve_pacing("libreoffice", {})
        self.assertEqual(pacing["strategy"], ip.PASTE)

    def test_disabled_forces_tool_default_even_for_flagged_app(self):
        self.assertEqual(
            ip.resolve_pacing("libreoffice", {"per_app_pacing_enabled": False}),
            {"strategy": ip.TYPE, "key_delay_ms": ip.XDOTOOL_DEFAULT_DELAY_MS},
        )

    def test_user_override_changes_strategy(self):
        pacing = ip.resolve_pacing("vscode", {"injection_pacing_overrides": {"vscode": {"strategy": "paste"}}})
        self.assertEqual(pacing["strategy"], ip.PASTE)

    def test_user_override_sets_delay_and_can_reoverride_flagged_app(self):
        pacing = ip.resolve_pacing(
            "libreoffice",
            {"injection_pacing_overrides": {"libreoffice": {"strategy": "type", "key_delay_ms": 80}}},
        )
        self.assertEqual(pacing, {"strategy": ip.TYPE, "key_delay_ms": 80})

    def test_override_bad_values_are_ignored(self):
        pacing = ip.resolve_pacing(
            "gedit",
            {"injection_pacing_overrides": {"gedit": {"strategy": "nonsense", "key_delay_ms": "fast"}}},
        )
        # Bad strategy + non-int delay both ignored → default preserved.
        self.assertEqual(pacing, {"strategy": ip.TYPE, "key_delay_ms": ip.XDOTOOL_DEFAULT_DELAY_MS})

    def test_overrides_not_a_dict_is_safe(self):
        self.assertEqual(
            ip.resolve_pacing("gedit", {"injection_pacing_overrides": ["bad"]}),
            {"strategy": ip.TYPE, "key_delay_ms": ip.XDOTOOL_DEFAULT_DELAY_MS},
        )


class DetectActiveAppTests(unittest.TestCase):
    def _run(self, stdout=b"", raise_exc=None):
        def fake_run(argv, **kwargs):
            if raise_exc is not None:
                raise raise_exc
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")
        return fake_run

    def test_x11_detects_and_normalizes_class(self):
        with patch("injection_pacing.os.environ", {"DISPLAY": ":0"}), \
             patch("injection_pacing.shutil.which", return_value="/usr/bin/xdotool"), \
             patch("injection_pacing.subprocess.run", side_effect=self._run(stdout=b"soffice.bin\n")), \
             patch("platform_capabilities.IS_WINDOWS", False):
            self.assertEqual(ip.detect_active_app_key(), "libreoffice")

    def test_x11_no_display_returns_empty(self):
        with patch("injection_pacing.os.environ", {}), \
             patch("platform_capabilities.IS_WINDOWS", False):
            self.assertEqual(ip.detect_active_app_key(), "")

    def test_x11_missing_xdotool_returns_empty(self):
        with patch("injection_pacing.os.environ", {"DISPLAY": ":0"}), \
             patch("injection_pacing.shutil.which", return_value=None), \
             patch("platform_capabilities.IS_WINDOWS", False):
            self.assertEqual(ip.detect_active_app_key(), "")

    def test_x11_subprocess_failure_degrades_to_empty(self):
        with patch("injection_pacing.os.environ", {"DISPLAY": ":0"}), \
             patch("injection_pacing.shutil.which", return_value="/usr/bin/xdotool"), \
             patch("injection_pacing.subprocess.run", side_effect=self._run(raise_exc=subprocess.TimeoutExpired("xdotool", 2))), \
             patch("platform_capabilities.IS_WINDOWS", False):
            self.assertEqual(ip.detect_active_app_key(), "")


if __name__ == "__main__":
    unittest.main()
