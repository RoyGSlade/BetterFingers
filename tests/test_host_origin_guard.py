"""Phase 0 item 5: the local API refuses DNS-rebinding and cross-site browser calls."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from backend.api.security import _allowed_cors_origins, check_request_origin

TOKEN = "t" * 64


def _client(port=8000):
    return TestClient(server.app, base_url=f"http://127.0.0.1:{port}")


class PureGuardTests(unittest.TestCase):
    def check(self, host, origin=None, port=8000, env=None):
        return check_request_origin(host, origin, server_port=port, env=env or {})

    def test_loopback_hosts_on_the_listening_port_pass(self):
        for host in ("127.0.0.1:8000", "localhost:8000", "LOCALHOST:8000", "[::1]:8000"):
            self.assertIsNone(self.check(host), host)

    def test_other_hosts_ports_and_malformed_values_are_refused(self):
        for host in (
            "evil.example:8000", "evil.example", "127.0.0.1.evil.example:8000", "127.0.0.1:9999",
            "127.0.0.1", "", None, "[::1", "::1:8000", "127.0.0.1:80a", "localhost:8000, evil.example",
            "0.0.0.0:8000", "192.168.1.5:8000", "testserver",
        ):
            self.assertEqual(self.check(host), "host_not_allowed", repr(host))

    def test_testserver_is_only_allowed_when_a_test_asks_for_it(self):
        self.assertEqual(check_request_origin("testserver", None, server_port=80, env={}), "host_not_allowed")
        self.assertIsNone(check_request_origin("testserver", None, server_port=80, env={}, allow_testserver=True))

    def test_no_origin_header_passes(self):
        self.assertIsNone(self.check("127.0.0.1:8000", None))
        self.assertIsNone(self.check("127.0.0.1:8000", ""))

    def test_browser_origins_are_refused_unless_configured(self):
        for origin in (
            "https://evil.example", "http://evil.example:8000", "null", "file://", "file:///x/index.html",
            "http://127.0.0.1:5173.evil.example", "http://localhost:3000", "http://127.0.0.1:18080",
        ):
            self.assertEqual(self.check("127.0.0.1:8000", origin), "origin_not_allowed", origin)

    def test_the_servers_own_origin_and_configured_origins_pass(self):
        self.assertIsNone(self.check("127.0.0.1:8000", "http://127.0.0.1:8000"))
        env = {"BETTERFINGERS_CORS_ORIGINS": "https://tools.example.com"}
        with patch.dict(os.environ, env):
            self.assertIsNone(self.check("127.0.0.1:8000", "https://tools.example.com"))

    def test_null_and_file_origins_cannot_be_configured_back_in(self):
        with patch.dict(os.environ, {"BETTERFINGERS_CORS_ORIGINS": "null, file://, https://ok.example"}):
            self.assertEqual(_allowed_cors_origins().count("null"), 0)
            self.assertNotIn("file://", _allowed_cors_origins())
            self.assertIn("https://ok.example", _allowed_cors_origins())

    def test_dev_server_origin_is_not_allowed_in_production(self):
        with patch.dict(os.environ, {"BETTERFINGERS_ENV": "production"}):
            self.assertEqual(_allowed_cors_origins(), [])
        with patch.dict(os.environ, {"BETTERFINGERS_ENV": "development"}):
            self.assertIn("http://localhost:5173", _allowed_cors_origins())

    def test_explicit_remote_bind_skips_only_the_host_check(self):
        env = {"BETTERFINGERS_ALLOW_REMOTE": "1"}
        self.assertIsNone(check_request_origin("192.168.1.5:8000", None, server_port=8000, env=env))
        self.assertEqual(
            check_request_origin("192.168.1.5:8000", "https://evil.example", server_port=8000, env=env),
            "origin_not_allowed",
        )


class HttpGuardTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.auth = {"Authorization": f"Bearer {TOKEN}"}

    def test_a_correct_loopback_request_still_works(self):
        response = _client().get("/health", headers=self.auth)
        self.assertEqual(response.status_code, 200)

    def test_rebinding_host_is_refused_even_with_a_valid_token(self):
        for host in ("evil.example:8000", "evil.example", "127.0.0.1:9999"):
            response = _client().get("/health", headers={**self.auth, "Host": host})
            self.assertEqual(response.status_code, 403, host)
            self.assertNotIn("evil", response.text)

    def test_rebinding_host_is_refused_before_the_token_is_even_checked(self):
        response = _client().get("/health", headers={"Host": "evil.example:8000"})
        self.assertEqual(response.status_code, 403)  # not 401: the guard is outermost

    def test_cross_site_origin_is_refused_for_every_method(self):
        headers = {**self.auth, "Origin": "https://evil.example"}
        self.assertEqual(_client().get("/health", headers=headers).status_code, 403)
        self.assertEqual(_client().post("/runtime/emergency-stop", headers=headers).status_code, 403)

    def test_cors_preflight_from_a_foreign_or_opaque_origin_is_refused(self):
        for origin in ("https://evil.example", "null", "file://"):
            response = _client().options(
                "/workflows/approve",
                headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                         "Access-Control-Request-Headers": "authorization,content-type"},
            )
            self.assertEqual(response.status_code, 403, origin)
            self.assertNotIn("access-control-allow-origin", {k.lower() for k in response.headers})

    def test_no_foreign_origin_ever_receives_cors_allow_headers(self):
        response = _client().get("/health", headers={**self.auth, "Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", {k.lower() for k in response.headers})

    def test_non_browser_callers_without_an_origin_are_unaffected(self):
        response = _client().get("/runtime/version", headers=self.auth)
        self.assertEqual(response.status_code, 200)


class WebSocketGuardTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _attempt(self, headers):
        with _client().websocket_connect("/ws/voice_status", headers=headers) as ws:
            ws.send_text(f"auth:{TOKEN}")
            return ws.receive_text()

    def test_good_client_authenticates(self):
        self.assertEqual(self._attempt({}), "auth_ok")

    def test_foreign_origin_cannot_open_the_socket(self):
        with self.assertRaises(Exception):
            self._attempt({"Origin": "https://evil.example"})

    def test_rebinding_host_cannot_open_the_socket(self):
        with self.assertRaises(Exception):
            self._attempt({"Host": "evil.example:8000"})


if __name__ == "__main__":
    unittest.main()
