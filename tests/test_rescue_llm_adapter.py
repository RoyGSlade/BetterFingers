"""Focused tests for backend.services.rescue_llm_adapter (I3.2).

No network access: `requests.post` is monkeypatched throughout. Verifies the
adapter is a faithful `list[dict] -> str` call_fn boundary for
backend.services.message_rescue.rescue_message, including its timeout
contract (a requests timeout must surface as a plain TimeoutError so
rescue_message's own `_looks_like_timeout` check takes the graceful branch).
"""

import unittest
from unittest.mock import patch

import requests

from backend.services.rescue_llm_adapter import build_llm_call_fn, compute_read_timeout_s


class _FakeEngine:
    api_url = "http://127.0.0.1:8080"


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"choices": [{"message": {"content": "hello"}}]}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class ComputeReadTimeoutTests(unittest.TestCase):
    def test_scales_with_tokens_within_bounds(self):
        low = compute_read_timeout_s(1)
        high = compute_read_timeout_s(4096)
        self.assertGreaterEqual(low, 45.0)
        self.assertLessEqual(high, 180.0)
        self.assertLess(low, high)

    def test_non_numeric_falls_back_to_default(self):
        self.assertGreater(compute_read_timeout_s("not-a-number"), 0)
        self.assertGreater(compute_read_timeout_s(None), 0)


class BuildLlmCallFnTests(unittest.TestCase):
    def test_success_returns_content_string(self):
        call_fn = build_llm_call_fn(_FakeEngine())
        with patch("backend.services.rescue_llm_adapter.requests.post", return_value=_FakeResponse()) as mock_post:
            result = call_fn([{"role": "user", "content": "hi"}])
        self.assertEqual(result, "hello")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(kwargs["json"]["stream"], False)
        self.assertIsInstance(kwargs["timeout"], tuple)
        self.assertEqual(len(kwargs["timeout"]), 2)

    def test_timeout_raised_as_plain_timeout_error(self):
        call_fn = build_llm_call_fn(_FakeEngine())
        with patch(
            "backend.services.rescue_llm_adapter.requests.post",
            side_effect=requests.exceptions.Timeout("read timed out"),
        ):
            with self.assertRaises(TimeoutError):
                call_fn([{"role": "user", "content": "hi"}])

    def test_http_error_status_propagates(self):
        call_fn = build_llm_call_fn(_FakeEngine())
        with patch(
            "backend.services.rescue_llm_adapter.requests.post",
            return_value=_FakeResponse(status_code=500),
        ):
            with self.assertRaises(requests.exceptions.HTTPError):
                call_fn([{"role": "user", "content": "hi"}])

    def test_max_output_tokens_clamped_into_valid_range(self):
        # Absurd inputs must not produce an out-of-range max_tokens payload.
        call_fn_low = build_llm_call_fn(_FakeEngine(), max_output_tokens=1)
        call_fn_high = build_llm_call_fn(_FakeEngine(), max_output_tokens=999999)
        with patch("backend.services.rescue_llm_adapter.requests.post", return_value=_FakeResponse()) as mock_post:
            call_fn_low([{"role": "user", "content": "hi"}])
            low_tokens = mock_post.call_args.kwargs["json"]["max_tokens"]
            call_fn_high([{"role": "user", "content": "hi"}])
            high_tokens = mock_post.call_args.kwargs["json"]["max_tokens"]
        self.assertGreaterEqual(low_tokens, 64)
        self.assertLessEqual(high_tokens, 4096)

    def test_module_never_imports_logging(self):
        import re

        import backend.services.rescue_llm_adapter as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("import logging", source)
        self.assertIsNone(re.search(r"\blogging\.\w+\(", source))


if __name__ == "__main__":
    unittest.main()
