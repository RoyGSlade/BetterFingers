"""Adapter contract + runtime detection (Wave 8B, D-0010).

No subprocess, no audio server: every guard here is either the null guard or
a fake, so these tests assert the *contract*, not any platform behavior.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.platform.audio_privacy import base  # noqa: E402


class CaptureStreamTests(unittest.TestCase):
    def test_allowlist_matches_case_insensitively_in_both_directions(self):
        stream = base.CaptureStream(key="1", muted=False, labels=("Discord",))
        self.assertTrue(stream.matches_allowlist(["discord"]))
        self.assertTrue(stream.matches_allowlist(["Discord Canary"]))  # label inside entry
        self.assertFalse(stream.matches_allowlist(["zoom"]))

    def test_an_empty_allowlist_matches_nothing(self):
        stream = base.CaptureStream(key="1", muted=False, labels=("Discord",))
        self.assertFalse(stream.matches_allowlist([]))
        self.assertFalse(stream.matches_allowlist(None))

    def test_blank_entries_and_blank_labels_never_match(self):
        # A blank allowlist entry must not become "match everything" via the
        # substring test ("" is a substring of every string).
        stream = base.CaptureStream(key="1", muted=False, labels=("Discord", ""))
        self.assertFalse(stream.matches_allowlist(["   ", ""]))


class MutedStreamRecordTests(unittest.TestCase):
    def test_record_round_trips(self):
        original = base.MutedStream(key="7", prior_muted=False, serial=42)
        restored = base.MutedStream.from_record(original.as_record())
        self.assertEqual(restored, original)

    def test_record_carries_identifiers_and_a_boolean_and_nothing_else(self):
        record = base.MutedStream(key="7", prior_muted=True, serial=1).as_record()
        self.assertEqual(set(record), {"key", "prior_muted", "serial"})

    def test_a_serialless_stream_omits_the_key_entirely(self):
        record = base.MutedStream(key="7", prior_muted=False).as_record()
        self.assertEqual(set(record), {"key", "prior_muted"})

    def test_unusable_records_are_rejected_rather_than_guessed(self):
        for bad in (None, {}, {"prior_muted": True}, {"key": ""}, {"key": 3}, "nope"):
            self.assertIsNone(base.MutedStream.from_record(bad), bad)


class NullGuardTests(unittest.TestCase):
    def test_it_is_never_available_and_carries_its_reason(self):
        guard = base.NullPrivacyGuard(base.UNAVAILABLE_TOOL_MISSING)
        self.assertFalse(guard.is_available())
        self.assertEqual(guard.availability(), (False, base.UNAVAILABLE_TOOL_MISSING))

    def test_engage_does_nothing_and_says_so(self):
        outcome = base.NullPrivacyGuard().engage(keep_unmuted_apps=["x"])
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.muted, [])

    def test_restore_is_complete_because_nothing_was_ever_changed(self):
        outcome = base.NullPrivacyGuard().restore([base.MutedStream("1", False)])
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.gone, 1)


class _FakeGuard(base.PrivacyGuard):
    name = "fake"

    def __init__(self, available, reason=base.AVAILABLE):
        self._available = available
        self._reason = reason

    def availability(self):
        return self._available, self._reason


class DetectGuardTests(unittest.TestCase):
    """Detection must be *runtime* proof, not a platform string."""

    def test_an_available_adapter_is_returned(self):
        guard = base.detect_guard("linux", factories={"linux": lambda: _FakeGuard(True)})
        self.assertEqual(guard.name, "fake")

    def test_an_unavailable_adapter_degrades_to_null_carrying_the_reason(self):
        guard = base.detect_guard(
            "linux",
            factories={"linux": lambda: _FakeGuard(False, base.UNAVAILABLE_TOOL_MISSING)},
        )
        self.assertIsInstance(guard, base.NullPrivacyGuard)
        self.assertEqual(guard.availability(), (False, base.UNAVAILABLE_TOOL_MISSING))

    def test_an_unknown_platform_is_wrong_platform_not_a_crash(self):
        guard = base.detect_guard("sunos", factories={"linux": lambda: _FakeGuard(True)})
        self.assertIsInstance(guard, base.NullPrivacyGuard)
        self.assertEqual(guard.availability()[1], base.UNAVAILABLE_WRONG_PLATFORM)

    def test_a_constructor_that_raises_degrades_instead_of_propagating(self):
        def _boom():
            raise RuntimeError("no audio server")

        guard = base.detect_guard("linux", factories={"linux": _boom})
        self.assertIsInstance(guard, base.NullPrivacyGuard)
        self.assertFalse(guard.is_available())

    def test_the_real_default_factories_cover_linux_and_windows(self):
        # Constructing them must not touch the audio server.
        factories = base._default_factories()
        self.assertEqual(set(factories), {"linux", "win"})
        self.assertEqual(factories["win"]().name, base.ADAPTER_WINDOWS_CORE_AUDIO)


class WindowsFeasibilityTests(unittest.TestCase):
    """Windows ships as a design, and must keep saying so."""

    def setUp(self):
        from backend.platform.audio_privacy import windows_core_audio

        self.module = windows_core_audio
        self.guard = windows_core_audio.WindowsCoreAudioPrivacyGuard()

    def test_it_is_not_implemented_and_reports_that_exact_reason(self):
        self.assertEqual(
            self.guard.availability(), (False, base.UNAVAILABLE_NOT_IMPLEMENTED)
        )

    def test_it_mutates_nothing(self):
        self.assertFalse(self.guard.engage().ok)
        self.assertEqual(self.guard.list_streams(), [])
        self.assertTrue(self.guard.restore([base.MutedStream("1", False)]).complete)

    def test_the_spike_acceptance_criteria_are_recorded_and_complete(self):
        criteria = set(self.module.SPIKE_ACCEPTANCE_CRITERIA)
        # The three that D-0010 makes non-negotiable: no name matching, exact
        # restoration, and recovery after a crash.
        self.assertIn("identify_own_session", criteria)
        self.assertIn("exact_restore", criteria)
        self.assertIn("restore_after_process_crash", criteria)
        self.assertIn("supported_api_only", criteria)


if __name__ == "__main__":
    unittest.main()
