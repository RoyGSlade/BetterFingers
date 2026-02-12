import signal
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from llm_engine import LLMEngine


class LLMEngineShutdownTrackingTests(unittest.TestCase):
    def setUp(self):
        self._ready = LLMEngine._ready
        self._process = LLMEngine._process
        self._process_pid = LLMEngine._process_pid
        self._owns_process = LLMEngine._owns_process

    def tearDown(self):
        LLMEngine._ready = self._ready
        LLMEngine._process = self._process
        LLMEngine._process_pid = self._process_pid
        LLMEngine._owns_process = self._owns_process

    @staticmethod
    def _new_engine():
        engine = LLMEngine.__new__(LLMEngine)
        engine.port = 8080
        engine.api_url = "http://127.0.0.1:8080"
        return engine

    def test_setup_server_tracks_pid_when_reusing_existing_server(self):
        engine = self._new_engine()
        LLMEngine._ready = False
        LLMEngine._process_pid = None

        with patch("llm_engine.is_server_running", return_value=True), patch(
            "llm_engine._find_server_pid_on_port", return_value=4242
        ), patch.object(engine, "_start_server") as start_mock:
            engine._setup_server()

        self.assertTrue(LLMEngine._ready)
        self.assertEqual(LLMEngine._process_pid, 4242)
        self.assertFalse(LLMEngine._owns_process)
        start_mock.assert_not_called()

    def test_shutdown_infers_pid_and_attempts_kill_when_untracked(self):
        engine = self._new_engine()
        LLMEngine._ready = True
        LLMEngine._process = None
        LLMEngine._process_pid = None
        LLMEngine._owns_process = True

        with patch("llm_engine.is_server_running", return_value=True), patch(
            "llm_engine._find_server_pid_on_port", return_value=4242
        ), patch("llm_engine.os.kill") as kill_mock, patch(
            "llm_engine.subprocess.run", return_value=SimpleNamespace(stdout="SUCCESS", stderr="")
        ):
            engine.shutdown()

        kill_mock.assert_called_once_with(4242, signal.SIGTERM)
        self.assertFalse(LLMEngine._ready)
        self.assertIsNone(LLMEngine._process_pid)
        self.assertFalse(LLMEngine._owns_process)

    def test_shutdown_does_not_kill_external_server_when_not_owned(self):
        engine = self._new_engine()
        LLMEngine._ready = True
        LLMEngine._process = None
        LLMEngine._process_pid = 4242
        LLMEngine._owns_process = False

        with patch("llm_engine.os.kill") as kill_mock, patch("llm_engine.subprocess.run") as run_mock:
            engine.shutdown()

        kill_mock.assert_not_called()
        run_mock.assert_not_called()
        self.assertFalse(LLMEngine._ready)
        self.assertIsNone(LLMEngine._process_pid)
        self.assertFalse(LLMEngine._owns_process)


if __name__ == "__main__":
    unittest.main()
