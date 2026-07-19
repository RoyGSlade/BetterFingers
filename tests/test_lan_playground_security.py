"""Unit tests for backend.lan_playground.security (board #33).

Pure-function tests only -- no FastAPI app, network, or model involved.
"""

import re
import unittest

from backend.lan_playground.security import (
    RateLimiter,
    constant_time_equals,
    generate_access_code,
    generate_room_code,
    generate_token,
    host_header_allowed,
    is_loopback_host,
    origin_allowed,
    sanitize_custom_instruction,
)


class LoopbackHostTests(unittest.TestCase):
    def test_loopback_hosts_recognized(self):
        for host in ("127.0.0.1", "localhost", "::1", "LOCALHOST", " 127.0.0.1 "):
            self.assertTrue(is_loopback_host(host))

    def test_non_loopback_hosts_rejected(self):
        for host in ("0.0.0.0", "192.168.1.5", "example.com", ""):
            self.assertFalse(is_loopback_host(host))


class AccessCodeTests(unittest.TestCase):
    def test_generated_code_is_high_entropy_and_url_safe(self):
        code = generate_access_code()
        self.assertGreaterEqual(len(code), 20)
        self.assertRegex(code, r"^[A-Za-z0-9_-]+$")

    def test_generated_codes_are_unique(self):
        codes = {generate_access_code() for _ in range(20)}
        self.assertEqual(len(codes), 20)

    def test_constant_time_equals_matches(self):
        self.assertTrue(constant_time_equals("abc123", "abc123"))

    def test_constant_time_equals_rejects_mismatch(self):
        self.assertFalse(constant_time_equals("abc123", "abc124"))

    def test_constant_time_equals_handles_empty(self):
        self.assertFalse(constant_time_equals("", ""))
        self.assertFalse(constant_time_equals("", "x"))
        self.assertFalse(constant_time_equals(None, "x"))


class TokenAndRoomCodeTests(unittest.TestCase):
    def test_generated_token_is_high_entropy_and_url_safe(self):
        token = generate_token()
        self.assertGreaterEqual(len(token), 20)
        self.assertRegex(token, r"^[A-Za-z0-9_-]+$")

    def test_generated_tokens_are_unique(self):
        tokens = {generate_token() for _ in range(20)}
        self.assertEqual(len(tokens), 20)

    def test_room_code_default_length_and_alphabet(self):
        code = generate_room_code()
        self.assertEqual(len(code), 8)
        self.assertNotIn("0", code)
        self.assertNotIn("O", code)
        self.assertNotIn("1", code)
        self.assertNotIn("I", code)
        self.assertNotIn("L", code)
        self.assertNotIn("U", code)

    def test_room_code_custom_length(self):
        self.assertEqual(len(generate_room_code(4)), 4)

    def test_room_codes_are_unique(self):
        codes = {generate_room_code() for _ in range(20)}
        self.assertEqual(len(codes), 20)


class HostOriginTests(unittest.TestCase):
    def test_host_header_allowed_matches_bare_hostname(self):
        self.assertTrue(host_header_allowed("192.168.1.5:8850", {"192.168.1.5"}))

    def test_host_header_allowed_rejects_unknown_host(self):
        self.assertFalse(host_header_allowed("evil.example:80", {"192.168.1.5"}))

    def test_host_header_allowed_rejects_empty(self):
        self.assertFalse(host_header_allowed("", {"192.168.1.5"}))

    def test_origin_allowed_when_absent(self):
        self.assertTrue(origin_allowed(None, {"http://192.168.1.5:8850"}))
        self.assertTrue(origin_allowed("", {"http://192.168.1.5:8850"}))

    def test_origin_allowed_exact_match(self):
        self.assertTrue(origin_allowed("http://192.168.1.5:8850", {"http://192.168.1.5:8850"}))

    def test_origin_rejected_when_not_in_allowlist(self):
        self.assertFalse(origin_allowed("http://evil.example", {"http://192.168.1.5:8850"}))


class SanitizeCustomInstructionTests(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(sanitize_custom_instruction("keep   it   short", 100), "keep it short")

    def test_enforces_length_cap(self):
        result = sanitize_custom_instruction("x" * 500, 50)
        self.assertEqual(len(result), 50)

    def test_strips_control_characters(self):
        result = sanitize_custom_instruction("hi\x00\x07there", 100)
        self.assertNotIn("\x00", result)
        self.assertNotIn("\x07", result)

    def test_empty_input(self):
        self.assertEqual(sanitize_custom_instruction("", 100), "")
        self.assertEqual(sanitize_custom_instruction(None, 100), "")


class RateLimiterTests(unittest.TestCase):
    def test_allows_up_to_limit_then_blocks(self):
        limiter = RateLimiter(max_requests=2, window_s=60.0)
        self.assertTrue(limiter.allow("client-a", now=0.0))
        self.assertTrue(limiter.allow("client-a", now=1.0))
        self.assertFalse(limiter.allow("client-a", now=2.0))

    def test_window_expiry_frees_capacity(self):
        limiter = RateLimiter(max_requests=1, window_s=10.0)
        self.assertTrue(limiter.allow("client-a", now=0.0))
        self.assertFalse(limiter.allow("client-a", now=5.0))
        self.assertTrue(limiter.allow("client-a", now=11.0))

    def test_keys_are_independent(self):
        limiter = RateLimiter(max_requests=1, window_s=60.0)
        self.assertTrue(limiter.allow("client-a", now=0.0))
        self.assertTrue(limiter.allow("client-b", now=0.0))
        self.assertFalse(limiter.allow("client-a", now=0.0))


class ModuleHygieneTests(unittest.TestCase):
    def test_module_never_calls_logging(self):
        import backend.lan_playground.security as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("import logging", source)
        self.assertIsNone(re.search(r"\blogging\.\w+\(", source))


if __name__ == "__main__":
    unittest.main()
