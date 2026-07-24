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


class RequiredInjectionToolTests(unittest.TestCase):
    def test_typing_methods_map_to_their_binary(self):
        self.assertEqual(platform_capabilities.required_injection_tool("xdotool"), "xdotool")
        self.assertEqual(platform_capabilities.required_injection_tool("wtype"), "wtype")
        self.assertEqual(platform_capabilities.required_injection_tool("ydotool"), "ydotool")

    def test_non_typing_methods_need_no_external_tool(self):
        self.assertIsNone(platform_capabilities.required_injection_tool("paste"))
        self.assertIsNone(platform_capabilities.required_injection_tool("none"))
        self.assertIsNone(platform_capabilities.required_injection_tool("pydirectinput"))


class InjectionHintExplicitMethodTests(unittest.TestCase):
    """injection_hint() must stay honest for a caller-supplied method, not just
    the cached startup-time global (used by get_injection_status())."""

    def test_explicit_none_on_wayland_names_wl_clipboard(self):
        with patch.object(platform_capabilities, "is_linux", True), patch.object(
            platform_capabilities, "is_wayland", True
        ):
            self.assertIn("wl-clipboard", platform_capabilities.injection_hint("none"))

    def test_explicit_none_on_x11_names_xclip(self):
        with patch.object(platform_capabilities, "is_linux", True), patch.object(
            platform_capabilities, "is_wayland", False
        ):
            self.assertIn("xclip", platform_capabilities.injection_hint("none"))

    def test_explicit_working_method_has_no_hint(self):
        self.assertEqual(platform_capabilities.injection_hint("wtype"), "")
        self.assertEqual(platform_capabilities.injection_hint("paste"), "")

    def test_default_still_uses_cached_global(self):
        with patch.object(platform_capabilities, "injection_method", "none"), patch.object(
            platform_capabilities, "is_linux", True
        ), patch.object(platform_capabilities, "is_wayland", False):
            self.assertIn("xclip", platform_capabilities.injection_hint())


class InjectionStatusTests(unittest.TestCase):
    """get_injection_status() must be a live (non-cached) re-check: no keys
    typed, no clipboard touched -- just shutil.which() PATH lookups -- so
    /doctor can honestly reflect a tool installed/removed after startup."""

    def _status(self, *, windows=False, linux=True, wayland=False, x11=True, tools=()):
        session = "wayland" if wayland else ("x11" if x11 else "")
        with patch.object(platform_capabilities, "is_windows", windows), patch.object(
            platform_capabilities, "is_linux", linux
        ), patch.object(platform_capabilities, "is_macos", False), patch.object(
            platform_capabilities, "is_wayland", wayland
        ), patch.object(platform_capabilities, "is_x11", x11), patch.object(
            platform_capabilities, "session_type", session
        ), patch("platform_capabilities.shutil.which", _which_map(tools)):
            return platform_capabilities.get_injection_status()

    def test_wayland_missing_everything_is_honestly_none(self):
        # No wtype/ydotool/xdotool AND no wl-copy/xclip/xsel -- the true
        # "silent failure" case the doctor route must surface.
        status = self._status(wayland=True, x11=False, tools=[])
        self.assertEqual(status["method"], "none")
        self.assertIsNone(status["required_tool"])
        self.assertFalse(status["tool_available"])
        self.assertEqual(status["clipboard_backend"], "")
        self.assertFalse(status["supports_typing"])
        self.assertFalse(status["supports_input_injection"])
        self.assertIn("wl-clipboard", status["hint"])

    def test_wayland_with_wtype_is_fully_available(self):
        status = self._status(wayland=True, x11=False, tools=["wtype"])
        self.assertEqual(status["method"], "wtype")
        self.assertEqual(status["required_tool"], "wtype")
        self.assertTrue(status["tool_available"])
        self.assertTrue(status["supports_typing"])
        self.assertEqual(status["hint"], "")

    def test_wayland_no_typing_tool_but_clipboard_present_is_paste(self):
        # wl-copy present, no wtype/ydotool: real typing is unavailable but
        # the universal clipboard-paste fallback honestly reports as working.
        status = self._status(wayland=True, x11=False, tools=["wl-copy"])
        self.assertEqual(status["method"], "paste")
        self.assertIsNone(status["required_tool"])
        self.assertTrue(status["tool_available"])
        self.assertEqual(status["clipboard_backend"], "wl-copy")
        self.assertFalse(status["supports_typing"])
        self.assertTrue(status["supports_input_injection"])
        self.assertEqual(status["hint"], "")

    def test_linux_x11_missing_xdotool_and_clipboard_tool_is_none(self):
        status = self._status(wayland=False, x11=True, tools=[])
        self.assertEqual(status["method"], "none")
        self.assertFalse(status["tool_available"])
        self.assertIn("xclip", status["hint"])

    def test_status_reports_session_type_fields(self):
        status = self._status(wayland=True, x11=False, tools=["wtype"])
        self.assertEqual(status["session_type"], "wayland")
        self.assertTrue(status["is_wayland"])
        self.assertFalse(status["is_x11"])

    def test_windows_reports_pydirectinput_available(self):
        status = self._status(windows=True, linux=False, x11=False, tools=[])
        self.assertEqual(status["method"], "pydirectinput")
        self.assertIsNone(status["required_tool"])
        self.assertTrue(status["tool_available"])

    def test_status_is_recomputed_live_not_cached(self):
        # Simulate a tool being installed *after* the stale module-level
        # globals were computed at import: the cached `injection_method`
        # stays "none", but a fresh get_injection_status() call picks it up.
        with patch.object(platform_capabilities, "injection_method", "none"), patch.object(
            platform_capabilities, "clipboard_backend", ""
        ), patch.object(platform_capabilities, "supports_basic_clipboard", False):
            status = self._status(wayland=True, x11=False, tools=["wtype"])
        self.assertEqual(status["method"], "wtype")
        self.assertNotEqual(status["method"], platform_capabilities.injection_method)


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
