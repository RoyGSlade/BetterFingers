"""User-content redaction for logs (DESIGN §9.3).

By default, no raw dictated text / TTS phrase / prompt may reach a log line — only
a character-count summary. A developer can opt into raw logging via an env var.
"""

import os
import re
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


class RedactExcTests(unittest.TestCase):
    def test_preserves_type_redacts_message(self):
        with patch.object(lr, "raw_text_logging_enabled", return_value=False):
            out = lr.redact_exc(RuntimeError("the user's secret prompt: launch the missiles"))
        self.assertTrue(out.startswith("RuntimeError: "))
        self.assertNotIn("missiles", out)
        self.assertIn("<redacted", out)

    def test_opt_in_returns_raw_message(self):
        with patch.object(lr, "raw_text_logging_enabled", return_value=True):
            out = lr.redact_exc(ValueError("raw detail"))
        self.assertEqual(out, "ValueError: raw detail")

    def test_empty_message_exception(self):
        with patch.object(lr, "raw_text_logging_enabled", return_value=False):
            out = lr.redact_exc(KeyError())
        self.assertTrue(out.startswith("KeyError: "))


class RedactStderrLinesTests(unittest.TestCase):
    def test_loader_error_line_survives_verbatim(self):
        stderr = "error while loading shared libraries: libmtmd.so.0: cannot open shared object file"
        with patch.object(lr, "raw_text_logging_enabled", return_value=False):
            out = lr.redact_stderr_lines(stderr)
        self.assertEqual(out, stderr)
        self.assertIn("libmtmd.so.0", out)

    def test_prompt_looking_line_is_redacted(self):
        stderr = "user prompt was: please write me a poem about my divorce"
        with patch.object(lr, "raw_text_logging_enabled", return_value=False):
            out = lr.redact_stderr_lines(stderr)
        self.assertNotIn("divorce", out)
        self.assertNotIn("poem", out)
        self.assertIn(f"<redacted {len(stderr)} chars>", out)

    def test_mixed_multiline_filters_per_line_and_preserves_line_count(self):
        stderr = (
            "loading model...\n"
            "prompt: write a story about my cat named Whiskers\n"
            "cuda error: out of memory\n"
        )
        with patch.object(lr, "raw_text_logging_enabled", return_value=False):
            out = lr.redact_stderr_lines(stderr)
        out_lines = out.split("\n")
        self.assertEqual(len(out_lines), 3)
        self.assertEqual(out_lines[0], "loading model...")
        self.assertNotIn("Whiskers", out_lines[1])
        self.assertIn("<redacted", out_lines[1])
        self.assertEqual(out_lines[2], "cuda error: out of memory")

    def test_empty_and_none_are_empty_string(self):
        with patch.object(lr, "raw_text_logging_enabled", return_value=False):
            self.assertEqual(lr.redact_stderr_lines(""), "")
            self.assertEqual(lr.redact_stderr_lines(None), "")

    def test_opt_in_returns_raw_stderr(self):
        stderr = "prompt: secret text\nloading model"
        with patch.object(lr, "raw_text_logging_enabled", return_value=True):
            self.assertEqual(lr.redact_stderr_lines(stderr), stderr)


_LOGGING_CALL_RE = re.compile(r"logging\.(debug|info|warning|error|exception|critical)\s*\(")
_SUSPICIOUS_TERMS = ("final_text", "raw_text", "dictated", "transcript", "prompt", "persona_example", "clipboard")
_REDACT_WRAPPERS = ("redact_user_text(", "redact_exc(", "redact_stderr_lines(")
_SKIP_DIR_NAMES = {".venv", "node_modules", "tests", ".git", "app", "__pycache__"}

# file:line -> reason, for verified-SAFE sites that happen to match a
# suspicious term without being user content (mirrors docs/redaction-audit.md's
# SAFE classifications). Add here with a one-line reason if a future audit
# clears a new match rather than wrapping it — never to silence a real one.
_ALLOWLIST = {
    # pyperclip/Win32 clipboard API exceptions: the message is a library/OS
    # failure (access denied, format unavailable, buffer too large) — these
    # APIs never embed the clipboard's own text content in their exceptions.
    "clipboard_capture.py:50": "pyperclip read failure, not clipboard content",
    "clipboard_capture.py:65": "pyperclip write failure, not clipboard content",
    "clipboard_capture.py:91": "pyperclip restore failure, not clipboard content",
    "clipboard_capture.py:149": "logs format id + byte size only, no content",
    "clipboard_capture.py:160": "Win32 GlobalSize/GlobalLock failure, not clipboard content",
    "clipboard_capture.py:211": "Win32 SetClipboardData failure, not clipboard content",
    "clipboard_capture.py:247": "delayed-restore worker's own exception, not clipboard content",
    "clipboard_capture.py:305": "no interpolation at all — static message string",
    "server.py:1013": "no interpolation at all — logging.exception('Clipboard copy failed')",
    "injector.py:262": "get_clipboard_text() ACCESS failure, not the text it would have returned",
}


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _python_source_files():
    root = _repo_root()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.relpath(os.path.join(dirpath, name), root)


class LoggingLeakGateTests(unittest.TestCase):
    """Regression gate (Tier-3 M4 A4): turns docs/redaction-audit.md's sweep
    into a standing check instead of a one-time snapshot — the whole point of
    this workstream is a gate that catches the NEXT feature adding
    `logging.info(f"... {final_text}")`, not just documenting today's state.

    Coarse by design (line-level substring match, not real data-flow
    analysis) — a static grep can't understand where a variable came from, so
    this is a tripwire, not a proof. False positives get a one-line
    _ALLOWLIST entry with a reason, exactly like an audit SAFE verdict;
    false negatives (a leak under a name outside _SUSPICIOUS_TERMS) are the
    known limit of this approach, same caveat the JS twin
    (app/tests/redact.test.mjs) documents for console.* sites.
    """

    def test_no_unwrapped_user_content_identifiers_in_logging_calls(self):
        offenders = []
        for relpath in _python_source_files():
            abspath = os.path.join(_repo_root(), relpath)
            try:
                with open(abspath, "r", encoding="utf-8", errors="ignore") as fh:
                    lines = fh.readlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                if not _LOGGING_CALL_RE.search(line):
                    continue
                lowered = line.lower()
                if not any(term in lowered for term in _SUSPICIOUS_TERMS):
                    continue
                if any(wrapper in line for wrapper in _REDACT_WRAPPERS):
                    continue
                key = f"{relpath}:{lineno}"
                if key in _ALLOWLIST:
                    continue
                offenders.append(f"{key}: {line.strip()}")
        self.assertEqual(
            offenders, [],
            "Unwrapped user-content-shaped logging call(s) — wrap with redact_user_text/"
            "redact_exc/redact_stderr_lines, or add a reasoned _ALLOWLIST entry if verified SAFE:\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
