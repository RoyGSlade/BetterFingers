"""type_text honors per-app pacing: paste for mangling apps, --delay otherwise."""

import unittest
from unittest.mock import patch

import injection_pacing
import injector as injector_mod
from injector import InputInjector


def _make_injector(config, method="xdotool"):
    with patch("injector.load_profile", return_value=config):
        inj = InputInjector(profile_name="Default")
    inj.injection_method = method
    return inj


class TypeTextPacingTests(unittest.TestCase):
    def setUp(self):
        # Force the Linux external-tool path regardless of host OS.
        p = patch.object(injector_mod, "IS_WINDOWS", False)
        p.start()
        self.addCleanup(p.stop)

    def test_mangling_app_uses_paste_not_typing(self):
        inj = _make_injector({"per_app_pacing_enabled": True})
        with patch.object(injection_pacing, "detect_active_app_key", return_value="libreoffice"), \
             patch.object(inj, "_type_via_external_tool") as typed, \
             patch.object(inj, "_paste_raw") as pasted:
            inj.type_text("hello world")
        pasted.assert_called_once()
        typed.assert_not_called()

    def test_default_app_types_with_tool_default_delay(self):
        inj = _make_injector({"per_app_pacing_enabled": True})
        with patch.object(injection_pacing, "detect_active_app_key", return_value="gedit"), \
             patch.object(inj, "_type_via_external_tool", return_value=True) as typed, \
             patch.object(inj, "_paste_raw") as pasted:
            inj.type_text("hello world")
        typed.assert_called_once()
        self.assertEqual(typed.call_args.kwargs.get("key_delay_ms"), injection_pacing.XDOTOOL_DEFAULT_DELAY_MS)
        pasted.assert_not_called()

    def test_disabled_skips_detection_and_types(self):
        inj = _make_injector({"per_app_pacing_enabled": False})
        with patch.object(injection_pacing, "detect_active_app_key") as detect, \
             patch.object(inj, "_type_via_external_tool", return_value=True) as typed:
            inj.type_text("hello world")
        detect.assert_not_called()  # disabled → no active-window subprocess
        typed.assert_called_once()

    def test_detection_failure_falls_back_to_typing(self):
        inj = _make_injector({"per_app_pacing_enabled": True})
        with patch.object(injection_pacing, "detect_active_app_key", side_effect=RuntimeError("boom")), \
             patch.object(inj, "_type_via_external_tool", return_value=True) as typed, \
             patch.object(inj, "_paste_raw") as pasted:
            inj.type_text("hello world")
        typed.assert_called_once()
        pasted.assert_not_called()

    def test_type_failure_falls_back_to_paste(self):
        inj = _make_injector({"per_app_pacing_enabled": True})
        with patch.object(injection_pacing, "detect_active_app_key", return_value="gedit"), \
             patch.object(inj, "_type_via_external_tool", return_value=False), \
             patch.object(inj, "_paste_raw") as pasted:
            inj.type_text("hello world")
        pasted.assert_called_once()


class XdotoolArgvTests(unittest.TestCase):
    def test_xdotool_argv_includes_delay_flag(self):
        inj = _make_injector({}, method="xdotool")
        with patch("injector._run_type_tool", return_value=True) as run:
            inj._type_via_external_tool("hi", key_delay_ms=45)
        argv = run.call_args.args[0]
        self.assertIn("--delay", argv)
        self.assertEqual(argv[argv.index("--delay") + 1], "45")
        self.assertEqual(argv[-1], "--")  # text is appended after the -- terminator

    def test_xdotool_argv_omits_delay_when_none(self):
        inj = _make_injector({}, method="xdotool")
        with patch("injector._run_type_tool", return_value=True) as run:
            inj._type_via_external_tool("hi", key_delay_ms=None)
        argv = run.call_args.args[0]
        self.assertNotIn("--delay", argv)


if __name__ == "__main__":
    unittest.main()
