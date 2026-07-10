import unittest

from wake_word import FakeWakeDetector, WakeWordService


class WakeWordServiceTests(unittest.TestCase):
    def _service(self, scores=None, **kwargs):
        detector = FakeWakeDetector(scores=scores)
        calls = []
        service = WakeWordService(detector, on_detect=lambda: calls.append(1), **kwargs)
        return service, calls

    def test_below_threshold_does_not_trigger(self):
        service, calls = self._service(scores=[0.2], threshold=0.55)
        triggered = service.process_chunk(None, 16000, now=0.0)
        self.assertFalse(triggered)
        self.assertEqual(calls, [])

    def test_at_or_above_threshold_triggers(self):
        service, calls = self._service(scores=[0.9], threshold=0.55)
        triggered = service.process_chunk(None, 16000, now=0.0)
        self.assertTrue(triggered)
        self.assertEqual(calls, [1])

    def test_cooldown_blocks_repeat_trigger(self):
        service, calls = self._service(scores=[0.9, 0.9], threshold=0.55, cooldown_ms=2500)
        self.assertTrue(service.process_chunk(None, 16000, now=0.0))
        self.assertFalse(service.process_chunk(None, 16000, now=1.0))
        self.assertEqual(calls, [1])

    def test_trigger_allowed_again_after_cooldown_elapses(self):
        service, calls = self._service(scores=[0.9, 0.9], threshold=0.55, cooldown_ms=2500)
        self.assertTrue(service.process_chunk(None, 16000, now=0.0))
        self.assertTrue(service.process_chunk(None, 16000, now=3.0))
        self.assertEqual(calls, [1, 1])

    def test_requires_vad_blocks_trigger_without_speech(self):
        service, calls = self._service(scores=[0.9], threshold=0.55, requires_vad=True)
        triggered = service.process_chunk(None, 16000, has_speech=False, now=0.0)
        self.assertFalse(triggered)
        self.assertEqual(calls, [])

    def test_requires_vad_false_ignores_speech_flag(self):
        service, calls = self._service(scores=[0.9], threshold=0.55, requires_vad=False)
        triggered = service.process_chunk(None, 16000, has_speech=False, now=0.0)
        self.assertTrue(triggered)
        self.assertEqual(calls, [1])

    def test_score_log_records_every_chunk(self):
        service, _ = self._service(scores=[0.1, 0.9], threshold=0.55)
        service.process_chunk(None, 16000, now=0.0)
        service.process_chunk(None, 16000, now=1.0)
        self.assertEqual(len(service.score_log), 2)
        self.assertFalse(service.score_log[0]["triggered"])
        self.assertTrue(service.score_log[1]["triggered"])

    def test_status_reports_config_and_recent_scores(self):
        service, _ = self._service(scores=[0.9], threshold=0.55, cooldown_ms=2500)
        service.process_chunk(None, 16000, now=0.0)
        status = service.status(now=1.0)
        self.assertEqual(status["threshold"], 0.55)
        self.assertEqual(status["cooldown_ms"], 2500)
        self.assertTrue(status["in_cooldown"])
        self.assertEqual(len(status["recent_scores"]), 1)

    def test_no_scores_queued_defaults_to_zero_never_triggers(self):
        service, calls = self._service(scores=[], threshold=0.55)
        triggered = service.process_chunk(None, 16000, now=0.0)
        self.assertFalse(triggered)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
