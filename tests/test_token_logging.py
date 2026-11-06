"""Phase 0 item 10: bearer tokens must not reach stdout, logs or access logs."""
import io
import logging
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api.security import announce_generated_token
from backend.privacy.secret_scrub import SecretRedactingFilter, install_log_redaction

TOKEN = "9f8e7d6c" * 8


class TokenAnnouncementTests(unittest.TestCase):
    def test_generated_token_is_never_printed(self):
        lines = []
        message = announce_generated_token(TOKEN, env={}, out=lines.append)
        text = "\n".join(lines) + message
        self.assertNotIn(TOKEN, text)
        self.assertIn("BETTERFINGERS_AUTH_TOKEN", text)  # tells the developer what to do instead

    def test_token_file_is_owner_only_and_still_not_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "token")
            lines = []
            announce_generated_token(TOKEN, env={"BETTERFINGERS_TOKEN_FILE": target}, out=lines.append)
            self.assertEqual(Path(target).read_text(encoding="utf-8"), TOKEN)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)
            self.assertNotIn(TOKEN, "\n".join(lines))

    def test_unwritable_token_file_degrades_without_leaking(self):
        lines = []
        announce_generated_token(TOKEN, env={"BETTERFINGERS_TOKEN_FILE": "/nonexistent-dir/x/token"}, out=lines.append)
        self.assertNotIn(TOKEN, "\n".join(lines))

    def test_no_print_in_server_emits_a_token(self):
        """Source guard: no print()/logging call in server.py formats a token value."""
        source = Path(__file__).resolve().parents[1].joinpath("server.py").read_text(encoding="utf-8")
        for match in re.finditer(r"print\((?:[^()]|\([^()]*\))*\)", source):
            self.assertNotRegex(match.group(0), r"BETTERFINGERS_AUTH_TOKEN=\{|result\[.token.\]|_security\[.token.\]")


class RedactionFilterTests(unittest.TestCase):
    def _logger(self, name):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        return logger, stream, handler

    def test_filter_masks_an_access_log_style_record(self):
        logger, stream, handler = self._logger("phase0.access")
        handler.addFilter(SecretRedactingFilter())
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", f"/ws/voice_status?token={TOKEN}", "1.1", 101)
        out = stream.getvalue()
        self.assertNotIn(TOKEN, out)
        self.assertIn("/ws/voice_status", out)
        self.assertIn("101", out)

    def test_filter_masks_authorization_values_in_any_message(self):
        logger, stream, handler = self._logger("phase0.generic")
        handler.addFilter(SecretRedactingFilter())
        logger.info("request headers: Authorization: Bearer %s", TOKEN)
        logger.info("env dump BETTERFINGERS_AUTH_TOKEN=%s", TOKEN)
        self.assertNotIn(TOKEN, stream.getvalue())

    def test_install_puts_the_filter_on_root_handlers_and_http_loggers(self):
        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root.addHandler(handler)
        self.addCleanup(root.removeHandler, handler)
        access = logging.getLogger("uvicorn.access")
        before = list(access.filters)
        self.addCleanup(lambda: setattr(access, "filters", before))
        install_log_redaction()
        install_log_redaction()  # idempotent
        self.assertEqual(sum(isinstance(f, SecretRedactingFilter) for f in handler.filters), 1)
        self.assertEqual(sum(isinstance(f, SecretRedactingFilter) for f in access.filters), 1)

    def test_a_real_root_handler_never_writes_the_token(self):
        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root.addHandler(handler)
        old_level = root.level
        root.setLevel(logging.INFO)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old_level)
        install_log_redaction()
        logging.getLogger("some.module").info("calling with Bearer %s now", TOKEN)
        self.assertNotIn(TOKEN, stream.getvalue())
        self.assertIn("now", stream.getvalue())

    def test_malformed_record_does_not_break_logging(self):
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "bad %d", ("not a number",), None)
        self.assertTrue(SecretRedactingFilter().filter(record))


class LogTailRedactionTests(unittest.TestCase):
    def test_diagnostics_log_tail_masks_tokens_already_on_disk(self):
        import server

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "debug.log"
            log.write_text(f"old line GET /ws/voice_status?token={TOKEN}\nplain line\n", encoding="utf-8")
            with patch.object(server, "get_debug_log_path", return_value=log):
                result = server.read_log_tail(10)
        joined = "\n".join(result["lines"])
        self.assertNotIn(TOKEN, joined)
        self.assertIn("plain line", joined)


if __name__ == "__main__":
    unittest.main()


class CodexRecheckLoggingGaps(unittest.TestCase):
    """Round 2, item 7 (second half). The Codex re-review listed three places the
    heuristic redaction did not reach: quoted JSON/repr token values, exception traceback
    text (the message filter never saw it) and secrets split across output chunks."""

    def test_quoted_json_and_repr_values_are_masked(self):
        from backend.privacy.secret_scrub import redact_secrets
        samples = [
            '{"token": "%s"}' % TOKEN,
            "{'access_token': '%s', 'x': 1}" % TOKEN,
            '{"Authorization": "Bearer %s"}' % TOKEN,
            "{'Authorization': 'abc-secret-value-123'}",
            '{"api_key":"sk-short"}',
            '{ "password" : "hunter2hunter2" }',
            'payload={"auth_token":"short-token-value"}',
            '{"client_secret": "s3cr3t-value"}',
        ]
        for sample in samples:
            out = redact_secrets(sample)
            for secret in (TOKEN, "abc-secret-value-123", "sk-short", "hunter2hunter2", "short-token-value", "s3cr3t-value"):
                self.assertNotIn(secret, out, sample)
            self.assertIn("[redacted]", out, sample)

    def test_ordinary_json_is_left_alone(self):
        from backend.privacy.secret_scrub import redact_secrets
        for sample in ('{"name": "Coach", "token_count": 5}', '{"author": "bob"}', '{"keys": ["a", "b"]}', '{"status": "ok"}'):
            self.assertEqual(redact_secrets(sample), sample)

    def test_a_traceback_that_quotes_a_credential_is_scrubbed(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        handler.addFilter(SecretRedactingFilter())
        logger = logging.getLogger("phase0.traceback")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        try:
            try:
                raise RuntimeError(f"request failed: Authorization: Bearer {TOKEN} and {{'token': '{TOKEN}'}}")
            except RuntimeError:
                logger.exception("handler crashed")
        finally:
            logger.handlers = []
        out = stream.getvalue()
        self.assertIn("Traceback", out)
        self.assertIn("RuntimeError", out)
        self.assertNotIn(TOKEN, out)

    def test_stack_info_is_scrubbed_too(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(SecretRedactingFilter())
        logger = logging.getLogger("phase0.stack")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        token_in_local = TOKEN  # noqa: F841 - appears in the frame source line below
        try:
            logger.info("marker", stack_info=True, extra={})
        finally:
            logger.handlers = []
        self.assertNotIn(TOKEN, stream.getvalue())

    def test_the_root_handlers_installed_by_setup_logging_scrub_exception_text(self):
        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.INFO)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, old)
        install_log_redaction()
        try:
            raise ValueError(f"bad header Bearer {TOKEN}")
        except ValueError:
            logging.getLogger("some.module").exception("boom")
        self.assertNotIn(TOKEN, stream.getvalue())
