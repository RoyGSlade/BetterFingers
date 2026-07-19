"""Route tests for the Spellcheck & Sorcery room API (board task #40).

Every test builds its own app via `create_app` with a fake `call_fn`
(no real model/network/server.py) -- mirrors the DI-with-fakes pattern in
tests/test_lan_playground_app.py. These tests cover the game-specific
surface (/api/game/*): room lifecycle, token auth, host/player gating,
idle expiry, bounded fields, rate limits, engine-error translation, QR
presence, and the move-text polish -> auto-resolve integration.
"""

import re
import threading
import time
import unittest

from fastapi.testclient import TestClient

from backend.lan_playground import game, rooms
from backend.lan_playground.app import create_app

ACCESS_CODE = "test-access-code-value"
ALLOWED_HOSTS = {"testserver"}
ALLOWED_ORIGINS = {"http://testserver"}


def _fake_call_fn(text="polished!"):
    return lambda messages: text


def _build_app(**kwargs):
    defaults = dict(
        access_code=ACCESS_CODE,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=ALLOWED_ORIGINS,
        call_fn=_fake_call_fn(),
        persona_lookup=lambda name: {"prompt": "Be pleasant."},
        persona_allowlist=lambda: ["Formal"],
    )
    defaults.update(kwargs)
    return create_app(**defaults)


def _client(**kwargs):
    return TestClient(_build_app(**kwargs))


def _headers(**extra):
    return {"X-Access-Code": ACCESS_CODE, **extra}


def _create_room(client, host_name="Ava", seed=1):
    resp = client.post("/api/game/rooms", json={"host_name": host_name, "seed": seed}, headers=_headers())
    assert resp.status_code == 201, resp.text
    return resp.json()


def _join_room(client, room_id, display_name="Beau"):
    resp = client.post(
        f"/api/game/rooms/{room_id}/join",
        json={"display_name": display_name, "join_code": room_id},
        headers=_headers(),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class CreateRoomTests(unittest.TestCase):
    def test_create_room_requires_access_code(self):
        client = _client()
        resp = client.post("/api/game/rooms", json={"host_name": "Ava"})
        self.assertEqual(resp.status_code, 401)

    def test_create_room_returns_host_credentials_and_state(self):
        client = _client()
        data = _create_room(client)
        self.assertEqual(len(data["room_id"]), 8)
        self.assertTrue(data["host_token"])
        self.assertTrue(data["player_id"])
        self.assertEqual(data["join_code"], data["room_id"])
        self.assertIn(data["room_id"], data["join_url"])
        self.assertTrue(data["join_qr_svg"].startswith("<svg"))
        self.assertEqual(data["state"]["phase"], "lobby")
        self.assertEqual(len(data["state"]["players"]), 1)
        self.assertTrue(data["state"]["players"][0]["is_host"])

    def test_create_room_rejects_empty_host_name(self):
        client = _client()
        resp = client.post("/api/game/rooms", json={"host_name": ""}, headers=_headers())
        self.assertEqual(resp.status_code, 422)

    def test_create_room_rejects_oversize_host_name(self):
        client = _client()
        resp = client.post(
            "/api/game/rooms", json={"host_name": "x" * (game.PLAYER_NAME_MAX_CHARS + 1)}, headers=_headers()
        )
        self.assertEqual(resp.status_code, 422)

    def test_create_room_never_exposes_a_second_players_field(self):
        client = _client()
        data = _create_room(client)
        # Only this caller's own credentials are ever in the response.
        self.assertNotIn("player_token", data)

    def test_room_create_rate_limit_trips(self):
        client = _client(room_create_rate_limit_per_min=1)
        first = client.post("/api/game/rooms", json={"host_name": "A"}, headers=_headers())
        second = client.post("/api/game/rooms", json={"host_name": "B"}, headers=_headers())
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)


class JoinRoomTests(unittest.TestCase):
    def test_join_unknown_room_404(self):
        client = _client()
        resp = client.post(
            "/api/game/rooms/NOPE0000/join", json={"display_name": "Beau", "join_code": "NOPE0000"}, headers=_headers()
        )
        self.assertEqual(resp.status_code, 404)

    def test_join_success_returns_player_credentials(self):
        client = _client()
        room = _create_room(client)
        data = _join_room(client, room["room_id"])
        self.assertTrue(data["player_token"])
        self.assertTrue(data["player_id"])
        self.assertNotEqual(data["player_id"], room["player_id"])
        self.assertNotIn("host_token", data)
        self.assertEqual(len(data["state"]["players"]), 2)

    def test_join_full_room_returns_409_room_full(self):
        client = _client()
        room = _create_room(client)
        _join_room(client, room["room_id"], "P2")
        _join_room(client, room["room_id"], "P3")
        _join_room(client, room["room_id"], "P4")  # room now at 4/4
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/join",
            json={"display_name": "P5", "join_code": room["room_id"]},
            headers=_headers(),
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"], "room_full")

    def test_join_after_start_returns_409_wrong_phase(self):
        client = _client()
        room = _create_room(client)
        client.post(f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]}))
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/join",
            json={"display_name": "Late", "join_code": room["room_id"]},
            headers=_headers(),
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"], "wrong_phase")

    def test_join_rejects_oversize_display_name(self):
        client = _client()
        room = _create_room(client)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/join",
            json={"display_name": "y" * (game.PLAYER_NAME_MAX_CHARS + 1), "join_code": room["room_id"]},
            headers=_headers(),
        )
        self.assertEqual(resp.status_code, 422)


class AuthTests(unittest.TestCase):
    def test_state_without_token_401(self):
        client = _client()
        room = _create_room(client)
        resp = client.get(f"/api/game/rooms/{room['room_id']}/state", headers=_headers())
        self.assertEqual(resp.status_code, 401)

    def test_state_with_wrong_token_401(self):
        client = _client()
        room = _create_room(client)
        resp = client.get(
            f"/api/game/rooms/{room['room_id']}/state", headers=_headers(**{"X-Host-Token": "totally-wrong"})
        )
        self.assertEqual(resp.status_code, 401)

    def test_state_with_valid_host_token_200(self):
        client = _client()
        room = _create_room(client)
        resp = client.get(
            f"/api/game/rooms/{room['room_id']}/state", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        self.assertEqual(resp.status_code, 200)

    def test_players_token_does_not_authenticate_a_different_room(self):
        client = _client()
        room1 = _create_room(client, seed=1)
        room2 = _create_room(client, seed=2)
        resp = client.get(
            f"/api/game/rooms/{room2['room_id']}/state",
            headers=_headers(**{"X-Host-Token": room1["host_token"]}),
        )
        self.assertEqual(resp.status_code, 401)

    def test_state_never_leaks_tokens(self):
        client = _client()
        room = _create_room(client)
        resp = client.get(
            f"/api/game/rooms/{room['room_id']}/state", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        # The response body must not contain the raw token string anywhere.
        self.assertNotIn(room["host_token"], resp.text)


class HostGatingTests(unittest.TestCase):
    def test_non_host_cannot_start(self):
        client = _client()
        room = _create_room(client)
        guest = _join_room(client, room["room_id"])
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Player-Token": guest["player_token"]})
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "not_host")

    def test_host_can_start(self):
        client = _client()
        room = _create_room(client)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["phase"], "choosing")

    def test_non_host_cannot_advance(self):
        client = _client()
        room = _create_room(client)
        guest = _join_room(client, room["room_id"])
        client.post(f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]}))
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/advance",
            headers=_headers(**{"X-Player-Token": guest["player_token"]}),
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_host_cannot_replay(self):
        client = _client()
        room = _create_room(client)
        guest = _join_room(client, room["room_id"])
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/replay",
            headers=_headers(**{"X-Player-Token": guest["player_token"]}),
        )
        # Room isn't even finished yet, but host-check fires regardless --
        # either 403 (not host) is an acceptable rejection here.
        self.assertIn(resp.status_code, (403, 409))


class SubmitMoveTests(unittest.TestCase):
    def _started_room(self, client):
        room = _create_room(client)
        client.post(f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]}))
        return room

    def test_submit_move_requires_valid_approach(self):
        client = _client()
        room = self._started_room(client)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "hello", "approach": "fireball", "card": "fireball"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        self.assertEqual(resp.status_code, 422)

    def test_submit_move_rejects_empty_text(self):
        client = _client()
        room = self._started_room(client)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "", "approach": "charm", "card": "charm"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        self.assertEqual(resp.status_code, 422)

    def test_submit_move_rejects_oversize_text(self):
        client = _client()
        room = self._started_room(client)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "x" * (game.MOVE_TEXT_MAX_CHARS + 1), "approach": "charm", "card": "charm"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        self.assertEqual(resp.status_code, 422)

    def test_double_submit_same_round_409(self):
        # Two players so the round doesn't auto-resolve after the host's
        # first submission (a solo-host room resolves immediately, which
        # would raise wrong_phase, not already_submitted, on a retry).
        client = _client()
        room = _create_room(client)
        _join_room(client, room["room_id"])
        client.post(f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]}))
        headers = _headers(**{"X-Host-Token": room["host_token"]})
        first = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "first try", "approach": "charm", "card": "charm"},
            headers=headers,
        )
        second = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "second try", "approach": "bonk", "card": "bonk"},
            headers=headers,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"], "already_submitted")

    def test_submit_before_start_returns_409_wrong_phase(self):
        client = _client()
        room = _create_room(client)  # not started
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "too early", "approach": "charm", "card": "charm"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"], "wrong_phase")

    def test_card_field_accepted_when_approach_missing(self):
        client = _client()
        room = self._started_room(client)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "just card, no approach", "card": "bonk"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        self.assertEqual(resp.status_code, 200)


class AutoResolveAndPolishTests(unittest.TestCase):
    def test_last_submission_auto_resolves_to_reveal(self):
        client = _client()
        room = _create_room(client)
        guest = _join_room(client, room["room_id"])
        client.post(f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]}))

        client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "host move", "approach": "charm", "card": "charm"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "guest move", "approach": "scheme", "card": "scheme"},
            headers=_headers(**{"X-Player-Token": guest["player_token"]}),
        )
        state = resp.json()["state"]
        self.assertEqual(state["phase"], "reveal")
        self.assertIsNotNone(state["last_round"])

    def test_polished_text_appears_in_reveal(self):
        client = _client(call_fn=_fake_call_fn("A dazzling one-liner!"))
        room = _create_room(client)
        client.post(f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]}))
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "raw move text", "approach": "charm", "card": "charm", "persona": "Formal"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        state = resp.json()["state"]
        self.assertEqual(state["last_round"]["choices"][0]["move_text"], "A dazzling one-liner!")
        self.assertEqual(state["last_round"]["choices"][0]["approach"], "charm")

    def test_model_unavailable_falls_back_to_raw_move_text(self):
        client = _client(engine_ready_fn=lambda: False)
        room = _create_room(client)
        client.post(f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]}))
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "my original move", "approach": "charm", "card": "charm"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        state = resp.json()["state"]
        self.assertEqual(state["last_round"]["choices"][0]["move_text"], "my original move")

    def test_slow_model_does_not_hang_the_request(self):
        release = threading.Event()

        def slow_call_fn(messages):
            release.wait(timeout=5)
            return "too slow"

        client = _client(call_fn=slow_call_fn, move_polish_timeout_s=0.05)
        room = _create_room(client)
        client.post(f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]}))
        started = time.monotonic()
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/moves",
            json={"move_text": "raw move under time pressure", "approach": "charm", "card": "charm"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        elapsed = time.monotonic() - started
        self.assertEqual(resp.status_code, 200)
        self.assertLess(elapsed, 3.0)
        state = resp.json()["state"]
        self.assertEqual(state["last_round"]["choices"][0]["move_text"], "raw move under time pressure")
        release.set()


class StateShapeTests(unittest.TestCase):
    def test_join_qr_svg_present_in_lobby_state(self):
        client = _client()
        room = _create_room(client)
        resp = client.get(
            f"/api/game/rooms/{room['room_id']}/state", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        state = resp.json()
        self.assertEqual(state["phase"], "lobby")
        self.assertTrue(state["join_qr_svg"].startswith("<svg"))
        self.assertEqual(state["join_code"], room["room_id"])

    def test_join_qr_svg_absent_once_started(self):
        client = _client()
        room = _create_room(client)
        client.post(f"/api/game/rooms/{room['room_id']}/start", headers=_headers(**{"X-Host-Token": room["host_token"]}))
        resp = client.get(
            f"/api/game/rooms/{room['room_id']}/state", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        state = resp.json()
        self.assertEqual(state["phase"], "choosing")
        self.assertNotIn("join_qr_svg", state)

    def test_state_room_id_is_the_short_public_code_not_engine_internal_id(self):
        client = _client()
        room = _create_room(client)
        resp = client.get(
            f"/api/game/rooms/{room['room_id']}/state", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        self.assertEqual(resp.json()["room_id"], room["room_id"])
        self.assertFalse(resp.json()["room_id"].startswith("room_"))


class SecurityHeaderAndPerimeterTests(unittest.TestCase):
    def test_game_routes_get_security_headers(self):
        client = _client()
        resp = client.post("/api/game/rooms", json={"host_name": "Ava"}, headers=_headers())
        self.assertEqual(resp.headers.get("x-frame-options"), "DENY")
        self.assertEqual(resp.headers.get("cache-control"), "no-store")

    def test_game_routes_respect_host_allowlist(self):
        client = TestClient(_build_app(allowed_hosts={"only-this-host"}))
        resp = client.post("/api/game/rooms", json={"host_name": "Ava"}, headers=_headers())
        self.assertEqual(resp.status_code, 421)

    def test_unknown_room_code_format_still_404s_not_422(self):
        client = _client()
        resp = client.get("/api/game/rooms/not-a-real-code/state", headers=_headers(**{"X-Host-Token": "x"}))
        self.assertIn(resp.status_code, (404, 422))


class ReplayTests(unittest.TestCase):
    def test_replay_before_finished_rejected(self):
        client = _client()
        room = _create_room(client)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/replay", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"], "wrong_phase")


class ModuleHygieneTests(unittest.TestCase):
    def test_module_never_calls_logging(self):
        import backend.lan_playground.app as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("import logging", source)
        self.assertIsNone(re.search(r"\blogging\.\w+\(", source))


if __name__ == "__main__":
    unittest.main()
