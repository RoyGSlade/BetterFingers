"""Whole-game HTTP acceptance tests for Spellcheck & Sorcery (board task #45).

Every app under test is built via ``create_app`` with injected fakes
(call_fn/persona_lookup/persona_allowlist/engine_ready_fn) -- no real
model, no server.py, no network. The only background "waiting" is a
daemon thread standing in for a slow model (bounded ``.wait(timeout=...)``,
same pattern already used in tests/test_lan_game_api.py); nothing in a
test's own driving/polling logic ever sleeps or busy-waits, and no wall
clock is used for TTL -- a fake clock dict is injected instead.

This file drives full five-encounter games end-to-end through the real
HTTP + auth + rooms.py + app.py stack (create -> join x N -> start ->
submit -> auto-resolve -> reveal -> advance -> ... -> finished -> replay).
It deliberately does NOT re-litigate what tests/test_lan_game_api.py
(single-round HTTP contract), tests/test_lan_game_engine.py (pure engine
unit tests), or tests/test_lan_game_concurrency.py (thread races) already
cover -- only the whole-game acceptance altitude that nothing else
currently exercises.
"""

import threading
import time
import unittest

from fastapi.testclient import TestClient

from backend.lan_playground import game, rooms
from backend.lan_playground.app import create_app

ACCESS_CODE = "e2e-access-code"
ALLOWED_HOSTS = {"testserver"}
ALLOWED_ORIGINS = {"http://testserver"}


def _headers(**extra):
    return {"X-Access-Code": ACCESS_CODE, **extra}


def _build_app(*, room_manager=None, call_fn=None, **kwargs):
    defaults = dict(
        access_code=ACCESS_CODE,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=ALLOWED_ORIGINS,
        call_fn=call_fn if call_fn is not None else (lambda messages: ""),
        persona_lookup=lambda name: None,
        persona_allowlist=lambda: [],
        # Generous budgets: rate-limit *enforcement* is already covered by
        # tests/test_lan_game_api.py -- a whole-game run legitimately makes
        # more action/join calls than those per-route tests do, and hitting
        # a limit here would be incidental noise, not the thing under test.
        room_join_rate_limit_per_min=100,
        room_state_rate_limit_per_min=300,
        room_action_rate_limit_per_min=300,
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


def _submit(client, room_id, token_header, approach, text="a bounded one-line move"):
    return client.post(
        f"/api/game/rooms/{room_id}/moves",
        json={"move_text": text, "approach": approach, "card": approach},
        headers=_headers(**token_header),
    )


def _advance(client, room_id, host_token):
    resp = client.post(f"/api/game/rooms/{room_id}/advance", headers=_headers(**{"X-Host-Token": host_token}))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _state(client, room_id, token_header):
    resp = client.get(f"/api/game/rooms/{room_id}/state", headers=_headers(**token_header))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _weakness(room_manager, room_id):
    """The real, live engine Room's current weakness -- never exposed on
    the wire itself (public_state only ever sends id/name/flavor), so the
    test reads it the same way tests/test_lan_game_engine.py does: directly
    off the shared game.Room object rather than guessing/recomputing it."""
    return room_manager.get_room(room_id)._current_encounter().weakness


def _resistant(room_manager, room_id):
    return room_manager.get_room(room_id)._current_encounter().resistant


class SoloFullRunAndReplayTests(unittest.TestCase):
    """Solo, five-encounter run start->finished, then a full replay cycle."""

    def test_solo_five_encounter_victory_then_replay(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room = _create_room(client, seed=1)
        room_id, host_token = room["room_id"], room["host_token"]

        _start(client, room_id, host_token)

        for round_num in range(len(game.ENCOUNTERS)):
            approach = _weakness(mgr, room_id)
            resp = _submit(client, room_id, {"X-Host-Token": host_token}, approach)
            self.assertEqual(resp.status_code, 200, resp.text)
            state = resp.json()["state"]
            self.assertEqual(state["phase"], "reveal")
            self.assertEqual(state["last_round"]["damage"], 0)
            self.assertEqual(state["hearts"], game.STARTING_HEARTS)

            advanced = _advance(client, room_id, host_token)
            if round_num + 1 == len(game.ENCOUNTERS):
                self.assertEqual(advanced["phase"], "finished")
                self.assertTrue(advanced["finished_victory"])
            else:
                self.assertEqual(advanced["phase"], "choosing")

        final = _state(client, room_id, {"X-Host-Token": host_token})
        self.assertEqual(final["phase"], "finished")
        self.assertTrue(final["finished_victory"])
        self.assertEqual(final["hearts"], game.STARTING_HEARTS)
        self.assertEqual(len(final["history"]), len(game.ENCOUNTERS))

        replay_resp = client.post(
            f"/api/game/rooms/{room_id}/replay", headers=_headers(**{"X-Host-Token": host_token})
        )
        self.assertEqual(replay_resp.status_code, 200, replay_resp.text)
        replay_state = replay_resp.json()
        self.assertEqual(replay_state["phase"], "lobby")
        self.assertEqual(replay_state["hearts"], game.STARTING_HEARTS)
        self.assertEqual(replay_state["round_index"], 0)
        self.assertEqual(replay_state["history"], [])
        self.assertIsNone(replay_state["finished_victory"])
        self.assertTrue(replay_state["join_qr_svg"].startswith("<svg"))

        # Confirm the replayed room is actually playable, not just reset.
        _start(client, room_id, host_token)
        approach = _weakness(mgr, room_id)
        resp = _submit(client, room_id, {"X-Host-Token": host_token}, approach)
        self.assertEqual(resp.json()["state"]["phase"], "reveal")


class FourPlayerFullRunTests(unittest.TestCase):
    def test_four_players_join_start_all_submit_through_victory(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room = _create_room(client, host_name="P1", seed=3)
        room_id, host_token, host_id = room["room_id"], room["host_token"], room["player_id"]

        tokens = {host_id: {"X-Host-Token": host_token}}
        for name in ("P2", "P3", "P4"):
            joined = _join_room(client, room_id, name)
            tokens[joined["player_id"]] = {"X-Player-Token": joined["player_token"]}
        self.assertEqual(len(tokens), game.MAX_PLAYERS)

        _start(client, room_id, host_token)

        for round_num in range(len(game.ENCOUNTERS)):
            approach = _weakness(mgr, room_id)
            player_ids = list(tokens.keys())
            last_state = None
            for i, pid in enumerate(player_ids):
                resp = _submit(client, room_id, tokens[pid], approach)
                self.assertEqual(resp.status_code, 200, resp.text)
                last_state = resp.json()["state"]
                if i < len(player_ids) - 1:
                    self.assertEqual(last_state["phase"], "choosing")  # not everyone in yet
                    self.assertTrue(last_state["you"]["submitted"])

            # The last submitter's own response already shows the round
            # auto-resolved -- no separate client-facing "resolve" call.
            self.assertEqual(last_state["phase"], "reveal")
            self.assertEqual(last_state["last_round"]["successes"], game.MAX_PLAYERS)
            self.assertEqual(last_state["last_round"]["backfires"], 0)
            self.assertEqual(last_state["last_round"]["damage"], 0)

            advanced = _advance(client, room_id, host_token)
            if round_num + 1 == len(game.ENCOUNTERS):
                self.assertEqual(advanced["phase"], "finished")
                self.assertTrue(advanced["finished_victory"])
            else:
                self.assertEqual(advanced["phase"], "choosing")

        final = _state(client, room_id, tokens[host_id])
        self.assertEqual(final["hearts"], game.STARTING_HEARTS)
        self.assertEqual(len(final["history"]), len(game.ENCOUNTERS))
        for record in final["history"]:
            self.assertEqual(record["successes"], game.MAX_PLAYERS)


class SecrecyBeforeRevealTests(unittest.TestCase):
    def test_pre_reveal_state_hides_choices_until_all_submit(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room = _create_room(client, host_name="Host", seed=5)
        room_id, host_token, host_id = room["room_id"], room["host_token"], room["player_id"]
        guest = _join_room(client, room_id, "Guest")
        guest_id, guest_token = guest["player_id"], guest["player_token"]

        _start(client, room_id, host_token)

        weakness = _weakness(mgr, room_id)
        submit_resp = _submit(
            client, room_id, {"X-Host-Token": host_token}, weakness, text="totally secret host move"
        )
        self.assertEqual(submit_resp.status_code, 200)
        self.assertEqual(submit_resp.json()["state"]["phase"], "choosing")  # guest hasn't submitted yet

        host_view = _state(client, room_id, {"X-Host-Token": host_token})
        guest_view = _state(client, room_id, {"X-Player-Token": guest_token})

        for view, expect_you_submitted in ((host_view, True), (guest_view, False)):
            self.assertEqual(view["phase"], "choosing")
            self.assertIsNone(view["last_round"])
            self.assertEqual(view["history"], [])
            self.assertEqual(view["you"]["submitted"], expect_you_submitted)

        players_by_id = {p["player_id"]: p for p in guest_view["players"]}
        self.assertTrue(players_by_id[host_id]["submitted"])
        self.assertFalse(players_by_id[guest_id]["submitted"])

        # The host's not-yet-revealed move text must not leak into any
        # other player's state response, not even as a raw substring.
        raw_body = client.get(
            f"/api/game/rooms/{room_id}/state", headers=_headers(**{"X-Player-Token": guest_token})
        ).text
        self.assertNotIn("totally secret host move", raw_body)

        # Once the guest submits, the round auto-resolves and NOW both
        # approaches/texts are revealed to everyone.
        resp = _submit(client, room_id, {"X-Player-Token": guest_token}, weakness, text="guest reveal move")
        state = resp.json()["state"]
        self.assertEqual(state["phase"], "reveal")
        revealed_texts = {c["move_text"] for c in state["last_round"]["choices"]}
        self.assertIn("totally secret host move", revealed_texts)
        self.assertIn("guest reveal move", revealed_texts)


class DamageThenVictoryTests(unittest.TestCase):
    """Deterministic partial damage (mixed successes/backfires among 4
    players) followed by a clean run to victory -- exercises the
    max(0, backfires - successes) damage math over an HTTP whole game,
    not just a single engine-level round."""

    def test_deterministic_partial_damage_then_recovery_to_victory(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room = _create_room(client, host_name="P1", seed=11)
        room_id, host_token, host_id = room["room_id"], room["host_token"], room["player_id"]
        tokens = {host_id: {"X-Host-Token": host_token}}
        for name in ("P2", "P3", "P4"):
            joined = _join_room(client, room_id, name)
            tokens[joined["player_id"]] = {"X-Player-Token": joined["player_token"]}
        player_ids = list(tokens.keys())

        _start(client, room_id, host_token)

        expected_hearts_after_round0 = game.STARTING_HEARTS - 2
        for round_num in range(len(game.ENCOUNTERS)):
            weakness = _weakness(mgr, room_id)
            resistant = _resistant(mgr, room_id)
            approaches = {player_ids[0]: weakness}
            for pid in player_ids[1:]:
                approaches[pid] = resistant if round_num == 0 else weakness

            last_state = None
            for pid in player_ids:
                resp = _submit(client, room_id, tokens[pid], approaches[pid])
                self.assertEqual(resp.status_code, 200, resp.text)
                last_state = resp.json()["state"]

            record = last_state["last_round"]
            if round_num == 0:
                # 1 success (host), 3 backfires (guests) -> damage 2.
                self.assertEqual(record["successes"], 1)
                self.assertEqual(record["backfires"], 3)
                self.assertEqual(record["damage"], 2)
            else:
                self.assertEqual(record["damage"], 0)
            self.assertEqual(last_state["hearts"], expected_hearts_after_round0)

            advanced = _advance(client, room_id, host_token)
            if round_num + 1 == len(game.ENCOUNTERS):
                self.assertEqual(advanced["phase"], "finished")
                self.assertTrue(advanced["finished_victory"])
                self.assertEqual(advanced["hearts"], expected_hearts_after_round0)


class DefeatPathTests(unittest.TestCase):
    def test_solo_always_backfiring_ends_in_defeat_before_round_five(self):
        mgr = rooms.RoomManager()
        client = _client(room_manager=mgr)
        room = _create_room(client, host_name="Doomed", seed=21)
        room_id, host_token = room["room_id"], room["host_token"]
        _start(client, room_id, host_token)

        rounds_played = 0
        state = None
        for _ in range(game.STARTING_HEARTS):
            resistant = _resistant(mgr, room_id)
            resp = _submit(client, room_id, {"X-Host-Token": host_token}, resistant)
            self.assertEqual(resp.status_code, 200, resp.text)
            state = resp.json()["state"]
            rounds_played += 1
            if state["phase"] == "finished":
                break
            _advance(client, room_id, host_token)

        self.assertEqual(state["phase"], "finished")
        self.assertFalse(state["finished_victory"])
        self.assertEqual(state["hearts"], 0)
        self.assertEqual(rounds_played, game.STARTING_HEARTS)
        self.assertLess(len(state["history"]), len(game.ENCOUNTERS))


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

        # room_b's own host token legitimately works on room_b.
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
        self.assertIn(room_id, lobby_state["join_url"])

        _start(client, room_id, host_token)
        active_state = _state(client, room_id, {"X-Host-Token": host_token})
        self.assertNotIn("join_qr_svg", active_state)
        self.assertNotIn("join_url", active_state)
        self.assertNotIn("join_code", active_state)


class ModelFallbackFullGameTests(unittest.TestCase):
    """Model error, model-unavailable, and slow-model-beyond-timeout, each
    hit in a different round of the same live game -- confirms every mode
    falls back to the player's raw move text, never hangs the request, and
    never touches scoring (which only ever reads `approach`)."""

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
            move_polish_timeout_s=0.05,
        )
        room = _create_room(client, host_name="Solo", seed=1)
        room_id, host_token = room["room_id"], room["host_token"]
        _start(client, room_id, host_token)

        moves = (
            "round 1: model raises an exception",
            "round 2: model reports not ready",
            "round 3: model is too slow",
        )
        started = time.monotonic()
        for i, text in enumerate(moves):
            ready["ok"] = i != 1  # only round index 1 simulates model_unavailable
            weakness = _weakness(mgr, room_id)
            resp = _submit(client, room_id, {"X-Host-Token": host_token}, weakness, text=text)
            self.assertEqual(resp.status_code, 200, resp.text)
            state = resp.json()["state"]
            self.assertEqual(state["last_round"]["choices"][0]["move_text"], text)
            self.assertEqual(state["last_round"]["damage"], 0)  # scoring never touched by model failures
            _advance(client, room_id, host_token)
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
