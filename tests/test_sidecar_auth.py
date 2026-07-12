"""Sidecar auth fails closed (review finding #5).

Startup policy: non-loopback binds require explicit opt-in AND a token;
production requires a token; a standalone dev launch gets a generated one.
HTTP auth uses constant-time comparison. The WebSocket authenticates via a
first-message frame (query-string tokens leak into logs); the legacy query
param still works but is deprecated.
"""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class StartupSecurityPolicyTests(unittest.TestCase):
    def test_loopback_dev_without_token_generates_one(self):
        result = server.validate_startup_security("127.0.0.1", None, env="development")
        self.assertTrue(result["ok"])
        self.assertTrue(result["generated"])
        self.assertGreaterEqual(len(result["token"]), 64)

    def test_production_without_token_refuses(self):
        result = server.validate_startup_security("127.0.0.1", None, env="production")
        self.assertFalse(result["ok"])
        self.assertIn("required in production", result["error"])

    def test_non_loopback_refused_without_opt_in(self):
        result = server.validate_startup_security("0.0.0.0", "tok", env="development")
        self.assertFalse(result["ok"])
        self.assertIn("non-loopback", result["error"])

    def test_non_loopback_with_opt_in_still_requires_token(self):
        result = server.validate_startup_security("0.0.0.0", None, env="development", allow_remote=True)
        self.assertFalse(result["ok"])

    def test_non_loopback_with_opt_in_and_token_ok(self):
        result = server.validate_startup_security("0.0.0.0", "tok", env="development", allow_remote=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["generated"])

    def test_loopback_variants_accepted(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            self.assertTrue(server.validate_startup_security(host, "tok")["ok"], host)


class HttpAuthTests(unittest.TestCase):
    def test_wrong_and_missing_tokens_rejected(self):
        client = TestClient(server.app)
        with patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": "secret-token"}):
            self.assertEqual(client.get("/health").status_code, 401)
            self.assertEqual(
                client.get("/health", headers={"Authorization": "Bearer wrong"}).status_code, 401)
            self.assertEqual(
                client.get("/health", headers={"Authorization": "Basic secret-token"}).status_code, 401)
            self.assertEqual(
                client.get("/health", headers={"Authorization": "Bearer secret-token"}).status_code, 200)


class WebSocketAuthTests(unittest.TestCase):
    def test_first_message_auth_accepted(self):
        client = TestClient(server.app)
        with patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": "ws-secret"}):
            with client.websocket_connect("/ws/voice_status") as ws:
                ws.send_text("auth:ws-secret")
                self.assertEqual(ws.receive_text(), "auth_ok")
                ws.send_text("ping")
                self.assertEqual(ws.receive_text(), "pong")

    def test_wrong_first_message_closes_socket(self):
        client = TestClient(server.app)
        with patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": "ws-secret"}):
            with client.websocket_connect("/ws/voice_status") as ws:
                ws.send_text("auth:wrong")
                with self.assertRaises(Exception):
                    ws.receive_text()  # closed with 1008

    def test_legacy_query_param_still_accepted(self):
        client = TestClient(server.app)
        with patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": "ws-secret"}):
            with client.websocket_connect("/ws/voice_status?token=ws-secret") as ws:
                self.assertEqual(ws.receive_text(), "auth_ok")
                ws.send_text("ping")
                self.assertEqual(ws.receive_text(), "pong")

    def test_no_token_configured_accepts_plainly(self):
        client = TestClient(server.app)
        env = {k: v for k, v in os.environ.items() if k != "BETTERFINGERS_AUTH_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            with client.websocket_connect("/ws/voice_status") as ws:
                ws.send_text("ping")
                self.assertEqual(ws.receive_text(), "pong")


if __name__ == "__main__":
    unittest.main()
