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

import asyncio
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


def _snapshot(client: TestClient, code: str, token: str) -> dict:
    resp = client.get(f"/api/stacks/rooms/{code}/snapshot", headers={**ACCESS_HEADER, **_token_header(token)})
    assert resp.status_code == 200, resp.text
    return resp.json()["view"]


def _content_catalog(client: TestClient) -> dict:
    resp = client.get("/api/stacks/content-catalog", headers=ACCESS_HEADER)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _first_live_general_and_persona_cards(catalog: dict) -> tuple[list[str], str]:
    general = [cid for cid, c in catalog["cards"].items() if c["source"] == "general" and c["live_at_creation"]][:2]
    persona = next(cid for cid, c in catalog["cards"].items() if c["source"] == "persona")
    return general, persona


def _make_hero(client: TestClient, code: str, token: str, name: str, catalog: dict, cmd_prefix: str) -> dict:
    """roll_attribute_dice -> create_hero over REST, returning the final
    command response body (so callers can inspect its `events`)."""
    background_id = sorted(catalog["backgrounds"])[0]
    general_card_ids, persona_card_id = _first_live_general_and_persona_cards(catalog)

    revision = _snapshot(client, code, token)["revision"]
    roll_resp = _submit(
        client, code, token, command_id=f"{cmd_prefix}-roll", idempotency_key=f"{cmd_prefix}-roll",
        expected_revision=revision, type="roll_attribute_dice",
    )
    assert roll_resp.status_code == 200, roll_resp.text
    roll_body = roll_resp.json()
    dice = roll_body["events"][0]["payload"]["dice"]
    attribute_names = ("force", "finesse", "insight", "presence")
    assignment = dict(zip(attribute_names, dice))

    create_resp = _submit(
        client, code, token, command_id=f"{cmd_prefix}-create", idempotency_key=f"{cmd_prefix}-create",
        expected_revision=roll_body["revision"], type="create_hero",
        payload={
            "name": name,
            "background_id": background_id,
            "attribute_assignment": assignment,
            "general_card_ids": general_card_ids,
            "persona_card_id": persona_card_id,
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    return create_resp.json()


class ContentCatalogTests(unittest.TestCase):
    def test_catalog_lists_backgrounds_cards_and_items(self):
        client = _client()
        catalog = _content_catalog(client)
        self.assertEqual(len(catalog["backgrounds"]), 4)
        self.assertGreaterEqual(len(catalog["cards"]), 20)
        self.assertGreaterEqual(len(catalog["items"]), 15)
        # Every card declares whether it can be picked at creation this wave
        # (heroes.deck.build_starting_deck's LIVE-op build-time gate) so the
        # character-builder picker never offers a card that would 400.
        for card in catalog["cards"].values():
            self.assertIn("live_at_creation", card)
        general_cards, persona_card = _first_live_general_and_persona_cards(catalog)
        self.assertEqual(len(general_cards), 2)
        self.assertEqual(catalog["cards"][persona_card]["source"], "persona")

    def test_catalog_requires_access_code(self):
        client = _client()
        resp = client.get("/api/stacks/content-catalog")
        self.assertEqual(resp.status_code, 401)


class HeroCreationTests(unittest.TestCase):
    def test_roll_then_create_hero_emits_public_sheet_and_private_hand(self):
        client = _client()
        room = _create_room(client)
        code, token, hero_id = room["room_code"], room["player_token"], room["hero_id"]
        catalog = _content_catalog(client)

        result = _make_hero(client, code, token, "Rey", catalog, "h1")
        event_types = [e["type"] for e in result["events"]]
        self.assertIn("hero_created", event_types)
        self.assertIn("hand_dealt", event_types)

        hero_created = next(e for e in result["events"] if e["type"] == "hero_created")
        self.assertEqual(hero_created["visibility"], "public")
        self.assertNotIn("hand", hero_created["payload"])
        self.assertIn("card_ids", hero_created["payload"]["deck"])
        self.assertEqual(hero_created["payload"]["deck"]["hand_count"], 4)

        hand_dealt = next(e for e in result["events"] if e["type"] == "hand_dealt")
        self.assertEqual(hand_dealt["visibility"], "private")
        self.assertEqual(len(hand_dealt["payload"]["hand"]), 4)

        view = _snapshot(client, code, token)
        self.assertEqual(len(view["heroes"][hero_id]["hand"]), 4)
        self.assertIsNotNone(view["heroes"][hero_id]["sheet"])
        self.assertEqual(view["heroes"][hero_id]["deck"]["hand_count"], 4)

    def test_hand_and_pending_dice_never_leak_to_another_viewer(self):
        client = _client()
        room = _create_room(client)
        code, token, hero_id = room["room_code"], room["player_token"], room["hero_id"]
        ally = _join_room(client, code, "Ally")
        ally_token = ally["player_token"]
        catalog = _content_catalog(client)

        _make_hero(client, code, token, "Rey", catalog, "h1")

        own_view = _snapshot(client, code, token)
        self.assertIn("hand", own_view["heroes"][hero_id])

        other_view = _snapshot(client, code, ally_token)
        self.assertNotIn("hand", other_view["heroes"][hero_id])
        # Deck COMPOSITION (the full owned card set) is public character-sheet
        # info -- only the hand/draw-pile order is private.
        self.assertEqual(other_view["heroes"][hero_id]["deck"]["card_ids"], own_view["heroes"][hero_id]["deck"]["card_ids"])
        self.assertIsNotNone(other_view["heroes"][hero_id]["sheet"])

    def test_ws_missed_events_never_deliver_hand_dealt_to_another_viewer(self):
        client = _client()
        room = _create_room(client)
        code, token, hero_id = room["room_code"], room["player_token"], room["hero_id"]
        ally = _join_room(client, code, "Ally")
        ally_token = ally["player_token"]
        catalog = _content_catalog(client)

        _make_hero(client, code, token, "Rey", catalog, "h1")

        with client.websocket_connect(f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={token}") as host_ws:
            host_first = host_ws.receive_json()
            self.assertIn("hand_dealt", [e["type"] for e in host_first["missed_events"]])

        with client.websocket_connect(f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={ally_token}") as ally_ws:
            ally_first = ally_ws.receive_json()
            self.assertNotIn("hand_dealt", [e["type"] for e in ally_first["missed_events"]])
            for event in ally_first["missed_events"]:
                self.assertNotIn("hand", event["payload"])

    def test_card_drawn_is_private_to_the_drawing_hero(self):
        client = _client()
        room = _create_room(client)
        code, token, hero_id = room["room_code"], room["player_token"], room["hero_id"]
        ally = _join_room(client, code, "Ally")
        ally_token = ally["player_token"]
        catalog = _content_catalog(client)

        create_result = _make_hero(client, code, token, "Rey", catalog, "h1")
        # Play a card first so the deck isn't empty and a fresh draw is legal.
        hand = next(e for e in create_result["events"] if e["type"] == "hand_dealt")["payload"]["hand"]
        revision = create_result["revision"]
        play_resp = _submit(
            client, code, token, command_id="play1", idempotency_key="play1",
            expected_revision=revision, type="play_card", payload={"card_id": hand[0]},
        )
        self.assertEqual(play_resp.status_code, 200, play_resp.text)

        draw_resp = _submit(
            client, code, token, command_id="draw1", idempotency_key="draw1",
            expected_revision=play_resp.json()["revision"], type="draw_cards", payload={"count": 1},
        )
        self.assertEqual(draw_resp.status_code, 200, draw_resp.text)
        draw_event = next(e for e in draw_resp.json()["events"] if e["type"] == "card_drawn")
        self.assertEqual(draw_event["visibility"], "private")

        own_view = _snapshot(client, code, token)
        other_view = _snapshot(client, code, ally_token)
        self.assertIn("hand", own_view["heroes"][hero_id])
        self.assertNotIn("hand", other_view["heroes"][hero_id])


class ItemInventoryTests(unittest.TestCase):
    def test_drop_then_pickup_by_another_hero_round_trips_through_ground_items(self):
        client = _client()
        room = _create_room(client)
        code, token, hero_id = room["room_code"], room["player_token"], room["hero_id"]
        ally = _join_room(client, code, "Ally")
        ally_token, ally_hero_id = ally["player_token"], ally["hero_id"]
        catalog = _content_catalog(client)

        _make_hero(client, code, token, "Rey", catalog, "h1")
        _make_hero(client, code, ally_token, "Sam", catalog, "h2")

        view = _snapshot(client, code, token)
        item_id = view["heroes"][hero_id]["inventory"]["items"][0]

        drop_resp = _submit(
            client, code, token, command_id="drop1", idempotency_key="drop1",
            expected_revision=view["revision"], type="drop_item", payload={"item_id": item_id},
        )
        self.assertEqual(drop_resp.status_code, 200, drop_resp.text)
        drop_event = next(e for e in drop_resp.json()["events"] if e["type"] == "item_dropped")
        instance_id = drop_event["payload"]["item_instance_id"]
        self.assertNotIn(item_id, drop_event["payload"]["inventory"]["items"])

        room_id = view["heroes"][hero_id]["room_id"]
        after_drop = _snapshot(client, code, token)
        self.assertEqual(after_drop["rooms"][room_id]["ground_items"][instance_id], item_id)

        ally_view = _snapshot(client, code, ally_token)
        pickup_resp = _submit(
            client, code, ally_token, command_id="pick1", idempotency_key="pick1",
            expected_revision=ally_view["revision"], type="pickup_item", payload={"item_instance_id": instance_id},
        )
        self.assertEqual(pickup_resp.status_code, 200, pickup_resp.text)
        pickup_event = next(e for e in pickup_resp.json()["events"] if e["type"] == "item_picked_up")
        self.assertIn(item_id, pickup_event["payload"]["inventory"]["items"])

        final = _snapshot(client, code, ally_token)
        self.assertNotIn(instance_id, final["rooms"][room_id]["ground_items"])
        self.assertIn(item_id, final["heroes"][ally_hero_id]["inventory"]["items"])

    def test_trade_item_between_two_heroes_in_same_room(self):
        client = _client()
        room = _create_room(client)
        code, token, hero_id = room["room_code"], room["player_token"], room["hero_id"]
        ally = _join_room(client, code, "Ally")
        ally_token, ally_hero_id = ally["player_token"], ally["hero_id"]
        catalog = _content_catalog(client)

        _make_hero(client, code, token, "Rey", catalog, "h1")
        _make_hero(client, code, ally_token, "Sam", catalog, "h2")

        view = _snapshot(client, code, token)
        item_id = view["heroes"][hero_id]["inventory"]["items"][0]

        trade_resp = _submit(
            client, code, token, command_id="trade1", idempotency_key="trade1",
            expected_revision=view["revision"], type="trade_item",
            payload={"to_hero_id": ally_hero_id, "item_id": item_id},
        )
        self.assertEqual(trade_resp.status_code, 200, trade_resp.text)
        trade_event = next(e for e in trade_resp.json()["events"] if e["type"] == "item_traded")
        self.assertEqual(trade_event["payload"]["from_hero_id"], hero_id)
        self.assertEqual(trade_event["payload"]["to_hero_id"], ally_hero_id)

        final = _snapshot(client, code, token)
        self.assertNotIn(item_id, final["heroes"][hero_id]["inventory"]["items"])
        self.assertIn(item_id, final["heroes"][ally_hero_id]["inventory"]["items"])

    def test_recover_body_loot_rejects_when_nothing_recoverable(self):
        client = _client()
        room = _create_room(client)
        code, token = room["room_code"], room["player_token"]
        catalog = _content_catalog(client)
        _make_hero(client, code, token, "Rey", catalog, "h1")

        view = _snapshot(client, code, token)
        resp = _submit(
            client, code, token, command_id="recover1", idempotency_key="recover1",
            expected_revision=view["revision"], type="recover_body_loot",
            payload={"dead_hero_id": "hero_nobody"},
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"]["code"], "illegal_action")

    def test_recover_body_loot_happy_path_via_directly_seeded_body(self):
        # Setting up a real permanent death is combat lane territory (out of
        # this lane's claimed files); seed RoomState.body_item_ids directly on
        # the adapter's internal domain state instead, the same
        # reach-into-`_domain_states` pattern tests/test_stacks_e2e.py and
        # tests/test_stacks_puzzle_rooms.py already use for setup.
        adapter = StacksEngineAdapter()
        manager = StacksRoomManager(adapter)
        app = _build_app(room_manager=manager)
        client = TestClient(app)
        room = _create_room(client)
        code, token, hero_id = room["room_code"], room["player_token"], room["hero_id"]
        catalog = _content_catalog(client)
        _make_hero(client, code, token, "Rey", catalog, "h1")

        view = _snapshot(client, code, token)
        room_id = view["heroes"][hero_id]["room_id"]
        domain_state = adapter._domain_states[view["run_id"]]
        domain_state.map.rooms[room_id].body_item_ids["hero_dead_ally"] = ("field_suture",)

        resp = _submit(
            client, code, token, command_id="recover1", idempotency_key="recover1",
            expected_revision=view["revision"], type="recover_body_loot",
            payload={"dead_hero_id": "hero_dead_ally"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        recover_event = next(e for e in resp.json()["events"] if e["type"] == "body_loot_recovered")
        self.assertEqual(recover_event["payload"]["item_ids"], ["field_suture"])
        self.assertIn("field_suture", recover_event["payload"]["inventory"]["items"])


class AuthoritativeCommandTests(unittest.TestCase):
    def test_apply_authoritative_runs_the_full_pipeline_with_viewer_none(self):
        # Prep for the §21.4 reaction-timeout auto-pass / §21.5 disconnected-
        # companion actions (stacks-enemyroll's transport-injection spec):
        # StacksRoomManager/StacksEngineAdapter.apply_authoritative submits a
        # command through the identical validate/handle/reduce/idempotency
        # pipeline as a player command, but with viewer=None. No domain
        # command actually needs viewer=None to behave differently yet
        # (resolve_reaction doesn't exist until board task #16 lands) -- this
        # is a plumbing regression guard: the new method must still produce a
        # normal ApplyResult and advance revision/event_log exactly like
        # apply() does for an ordinary command.
        adapter = StacksEngineAdapter()
        manager = StacksRoomManager(adapter)
        app = _build_app(room_manager=manager)
        client = TestClient(app)
        room = _create_room(client)
        code, hero_id = room["room_code"], room["hero_id"]

        command = Command(
            command_id="auth-1",
            idempotency_key="auth-1",
            run_id=room["run_id"],
            hero_id=hero_id,
            encounter_id=None,
            expected_revision=room["revision"],
            type="pass",
            payload={},
        )
        result = manager.apply_authoritative(code, command)
        self.assertFalse(result.replayed)
        self.assertEqual(result.revision, room["revision"] + 1)
        self.assertTrue(any(e.type == "turn_passed" for e in result.events))

        # Idempotent replay works identically through this path too.
        replay = manager.apply_authoritative(code, command)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.revision, result.revision)


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


class J1JoinWithoutIdentityTests(unittest.TestCase):
    """wavebasedgame.md S3.1 "J1": joining/creating a room must not require
    hero identity up front -- that's the character-builder screen's job.
    host_name/display_name are optional; omitting them still produces a
    working room/hero with a server-assigned placeholder name."""

    def test_create_room_without_host_name_succeeds(self):
        client = _client()
        resp = client.post("/api/stacks/rooms", json={"seed": None}, headers=ACCESS_HEADER)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIn("hero_id", body)
        self.assertIn("player_token", body)

    def test_join_room_without_display_name_succeeds(self):
        client = _client()
        room = _create_room(client)
        resp = client.post(f"/api/stacks/rooms/{room['room_code']}/join", json={}, headers=ACCESS_HEADER)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIn("hero_id", body)
        self.assertNotEqual(body["hero_id"], room["hero_id"])

    def test_create_room_without_body_fields_still_gets_a_usable_hero_name(self):
        # The room manager must assign SOME non-empty display name server-side
        # (not a client-invented value) so the wire's hero.name field, read by
        # every viewer's project(), is never blank.
        client = _client()
        room = client.post("/api/stacks/rooms", json={}, headers=ACCESS_HEADER).json()
        view = _snapshot(client, room["room_code"], room["player_token"])
        name = view["heroes"][room["hero_id"]]["name"]
        self.assertTrue(name and name.strip())

    def test_placeholder_names_are_distinct_per_hero_in_the_same_room(self):
        client = _client()
        room = client.post("/api/stacks/rooms", json={}, headers=ACCESS_HEADER).json()
        ally = client.post(f"/api/stacks/rooms/{room['room_code']}/join", json={}, headers=ACCESS_HEADER).json()
        view = _snapshot(client, room["room_code"], room["player_token"])
        host_name = view["heroes"][room["hero_id"]]["name"]
        ally_name = view["heroes"][ally["hero_id"]]["name"]
        self.assertNotEqual(host_name, ally_name)

    def test_explicit_empty_string_name_is_still_rejected(self):
        # Omitting the field means "assign a placeholder"; an explicit empty
        # string is a schema error, same as before this wave's change.
        client = _client()
        resp = client.post("/api/stacks/rooms", json={"host_name": "", "seed": None}, headers=ACCESS_HEADER)
        self.assertEqual(resp.status_code, 422)

    def test_explicit_host_name_is_still_honored(self):
        client = _client()
        room = _create_room(client, host_name="Named Host")
        view = _snapshot(client, room["room_code"], room["player_token"])
        self.assertEqual(view["heroes"][room["hero_id"]]["name"], "Named Host")

    def test_create_hero_chosen_name_replaces_join_placeholder(self):
        # The J1 split means join assigns a placeholder; the name chosen on
        # the creation screen (create_hero's validated payload, stored on the
        # domain HeroSheet) must become the wire hero.name every viewer sees
        # afterward -- the placeholder may never outlive character creation.
        client = _client()
        room = client.post("/api/stacks/rooms", json={}, headers=ACCESS_HEADER).json()
        code, token, hero_id = room["room_code"], room["player_token"], room["hero_id"]
        placeholder = _snapshot(client, code, token)["heroes"][hero_id]["name"]
        self.assertTrue(placeholder and placeholder.strip())

        catalog = _content_catalog(client)
        _make_hero(client, code, token, "Mirielle the Unbound", catalog, "j1name")
        view = _snapshot(client, code, token)
        self.assertEqual(view["heroes"][hero_id]["name"], "Mirielle the Unbound")
        self.assertNotEqual(view["heroes"][hero_id]["name"], placeholder)

    def test_chosen_name_survives_for_other_viewers_too(self):
        # Same contract from a second player's viewpoint: project() is
        # viewer-filtered, but hero display names are public wire state.
        client = _client()
        room = client.post("/api/stacks/rooms", json={}, headers=ACCESS_HEADER).json()
        ally = client.post(f"/api/stacks/rooms/{room['room_code']}/join", json={}, headers=ACCESS_HEADER).json()
        catalog = _content_catalog(client)
        _make_hero(client, room["room_code"], room["player_token"], "Mirielle the Unbound", catalog, "j1nm2")
        ally_view = _snapshot(client, room["room_code"], ally["player_token"])
        self.assertEqual(ally_view["heroes"][room["hero_id"]]["name"], "Mirielle the Unbound")


class _FakeReactionManager:
    """Minimal StacksRoomManager stand-in for ReactionAutoPass unit tests:
    serves scripted project() views and records apply_authoritative calls."""

    def __init__(self, views):
        self.views = list(views)  # consumed one per project() call; last repeats
        self.applied = []

    def project(self, code, viewer):
        assert viewer is None, "auto-pass must use the authoritative (viewer=None) pipeline"
        return self.views.pop(0) if len(self.views) > 1 else self.views[0]

    def get_state(self, code):
        class _S:
            run_id = "run_test"

        return _S()

    def apply_authoritative(self, code, command):
        self.applied.append(command)

        class _R:
            events = []
            revision = 8

        return _R()


class _FakeHub:
    def __init__(self):
        self.broadcasts = []

    async def broadcast_event(self, code, event, revision):
        self.broadcasts.append((code, event, revision))


def _pending_view(reaction_id="cevt_3_1", revision=7):
    return {
        "revision": revision,
        "conflict": {
            "room_0_0": {
                "encounter_id": "enc_1",
                "pending_reaction": {"reaction_id": reaction_id, "defender_id": "hero_a"},
            }
        },
    }


class ReactionAutoPassTimerTests(unittest.TestCase):
    """S21.4 decision timer (wave-5 task #16 director close-out): the
    transport injects a server-originated resolve_reaction "pass" when the
    window expires unanswered; an answered window fires nothing; one window
    is never double-armed. Wall-clock lives here in the transport -- the
    reducer never sees a timer (wave-5 director ruling)."""

    def test_expired_window_injects_a_pass_command(self):
        from backend.lan_playground.stacks_api import ReactionAutoPass

        manager = _FakeReactionManager([_pending_view()])
        hub = _FakeHub()

        async def run():
            autopass = ReactionAutoPass(manager, hub, delay_seconds=0.01)
            autopass.scan_and_schedule("room")
            await asyncio.sleep(0.05)

        asyncio.run(run())
        self.assertEqual(len(manager.applied), 1)
        command = manager.applied[0]
        self.assertEqual(command.type, "resolve_reaction")
        self.assertEqual(command.hero_id, "hero_a")
        self.assertEqual(command.payload, {"reaction_id": "cevt_3_1", "reaction": "pass"})

    def test_answered_window_fires_nothing(self):
        from backend.lan_playground.stacks_api import ReactionAutoPass

        # First project() arms the timer; by expiry the reaction is resolved.
        manager = _FakeReactionManager(
            [
                _pending_view(),
                {"revision": 9, "conflict": {"room_0_0": {"encounter_id": "enc_1", "pending_reaction": None}}},
            ]
        )
        hub = _FakeHub()

        async def run():
            autopass = ReactionAutoPass(manager, hub, delay_seconds=0.01)
            autopass.scan_and_schedule("room")
            await asyncio.sleep(0.05)

        asyncio.run(run())
        self.assertEqual(manager.applied, [])

    def test_same_reaction_is_never_double_armed(self):
        from backend.lan_playground.stacks_api import ReactionAutoPass

        manager = _FakeReactionManager([_pending_view()])
        hub = _FakeHub()

        async def run():
            autopass = ReactionAutoPass(manager, hub, delay_seconds=0.01)
            autopass.scan_and_schedule("room")
            autopass.scan_and_schedule("room")  # second scan, same reaction_id
            await asyncio.sleep(0.05)

        asyncio.run(run())
        self.assertEqual(len(manager.applied), 1)


if __name__ == "__main__":
    unittest.main()
