"""Route tests for The Lost Meaning room API (board task #2).

Every test builds its own app via `create_app` with a fake `call_fn`
(no real model/network/server.py) -- mirrors the DI-with-fakes pattern in
tests/test_lan_playground_app.py. These tests run against the *real*
`backend.lan_playground.game.Room` (board task #1's engine) through the
full HTTP + auth + rooms.py + app.py stack: room lifecycle, token auth,
host/spotlight/ally gating, idle expiry, bounded fields, rate limits,
engine-error translation, QR presence, and the BetterFingers
draft-variant/narration integration.
"""

import json
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


def _rescue_json(faithful="ok", clearer="ok.", alternate="sure."):
    return json.dumps(
        {
            "assessment": {"intent": "", "ambiguity_risk": "low", "missing_details": [], "clarification_question": ""},
            "variants": {"faithful": faithful, "clearer": clearer, "alternate": alternate},
        }
    )


def _fake_call_fn(**overrides):
    def call_fn(messages):
        return _rescue_json(
            faithful=overrides.get("faithful", "ok"),
            clearer=overrides.get("clearer", "ok."),
            alternate=overrides.get("alternate", "sure."),
        )

    return call_fn


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


def _state(client, room_id, token_header):
    resp = client.get(f"/api/game/rooms/{room_id}/state", headers=_headers(**token_header))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start(client, room_id, host_token):
    resp = client.post(f"/api/game/rooms/{room_id}/start", headers=_headers(**{"X-Host-Token": host_token}))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _spotlight_hero(state):
    return next(h for h in state["heroes"] if h["hero_id"] == state["spotlight_hero_id"])


def _first_move_id(state):
    return _spotlight_hero(state)["deck"][0]["id"]


def _first_target(state):
    return state["encounter"]["targets"][0]


def _submit_spotlight(client, room_id, header, state, move_id=None, target_id=None, desired_outcome="handle it"):
    return client.post(
        f"/api/game/rooms/{room_id}/spotlight",
        json={
            "move_id": move_id or _first_move_id(state),
            "target_id": target_id or _first_target(state),
            "desired_outcome": desired_outcome,
        },
        headers=_headers(**header),
    )


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
        # Full hero roster is always visible (public character sheets).
        self.assertEqual(len(data["state"]["heroes"]), game.MAX_PLAYERS)

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

    def test_join_success_returns_player_credentials_and_binds_next_hero_slot(self):
        client = _client()
        room = _create_room(client)
        data = _join_room(client, room["room_id"])
        self.assertTrue(data["player_token"])
        self.assertTrue(data["player_id"])
        self.assertNotEqual(data["player_id"], room["player_id"])
        self.assertNotIn("host_token", data)
        self.assertEqual(len(data["state"]["players"]), 2)
        second_player = next(p for p in data["state"]["players"] if p["player_id"] == data["player_id"])
        self.assertIsNotNone(second_player["hero_id"])
        self.assertNotEqual(second_player["hero_id"], room["state"]["players"][0]["hero_id"])

    def test_join_full_room_returns_409_room_full(self):
        client = _client()
        room = _create_room(client)
        _join_room(client, room["room_id"], "P2")
        _join_room(client, room["room_id"], "P3")
        _join_room(client, room["room_id"], "P4")  # room now at 4/4 (fixed hero roster)
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
        _start(client, room["room_id"], room["host_token"])
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
        state = _start(client, room["room_id"], room["host_token"])
        self.assertEqual(state["phase"], "spotlight_action")
        self.assertIsNotNone(state["spotlight_hero_id"])

    def test_non_host_cannot_advance(self):
        client = _client()
        room = _create_room(client)
        guest = _join_room(client, room["room_id"])
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
        self.assertIn(resp.status_code, (403, 409))


class SpotlightActionTests(unittest.TestCase):
    def test_submit_requires_valid_move(self):
        client = _client()
        room = _create_room(client)
        state = _start(client, room["room_id"], room["host_token"])
        resp = _submit_spotlight(client, room["room_id"], {"X-Host-Token": room["host_token"]}, state, move_id="not_a_real_move")
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"], "invalid_move")

    def test_submit_requires_valid_target(self):
        client = _client()
        room = _create_room(client)
        state = _start(client, room["room_id"], room["host_token"])
        resp = _submit_spotlight(
            client, room["room_id"], {"X-Host-Token": room["host_token"]}, state, target_id="not a real target"
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"], "invalid_target")

    def test_submit_rejects_empty_desired_outcome(self):
        client = _client()
        room = _create_room(client)
        _start(client, room["room_id"], room["host_token"])
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/spotlight",
            json={"move_id": "x", "target_id": "y", "desired_outcome": ""},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        self.assertEqual(resp.status_code, 422)

    def test_non_spotlight_player_gets_wrong_turn(self):
        client = _client()
        room = _create_room(client)
        guest = _join_room(client, room["room_id"])
        state = _start(client, room["room_id"], room["host_token"])
        # Host is always round-0 spotlight (first join binds hero_order[0],
        # and encounter_index 0 % 4 == 0) -- the guest is an ally, not
        # spotlight, so their attempt must be rejected.
        resp = _submit_spotlight(client, room["room_id"], {"X-Player-Token": guest["player_token"]}, state)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "wrong_turn")

    def test_submit_before_start_returns_409_wrong_phase(self):
        client = _client()
        room = _create_room(client)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/spotlight",
            json={"move_id": "x", "target_id": "y", "desired_outcome": "z"},
            headers=_headers(**{"X-Host-Token": room["host_token"]}),
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"], "wrong_phase")

    def test_double_submit_same_round_returns_409(self):
        # submit_spotlight_action() transitions phase -> ally_support the
        # instant it succeeds, so a second call always fails the *phase*
        # check first -- game.py's AlreadySubmittedError branch for this
        # method is unreachable via two real HTTP calls (it would only ever
        # fire from a same-phase re-entrant call, which can't happen here).
        client = _client()
        room = _create_room(client)
        state = _start(client, room["room_id"], room["host_token"])
        header = {"X-Host-Token": room["host_token"]}
        first = _submit_spotlight(client, room["room_id"], header, state)
        self.assertEqual(first.status_code, 200)
        second = _submit_spotlight(client, room["room_id"], header, state)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"], "wrong_phase")

    def test_success_moves_to_ally_support_and_is_public(self):
        client = _client()
        room = _create_room(client)
        state = _start(client, room["room_id"], room["host_token"])
        header = {"X-Host-Token": room["host_token"]}
        resp = _submit_spotlight(client, room["room_id"], header, state, desired_outcome="settle it fairly")
        self.assertEqual(resp.status_code, 200)
        new_state = resp.json()["state"]
        self.assertEqual(new_state["phase"], "ally_support")
        self.assertEqual(new_state["current_action"]["desired_outcome"], "settle it fairly")
        self.assertIsNone(new_state["current_action"]["approved_text"])


class TwoPlayerRoundHarness(unittest.TestCase):
    """Host (spotlight for round 0) + one real ally; the other two hero
    slots are companions, which the engine auto-plays -- giving a minimal,
    fully-real harness for every single-actor gate (support/open-draft/
    draft/approve/react/resolve) without needing all 4 human slots filled.
    """

    def _room(self, client, **kwargs):
        room = _create_room(client, **kwargs)
        guest = _join_room(client, room["room_id"], "Guest")
        state = _start(client, room["room_id"], room["host_token"])
        host_header = {"X-Host-Token": room["host_token"]}
        guest_header = {"X-Player-Token": guest["player_token"]}
        self.assertEqual(state["spotlight_hero_id"], next(p for p in state["players"] if p["is_host"])["hero_id"])
        return room, guest, host_header, guest_header, state

    def _to_ally_support(self, client, room, host_header, state):
        resp = _submit_spotlight(client, room["room_id"], host_header, state)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["state"]


class SupportTests(TwoPlayerRoundHarness):
    def test_spotlight_hero_cannot_submit_support(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        state = self._to_ally_support(client, room, host_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/support",
            json={"kind": "assist", "detail": "I help"},
            headers=_headers(**host_header),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "wrong_turn")

    def test_invalid_kind_rejected(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        state = self._to_ally_support(client, room, host_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/support",
            json={"kind": "fireball", "detail": ""},
            headers=_headers(**guest_header),
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"], "invalid_support_kind")

    def test_valid_support_then_double_submit_409(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        state = self._to_ally_support(client, room, host_header, state)
        first = client.post(
            f"/api/game/rooms/{room['room_id']}/support",
            json={"kind": "clue", "detail": "It's the ledger."},
            headers=_headers(**guest_header),
        )
        self.assertEqual(first.status_code, 200, first.text)
        second = client.post(
            f"/api/game/rooms/{room['room_id']}/support",
            json={"kind": "assist", "detail": ""},
            headers=_headers(**guest_header),
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["detail"], "already_submitted")

    def test_support_content_hidden_from_other_players_pre_resolve(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        state = self._to_ally_support(client, room, host_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/support",
            json={"kind": "clue", "detail": "totally secret clue content"},
            headers=_headers(**guest_header),
        )
        self.assertEqual(resp.status_code, 200)
        host_view = _state(client, room["room_id"], host_header)
        self.assertNotIn("totally secret clue content", json.dumps(host_view))


class OpenDraftTests(TwoPlayerRoundHarness):
    def test_non_host_cannot_open_draft(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        state = self._to_ally_support(client, room, host_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/support",
            json={"kind": "assist", "detail": ""},
            headers=_headers(**guest_header),
        )
        resp = client.post(f"/api/game/rooms/{room['room_id']}/open-draft", headers=_headers(**guest_header))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "not_host")

    def test_open_draft_before_all_support_submitted_409(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_ally_support(client, room, host_header, state)
        resp = client.post(f"/api/game/rooms/{room['room_id']}/open-draft", headers=_headers(**host_header))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"], "not_all_submitted")

    def test_open_draft_succeeds_once_support_complete(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        state = self._to_ally_support(client, room, host_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/support",
            json={"kind": "assist", "detail": ""},
            headers=_headers(**guest_header),
        )
        resp = client.post(f"/api/game/rooms/{room['room_id']}/open-draft", headers=_headers(**host_header))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["state"]["phase"], "spotlight_draft")


class DraftAndApproveTests(TwoPlayerRoundHarness):
    def _to_spotlight_draft(self, client, room, host_header, guest_header, state):
        state = self._to_ally_support(client, room, host_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/support",
            json={"kind": "assist", "detail": ""},
            headers=_headers(**guest_header),
        )
        resp = client.post(f"/api/game/rooms/{room['room_id']}/open-draft", headers=_headers(**host_header))
        return resp.json()["state"]

    def test_non_spotlight_cannot_draft(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "trying to draft as an ally"},
            headers=_headers(**guest_header),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "wrong_turn")

    def test_draft_generates_exactly_three_variants(self):
        client = _client(call_fn=_fake_call_fn(faithful="We cite the ledger.", clearer="Ledger, please.", alternate="Per the ledger."))
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "We point at the ledger."},
            headers=_headers(**host_header),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        draft = resp.json()["state"]["you"]["draft"]
        self.assertEqual(len(draft["variants"]), 3)
        self.assertEqual(draft["variants"], ["We cite the ledger.", "Ledger, please.", "Per the ledger."])
        self.assertIsNone(draft["approved_text"])

    def test_draft_only_visible_to_spotlight_not_even_host_when_host_is_not_spotlight(self):
        # Round 1's spotlight rotates to the *next* hero -- rebuild a room
        # where the guest, not the host, ends up as spotlight isn't directly
        # controllable via seed alone, so instead we assert the documented
        # engine correction directly off round 0: the ally (guest) must
        # never see the spotlight's (host's) draft even though the ally
        # could otherwise be mistaken for a privileged viewer.
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "a very secret rough draft"},
            headers=_headers(**host_header),
        )
        guest_view = _state(client, room["room_id"], guest_header)
        self.assertIsNone(guest_view["you"]["draft"])
        self.assertNotIn("a very secret rough draft", json.dumps(guest_view))

    def test_model_unavailable_falls_back_to_three_copies_of_rough_text(self):
        client = _client(engine_ready_fn=lambda: False)
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "my own raw words"},
            headers=_headers(**host_header),
        )
        self.assertEqual(resp.status_code, 200)
        draft = resp.json()["state"]["you"]["draft"]
        self.assertEqual(draft["variants"], ["my own raw words"] * 3)

    def test_malformed_model_output_falls_back_safely(self):
        client = _client(call_fn=lambda messages: "not json at all {{{")
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "call me back at 555-1234"},
            headers=_headers(**host_header),
        )
        self.assertEqual(resp.status_code, 200)
        draft = resp.json()["state"]["you"]["draft"]
        self.assertEqual(len(draft["variants"]), 3)
        # rescue_message's own preservation fallback keeps the original text.
        self.assertTrue(all("555-1234" in v for v in draft["variants"]))

    def test_slow_model_times_out_and_falls_back_without_hanging(self):
        release = threading.Event()

        def slow_call_fn(messages):
            release.wait(timeout=5)
            return _rescue_json()

        client = _client(call_fn=slow_call_fn, draft_timeout_s=0.05)
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        started = time.monotonic()
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "under time pressure"},
            headers=_headers(**host_header),
        )
        elapsed = time.monotonic() - started
        self.assertEqual(resp.status_code, 200)
        self.assertLess(elapsed, 3.0)
        draft = resp.json()["state"]["you"]["draft"]
        self.assertEqual(draft["variants"], ["under time pressure"] * 3)
        release.set()

    def test_approve_before_draft_returns_wrong_phase(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/approve",
            json={"chosen_text": "too early", "intent": "resolve it"},
            headers=_headers(**host_header),
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"], "wrong_phase")

    def test_non_spotlight_cannot_approve(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "we handle it"},
            headers=_headers(**host_header),
        )
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/approve",
            json={"chosen_text": "an ally trying to approve", "intent": "resolve it"},
            headers=_headers(**guest_header),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "wrong_turn")

    def test_approve_requires_both_text_and_intent(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "we handle it"},
            headers=_headers(**host_header),
        )
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/approve",
            json={"chosen_text": "", "intent": "resolve it"},
            headers=_headers(**host_header),
        )
        self.assertEqual(resp.status_code, 422)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/approve",
            json={"chosen_text": "fine words", "intent": ""},
            headers=_headers(**host_header),
        )
        self.assertEqual(resp.status_code, 422)

    def test_approve_moves_to_ally_reaction_and_own_hero_edit_is_allowed(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_spotlight_draft(client, room, host_header, guest_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "we handle it"},
            headers=_headers(**host_header),
        )
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/approve",
            json={"chosen_text": "my own hand-edited final line", "intent": "resolve calmly"},
            headers=_headers(**host_header),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        state = resp.json()["state"]
        self.assertEqual(state["phase"], "ally_reaction")
        self.assertEqual(state["current_action"]["approved_text"], "my own hand-edited final line")
        self.assertEqual(state["current_action"]["intent"], "resolve calmly")


class ReactAndResolveTests(TwoPlayerRoundHarness):
    def _to_ally_reaction(self, client, room, host_header, guest_header, state):
        state = self._to_ally_support(client, room, host_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/support",
            json={"kind": "assist", "detail": ""},
            headers=_headers(**guest_header),
        )
        client.post(f"/api/game/rooms/{room['room_id']}/open-draft", headers=_headers(**host_header))
        client.post(
            f"/api/game/rooms/{room['room_id']}/draft",
            json={"rough_text": "we handle it"},
            headers=_headers(**host_header),
        )
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/approve",
            json={"chosen_text": "we handle it, calmly", "intent": "resolve it"},
            headers=_headers(**host_header),
        )
        return resp.json()["state"]

    def test_spotlight_cannot_react_to_own_action(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_ally_reaction(client, room, host_header, guest_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/react",
            json={"verb": "assist", "detail": ""},
            headers=_headers(**host_header),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "wrong_turn")

    def test_invalid_verb_rejected(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_ally_reaction(client, room, host_header, guest_header, state)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/react",
            json={"verb": "smoosh", "detail": ""},
            headers=_headers(**guest_header),
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"], "invalid_reaction_verb")

    def test_resolve_before_all_reactions_409(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_ally_reaction(client, room, host_header, guest_header, state)
        resp = client.post(f"/api/game/rooms/{room['room_id']}/resolve", headers=_headers(**host_header))
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"], "not_all_submitted")

    def test_reaction_content_hidden_pre_resolve_then_revealed(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_ally_reaction(client, room, host_header, guest_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/react",
            json={"verb": "challenge", "detail": "a secret challenge line"},
            headers=_headers(**guest_header),
        )
        host_view = _state(client, room["room_id"], host_header)
        self.assertNotIn("a secret challenge line", json.dumps(host_view))
        resp = client.post(f"/api/game/rooms/{room['room_id']}/resolve", headers=_headers(**host_header))
        self.assertEqual(resp.status_code, 200, resp.text)
        state = resp.json()["state"]
        self.assertEqual(state["phase"], "reveal")
        reaction_texts = [r["detail"] for r in state["last_round"]["reactions"]]
        self.assertIn("a secret challenge line", reaction_texts)

    def test_non_host_cannot_resolve(self):
        client = _client()
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_ally_reaction(client, room, host_header, guest_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/react",
            json={"verb": "assist", "detail": ""},
            headers=_headers(**guest_header),
        )
        resp = client.post(f"/api/game/rooms/{room['room_id']}/resolve", headers=_headers(**guest_header))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["detail"], "not_host")

    def test_resolve_produces_narration_that_survives_a_state_refetch(self):
        client = _client(call_fn=_fake_call_fn())
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_ally_reaction(client, room, host_header, guest_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/react",
            json={"verb": "assist", "detail": ""},
            headers=_headers(**guest_header),
        )
        resp = client.post(f"/api/game/rooms/{room['room_id']}/resolve", headers=_headers(**host_header))
        self.assertEqual(resp.status_code, 200, resp.text)
        state = resp.json()["state"]
        self.assertTrue(state["last_round"]["narration"])
        # Narration must persist across a plain GET /state, not just the
        # resolve response itself.
        refetched = _state(client, room["room_id"], host_header)
        self.assertEqual(refetched["last_round"]["narration"], state["last_round"]["narration"])
        self.assertEqual(refetched["history"][-1]["narration"], state["last_round"]["narration"])

    def test_narration_falls_back_deterministically_when_model_unavailable(self):
        client = _client(engine_ready_fn=lambda: False)
        room, guest, host_header, guest_header, state = self._room(client)
        self._to_ally_reaction(client, room, host_header, guest_header, state)
        client.post(
            f"/api/game/rooms/{room['room_id']}/react",
            json={"verb": "assist", "detail": ""},
            headers=_headers(**guest_header),
        )
        resp = client.post(f"/api/game/rooms/{room['room_id']}/resolve", headers=_headers(**host_header))
        self.assertEqual(resp.status_code, 200, resp.text)
        narration = resp.json()["state"]["last_round"]["narration"]
        self.assertTrue(narration)  # deterministic template, never empty/missing


class VoiceProfileTests(unittest.TestCase):
    def test_update_and_reflected_in_state(self):
        client = _client()
        room = _create_room(client)
        header = {"X-Host-Token": room["host_token"]}
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/voice-profile",
            json={"utterance_count": 12, "confidence": 0.75, "calibrated": True},
            headers=_headers(**header),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        state = resp.json()["state"]
        self.assertEqual(state["you"]["voice_profile"], {"utterance_count": 12, "confidence": 0.75, "calibrated": True})
        hero_id = state["you"]["hero_id"]
        hero = next(h for h in state["heroes"] if h["hero_id"] == hero_id)
        self.assertTrue(hero["voice_calibrated"])

    def test_out_of_range_values_rejected(self):
        client = _client()
        room = _create_room(client)
        header = {"X-Host-Token": room["host_token"]}
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/voice-profile",
            json={"utterance_count": -1, "confidence": 0.5, "calibrated": False},
            headers=_headers(**header),
        )
        self.assertEqual(resp.status_code, 422)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/voice-profile",
            json={"utterance_count": 5, "confidence": 1.5, "calibrated": False},
            headers=_headers(**header),
        )
        self.assertEqual(resp.status_code, 422)

    def test_never_accepts_audio_field(self):
        client = _client()
        room = _create_room(client)
        header = {"X-Host-Token": room["host_token"]}
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/voice-profile",
            json={"utterance_count": 1, "confidence": 0.1, "calibrated": False, "raw_audio": "base64stuffhere"},
            headers=_headers(**header),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("raw_audio", json.dumps(resp.json()))


class ReplayTests(unittest.TestCase):
    def test_replay_before_finished_rejected(self):
        client = _client()
        room = _create_room(client)
        resp = client.post(
            f"/api/game/rooms/{room['room_id']}/replay", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"], "wrong_phase")


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
        _start(client, room["room_id"], room["host_token"])
        resp = client.get(
            f"/api/game/rooms/{room['room_id']}/state", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        state = resp.json()
        self.assertEqual(state["phase"], "spotlight_action")
        self.assertNotIn("join_qr_svg", state)

    def test_state_room_id_is_the_short_public_code_not_engine_internal_id(self):
        client = _client()
        room = _create_room(client)
        resp = client.get(
            f"/api/game/rooms/{room['room_id']}/state", headers=_headers(**{"X-Host-Token": room["host_token"]})
        )
        self.assertEqual(resp.json()["room_id"], room["room_id"])
        self.assertFalse(resp.json()["room_id"].startswith("room_"))

    def test_private_clue_visible_only_to_own_hero(self):
        client = _client()
        room = _create_room(client)
        guest = _join_room(client, room["room_id"])
        _start(client, room["room_id"], room["host_token"])
        host_view = _state(client, room["room_id"], {"X-Host-Token": room["host_token"]})
        guest_view = _state(client, room["room_id"], {"X-Player-Token": guest["player_token"]})
        self.assertTrue(host_view["you"]["private_clue"])
        self.assertTrue(guest_view["you"]["private_clue"])
        self.assertNotEqual(host_view["you"]["private_clue"], guest_view["you"]["private_clue"])
        self.assertNotIn(host_view["you"]["private_clue"], json.dumps(guest_view))


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


class ModuleHygieneTests(unittest.TestCase):
    def test_module_never_calls_logging(self):
        import backend.lan_playground.app as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("import logging", source)
        self.assertIsNone(re.search(r"\blogging\.\w+\(", source))


if __name__ == "__main__":
    unittest.main()
