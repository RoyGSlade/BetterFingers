"""Route/protocol tests for The Lost Meaning: Infinite Stacks transport
(board task #3), covering infinite_stacks.md S21.2 / docs/INFINITE_STACKS_CONTRACTS.md:

- expected-revision conflict -> CommandError with a current legal-action
  summary, never a bare error;
- idempotent command replay (same idempotency_key) is a no-op;
- reconnect delivers a snapshot plus a missed-event summary;
- viewer-filtered projections: no viewer ever receives another hero's
  private_clue, over REST snapshot or the WebSocket event stream.

Every test builds its own app via `create_stacks_app` -- no shared server
process, no real model calls. Mirrors the DI-with-a-fresh-app-per-test
pattern in tests/test_lan_game_api.py.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.lan_playground.stacks_api import StacksRoomManager, create_stacks_app
from backend.lan_playground.stacks_engine import StacksEngineAdapter
from backend.lan_playground.stacks_protocol import Command

ACCESS_CODE = "test-stacks-access-code"
ALLOWED_HOSTS = {"testserver"}
ALLOWED_ORIGINS: set[str] = set()

ACCESS_HEADER = {"X-Access-Code": ACCESS_CODE}


def _build_app(**kwargs):
    defaults = dict(
        access_code=ACCESS_CODE,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=ALLOWED_ORIGINS,
        room_manager=StacksRoomManager(StacksEngineAdapter()),
    )
    defaults.update(kwargs)
    return create_stacks_app(**defaults)


def _client(**kwargs) -> TestClient:
    return TestClient(_build_app(**kwargs))


def _token_header(token: str) -> dict[str, str]:
    return {"X-Player-Token": token}


def _create_room(client: TestClient, host_name: str = "Host", seed: int | None = None) -> dict:
    resp = client.post("/api/stacks/rooms", json={"host_name": host_name, "seed": seed}, headers=ACCESS_HEADER)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _join_room(client: TestClient, code: str, display_name: str) -> dict:
    resp = client.post(f"/api/stacks/rooms/{code}/join", json={"display_name": display_name}, headers=ACCESS_HEADER)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _submit(client: TestClient, code: str, token: str, **body_overrides):
    body = dict(command_id="cmd-1", idempotency_key="idem-1", expected_revision=0, type="pass", payload={})
    body.update(body_overrides)
    headers = {**ACCESS_HEADER, **_token_header(token)}
    return client.post(f"/api/stacks/rooms/{code}/commands", json=body, headers=headers)


def _first_breach_direction(state, hero_id: str) -> str | None:
    room = state.rooms[state.heroes[hero_id].room_id]
    for direction, connector in room.connectors.items():
        if connector.state == "undiscovered":
            return direction
    return None


def _seed_with_first_breach_family(target_family: str, *, upper_bound: int = 2000) -> int:
    # The real engine generates the whole map topology (burning a variable
    # number of RNG draws) before any breach ever rolls its d8, so a bare
    # Random(seed).randint(1, 8) no longer predicts the roll -- scan seeds
    # through the real engine instead and read the emitted event's family.
    # Which of the entrance's DOOR directions gets breached doesn't change
    # the d8 draw's position in the stream (direction choice draws no
    # randomness), so any valid direction is representative here.
    for seed in range(upper_bound):
        adapter = StacksEngineAdapter()
        state = adapter.create_run(seed=seed)
        adapter.apply(
            state,
            Command(
                command_id="seed-scan-join",
                idempotency_key="seed-scan-join",
                run_id=state.run_id,
                hero_id="hero_host",
                encounter_id=None,
                expected_revision=state.revision,
                type="join_run",
                payload={"display_name": "Host"},
            ),
        )
        direction = _first_breach_direction(state, "hero_host")
        if direction is None:
            continue
        result = adapter.apply(
            state,
            Command(
                command_id="seed-scan-breach",
                idempotency_key="seed-scan-breach",
                run_id=state.run_id,
                hero_id="hero_host",
                encounter_id=None,
                expected_revision=state.revision,
                type="breach",
                payload={"direction": direction},
            ),
        )
        family = next((e.payload["family"] for e in result.events if e.type == "die_rolled"), None)
        if family == target_family:
            return seed
    raise AssertionError("no seed found in range")


class RevisionConflictTests(unittest.TestCase):
    def test_stale_revision_returns_legal_actions_not_bare_error(self):
        client = _client()
        room = _create_room(client)
        code, token = room["room_code"], room["player_token"]

        resp = _submit(
            client,
            code,
            token,
            command_id="cmd-stale",
            idempotency_key="idem-stale",
            expected_revision=999,
            type="pass",
        )
        self.assertEqual(resp.status_code, 409)
        detail = resp.json()["detail"]
        self.assertEqual(detail["code"], "stale_revision")
        legal = detail["legal_actions"]
        self.assertIn("revision", legal)
        self.assertIn("can_pass", legal)
        self.assertEqual(legal["hero_id"], room["hero_id"])

    def test_correct_revision_is_accepted(self):
        client = _client()
        room = _create_room(client)
        code, token = room["room_code"], room["player_token"]

        resp = _submit(
            client,
            code,
            token,
            command_id="cmd-ok",
            idempotency_key="idem-ok",
            expected_revision=room["revision"],
            type="pass",
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["revision"], room["revision"] + 1)


class IdempotencyTests(unittest.TestCase):
    def test_replaying_same_idempotency_key_is_a_noop(self):
        client = _client()
        room = _create_room(client)
        code, token = room["room_code"], room["player_token"]

        first = _submit(
            client,
            code,
            token,
            command_id="cmd-dup",
            idempotency_key="idem-dup",
            expected_revision=room["revision"],
            type="pass",
        )
        self.assertEqual(first.status_code, 200)
        first_body = first.json()
        self.assertFalse(first_body["replayed"])

        # Same idempotency_key again, even with a now-stale expected_revision
        # -- contract S2: idempotent-safe replay bypasses the revision check.
        second = _submit(
            client,
            code,
            token,
            command_id="cmd-dup",
            idempotency_key="idem-dup",
            expected_revision=room["revision"],  # stale by now, but must not matter
            type="pass",
        )
        self.assertEqual(second.status_code, 200)
        second_body = second.json()
        self.assertTrue(second_body["replayed"])
        self.assertEqual(second_body["revision"], first_body["revision"])
        self.assertEqual(second_body["events"], first_body["events"])

    def test_replay_does_not_double_apply_state_change(self):
        client = _client()
        room = _create_room(client)
        code, token = room["room_code"], room["player_token"]

        for _ in range(3):
            resp = _submit(
                client,
                code,
                token,
                command_id="cmd-move-dup",
                idempotency_key="idem-move-dup",
                expected_revision=room["revision"],
                type="pass",
            )
        # Three identical submissions must still land on revision+1, not +3.
        self.assertEqual(resp.json()["revision"], room["revision"] + 1)


class ReconnectTests(unittest.TestCase):
    def test_ws_connect_sends_snapshot_and_missed_events(self):
        client = _client()
        room = _create_room(client)
        code, token = room["room_code"], room["player_token"]
        other = _join_room(client, code, "Ally")

        url = f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={token}&since_revision=0"
        with client.websocket_connect(url) as ws:
            first = ws.receive_json()
            self.assertEqual(first["kind"], "reconnect_summary")
            self.assertEqual(first["since_revision"], 0)
            self.assertIn("snapshot", first)
            self.assertEqual(first["snapshot"]["view"]["viewer"], room["hero_id"])
            # Ally already joined before this socket connected -- that's a
            # missed public event this connection should see on connect.
            missed_types = [e["type"] for e in first["missed_events"]]
            self.assertIn("hero_joined", missed_types)

        # Reconnect with since_revision advanced past the join: no more
        # missed events, but the snapshot must still reflect current state.
        with client.websocket_connect(
            f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={token}&since_revision={other['revision']}"
        ) as ws:
            second = ws.receive_json()
            self.assertEqual(second["missed_events"], [])
            self.assertEqual(second["snapshot"]["revision"], other["revision"])

    def test_missed_events_since_last_seen_revision_only(self):
        client = _client()
        room = _create_room(client)
        code, token = room["room_code"], room["player_token"]
        _join_room(client, code, "Ally")

        # Connect once, note the revision we're caught up to, then disconnect.
        with client.websocket_connect(f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={token}") as ws:
            snapshot = ws.receive_json()
            seen_revision = snapshot["snapshot"]["revision"]

        pass_resp = _submit(
            client,
            code,
            token,
            command_id="cmd-between",
            idempotency_key="idem-between",
            expected_revision=seen_revision,
            type="pass",
        )
        self.assertEqual(pass_resp.status_code, 200)

        with client.websocket_connect(
            f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={token}&since_revision={seen_revision}"
        ) as ws:
            reconnect = ws.receive_json()
            missed_types = [e["type"] for e in reconnect["missed_events"]]
            self.assertIn("turn_passed", missed_types)


class ProjectionPrivacyTests(unittest.TestCase):
    def _room_with_private_clue_via_breach(self):
        seed = _seed_with_first_breach_family("mystery_chamber")
        client = _client()
        room = _create_room(client, seed=seed)
        code, host_token, host_hero = room["room_code"], room["player_token"], room["hero_id"]
        ally = _join_room(client, code, "Ally")
        ally_token, ally_hero = ally["player_token"], ally["hero_id"]

        # Read the entrance's actual DOOR connectors from the projected
        # snapshot rather than assuming a fixed direction -- the real map
        # topology is randomized and "north" isn't guaranteed to be a door.
        snapshot = client.get(
            f"/api/stacks/rooms/{code}/snapshot", headers={**ACCESS_HEADER, **_token_header(host_token)}
        ).json()["view"]
        host_room = snapshot["rooms"][snapshot["heroes"][host_hero]["room_id"]]
        direction = next(d for d, c in host_room["connectors"].items() if c["state"] == "undiscovered")

        breach = _submit(
            client,
            code,
            host_token,
            command_id="cmd-breach",
            idempotency_key="idem-breach",
            expected_revision=ally["revision"],
            type="breach",
            payload={"direction": direction},
        )
        self.assertEqual(breach.status_code, 200, breach.text)
        events = breach.json()["events"]
        self.assertTrue(any(e["type"] == "private_clue_assigned" for e in events))
        return client, code, host_token, host_hero, ally_token, ally_hero

    def test_snapshot_never_exposes_another_heros_private_clue(self):
        client, code, host_token, host_hero, ally_token, ally_hero = self._room_with_private_clue_via_breach()

        own_view = client.get(
            f"/api/stacks/rooms/{code}/snapshot", headers={**ACCESS_HEADER, **_token_header(host_token)}
        ).json()["view"]
        self.assertIsNotNone(own_view["heroes"][host_hero]["private_clue"])

        other_view = client.get(
            f"/api/stacks/rooms/{code}/snapshot", headers={**ACCESS_HEADER, **_token_header(ally_token)}
        ).json()["view"]
        # The ally's own hero entry may or may not carry the key (None if
        # never assigned), but the host's entry as seen by the ally must
        # never carry the field at all -- not even as null.
        self.assertNotIn("private_clue", other_view["heroes"][host_hero])

    def test_ws_broadcast_never_pushes_private_event_to_other_viewer(self):
        client, code, host_token, host_hero, ally_token, ally_hero = self._room_with_private_clue_via_breach()

        # The private_clue_assigned event was produced by a REST call before
        # either socket connects, so this exercises the same visibility
        # filter via the reconnect missed-events path (events_since), which
        # ConnectionHub.broadcast_event also shares (Event.visible_to_viewer).
        with client.websocket_connect(f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={host_token}") as host_ws:
            host_first = host_ws.receive_json()
            host_missed_types = [e["type"] for e in host_first["missed_events"]]
            self.assertIn("private_clue_assigned", host_missed_types)

        with client.websocket_connect(f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={ally_token}") as ally_ws:
            ally_first = ally_ws.receive_json()
            ally_missed_types = [e["type"] for e in ally_first["missed_events"]]
            self.assertNotIn("private_clue_assigned", ally_missed_types)
            for event in ally_first["missed_events"]:
                self.assertNotIn("clue", event["payload"])

    def test_room_secrets_never_serialized_in_any_projection(self):
        client, code, host_token, host_hero, ally_token, ally_hero = self._room_with_private_clue_via_breach()
        for token in (host_token, ally_token):
            view = client.get(
                f"/api/stacks/rooms/{code}/snapshot", headers={**ACCESS_HEADER, **_token_header(token)}
            ).json()["view"]
            for room_payload in view["rooms"].values():
                self.assertNotIn("secrets", room_payload)


class AuthAndPolicyTests(unittest.TestCase):
    def test_commands_require_valid_player_token(self):
        client = _client()
        room = _create_room(client)
        resp = _submit(client, room["room_code"], "not-a-real-token", expected_revision=room["revision"])
        self.assertEqual(resp.status_code, 401)

    def test_commands_require_access_code(self):
        client = _client()
        room = _create_room(client)
        resp = client.post(
            f"/api/stacks/rooms/{room['room_code']}/commands",
            json=dict(
                command_id="cmd-noaccess",
                idempotency_key="idem-noaccess",
                expected_revision=room["revision"],
                type="pass",
                payload={},
            ),
            headers=_token_header(room["player_token"]),
        )
        self.assertEqual(resp.status_code, 401)

    def test_unknown_room_join_returns_404(self):
        client = _client()
        resp = client.post(
            "/api/stacks/rooms/NOPE1234/join", json={"display_name": "Nobody"}, headers=ACCESS_HEADER
        )
        self.assertEqual(resp.status_code, 404)

    def test_unknown_room_snapshot_with_invalid_token_returns_401_not_404(self):
        # Token lookup fails closed before room existence is checked, so an
        # unknown room code doesn't leak whether it ever existed.
        client = _client()
        resp = client.get(
            "/api/stacks/rooms/NOPE1234/snapshot", headers={**ACCESS_HEADER, **_token_header("whatever")}
        )
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
