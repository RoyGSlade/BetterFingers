import unittest
from unittest.mock import patch

from llm_engine import LLMEngine


class LLMEngineReloadTests(unittest.TestCase):
    def setUp(self):
        self._ready = LLMEngine._ready
        self._process = LLMEngine._process

    def tearDown(self):
        LLMEngine._ready = self._ready
        LLMEngine._process = self._process

    def _new_engine(self):
        engine = LLMEngine.__new__(LLMEngine)
        engine.port = 8080
        engine.api_url = "http://127.0.0.1:8080"
        return engine

    def test_ensure_ready_restarts_when_not_ready(self):
        engine = self._new_engine()
        LLMEngine._ready = False

        def _mark_ready():
            LLMEngine._ready = True

        with patch("llm_engine.is_server_running", return_value=False), patch.object(
            engine, "_setup_server", side_effect=_mark_ready
        ) as setup_mock:
            self.assertTrue(engine.ensure_ready())
            setup_mock.assert_called_once()

    def test_process_fast_lane_calls_ensure_ready_after_shutdown(self):
        engine = self._new_engine()
        LLMEngine._ready = False

        with patch.object(engine, "ensure_ready", return_value=True) as ensure_mock, patch.object(
            engine, "_call_api", return_value="cleaned output"
        ):
            output = engine.process_fast_lane("hello world")
            self.assertEqual(output, "cleaned output")
            ensure_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
