"""Clipboard restoration after paste-injection (§7, M2).

Pasting a draft puts it on the clipboard; the user's prior clipboard must come
back afterward so injection doesn't destroy what they had copied — but only if
nothing new was copied in the meantime.
"""

import unittest
from unittest.mock import patch

import clipboard_capture as cc
import injector as injector_mod
import utils
from injector import InputInjector


class _ImmediateThread:
    """Run the worker synchronously so the fire-and-forget restore is testable."""

    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()


class ScheduleTextClipboardRestoreTests(unittest.TestCase):
    def _clipboard(self, initial):
        box = {"value": initial}
        return box, (lambda: box["value"]), (lambda v: box.__setitem__("value", v) or True)

    def test_restores_prior_when_injected_still_present(self):
        box, get, setv = self._clipboard("DRAFT")  # paste left the draft on the clipboard
        with patch.object(cc, "_clipboard_get_text", get), patch.object(cc, "_clipboard_set_text", setv), patch.object(
            cc.threading, "Thread", _ImmediateThread
        ):
            cc.schedule_text_clipboard_restore("PRIOR", "DRAFT", delay_ms=0)
        self.assertEqual(box["value"], "PRIOR")

    def test_noop_when_user_copied_something_new(self):
        box, get, setv = self._clipboard("USER'S NEW COPY")
        with patch.object(cc, "_clipboard_get_text", get), patch.object(cc, "_clipboard_set_text", setv), patch.object(
            cc.threading, "Thread", _ImmediateThread
        ):
            cc.schedule_text_clipboard_restore("PRIOR", "DRAFT", delay_ms=0)
        self.assertEqual(box["value"], "USER'S NEW COPY")  # never clobbered

    def test_noop_when_prior_equals_injected(self):
        set_calls = []
        with patch.object(cc, "_clipboard_set_text", lambda v: set_calls.append(v)), patch.object(
            cc.threading, "Thread", _ImmediateThread
        ):
            cc.schedule_text_clipboard_restore("SAME", "SAME", delay_ms=0)
        self.assertEqual(set_calls, [])  # early return, no thread, no write


class PasteRestoreTests(unittest.TestCase):
    def _injector(self, restore):
        inj = InputInjector(profile_name="Default")
        inj.config["restore_clipboard_after_paste"] = restore
        return inj

    def test_paste_snapshots_prior_and_schedules_restore(self):
        inj = self._injector(restore=True)
        scheduled = {}
        with patch.object(injector_mod, "pyperclip") as pyperclip, patch.object(
            inj, "_send_paste_hotkey"
        ), patch.object(injector_mod.clipboard_capture, "get_clipboard_text", return_value="PRIOR"), patch.object(
            injector_mod.clipboard_capture,
            "schedule_text_clipboard_restore",
            side_effect=lambda prior, injected, **kw: scheduled.update(prior=prior, injected=injected),
        ):
            inj._paste_raw("DRAFT")
        pyperclip.copy.assert_called_once_with("DRAFT")
        self.assertEqual(scheduled, {"prior": "PRIOR", "injected": "DRAFT"})

    def test_paste_skips_restore_when_disabled(self):
        inj = self._injector(restore=False)
        with patch.object(injector_mod, "pyperclip"), patch.object(inj, "_send_paste_hotkey"), patch.object(
            injector_mod.clipboard_capture, "get_clipboard_text"
        ) as get_clip, patch.object(injector_mod.clipboard_capture, "schedule_text_clipboard_restore") as sched:
            inj._paste_raw("DRAFT")
        get_clip.assert_not_called()
        sched.assert_not_called()

    def test_paste_failure_skips_restore(self):
        inj = self._injector(restore=True)
        with patch.object(injector_mod.pyperclip, "copy", side_effect=RuntimeError("no clipboard")), patch.object(
            injector_mod, "keyboard"
        ), patch.object(injector_mod.clipboard_capture, "get_clipboard_text", return_value="PRIOR"), patch.object(
            injector_mod.clipboard_capture, "schedule_text_clipboard_restore"
        ) as sched:
            inj._paste_raw("DRAFT")
        sched.assert_not_called()  # never schedule a restore when the paste itself failed


class ProfileFieldTests(unittest.TestCase):
    def test_default_on(self):
        self.assertTrue(utils._profile_defaults()["restore_clipboard_after_paste"])

    def test_sanitize_coerces(self):
        defaults = utils._profile_defaults()
        cfg = utils._sanitize_profile_values({"restore_clipboard_after_paste": "no"}, defaults)
        self.assertFalse(cfg["restore_clipboard_after_paste"])


if __name__ == "__main__":
    unittest.main()
