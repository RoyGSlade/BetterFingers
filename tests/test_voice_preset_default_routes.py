"""Route-behavior tests for the new "default voice preset" endpoints in
routes_user_config.py: GET /voice-presets exposing a "default" field, POST
/voice-presets/{name}/make-default, and DELETE /voice-presets-default.

Mirrors tests/test_server_wake_routes.py's TestClient pattern and
tests/test_voice_presets.py's / tests/test_server_persona_routes.py's
APPDATA-isolation setUp/tearDown (voice_presets.py has no in-memory cache to
reset between tests -- it reads straight from disk each call -- so
re-pointing APPDATA is the only isolation needed).
"""
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

import server


class VoicePresetDefaultRoutesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()

    def _client(self):
        return TestClient(server.app)

    def test_get_voice_presets_reports_no_default_by_default(self):
        with self._client() as client:
            r = client.get("/voice-presets")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertIsNone(body["default"])
        self.assertEqual(body["presets"], [])

    def test_make_default_then_get_reflects_it(self):
        with self._client() as client:
            client.post("/voice-presets", json={"name": "Warm Assistant", "base": "af_heart"})
            r = client.post("/voice-presets/Warm Assistant/make-default")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["default"], "Warm Assistant")

            r2 = client.get("/voice-presets")
            self.assertEqual(r2.json()["default"], "Warm Assistant")

    def test_make_default_unknown_name_404(self):
        with self._client() as client:
            r = client.post("/voice-presets/Does Not Exist/make-default")
        self.assertEqual(r.status_code, 404)

    def test_clear_default_route(self):
        with self._client() as client:
            client.post("/voice-presets", json={"name": "Warm Assistant", "base": "af_heart"})
            client.post("/voice-presets/Warm Assistant/make-default")

            r = client.delete("/voice-presets-default")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertTrue(body["ok"])
            self.assertIsNone(body["default"])

            r2 = client.get("/voice-presets")
            self.assertIsNone(r2.json()["default"])

    def test_clear_default_when_unset_is_a_noop_200(self):
        with self._client() as client:
            r = client.delete("/voice-presets-default")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["default"])

    def test_deleting_the_default_preset_clears_the_default(self):
        with self._client() as client:
            client.post("/voice-presets", json={"name": "Warm Assistant", "base": "af_heart"})
            client.post("/voice-presets/Warm Assistant/make-default")

            client.delete("/voice-presets/Warm Assistant")

            r = client.get("/voice-presets")
            body = r.json()
            self.assertEqual(body["presets"], [])
            self.assertIsNone(body["default"])

    def test_preset_literally_named_default_is_still_deletable(self):
        # Regression guard for the routing-collision fix: DELETE
        # /voice-presets-default (a structurally distinct path) must never
        # shadow DELETE /voice-presets/{name} with name="default".
        with self._client() as client:
            client.post("/voice-presets", json={"name": "default", "base": "af_heart"})
            r = client.get("/voice-presets")
            self.assertEqual([p["name"] for p in r.json()["presets"]], ["default"])

            r2 = client.delete("/voice-presets/default")
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json()["presets"], [])

    def test_making_a_preset_named_default_the_default_works_normally(self):
        # The literal string "default" is a perfectly valid preset name and
        # a perfectly valid default-preset value; only the *route path* for
        # clearing needed to dodge collision, not the data itself.
        with self._client() as client:
            client.post("/voice-presets", json={"name": "default", "base": "af_heart"})
            r = client.post("/voice-presets/default/make-default")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["default"], "default")

            r2 = client.get("/voice-presets")
            self.assertEqual(r2.json()["default"], "default")


if __name__ == "__main__":
    unittest.main()
