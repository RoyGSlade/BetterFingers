import importlib
import unittest
from unittest.mock import patch

import platform_capabilities
from injector import InputInjector


def _which_map(available):
    """Return a fake shutil.which that only 'finds' tools in `available`."""
    available = set(available)

    def _which(name):
        return f"/usr/bin/{name}" if name in available else None

    return _which


class DetectInjectionMethodTests(unittest.TestCase):
    def _detect(self, *, windows=False, linux=True, wayland=False, x11=True, tools=()):
        with patch.object(platform_capabilities, "is_windows", windows), patch.object(
            platform_capabilities, "is_linux", linux
        ), patch.object(platform_capabilities, "is_wayland", wayland), patch.object(
            platform_capabilities, "is_x11", x11
        ), patch.object(
            platform_capabilities, "supports_basic_clipboard", True
        ), patch(
            "platform_capabilities.shutil.which", _which_map(tools)
        ):
            return platform_capabilities.detect_injection_method()

    def test_windows_uses_pydirectinput(self):
        self.assertEqual(
            self._detect(windows=True, linux=False, tools=()), "pydirectinput"
        )

    def test_linux_x11_prefers_xdotool(self):
        self.assertEqual(
            self._detect(wayland=False, x11=True, tools=["xdotool"]), "xdotool"
        )

    def test_linux_x11_without_xdotool_falls_back_to_paste(self):
        self.assertEqual(self._detect(wayland=False, x11=True, tools=[]), "paste")

    def test_wayland_prefers_wtype_over_ydotool(self):
        self.assertEqual(
            self._detect(wayland=True, x11=False, tools=["wtype", "ydotool"]),
            "wtype",
        )

    def test_wayland_uses_ydotool_when_no_wtype(self):
        self.assertEqual(
            self._detect(wayland=True, x11=False, tools=["ydotool"]), "ydotool"
        )

    def test_wayland_without_typing_tools_falls_back_to_paste(self):
        self.assertEqual(self._detect(wayland=True, x11=False, tools=[]), "paste")

    def test_no_clipboard_reports_none(self):
        with patch.object(platform_capabilities, "is_windows", False), patch.object(
            platform_capabilities, "is_linux", False
        ), patch.object(
            platform_capabilities, "supports_basic_clipboard", False
        ), patch(
            "platform_capabilities.shutil.which", _which_map([])
        ):
            self.assertEqual(platform_capabilities.detect_injection_method(), "none")


class ClipboardBackendDetectionTests(unittest.TestCase):
    """A stock Linux box without xclip/xsel/wl-clipboard has no working clipboard,
    so injection is genuinely unavailable — the app must not claim otherwise."""

    def _detect(self, *, windows=False, macos=False, linux=True, wayland=False, tools=()):
        with patch.object(platform_capabilities, "is_windows", windows), patch.object(
            platform_capabilities, "is_macos", macos
        ), patch.object(platform_capabilities, "is_linux", linux), patch.object(
            platform_capabilities, "is_wayland", wayland
        ), patch("platform_capabilities.shutil.which", _which_map(tools)):
            return platform_capabilities._detect_clipboard_backend()

    def test_windows_native(self):
        self.assertEqual(self._detect(windows=True, linux=False), "native")

    def test_macos_native(self):
        self.assertEqual(self._detect(macos=True, linux=False), "native")

    def test_linux_x11_prefers_xclip(self):
        self.assertEqual(self._detect(tools=["xclip", "xsel"]), "xclip")

    def test_linux_x11_xsel_fallback(self):
        self.assertEqual(self._detect(tools=["xsel"]), "xsel")

    def test_linux_wayland_wl_copy(self):
        self.assertEqual(self._detect(wayland=True, tools=["wl-copy"]), "wl-copy")

    def test_linux_no_backend_is_empty(self):
        self.assertEqual(self._detect(tools=[]), "")


class InjectionHintTests(unittest.TestCase):
    def test_no_hint_when_injection_available(self):
        with patch.object(platform_capabilities, "injection_method", "paste"):
            self.assertEqual(platform_capabilities.injection_hint(), "")

    def test_linux_x11_hint_names_xclip(self):
        with patch.object(platform_capabilities, "injection_method", "none"), patch.object(
            platform_capabilities, "is_linux", True
        ), patch.object(platform_capabilities, "is_wayland", False):
            self.assertIn("xclip", platform_capabilities.injection_hint())

    def test_linux_wayland_hint_names_wl_clipboard(self):
        with patch.object(platform_capabilities, "injection_method", "none"), patch.object(
            platform_capabilities, "is_linux", True
        ), patch.object(platform_capabilities, "is_wayland", True):
            self.assertIn("wl-clipboard", platform_capabilities.injection_hint())


class CapabilitiesFieldTests(unittest.TestCase):
    def test_capabilities_expose_injection_fields(self):
        caps = platform_capabilities.get_capabilities()
        self.assertIn("injection_method", caps)
        self.assertIn("supports_typing", caps)
        self.assertIn("clipboard_backend", caps)
        self.assertIn("injection_hint", caps)
        self.assertIn(
            caps["injection_method"],
            {"pydirectinput", "xdotool", "wtype", "ydotool", "paste", "none"},
        )
        # supports_typing must be consistent with the chosen method.
        expected_typing = caps["injection_method"] not in ("paste", "none")
        self.assertEqual(caps["supports_typing"], expected_typing)


class TypeTextRoutingTests(unittest.TestCase):
    @patch("injector.load_profile", return_value={})
    def test_type_text_uses_external_tool_on_linux(self, _load_profile):
        with patch("injector.IS_WINDOWS", False):
            inj = InputInjector(profile_name="Default")
            inj.injection_method = "xdotool"
            with patch("injector._run_type_tool", return_value=True) as run_tool, patch.object(
                inj, "_paste_raw"
            ) as paste_raw:
                inj.type_text("hello")
                run_tool.assert_called_once()
                # argv[0] should be xdotool; text passed through.
                args, _ = run_tool.call_args
                self.assertEqual(args[0][0], "xdotool")
                self.assertEqual(args[1], "hello")
                paste_raw.assert_not_called()

    @patch("injector.load_profile", return_value={})
    def test_type_text_falls_back_to_paste_when_tool_fails(self, _load_profile):
        with patch("injector.IS_WINDOWS", False):
            inj = InputInjector(profile_name="Default")
            inj.injection_method = "wtype"
            with patch("injector._run_type_tool", return_value=False), patch.object(
                inj, "_paste_raw"
            ) as paste_raw:
                inj.type_text("hello")
                paste_raw.assert_called_once_with("hello")

    @patch("injector.load_profile", return_value={})
    def test_type_text_uses_paste_when_method_is_paste(self, _load_profile):
        with patch("injector.IS_WINDOWS", False):
            inj = InputInjector(profile_name="Default")
            inj.injection_method = "paste"
            with patch("injector._run_type_tool") as run_tool, patch.object(
                inj, "_paste_raw"
            ) as paste_raw:
                inj.type_text("hi")
                run_tool.assert_not_called()
                paste_raw.assert_called_once_with("hi")


if __name__ == "__main__":
    unittest.main()
