import unittest

from fastapi.testclient import TestClient

import server


class SupportReportRouteTests(unittest.TestCase):
    def setUp(self):
        # Non-invasive contract: the report must not initialize models.
        server.transcriber = None
        server.tts_engine = None
        self.client = TestClient(server.app)

    def test_endpoint_returns_markdown_report(self):
        resp = self.client.get("/diagnostics/support-report")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("markdown", body)
        md = body["markdown"]
        self.assertIn("# BetterFingers Support Report", md)
        self.assertIn("no transcription content", md.lower())
        # Structured payload rides along for programmatic consumers.
        self.assertIn("report", body)
        self.assertIn("paths", body["report"])

    def test_report_is_non_invasive(self):
        # Generating the report must NOT initialize the STT/TTS singletons.
        self.client.get("/diagnostics/support-report")
        self.assertIsNone(server.transcriber)
        self.assertIsNone(server.tts_engine)

    def test_message_rescue_section_counts_only_no_content_leak(self):
        secret_context = "SECRET CONTEXT: order #48213, ship to 900 Maple"
        self.client.post("/message-rescue/context/manual", json={"text": secret_context})
        secret_example = {"raw": "call them back", "out": "Please call them back today.", "consent": True}
        self.client.post("/personas/SupportReportTestPersona/examples", json=secret_example)
        try:
            resp = self.client.get("/diagnostics/support-report")
            self.assertEqual(resp.status_code, 200, resp.text)
            md = resp.json()["markdown"]
            self.assertIn("## Message Rescue & persona learning", md)
            self.assertIn("active (in memory only)", md)
            self.assertIn("persisted to disk", md)
            for secret in (secret_context, "48213", "call them back", "call them back today"):
                self.assertNotIn(secret, md)
        finally:
            self.client.delete("/message-rescue/context")
            self.client.delete("/personas/SupportReportTestPersona/examples")

    def test_recent_errors_are_redacted(self):
        # A runtime error whose message carries a long multi-line string must be
        # collapsed + length-capped in the rendered report (defense in depth).
        server.record_runtime_error("stt", "boom\nsecond line\n" + ("x" * 5000), severity="warning")
        md = self.client.get("/diagnostics/support-report").json()["markdown"]
        self.assertIn("boom second line", md)   # newlines collapsed
        self.assertIn("…", md)                    # length-capped
        self.assertNotIn("x" * 400, md)           # raw long run not present verbatim


if __name__ == "__main__":
    unittest.main()
