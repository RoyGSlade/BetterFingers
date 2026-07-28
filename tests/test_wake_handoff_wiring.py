"""Wave 8B wiring: wake handoff into the recorder, and the privacy lease on
every stop path.

Wave 8A landed ``wake_pretrigger`` complete and tested but unwired, and
``restore_complete`` as a constant. These tests cover the seams that changed:
the recorder's prepend entry point, the wake reason forcing trailing-silence
command capture, the listener's chunk observer, routes_wake's arm/feed/
activate cycle, and lease acquire/release around a recording.

All audio and subprocess work is mocked; nothing here opens a device.
"""
import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import recorder as recorder_mod  # noqa: E402
import wake_pretrigger  # noqa: E402
import wake_word  # noqa: E402


class FakeSubscription:
    def __init__(self):
        self.active = True
        self.closed = False

    def close(self):
        self.closed = True
        self.active = False


class FakeBroker:
    def __init__(self, fail=False):
        self.fail = fail
        self.subscription = None
        self.callback = None

    def subscribe(self, name, callback, device=None, allow_default_fallback=True,
                  on_stream_error=None):
        if self.fail:
            return None
        self.callback = callback
        self.subscription = FakeSubscription()
        return self.subscription


class FakeLease:
    def __init__(self):
        self.acquires = []
        self.releases = []
        self.held = False

    def acquire(self, config, reason="recording"):
        self.acquires.append(reason)
        self.held = True
        return {"held": True}

    def release(self, reason="stop"):
        self.releases.append(reason)
        self.held = False
        return {"held": False}


def build_recorder(broker=None, lease=None):
    return recorder_mod.AudioRecorder(
        broker=broker if broker is not None else FakeBroker(),
        privacy_lease=lease if lease is not None else FakeLease(),
    )


def chunk(value=0.5, frames=160):
    return np.full(frames, value, dtype=np.float32)


class PrependAudioTests(unittest.TestCase):
    """The recorder's missing "prepend this audio" entry point (D-0025)."""

    def setUp(self):
        self.broker = FakeBroker()
        self.recorder = build_recorder(broker=self.broker)
        patcher = mock.patch.object(recorder_mod, "load_profile", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_pre_roll_lands_before_the_first_live_chunk(self):
        pre_roll = chunk(0.1, frames=320)
        self.recorder.start_recording("Default", reason="wake_word", prepend_audio=pre_roll)
        self.broker.callback(chunk(0.9), 16000)
        result = self.recorder.stop_recording()

        self.assertEqual(result.sample_count, 320 + 160)
        # The pre-roll is the head of the clip, in order.
        np.testing.assert_allclose(result.audio_data[:320], pre_roll)
        self.assertAlmostEqual(float(result.audio_data[320]), 0.9)

    def test_no_pre_roll_records_exactly_what_was_captured(self):
        self.recorder.start_recording("Default")
        self.broker.callback(chunk(0.9), 16000)
        self.assertEqual(self.recorder.stop_recording().sample_count, 160)

    def test_an_empty_pre_roll_changes_nothing(self):
        self.recorder.start_recording(
            "Default", reason="wake_word", prepend_audio=np.array([], dtype=np.float32)
        )
        self.broker.callback(chunk(), 16000)
        self.assertEqual(self.recorder.stop_recording().sample_count, 160)

    def test_a_malformed_pre_roll_is_dropped_rather_than_failing_the_recording(self):
        # Losing the first word is bad; losing the whole command is worse.
        self.recorder.start_recording("Default", reason="wake_word", prepend_audio="not audio")
        self.assertTrue(self.recorder.recording)
        self.broker.callback(chunk(), 16000)
        self.assertEqual(self.recorder.stop_recording().sample_count, 160)

    def test_the_late_prepend_method_inserts_at_the_head(self):
        self.recorder.start_recording("Default", reason="wake_word")
        self.broker.callback(chunk(0.9), 16000)
        self.assertEqual(self.recorder.prepend_audio(chunk(0.1, frames=80)), 80)
        result = self.recorder.stop_recording()
        self.assertAlmostEqual(float(result.audio_data[0]), 0.1)
        self.assertEqual(result.sample_count, 240)

    def test_prepending_to_a_stopped_recorder_is_dropped_not_buffered(self):
        # Audio handed to a stopped recorder must never leak into the next clip.
        self.assertEqual(self.recorder.prepend_audio(chunk()), 0)
        self.recorder.start_recording("Default")
        self.assertEqual(self.recorder.stop_recording().sample_count, 0)

    def test_a_failed_start_leaves_no_pre_roll_behind(self):
        rec = build_recorder(broker=FakeBroker(fail=True))
        rec.start_recording("Default", reason="wake_word", prepend_audio=chunk())
        self.assertFalse(rec.recording)
        self.assertEqual(rec.frames, [])


class CommandCaptureTests(unittest.TestCase):
    """A wake-started recording has no key release, so it must end itself."""

    def setUp(self):
        self.broker = FakeBroker()
        self.recorder = build_recorder(broker=self.broker)

    def _start(self, config, reason):
        with mock.patch.object(recorder_mod, "load_profile", return_value=config):
            self.recorder.start_recording("Default", reason=reason)

    def test_a_wake_start_always_gets_a_detector_even_with_auto_stop_off(self):
        self._start({"auto_stop_after_silence_enabled": False}, "wake_word")
        self.assertIsNotNone(self.recorder._auto_stop_detector)

    def test_a_keyboard_start_still_honors_the_auto_stop_setting(self):
        self._start({"auto_stop_after_silence_enabled": False}, "keyboard_ptt")
        self.assertIsNone(self.recorder._auto_stop_detector)

    def test_a_keyboard_start_with_auto_stop_on_gets_a_detector(self):
        self._start({"auto_stop_after_silence_enabled": True}, "keyboard_ptt")
        self.assertIsNotNone(self.recorder._auto_stop_detector)

    def test_the_wake_detector_uses_the_command_capture_timings(self):
        self._start({}, "wake_word")
        detector = self.recorder._auto_stop_detector
        self.assertEqual(detector.silence_ms, wake_pretrigger.DEFAULT_COMMAND_SILENCE_MS)
        self.assertEqual(detector.min_recording_ms, wake_pretrigger.DEFAULT_COMMAND_MIN_MS)

    def test_command_capture_reuses_the_profile_silence_thresholds(self):
        # One notion of "silence" to tune, not two.
        self._start({"no_audio_min_rms": 0.02, "no_audio_min_peak": 0.09}, "wake_word")
        detector = self.recorder._auto_stop_detector
        self.assertAlmostEqual(detector.rms_threshold, 0.02)
        self.assertAlmostEqual(detector.peak_threshold, 0.09)


class PrivacyLeaseLifecycleTests(unittest.TestCase):
    """Every stop path releases. That is the whole requirement."""

    def setUp(self):
        self.lease = FakeLease()
        self.broker = FakeBroker()
        self.recorder = build_recorder(broker=self.broker, lease=self.lease)
        patcher = mock.patch.object(recorder_mod, "load_profile", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_starting_acquires_with_the_start_reason(self):
        self.recorder.start_recording("Default", reason="wake_word")
        self.assertEqual(self.lease.acquires, ["wake_word"])

    def test_a_normal_stop_releases(self):
        self.recorder.start_recording("Default")
        self.recorder.stop_recording("manual")
        self.assertEqual(self.lease.releases, ["manual"])

    def test_trailing_silence_auto_stop_releases(self):
        self.recorder.start_recording("Default")
        self.recorder.stop_recording("trailing_silence")
        self.assertEqual(self.lease.releases, ["trailing_silence"])

    def test_the_watchdog_force_stop_releases(self):
        self.recorder.start_recording("Default")
        self.recorder.stop_recording("watchdog_timeout")
        self.assertEqual(self.lease.releases, ["watchdog_timeout"])

    def test_a_recorder_that_could_not_start_releases_immediately(self):
        rec = recorder_mod.AudioRecorder(broker=FakeBroker(fail=True), privacy_lease=self.lease)
        rec.start_recording("Default")
        self.assertEqual(self.lease.acquires, ["manual"])
        self.assertEqual(self.lease.releases, ["recorder_failed"])

    def test_stopping_when_not_recording_still_releases(self):
        # Emergency stop and the privacy wipe both drain the recorder without
        # knowing whether it was running.
        self.recorder.stop_recording("emergency_stop")
        self.assertEqual(self.lease.releases, ["emergency_stop"])

    def test_privacy_is_engaged_before_the_stream_opens(self):
        order = []
        self.lease.acquire = lambda config, reason="recording": order.append("acquire")
        original = self.broker.subscribe

        def tracking(*args, **kwargs):
            order.append("subscribe")
            return original(*args, **kwargs)

        self.broker.subscribe = tracking
        self.recorder.start_recording("Default")
        self.assertEqual(order, ["acquire", "subscribe"])

    def test_a_lease_that_raises_never_breaks_a_recording(self):
        boom = mock.Mock()
        boom.acquire.side_effect = RuntimeError("no mixer")
        boom.release.side_effect = RuntimeError("no mixer")
        rec = build_recorder(broker=FakeBroker(), lease=boom)
        rec.start_recording("Default")
        self.assertTrue(rec.recording)
        self.assertEqual(rec.stop_recording().stop_reason, "manual")


class WakeListenerObserverTests(unittest.TestCase):
    def _listener(self):
        service = mock.Mock()
        service.process_chunk.return_value = False
        return wake_word.WakeListener(service), service

    def test_chunks_reach_the_observer_before_they_are_scored(self):
        # The pre-roll must include the audio a detection is about to fire on.
        listener, service = self._listener()
        order = []
        listener.chunk_observer = lambda c, sr=None: order.append("observe")
        service.process_chunk.side_effect = lambda *a, **k: order.append("score")

        listener._on_chunk(chunk(), 16000)
        self.assertEqual(order, ["observe", "score"])

    def test_no_observer_is_the_wave_8a_behavior(self):
        listener, service = self._listener()
        listener._on_chunk(chunk(), 16000)
        service.process_chunk.assert_called_once()

    def test_a_failing_observer_never_stops_wake_detection(self):
        listener, service = self._listener()
        listener.chunk_observer = mock.Mock(side_effect=RuntimeError("ring broke"))
        listener._on_chunk(chunk(), 16000)
        service.process_chunk.assert_called_once()


class RoutesWakeHandoffTests(unittest.TestCase):
    """arm on enable, feed while listening, activate on detection, wipe on
    disable — the four calls D-0025 listed as not landed."""

    def setUp(self):
        import routes_wake

        self.routes_wake = routes_wake
        routes_wake._handoff = None
        self.addCleanup(setattr, routes_wake, "_handoff", None)

    def test_the_handoff_is_a_process_singleton(self):
        self.assertIs(self.routes_wake.get_wake_handoff(), self.routes_wake.get_wake_handoff())

    def test_the_observer_feeds_the_ring_while_armed(self):
        handoff = self.routes_wake.get_wake_handoff()
        handoff.arm()
        observe = self.routes_wake._build_chunk_observer(handoff)
        observe(chunk(frames=320), 16000)
        self.assertEqual(handoff.ring.frame_count(), 320)

    def test_the_ring_is_not_fed_while_the_recorder_owns_the_stream(self):
        handoff = self.routes_wake.get_wake_handoff()
        handoff.arm()
        handoff.activate()                       # a detection disarmed it
        observe = self.routes_wake._build_chunk_observer(handoff)

        with mock.patch.object(self.routes_wake, "_recording_in_progress", return_value=True):
            observe(chunk(), 16000)
        self.assertFalse(handoff.is_armed())
        self.assertEqual(handoff.ring.frame_count(), 0)

    def test_the_ring_re_arms_once_the_command_recording_is_over(self):
        # Otherwise the NEXT wake loses its first word.
        handoff = self.routes_wake.get_wake_handoff()
        handoff.arm()
        handoff.activate()
        observe = self.routes_wake._build_chunk_observer(handoff)

        with mock.patch.object(self.routes_wake, "_recording_in_progress", return_value=False):
            observe(chunk(frames=160), 16000)
        self.assertTrue(handoff.is_armed())
        self.assertEqual(handoff.ring.frame_count(), 160)

    def test_activate_hands_over_the_pre_roll_and_wipes_the_ring(self):
        handoff = self.routes_wake.get_wake_handoff()
        handoff.arm()
        handoff.on_chunk(chunk(0.4, frames=240), 16000)

        audio = handoff.activate()
        self.assertEqual(int(audio.size), 240)
        self.assertEqual(handoff.ring.frame_count(), 0)

    def test_wiping_the_pretrigger_drops_retained_audio(self):
        handoff = self.routes_wake.get_wake_handoff()
        handoff.arm()
        handoff.on_chunk(chunk(frames=160), 16000)

        self.assertTrue(self.routes_wake.wipe_wake_pretrigger())
        self.assertEqual(handoff.ring.frame_count(), 0)
        self.assertFalse(handoff.is_armed())

    def test_wiping_before_wake_was_ever_enabled_is_safe(self):
        self.assertFalse(self.routes_wake.wipe_wake_pretrigger())

    def test_stopping_the_listener_clears_the_observer_and_wipes_the_ring(self):
        handoff = self.routes_wake.get_wake_handoff()
        handoff.arm()
        handoff.on_chunk(chunk(frames=160), 16000)

        listener = mock.Mock()
        self.routes_wake._listener = listener
        self.routes_wake.stop_wake_listener()

        self.assertIsNone(listener.chunk_observer)
        listener.stop.assert_called_once()
        self.assertEqual(handoff.ring.frame_count(), 0)
        self.assertFalse(handoff.is_armed())

    def test_recording_in_progress_is_false_when_no_manager_exists(self):
        with mock.patch.dict(sys.modules, {"server": mock.Mock(hotkey_manager=None)}):
            self.assertFalse(self.routes_wake._recording_in_progress())


class HotkeyManagerThreadingTests(unittest.TestCase):
    """The reason and the pre-roll have to survive the trip to the recorder."""

    def _manager(self):
        import hotkey_manager

        manager = hotkey_manager.HotkeyManager.__new__(hotkey_manager.HotkeyManager)
        manager.recorder = mock.Mock()
        manager.recorder.recording = True
        manager.is_recording = False
        manager.is_busy_callback = None
        manager.on_start_ui = None
        manager.on_force_stop = None
        manager.current_profile = "Default"
        manager.recording_start_time = 0.0
        manager.last_stop_reason = "manual"
        manager.max_recording_seconds = 0
        manager._watchdog_timer = None
        import threading

        manager.state_lock = threading.Lock()
        return manager

    def test_the_wake_reason_and_pre_roll_reach_start_recording(self):
        manager = self._manager()
        audio = chunk(frames=320)
        manager.request_start(reason="wake_word", prepend_audio=audio)

        manager.recorder.start_recording.assert_called_once()
        _args, kwargs = manager.recorder.start_recording.call_args
        self.assertEqual(kwargs["reason"], "wake_word")
        np.testing.assert_allclose(kwargs["prepend_audio"], audio)

    def test_an_ordinary_start_passes_its_own_reason_and_no_pre_roll(self):
        manager = self._manager()
        manager.request_start(reason="keyboard_ptt")
        _args, kwargs = manager.recorder.start_recording.call_args
        self.assertEqual(kwargs["reason"], "keyboard_ptt")
        self.assertIsNone(kwargs["prepend_audio"])


if __name__ == "__main__":
    unittest.main()
