"""Whole-game HTTP acceptance tests for The Lost Meaning (board task #2).

Every app under test is built via ``create_app`` with injected fakes
(call_fn/persona_lookup/persona_allowlist/engine_ready_fn) -- no real
model, no server.py, no network. This file drives full games end-to-end
through the real HTTP + auth + rooms.py + app.py + game.py stack (create ->
join x N -> start -> spotlight -> support -> open-draft -> draft -> approve
-> react -> resolve -> advance -> ... -> finished -> replay), including
companion auto-play for unclaimed/disconnected hero slots. It deliberately
does NOT re-litigate what tests/test_lan_game_api.py (single-route HTTP
contract) or tests/test_lan_game_concurrency.py (thread races) already
cover -- only the whole-game acceptance altitude neither of those touches.
"""

import json
import threading
import time
import unittest

from fastapi.testclient import TestClient

from backend.lan_playground import game, rooms
from backend.lan_playground.app import create_app

ACCESS_CODE = "e2e-access-code"
ALLOWED_HOSTS = {"testserver"}
ALLOWED_ORIGINS = {"http://testserver"}


def _rescue_json(faithful="ok", clearer="ok.", alternate="sure."):
    return json.dumps(
        {
            "assessment": {"intent": "", "ambiguity_risk": "low", "missing_details": [], "clarification_question": ""},
            "variants": {"faithful": faithful, "clearer": clearer, "alternate": alternate},
        }
    )


def _default_call_fn(messages):
    return _rescue_json()


def _headers(**extra):
    return {"X-Access-Code": ACCESS_CODE, **extra}


def _build_app(*, room_manager=None, call_fn=None, **kwargs):
    defaults = dict(
        access_code=ACCESS_CODE,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=ALLOWED_ORIGINS,
        call_fn=call_fn if call_fn is not None else _default_call_fn,
        persona_lookup=lambda name: None,
        persona_allowlist=lambda: [],
        # Generous budgets: rate-limit *enforcement* is already covered by
        # tests/test_lan_game_api.py -- a whole-game run legitimately makes
        # more action calls than those per-route tests do.
        room_join_rate_limit_per_min=100,
        room_state_rate_limit_per_min=300,
        room_action_rate_limit_per_min=300,
        room_draft_rate_limit_per_min=100,
    )
    if room_manager is not None:
        defaults["room_manager"] = room_manager
    defaults.update(kwargs)
    return create_app(**defaults)


def _client(**kwargs):
    return TestClient(_build_app(**kwargs))


def _create_room(client, host_name="Host", seed=1):
    resp = client.post("/api/game/rooms", json={"host_name": host_name, "seed": seed}, headers=_headers())
    assert resp.status_code == 201, resp.text
    return resp.json()


def _join_room(client, room_id, display_name):
    resp = client.post(
        f"/api/game/rooms/{room_id}/join",
        json={"display_name": display_name, "join_code": room_id},
        headers=_headers(),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start(client, room_id, host_token):
    resp = client.post(f"/api/game/rooms/{room_id}/start", headers=_headers(**{"X-Host-Token": host_token}))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _state(client, room_id, header):
    resp = client.get(f"/api/game/rooms/{room_id}/state", headers=_headers(**header))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _post(client, room_id, path, header, body=None):
    resp = client.post(f"/api/game/rooms/{room_id}{path}", json=body or {}, headers=_headers(**header))
    assert resp.status_code == 200, resp.text
    return resp.json()["state"] if "state" in resp.json() else resp.json()


def _play_one_players_step(client, room_id, header):
    """Drives exactly the current player's next action according to their
    own ``you.pending_step`` (an engine-provided field naming exactly what
    that viewer may do next). Returns the resulting state, or None if this
    player has nothing to do right now."""
    state = _state(client, room_id, header)
    step = state["you"]["pending_step"]
    if step is None:
        return None
    if step == "start":
        return _post(client, room_id, "/start", header)
    if step == "declare_action":
        hero = next(h for h in state["heroes"] if h["hero_id"] == state["spotlight_hero_id"])
        return _post(
            client,
            room_id,
            "/spotlight",
            header,
            {"move_id": hero["deck"][0]["id"], "target_id": state["encounter"]["targets"][0], "desired_outcome": "handle it"},
        )
    if step == "submit_support":
        return _post(client, room_id, "/support", header, {"kind": "assist", "detail": "backing them up"})
    if step == "open_draft":
        return _post(client, room_id, "/open-draft", header)
    if step == "submit_rough_text":
        return _post(client, room_id, "/draft", header, {"rough_text": "We handle it, plainly."})
    if step == "approve_message":
        draft = state["you"]["draft"]
        return _post(client, room_id, "/approve", header, {"chosen_text": draft["variants"][0], "intent": "resolve it"})
    if step == "submit_reaction":
        return _post(client, room_id, "/react", header, {"verb": "assist", "detail": "helping out"})
    if step == "resolve":
        return _post(client, room_id, "/resolve", header)
    if step == "advance":
        return _post(client, room_id, "/advance", header)
    if step == "replay":
        return _post(client, room_id, "/replay", header)
    raise AssertionError(f"unhandled pending_step {step!r}")


def _play_round_to_reveal(client, room_id, headers, max_iterations=40):
    """Cycles through every header's pending_step until the room reaches
    'reveal' or 'finished' -- bounded so a stuck state machine fails fast
    instead of hanging the suite."""
    for _ in range(max_iterations):
        state = _state(client, room_id, headers[0])
        if state["phase"] in ("reveal", "finished"):
            return state
        acted = False
        for header in headers:
            result = _play_one_players_step(client, room_id, header)
            if result is not None:
                acted = True
        if not acted:
            raise AssertionError(f"no header had a pending_step in phase {state['phase']!r} -- state machine stuck")
    raise AssertionError("round did not reach reveal/finished within bounded iterations")


def _play_full_game(client, room_id, headers, host_header, max_rounds=None):
    max_rounds = max_rounds or (len(game.ENCOUNTERS) + 2)
    state = None
    for _ in range(max_rounds):
        state = _play_round_to_reveal(client, room_id, headers)
        if state["phase"] == "finished":
            return state
        state = _post(client, room_id, "/advance", host_header)
        if state["phase"] == "finished":
            return state
    return state


class SoloFullRunAndReplayTests(unittest.TestCase):
    """Solo host (3 companion allies) drives a full multi-round game
    start->finished purely through their own pending_step, then a full
    replay cycle."""

    def test_solo_full_run_then_replay_is_playable_again(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room = _create_room(client, seed=1)
        room_id, host_token = room["room_id"], room["host_token"]
        host_header = {"X-Host-Token": host_token}

        final = _play_full_game(client, room_id, [host_header], host_header)
        self.assertEqual(final["phase"], "finished")
        self.assertIn(final["finished_victory"], (True, False))
        self.assertGreaterEqual(len(final["history"]), 1)
        self.assertLessEqual(len(final["history"]), len(game.ENCOUNTERS))
        for record in final["history"]:
            self.assertTrue(record["narration"])
            self.assertIn("die_roll", record)
            self.assertTrue(record["modifiers"])

        replay_resp = client.post(f"/api/game/rooms/{room_id}/replay", headers=_headers(**host_header))
        self.assertEqual(replay_resp.status_code, 200, replay_resp.text)
        replay_state = replay_resp.json()
        self.assertEqual(replay_state["phase"], "lobby")
        self.assertEqual(replay_state["hearts"], game.STARTING_HEARTS)
        self.assertEqual(replay_state["round_index"], 0)
        self.assertEqual(replay_state["history"], [])
        self.assertIsNone(replay_state["finished_victory"])
        self.assertTrue(replay_state["join_qr_svg"].startswith("<svg"))

        # Confirm the replayed room is actually playable, not just reset --
        # play exactly round 0 again (not _play_full_game, which also calls
        # /advance once it reaches reveal: since round 1's spotlight can be
        # a companion that autoplay immediately declares for, that would
        # leave phase mid-ally_support, not at a clean round boundary).
        second_round_state = _play_round_to_reveal(client, room_id, [host_header])
        self.assertIn(second_round_state["phase"], ("reveal", "finished"))


class FourPlayerFullRunTests(unittest.TestCase):
    def test_four_players_join_bind_distinct_heroes_and_play_one_full_round(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room = _create_room(client, host_name="P1", seed=3)
        room_id, host_token = room["room_id"], room["host_token"]
        headers = [{"X-Host-Token": host_token}]
        for name in ("P2", "P3", "P4"):
            joined = _join_room(client, room_id, name)
            headers.append({"X-Player-Token": joined["player_token"]})
        self.assertEqual(len(headers), game.MAX_PLAYERS)

        lobby_state = _state(client, room_id, headers[0])
        hero_ids = {p["hero_id"] for p in lobby_state["players"]}
        self.assertEqual(len(hero_ids), game.MAX_PLAYERS)  # every player bound a distinct hero

        _start(client, room_id, host_token)
        state = _play_round_to_reveal(client, room_id, headers)
        self.assertEqual(state["phase"], "reveal")
        self.assertEqual(len(state["last_round"]["support"]), game.MAX_PLAYERS - 1)  # every ally, not the spotlight
        self.assertEqual(len(state["last_round"]["reactions"]), game.MAX_PLAYERS - 1)
        # No companions in a full 4-human room.
        for hero in state["heroes"]:
            self.assertFalse(hero["is_companion"])

        advanced = _post(client, room_id, "/advance", headers[0])
        self.assertIn(advanced["phase"], ("spotlight_action", "finished"))


class SecrecyBeforeRevealTests(unittest.TestCase):
    def test_support_and_reaction_content_hidden_until_resolve_and_clues_are_asymmetric(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room = _create_room(client, host_name="Host", seed=5)
        room_id, host_token = room["room_id"], room["host_token"]
        guest = _join_room(client, room_id, "Guest")
        host_header = {"X-Host-Token": host_token}
        guest_header = {"X-Player-Token": guest["player_token"]}

        _start(client, room_id, host_token)
        host_state = _state(client, room_id, host_header)
        guest_state = _state(client, room_id, guest_header)
        self.assertNotEqual(host_state["you"]["private_clue"], guest_state["you"]["private_clue"])
        self.assertNotIn(host_state["you"]["private_clue"], json.dumps(guest_state))

        # Host is spotlight round 0 -- drive to ally_support then have the
        # guest submit a support with secret content.
        _play_one_players_step(client, room_id, host_header)  # declare_action
        _post(
            client, room_id, "/support", guest_header, {"kind": "clue", "detail": "totally secret support content"}
        )
        raw_host_view = client.get(f"/api/game/rooms/{room_id}/state", headers=_headers(**host_header)).text
        self.assertNotIn("totally secret support content", raw_host_view)

        # Finish the round (companions fill remaining allies; guest already went).
        state = _play_round_to_reveal(client, room_id, [host_header, guest_header])
        self.assertEqual(state["phase"], "reveal")
        support_details = [s["detail"] for s in state["last_round"]["support"]]
        self.assertIn("totally secret support content", support_details)


class TokenAuthAcceptanceTests(unittest.TestCase):
    def test_invalid_and_cross_room_tokens_are_rejected(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room_a = _create_room(client, host_name="A-Host", seed=1)
        room_b = _create_room(client, host_name="B-Host", seed=2)

        garbage = client.get(
            f"/api/game/rooms/{room_a['room_id']}/state", headers=_headers(**{"X-Host-Token": "not-a-real-token"})
        )
        self.assertEqual(garbage.status_code, 401)

        cross_room_state = client.get(
            f"/api/game/rooms/{room_a['room_id']}/state",
            headers=_headers(**{"X-Host-Token": room_b["host_token"]}),
        )
        self.assertEqual(cross_room_state.status_code, 401)

        cross_room_start = client.post(
            f"/api/game/rooms/{room_a['room_id']}/start",
            headers=_headers(**{"X-Host-Token": room_b["host_token"]}),
        )
        self.assertEqual(cross_room_start.status_code, 401)

        own_room = client.get(
            f"/api/game/rooms/{room_b['room_id']}/state", headers=_headers(**{"X-Host-Token": room_b["host_token"]})
        )
        self.assertEqual(own_room.status_code, 200)


class QRLobbyOnlyAcceptanceTests(unittest.TestCase):
    def test_qr_present_only_in_lobby_and_encodes_the_join_code(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room = _create_room(client, host_name="Host", seed=1)
        room_id, host_token = room["room_id"], room["host_token"]

        self.assertTrue(room["join_qr_svg"].startswith("<svg"))
        self.assertIn(room_id, room["join_url"])

        lobby_state = _state(client, room_id, {"X-Host-Token": host_token})
        self.assertTrue(lobby_state["join_qr_svg"].startswith("<svg"))
        self.assertEqual(lobby_state["join_code"], room_id)

        _start(client, room_id, host_token)
        active_state = _state(client, room_id, {"X-Host-Token": host_token})
        self.assertNotIn("join_qr_svg", active_state)
        self.assertNotIn("join_url", active_state)
        self.assertNotIn("join_code", active_state)


class ModelFallbackFullGameTests(unittest.TestCase):
    """Model error, model-unavailable, and slow-model-beyond-timeout, each
    hit on a different round of the same live solo game -- confirms every
    mode falls back safely, never hangs the request, and never touches
    scoring (which only ever reads move_id/target_id/verb + the seeded
    die, never draft/variant/approved text)."""

    def test_model_unavailable_error_and_slow_all_fall_back_safely(self):
        calls = {"n": 0}
        release = threading.Event()
        ready = {"ok": True}

        def flaky_call_fn(messages):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("model exploded")
            release.wait(timeout=5)  # background thread only -- never the test's own wait
            return "should never be used -- timeout beats it"

        mgr = rooms.RoomManager()
        client = _client(
            room_manager=mgr,
            call_fn=flaky_call_fn,
            engine_ready_fn=lambda: ready["ok"],
            draft_timeout_s=0.05,
            narration_timeout_s=0.05,
        )
        room = _create_room(client, host_name="Solo", seed=1)
        room_id, host_token = room["room_id"], room["host_token"]
        host_header = {"X-Host-Token": host_token}
        _start(client, room_id, host_token)

        started = time.monotonic()
        for i in range(3):
            ready["ok"] = i != 1  # round index 1 simulates model_unavailable
            state = _play_round_to_reveal(client, room_id, [host_header])
            self.assertEqual(state["phase"], "reveal")
            self.assertTrue(state["last_round"]["narration"])  # deterministic fallback, never empty
            if state["phase"] != "finished":
                _post(client, room_id, "/advance", host_header)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 3.0)
        release.set()


class ExpiredPrunedRoomTests(unittest.TestCase):
    def test_expired_room_becomes_404_everywhere(self):
        clock = {"t": 0.0}
        mgr = rooms.RoomManager(clock=lambda: clock["t"], ttl_s=100.0)
        client = _client(room_manager=mgr)
        room = _create_room(client, host_name="Ghost", seed=1)
        room_id, host_token = room["room_id"], room["host_token"]

        state = _state(client, room_id, {"X-Host-Token": host_token})
        self.assertEqual(state["phase"], "lobby")

        clock["t"] = 500.0  # well past ttl_s=100 with no activity since

        expired_state = client.get(
            f"/api/game/rooms/{room_id}/state", headers=_headers(**{"X-Host-Token": host_token})
        )
        self.assertEqual(expired_state.status_code, 404)

        expired_join = client.post(
            f"/api/game/rooms/{room_id}/join",
            json={"display_name": "TooLate", "join_code": room_id},
            headers=_headers(),
        )
        self.assertEqual(expired_join.status_code, 404)

        expired_start = client.post(
            f"/api/game/rooms/{room_id}/start", headers=_headers(**{"X-Host-Token": host_token})
        )
        self.assertEqual(expired_start.status_code, 404)


if __name__ == "__main__":
    unittest.main()
