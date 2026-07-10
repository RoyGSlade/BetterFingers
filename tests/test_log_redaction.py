"""User-content redaction for logs (DESIGN §9.3).

By default, no raw dictated text / TTS phrase / prompt may reach a log line — only
a character-count summary. A developer can opt into raw logging via an env var.
"""

import unittest
from unittest.mock import patch

import log_redaction as lr


class RedactUserTextTests(unittest.TestCase):
    def test_default_redacts_content_but_keeps_length(self):
        with patch.dict("os.environ", {}, clear=False):
            # Ensure the opt-in is not set for this case.
            with patch.object(lr, "raw_text_logging_enabled", return_value=False):
                self.assertEqual(lr.redact_user_text("hello world"), "<redacted 11 chars>")

    def test_default_does_not_leak_any_substring(self):
        secret = "my bank pin is 4321"
        with patch.object(lr, "raw_text_logging_enabled", return_value=False):
            out = lr.redact_user_text(secret)
        self.assertNotIn("bank", out)
        self.assertNotIn("4321", out)
        self.assertIn(str(len(secret)), out)

    def test_empty_and_none_render_as_empty_marker(self):
        with patch.object(lr, "raw_text_logging_enabled", return_value=False):
            self.assertEqual(lr.redact_user_text(""), "<empty>")
            self.assertEqual(lr.redact_user_text(None), "<empty>")

    def test_opt_in_returns_raw_text(self):
        with patch.object(lr, "raw_text_logging_enabled", return_value=True):
            self.assertEqual(lr.redact_user_text("hello world"), "hello world")
            self.assertEqual(lr.redact_user_text(None), "")

    def test_env_var_controls_opt_in(self):
        for value, expected in [("1", True), ("true", True), ("ON", True), ("yes", True),
                                ("0", False), ("", False), ("nope", False)]:
            with patch.dict("os.environ", {"BETTERFINGERS_LOG_RAW_TEXT": value}, clear=False):
                self.assertEqual(lr.raw_text_logging_enabled(), expected, value)

    def test_env_var_absent_is_disabled(self):
        env = {k: v for k, v in __import__("os").environ.items() if k != "BETTERFINGERS_LOG_RAW_TEXT"}
        with patch.dict("os.environ", env, clear=True):
            self.assertFalse(lr.raw_text_logging_enabled())

    def test_non_string_input_is_coerced(self):
        with patch.object(lr, "raw_text_logging_enabled", return_value=False):
            self.assertEqual(lr.redact_user_text(12345), "<redacted 5 chars>")

    def test_redacted_len(self):
        self.assertEqual(lr.redacted_len("hello"), 5)
        self.assertEqual(lr.redacted_len(None), 0)
        self.assertEqual(lr.redacted_len(""), 0)


if __name__ == "__main__":
    unittest.main()
