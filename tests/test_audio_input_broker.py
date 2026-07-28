"""Wave 8A package B: exactly one owner of the microphone.

Every stream here is a stub built through the broker's injectable
``stream_factory`` — no test in this file opens a real audio device.
"""

import sys
import threading
import unittest

import audio_input_broker
from audio_input_broker import AudioInputBroker


class FakeBuffer(list):
    """Stands in for the ndarray sounddevice hands the callback.

    Deliberately stdlib-only: the broker never imports numpy (it only calls
    ``.copy()`` on whatever the stream delivers), so these tests run in a bare
    interpreter as well as in the project venv.
    """

    def copy(self):
        return FakeBuffer(list(self))


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.device = kwargs.get("device")
        self.callback = kwargs.get("callback")
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        self.started = False

    def close(self):
        self.closed = True

    def emit(self, chunk):
        self.callback(chunk, len(chunk), None, None)


class FakeFactory:
    """Records every open attempt; ``fail_devices`` raise instead of opening."""

    def __init__(self, fail_devices=()):
        self.fail_devices = set(fail_devices)
        self.attempts = []
        self.streams = []

    def __call__(self, **kwargs):
        device = kwargs.get("device")
        self.attempts.append(device)
        if device in self.fail_devices:
            raise RuntimeError(f"device {device} busy")
        stream = FakeStream(**kwargs)
        self.streams.append(stream)
        return stream

    @property
    def live(self):
        return [s for s in self.streams if not s.closed]


def chunk(value=0.5, frames=1280):
    return FakeBuffer([[value]] * frames)


class BrokerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.factory = FakeFactory()
        self.broker = AudioInputBroker(stream_factory=self.factory)

    def test_closed_until_the_first_subscriber(self):
        self.assertFalse(self.broker.is_open())
        self.assertEqual(self.factory.attempts, [])

    def test_first_subscribe_opens_and_starts_one_stream(self):
        sub = self.broker.subscribe("wake", lambda c, sr: None)
        self.assertIsNotNone(sub)
        self.assertTrue(self.broker.is_open())
        self.assertEqual(len(self.factory.streams), 1)
        self.assertTrue(self.factory.streams[0].started)

    def test_second_subscriber_reuses_the_same_stream(self):
        self.broker.subscribe("wake", lambda c, sr: None)
        self.broker.subscribe("recorder", lambda c, sr: None)
        self.assertEqual(len(self.factory.streams), 1)
        self.assertEqual(self.broker.subscriber_names(), ["wake", "recorder"])

    def test_device_is_released_only_when_the_last_subscriber_leaves(self):
        wake = self.broker.subscribe("wake", lambda c, sr: None)
        recorder = self.broker.subscribe("recorder", lambda c, sr: None)

        wake.close()
        self.assertTrue(self.broker.is_open(), "a live recording must keep the mic open")
        self.assertFalse(self.factory.streams[0].closed)

        recorder.close()
        self.assertFalse(self.broker.is_open())
        self.assertTrue(self.factory.streams[0].closed)

    def test_disabling_the_only_holder_releases_the_device(self):
        # The wake-word case from the objective: nothing else holds it, so
        # disabling wake must fully close the stream, not merely pause it.
        wake = self.broker.subscribe("wake", lambda c, sr: None)
        wake.close()
        self.assertFalse(self.broker.is_open())
        self.assertTrue(self.factory.streams[0].closed)
        self.assertEqual(self.broker.subscriber_names(), [])

    def test_close_is_idempotent(self):
        wake = self.broker.subscribe("wake", lambda c, sr: None)
        self.assertTrue(wake.close())
        self.assertFalse(wake.close())
        self.assertFalse(wake.active)

    def test_reopen_after_full_release(self):
        self.broker.subscribe("wake", lambda c, sr: None).close()
        self.broker.subscribe("recorder", lambda c, sr: None)
        self.assertEqual(len(self.factory.streams), 2)
        self.assertTrue(self.broker.is_open())

    def test_stop_all_drops_everyone_and_closes(self):
        self.broker.subscribe("wake", lambda c, sr: None)
        self.broker.subscribe("recorder", lambda c, sr: None)
        dropped = self.broker.stop_all()
        self.assertEqual(dropped, 2)
        self.assertFalse(self.broker.is_open())
        self.assertEqual(self.broker.subscriber_names(), [])
        self.assertTrue(self.factory.streams[0].closed)

    def test_stop_all_is_safe_when_nothing_was_ever_opened(self):
        self.assertEqual(self.broker.stop_all(), 0)
        self.assertFalse(self.broker.is_open())

    def test_a_subscription_closed_after_stop_all_does_not_reclose(self):
        sub = self.broker.subscribe("wake", lambda c, sr: None)
        self.broker.stop_all()
        self.assertFalse(sub.close())


class BrokerFormatTests(unittest.TestCase):
    def test_stream_opens_with_the_shared_capture_format(self):
        factory = FakeFactory()
        broker = AudioInputBroker(stream_factory=factory)
        broker.subscribe("wake", lambda c, sr: None)
        kwargs = factory.streams[0].kwargs
        self.assertEqual(kwargs["samplerate"], 16000)
        self.assertEqual(kwargs["channels"], 1)
        self.assertEqual(kwargs["dtype"], "float32")
        self.assertEqual(kwargs["blocksize"], 1280)


class BrokerDeviceTests(unittest.TestCase):
    def setUp(self):
        self.factory = FakeFactory()
        self.broker = AudioInputBroker(stream_factory=self.factory)

    def test_no_preference_opens_the_system_default(self):
        self.broker.subscribe("wake", lambda c, sr: None)
        self.assertEqual(self.factory.attempts, [None])
        self.assertIsNone(self.broker.device())

    def test_explicit_preference_is_honored(self):
        self.broker.subscribe("recorder", lambda c, sr: None, device=3)
        self.assertEqual(self.factory.attempts, [3])
        self.assertEqual(self.broker.device(), 3)

    def test_failed_device_falls_back_to_the_system_default(self):
        factory = FakeFactory(fail_devices={5})
        broker = AudioInputBroker(stream_factory=factory)
        sub = broker.subscribe("recorder", lambda c, sr: None, device=5)
        self.assertIsNotNone(sub)
        self.assertEqual(factory.attempts, [5, None])
        self.assertIsNone(broker.device())
        self.assertTrue(broker.status()["fell_back_to_default"])

    def test_fallback_can_be_refused(self):
        factory = FakeFactory(fail_devices={5})
        broker = AudioInputBroker(stream_factory=factory)
        sub = broker.subscribe("recorder", lambda c, sr: None, device=5, allow_default_fallback=False)
        self.assertIsNone(sub)
        self.assertEqual(factory.attempts, [5])

    def test_total_open_failure_returns_none_and_leaves_nobody_registered(self):
        factory = FakeFactory(fail_devices={5, None})
        broker = AudioInputBroker(stream_factory=factory)
        sub = broker.subscribe("recorder", lambda c, sr: None, device=5)
        self.assertIsNone(sub)
        self.assertFalse(broker.is_open())
        self.assertEqual(broker.subscriber_names(), [])
        self.assertIn("device_open_failed", broker.status()["last_error"])

    def test_open_failure_calls_the_subscribers_error_handler(self):
        factory = FakeFactory(fail_devices={None})
        broker = AudioInputBroker(stream_factory=factory)
        seen = []
        broker.subscribe("wake", lambda c, sr: None, on_stream_error=seen.append)
        self.assertEqual(len(seen), 1)
        self.assertIn("device_open_failed", seen[0])

    def test_no_preference_subscriber_does_not_disturb_an_open_device(self):
        self.broker.subscribe("recorder", lambda c, sr: None, device=3)
        self.broker.subscribe("meter", lambda c, sr: None)
        self.assertEqual(self.factory.attempts, [3])
        self.assertEqual(self.broker.device(), 3)

    def test_matching_preference_does_not_reopen(self):
        self.broker.subscribe("wake", lambda c, sr: None, device=3)
        self.broker.subscribe("recorder", lambda c, sr: None, device=3)
        self.assertEqual(self.factory.attempts, [3])

    def test_a_new_explicit_preference_reopens_under_live_subscribers(self):
        wake = self.broker.subscribe("wake", lambda c, sr: None, device=3)
        self.broker.subscribe("recorder", lambda c, sr: None, device=7)
        self.assertEqual(self.factory.attempts, [3, 7])
        self.assertEqual(self.broker.device(), 7)
        self.assertTrue(self.factory.streams[0].closed)
        self.assertTrue(wake.active, "the existing subscriber keeps listening across the switch")
        self.assertEqual(self.broker.subscriber_names(), ["wake", "recorder"])

    def test_set_device_switches_under_live_subscribers(self):
        self.broker.subscribe("wake", lambda c, sr: None)
        self.assertTrue(self.broker.set_device(4))
        self.assertEqual(self.factory.attempts, [None, 4])
        self.assertEqual(self.broker.device(), 4)

    def test_set_device_to_the_open_device_is_a_noop(self):
        self.broker.subscribe("wake", lambda c, sr: None, device=2)
        self.assertTrue(self.broker.set_device(2))
        self.assertEqual(self.factory.attempts, [2])

    def test_set_device_with_no_subscribers_only_records_the_preference(self):
        self.assertTrue(self.broker.set_device(6))
        self.assertEqual(self.factory.attempts, [])
        self.assertEqual(self.broker.device(), 6)
        self.broker.subscribe("wake", lambda c, sr: None)
        self.assertEqual(self.factory.attempts, [6])

    def test_a_failed_switch_restores_the_previously_working_device(self):
        factory = FakeFactory(fail_devices={9})
        broker = AudioInputBroker(stream_factory=factory)
        broker.subscribe("wake", lambda c, sr: None, device=2)
        self.assertFalse(broker.set_device(9, allow_default_fallback=False))
        self.assertEqual(factory.attempts, [2, 9, 2])
        self.assertTrue(broker.is_open())
        self.assertEqual(broker.device(), 2)
        self.assertIn("device_open_failed", broker.status()["last_error"])

    def test_a_failed_switch_still_delivers_audio_to_the_survivors(self):
        factory = FakeFactory(fail_devices={9})
        broker = AudioInputBroker(stream_factory=factory)
        got = []
        broker.subscribe("wake", lambda c, sr: got.append(c), device=2)
        broker.set_device(9, allow_default_fallback=False)
        factory.live[0].emit(chunk())
        self.assertEqual(len(got), 1)

    def test_a_failed_new_preference_does_not_strand_existing_subscribers(self):
        factory = FakeFactory(fail_devices={9, None})
        broker = AudioInputBroker(stream_factory=factory)
        got = []
        broker.subscribe("wake", lambda c, sr: got.append(c), device=2)
        self.assertIsNone(broker.subscribe("recorder", lambda c, sr: None, device=9))
        self.assertEqual(broker.subscriber_names(), ["wake"])
        self.assertTrue(broker.is_open())
        factory.live[0].emit(chunk())
        self.assertEqual(len(got), 1)

    def test_unrecoverable_switch_notifies_every_subscriber(self):
        factory = FakeFactory(fail_devices={9, 2, None})
        broker = AudioInputBroker(stream_factory=FakeFactory())
        # Open cleanly first, then swap in a factory where nothing opens.
        seen = []
        broker.subscribe("wake", lambda c, sr: None, device=2, on_stream_error=seen.append)
        broker.stream_factory = factory
        self.assertFalse(broker.set_device(9))
        self.assertFalse(broker.is_open())
        self.assertEqual(len(seen), 1)


class BrokerFanOutTests(unittest.TestCase):
    def setUp(self):
        self.factory = FakeFactory()
        self.broker = AudioInputBroker(stream_factory=self.factory)

    def _stream(self):
        return self.factory.streams[0]

    def test_every_subscriber_receives_the_chunk(self):
        a, b = [], []
        self.broker.subscribe("wake", lambda c, sr: a.append((c, sr)))
        self.broker.subscribe("meter", lambda c, sr: b.append((c, sr)))
        self._stream().emit(chunk(0.25))
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        self.assertEqual(a[0][1], 16000)
        self.assertAlmostEqual(float(a[0][0][0][0]), 0.25)

    def test_the_chunk_is_a_copy_not_the_reused_portaudio_buffer(self):
        got = []
        self.broker.subscribe("wake", lambda c, sr: got.append(c))
        buffer = chunk(0.5)
        self._stream().emit(buffer)
        buffer[:] = [[0.0]] * len(buffer)  # PortAudio reuses its buffer
        self.assertAlmostEqual(float(got[0][0][0]), 0.5)

    def test_a_raising_subscriber_does_not_starve_its_peers(self):
        got = []

        def boom(c, sr):
            raise RuntimeError("subscriber exploded")

        self.broker.subscribe("bad", boom)
        self.broker.subscribe("good", lambda c, sr: got.append(c))
        self._stream().emit(chunk())
        self._stream().emit(chunk())
        self.assertEqual(len(got), 2)
        self.assertEqual(self.broker.status()["callback_errors"], 2)

    def test_a_closed_subscriber_stops_receiving_audio(self):
        got = []
        sub = self.broker.subscribe("wake", lambda c, sr: got.append(c))
        self.broker.subscribe("recorder", lambda c, sr: None)
        sub.close()
        self._stream().emit(chunk())
        self.assertEqual(got, [])

    def test_callback_after_full_release_is_harmless(self):
        stream_callback = None
        got = []
        sub = self.broker.subscribe("wake", lambda c, sr: got.append(c))
        stream_callback = self._stream().callback
        sub.close()
        stream_callback(chunk(), 1280, None, None)  # a late in-flight callback
        self.assertEqual(got, [])

    def test_a_stream_status_flag_does_not_break_delivery(self):
        got = []
        self.broker.subscribe("wake", lambda c, sr: got.append(c))
        self._stream().callback(chunk(), 1280, "input overflow", None)
        self.assertEqual(len(got), 1)


class BrokerConcurrencyTests(unittest.TestCase):
    def test_closing_a_subscription_never_deadlocks_against_the_callback(self):
        # The audio callback must not take the broker lock: if it did, closing
        # a stream from another thread while a callback is in flight would
        # deadlock. Prove it by closing from inside the callback's thread while
        # the main thread holds the lock.
        factory = FakeFactory()
        broker = AudioInputBroker(stream_factory=factory)
        entered = threading.Event()
        release = threading.Event()

        def slow(c, sr):
            entered.set()
            release.wait(2.0)

        broker.subscribe("slow", slow)
        stream = factory.streams[0]
        worker = threading.Thread(target=lambda: stream.emit(chunk()), daemon=True)
        worker.start()
        self.assertTrue(entered.wait(2.0))

        done = threading.Event()

        def closer():
            broker.stop_all()
            done.set()

        closing = threading.Thread(target=closer, daemon=True)
        closing.start()
        self.assertTrue(done.wait(2.0), "stop_all() blocked on the audio callback")
        release.set()
        worker.join(2.0)


class BrokerStatusTests(unittest.TestCase):
    def test_status_reports_holders_and_device(self):
        factory = FakeFactory()
        broker = AudioInputBroker(stream_factory=factory)
        broker.subscribe("wake", lambda c, sr: None, device=2)
        status = broker.status()
        self.assertTrue(status["open"])
        self.assertEqual(status["device"], 2)
        self.assertEqual(status["subscribers"], ["wake"])
        self.assertEqual(status["subscriber_count"], 1)
        self.assertEqual(status["last_error"], "")
        self.assertEqual(status["sample_rate"], 16000)

    def test_status_of_an_idle_broker(self):
        status = AudioInputBroker(stream_factory=FakeFactory()).status()
        self.assertFalse(status["open"])
        self.assertEqual(status["subscriber_count"], 0)


class SingletonTests(unittest.TestCase):
    def tearDown(self):
        audio_input_broker.reset_broker_for_tests()

    def test_get_broker_returns_one_process_wide_owner(self):
        self.assertIs(audio_input_broker.get_broker(), audio_input_broker.get_broker())

    def test_reset_closes_whatever_the_singleton_held(self):
        factory = FakeFactory()
        broker = audio_input_broker.get_broker()
        broker.stream_factory = factory
        broker.subscribe("wake", lambda c, sr: None)
        audio_input_broker.reset_broker_for_tests()
        self.assertTrue(factory.streams[0].closed)
        self.assertIsNot(audio_input_broker.get_broker(), broker)


try:
    import sounddevice as _sd
except Exception:  # pragma: no cover - bare interpreter without PortAudio
    _sd = None


@unittest.skipIf(_sd is None, "sounddevice is not importable in this interpreter")
class DefaultStreamFactoryTests(unittest.TestCase):
    def test_it_resolves_sounddevice_at_call_time(self):
        # Guards the property every test in this repo depends on: patching
        # sounddevice.InputStream must reach the broker. sys.modules is pinned
        # to the real module for the duration because another test in a full
        # run may have left a MagicMock in sys.modules["sounddevice"] — the
        # factory's call-time import would resolve the leak, not our patch.
        from unittest.mock import patch

        sd = _sd
        with patch.dict(sys.modules, {"sounddevice": sd}), patch.object(sd, "InputStream", FakeStream):
            stream = audio_input_broker._DefaultStreamFactory()(
                samplerate=16000, device=None, channels=1, dtype="float32",
                blocksize=1280, callback=lambda *a: None,
            )
        self.assertIsInstance(stream, FakeStream)


if __name__ == "__main__":
    unittest.main()
