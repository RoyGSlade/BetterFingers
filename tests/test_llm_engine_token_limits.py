import unittest
from unittest.mock import Mock, patch

from llm_engine import LLMEngine


class LLMEngineTokenLimitTests(unittest.TestCase):
    def _engine(self):
        engine = LLMEngine.__new__(LLMEngine)
        engine.api_url = "http://127.0.0.1:8080"
        return engine

    @patch("llm_engine.requests.post")
    def test_call_api_uses_explicit_max_output_tokens(self, post_mock):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        post_mock.return_value = fake_response

        engine = self._engine()
        result = engine._call_api("hello", "prompt", max_output_tokens=777)

        self.assertEqual(result, "ok")
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["max_tokens"], 777)

    @patch("llm_engine.requests.post")
    def test_call_api_clamps_small_max_tokens(self, post_mock):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        post_mock.return_value = fake_response

        engine = self._engine()
        engine._call_api("hello", "prompt", max_output_tokens=1)

        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["max_tokens"], 64)


if __name__ == "__main__":
    unittest.main()
