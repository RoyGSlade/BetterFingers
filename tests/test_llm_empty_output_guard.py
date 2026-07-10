"""Empty-completion guard for LLM cleanup (persona-lane data-loss fix).

Sibling of the read-timeout bug (see test_api_timeout.py). `_call_api` returned
the model's completion verbatim, so an empty completion ("") for real speech was
handed straight back. On the main dictation path (server.py) there is *no* raw
fallback, so that empty string became the draft and got injected — the user's
dictation silently vanished. llama-server genuinely emits "" when its slot is
still churning (observed live after a prior request timed out).

The guard: an empty/whitespace completion for non-empty input falls back to the
raw text. Falling back to raw is never worse than raw; emitting empty is data loss.
"""

import unittest
from unittest.mock import Mock, patch

from llm_engine import LLMEngine


class CallApiEmptyOutputGuardTests(unittest.TestCase):
    def _engine(self):
        engine = LLMEngine.__new__(LLMEngine)
        engine.api_url = "http://127.0.0.1:8080"
        return engine

    def _post_returning(self, content):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"choices": [{"message": {"content": content}}]}
        return fake_response

    @patch("llm_engine.requests.post")
    def test_empty_completion_falls_back_to_raw(self, post_mock):
        post_mock.return_value = self._post_returning("")
        engine = self._engine()
        raw = "i wanted to talk about the timeline"
        self.assertEqual(engine._call_api(raw, "prompt"), raw)

    @patch("llm_engine.requests.post")
    def test_whitespace_only_completion_falls_back_to_raw(self, post_mock):
        post_mock.return_value = self._post_returning("   \n\t ")
        engine = self._engine()
        raw = "some real words here"
        self.assertEqual(engine._call_api(raw, "prompt"), raw)

    @patch("llm_engine.requests.post")
    def test_normal_completion_passes_through(self, post_mock):
        post_mock.return_value = self._post_returning("  cleaned text.  ")
        engine = self._engine()
        # Real cleanup still wins and is stripped.
        self.assertEqual(engine._call_api("raw words", "prompt"), "cleaned text.")

    @patch("llm_engine.requests.post")
    def test_empty_input_with_empty_completion_stays_empty(self, post_mock):
        # No dictation to protect: an empty result for empty input is fine and must
        # NOT be replaced by the (also empty) input in a way that masks the guard.
        post_mock.return_value = self._post_returning("")
        engine = self._engine()
        self.assertEqual(engine._call_api("   ", "prompt"), "")

    @patch("llm_engine.requests.post")
    def test_transport_error_still_returns_raw(self, post_mock):
        # The pre-existing failure path must keep returning raw, not crash.
        post_mock.side_effect = RuntimeError("connection refused")
        engine = self._engine()
        raw = "keep my words"
        self.assertEqual(engine._call_api(raw, "prompt"), raw)


if __name__ == "__main__":
    unittest.main()
