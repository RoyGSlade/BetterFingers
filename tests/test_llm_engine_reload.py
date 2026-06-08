import tempfile
import unittest
from unittest.mock import Mock, patch

from llm_engine import LLMEngine


class LLMEngineReloadTests(unittest.TestCase):
    def setUp(self):
        self._ready = LLMEngine._ready
        self._process = LLMEngine._process
        self._process_pid = LLMEngine._process_pid
        self._owns_process = LLMEngine._owns_process
        self._initialized = LLMEngine._initialized
        self._stderr_log = LLMEngine._stderr_log
        self._last_error = LLMEngine._last_error
        self._last_error_details = LLMEngine._last_error_details

    def tearDown(self):
        LLMEngine._ready = self._ready
        LLMEngine._process = self._process
        LLMEngine._process_pid = self._process_pid
        LLMEngine._owns_process = self._owns_process
        LLMEngine._initialized = self._initialized
        LLMEngine._stderr_log = self._stderr_log
        LLMEngine._last_error = self._last_error
        LLMEngine._last_error_details = self._last_error_details

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

    def test_start_server_includes_gemma_4_server_args(self):
        engine = self._new_engine()
        engine.model_id = "gemma-4-e4b-q4"
        process = Mock()
        process.pid = 123

        with patch("llm_engine.os.path.exists", return_value=True), patch(
            "llm_engine.get_server_path", return_value="/tmp/llama-server"
        ), patch("llm_engine.get_model_path", return_value="/tmp/gemma-4.gguf"), patch(
            "llm_engine.subprocess.Popen", return_value=process
        ) as popen, patch.object(engine, "_wait_for_server"):
            engine._start_server()

        cmd = popen.call_args.args[0]
        self.assertIn("--jinja", cmd)
        self.assertIn("--chat-template-kwargs", cmd)
        self.assertIn('{"enable_thinking":false}', cmd)

    def test_wait_for_server_records_immediate_process_exit(self):
        engine = self._new_engine()
        process = Mock()
        process.poll.return_value = 127
        LLMEngine._process = process
        LLMEngine._ready = False
        LLMEngine._stderr_log = tempfile.TemporaryFile()
        LLMEngine._stderr_log.write(b"error while loading shared libraries: libmtmd.so.0")
        LLMEngine._stderr_log.seek(0)

        with patch("llm_engine.requests.get", side_effect=RuntimeError("not listening")), patch.object(
            engine, "shutdown"
        ) as shutdown_mock:
            engine._wait_for_server()

        self.assertIn("libmtmd.so.0", LLMEngine._last_error)
        self.assertEqual(LLMEngine._last_error_details["returncode"], 127)
        shutdown_mock.assert_called_once()

        LLMEngine._stderr_log.close()
        LLMEngine._stderr_log = None


if __name__ == "__main__":
    unittest.main()
