"""Controller and Stream Deck routes (Wave 10), over the real router.

Mounted onto a bare FastAPI app for the same reason the Wave 9 route tests are:
the ``app.include_router`` line in server.py is integration-owned (documented in
docs/release/WAVE10_INTEGRATION_DIFFS.md), and a test that waited for it would
report Wave 10 as untested for reasons that have nothing to do with Wave 10.
"""

import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import input_devices as routes_input
from backend.services.input_dispatch import InputActionDispatcher, InputActionHandlers
from backend.stores.app_profiles import AppProfileStore
from backend.stores.controller_bindings import ControllerBindingStore
from backend.stores.stream_deck_config import StreamDeckConfigStore, plugin_action_uuid


def single(token, **extra):
    spec = {"input": {"style": "single", "events": [token]}}
    spec.update(extra)
    return spec


class RouteTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bindings_path = os.path.join(self.tmp, "controller_bindings.json")
        self.deck_path = os.path.join(self.tmp, "stream_deck_config.json")
        self.profiles_path = os.path.join(self.tmp, "app_profiles.json")

        self._orig_bindings = routes_input._bindings
        self._orig_decks = routes_input._decks
        self._orig_dispatcher = routes_input.get_dispatcher()
        routes_input._bindings = lambda: ControllerBindingStore(path=self.bindings_path)
        routes_input._decks = lambda: StreamDeckConfigStore(path=self.deck_path)

        self.profiles = AppProfileStore(path=self.profiles_path)
        routes_input.AppProfileStore = lambda: AppProfileStore(path=self.profiles_path)

        self.calls = []
        self.dispatcher = InputActionDispatcher(InputActionHandlers(
            begin_dictation=lambda: self.calls.append("begin_dictation"),
            end_dictation=lambda: self.calls.append("end_dictation"),
            begin_command=lambda: self.calls.append("begin_command"),
            end_command=lambda: self.calls.append("end_command"),
            emergency_stop=lambda: self.calls.append("emergency_stop"),
            copy_latest=lambda: self.calls.append("copy_latest"),
        ))
        routes_input.set_dispatcher(self.dispatcher)

        app = FastAPI()
        app.include_router(routes_input.router)
        self.client = TestClient(app)

    def tearDown(self):
        routes_input._bindings = self._orig_bindings
        routes_input._decks = self._orig_decks
        routes_input.AppProfileStore = AppProfileStore
        routes_input.set_dispatcher(self._orig_dispatcher)


class VocabularyRouteTests(RouteTestCase):
    def test_the_route_publishes_the_closed_vocabulary_and_what_is_wired(self):
        body = self.client.get("/input/vocabulary").json()
        self.assertTrue(body["ok"])
        self.assertIn("dictation.begin", [row["id"] for row in body["actions"]])
        self.assertIn("emergency.stop", body["required"])
        # The honest half: only handlers this build actually wired.
        self.assertIn("emergency.stop", body["available"])
        self.assertNotIn("latest.read", body["available"])


class BindingRouteTests(RouteTestCase):
    def test_set_resolve_and_clear(self):
        response = self.client.post("/input/bindings/set", json={
            "action_id": "dictation.begin",
            "binding": single("button:4", mode="hold"),
            "device_key": "controller:pad",
        })
        self.assertTrue(response.json()["ok"], response.json())

        body = self.client.get("/input/bindings?device_key=controller:pad").json()
        self.assertEqual(body["resolved"]["dictation.begin"]["mode"], "hold")
        self.assertEqual(body["devices"], ["controller:pad"])

        self.client.post("/input/bindings/clear",
                         json={"action_id": "dictation.begin", "device_key": "controller:pad"})
        body = self.client.get("/input/bindings?device_key=controller:pad").json()
        self.assertEqual(body["resolved"], {})

    def test_the_three_layers_are_reported_separately(self):
        """"Why does this button do that?" is the question a binding UI exists to
        answer, and it cannot be answered from the resolved map alone."""
        self.client.post("/input/bindings/set", json={
            "action_id": "emergency.stop", "binding": single("button:9"),
        })
        self.client.post("/input/bindings/set", json={
            "action_id": "dictation.begin", "binding": single("button:4"),
            "device_key": "controller:pad",
        })
        self.profiles.save({
            "id": "rocket_league",
            "bindings": {"dictation.begin": single("button:1")},
        })

        body = self.client.get(
            "/input/bindings?device_key=controller:pad&profile_id=rocket_league",
        ).json()

        self.assertIn("emergency.stop", body["layers"]["global"])
        self.assertIn("dictation.begin", body["layers"]["device"])
        self.assertIn("dictation.begin", body["layers"]["application_profile"])
        # Most specific wins for the action it names; the panic button stays put.
        self.assertEqual(body["resolved"]["dictation.begin"]["input"]["events"], ["button:1"])
        self.assertEqual(body["resolved"]["emergency.stop"]["input"]["events"], ["button:9"])

    def test_a_deleted_profile_does_not_break_a_button(self):
        """A controller press must not 404 because a profile was deleted while a
        game was running."""
        body = self.client.get("/input/bindings?profile_id=gone_forever").json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["layers"]["application_profile"], {})

    def test_a_binding_with_no_button_is_refused_with_a_reason(self):
        response = self.client.post("/input/bindings/set", json={
            "action_id": "dictation.begin", "binding": {"mode": "hold"},
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("which button", response.json()["detail"])

    def test_settings_round_trip_and_clamp(self):
        body = self.client.post("/input/settings",
                                json={"enabled": False, "debounce_ms": 9999}).json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["debounce_ms"], 500)


class DispatchRouteTests(RouteTestCase):
    def test_a_refusal_comes_back_as_a_code_not_a_4xx(self):
        """A key press is a person pressing a button, and the plugin's job is to
        show them a code on the key — which it can only do if it gets one."""
        response = self.client.post("/input/dispatch", json={"action_id": "not.a.thing"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "unknown_action")

    def test_a_stream_deck_press_reaches_the_same_handler_a_controller_press_does(self):
        """The gate, asserted: two device kinds, one contract."""
        self.client.post("/input/dispatch", json={
            "action_id": "emergency.stop", "source": "stream_deck",
            "device_key": "stream_deck:DEV1",
        })
        self.client.post("/input/dispatch", json={
            "action_id": "emergency.stop", "source": "controller",
            "device_key": "controller:pad",
        })
        self.assertEqual(self.calls, ["emergency_stop", "emergency_stop"])

    def test_an_unwired_action_reports_unavailable_rather_than_succeeding(self):
        body = self.client.post("/input/dispatch", json={"action_id": "latest.read"}).json()
        self.assertEqual(body["status"], "unavailable")

    def test_recent_shows_codes_only(self):
        self.client.post("/input/dispatch", json={
            "action_id": "emergency.stop", "source": "controller", "device_key": "controller:pad",
        })
        rows = self.client.get("/input/recent?limit=5").json()["recent"]
        self.assertEqual(rows[-1]["action_id"], "emergency.stop")
        self.assertEqual(rows[-1]["device_kind"], "controller")
        self.assertNotIn("param", rows[-1])


class CaptureRouteTests(RouteTestCase):
    """The wizard's "press a button now", over the real engine."""

    def setUp(self):
        super().setUp()
        from backend.services.controller_engine import ControllerEngine

        self.engine = ControllerEngine(
            lambda *a, **k: None, lambda _key: {}, debounce_ms=0, clock=lambda: 0.0,
        )
        self.engine.device_added("controller:pad")
        self._orig_capture = routes_input._capture_source
        routes_input.set_capture_source(self.engine)

    def tearDown(self):
        routes_input.set_capture_source(self._orig_capture)
        super().tearDown()

    def test_a_press_becomes_a_binding_once_the_button_is_released(self):
        self.assertTrue(self.client.post("/input/capture/start").json()["ok"])
        self.engine.token_down("controller:pad", "button:4", now=0.0)
        self.assertIsNone(self.client.get("/input/capture/result").json()["binding"])
        self.engine.token_up("controller:pad", "button:4", now=0.2)
        body = self.client.get("/input/capture/result").json()
        self.assertEqual(body["binding"]["events"], ["button:4"])
        self.assertEqual(body["binding"]["style"], "single")

    def test_cancelling_stops_the_capture(self):
        self.client.post("/input/capture/start")
        self.assertFalse(self.client.post("/input/capture/cancel").json()["capturing"])
        self.assertFalse(self.client.get("/input/capture/result").json()["capturing"])

    def test_a_build_with_no_engine_reports_unavailable_rather_than_pretending(self):
        """Every CI runner this project has lacks joystick support. Reporting
        "listening" on such a machine would leave the wizard waiting forever with
        no explanation."""
        routes_input.set_capture_source(None)
        body = self.client.post("/input/capture/start").json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "unavailable")
        self.assertIsNone(self.client.get("/input/capture/result").json()["binding"])


class StreamDeckRouteTests(RouteTestCase):
    def test_pairing_reports_paired_without_storing_the_token(self):
        self.assertTrue(self.client.post("/stream-deck/pair",
                                         json={"token": "s3cret"}).json()["ok"])
        self.assertTrue(self.client.get("/stream-deck").json()["paired"])
        self.assertNotIn("s3cret", open(self.deck_path, encoding="utf-8").read())

    def test_a_key_is_mirrored_and_shown_back(self):
        self.client.post("/stream-deck/key", json={
            "context": "ctx1", "action": plugin_action_uuid("latest.copy"),
            "device": "DEV1", "title": "Copy",
        })
        body = self.client.get("/stream-deck").json()
        self.assertEqual([row["action_id"] for row in body["keys"]], ["latest.copy"])
        self.assertEqual(body["coverage"]["key_count"], 1)

    def test_a_key_naming_someone_elses_plugin_action_is_refused(self):
        response = self.client.post("/stream-deck/key", json={
            "context": "ctx1", "action": "com.someoneelse.plugin.latest.copy",
        })
        self.assertEqual(response.status_code, 400)

    def test_disabling_the_deck_also_gates_dispatch(self):
        self.client.post("/stream-deck/enabled", json={"enabled": False})
        body = self.client.post("/input/dispatch", json={
            "action_id": "latest.copy", "source": "stream_deck", "device_key": "stream_deck:DEV1",
        }).json()
        self.assertEqual(body["status"], "disabled")
        # The panic button works from a switched-off deck anyway.
        body = self.client.post("/input/dispatch", json={
            "action_id": "emergency.stop", "source": "stream_deck",
            "device_key": "stream_deck:DEV1",
        }).json()
        self.assertTrue(body["ok"])

    def test_a_deck_disconnect_releases_only_what_that_deck_held(self):
        """D-0026, over the wire: the release goes through the ordinary
        dispatcher, and only for the device that vanished."""
        self.client.post("/input/dispatch", json={
            "action_id": "command.begin", "source": "stream_deck",
            "device_key": "stream_deck:DEV1", "hold": True,
        })
        self.client.post("/input/dispatch", json={
            "action_id": "dictation.begin", "source": "controller",
            "device_key": "controller:pad", "hold": True,
        })

        body = self.client.post("/stream-deck/device/disconnected",
                                json={"device": "DEV1"}).json()

        self.assertEqual(body["released"], ["command.end"])
        self.assertIn("end_command", self.calls)
        self.assertNotIn("end_dictation", self.calls)
        self.assertEqual(self.dispatcher.held_actions("controller:pad"), ["dictation.begin"])

    def test_the_qualification_status_is_reachable_from_the_ui(self):
        body = self.client.get("/stream-deck/qualification").json()
        self.assertFalse(body["qualified"])
        self.assertTrue(body["protocol_tested"])


if __name__ == "__main__":
    unittest.main()
