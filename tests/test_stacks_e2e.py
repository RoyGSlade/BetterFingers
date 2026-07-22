"""End-to-end golden-floor slice (infinite_stacks.md S33) through the REAL
domain/systems engine, driven over the transport layer (board task #4).

Proves StacksEngineAdapter's delegation to backend.lan_playground.{domain,
systems} end to end: multiple heroes join and split into different rooms,
breach unexplored tiles with visible d8 results, spend and refresh Exploration
Energy at the all-heroes world-round boundary (S8.2 -- HeroState.submitted_turn
drives it, not auto-end-of-turn), reconnect mid-run to an identical viewer
snapshot, and projection privacy holds over the real engine. A final test
proves determinism directly against two independent engine instances: same
seed + same command sequence => same wire event log => same domain state hash.

Every test builds its own app (no shared server process), mirroring
tests/test_stacks_api.py's pattern.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.lan_playground.stacks_api import StacksRoomManager, create_stacks_app
from backend.lan_playground.stacks_engine import StacksEngineAdapter
from backend.lan_playground.stacks_protocol import Command, ROOM_FAMILY_BY_D8

ACCESS_CODE = "test-stacks-e2e-access-code"
ALLOWED_HOSTS = {"testserver"}
ALLOWED_ORIGINS: set[str] = set()
ACCESS_HEADER = {"X-Access-Code": ACCESS_CODE}

# J12 (docs/PLAYTEST_FINDINGS_2026-07-20.md, wavebasedgame.md S3.1) regression
# check: tests/stacks_client_check/j12_legal_actions_check.mjs imports the
# REAL client modules (core/store.js's reduceServerMessage/applyView,
# core/selectors.js's selectLegalActionsSummary/selectHintText, core/
# commands.js's command builders) and runs them against a real engine
# snapshot -- see that file's header comment for why no DOM is needed for
# this check (screens/map.js only reads the same selector this proves is
# populated; it never independently computes legality).
J12_CHECK_SCRIPT = Path(__file__).resolve().parent / "stacks_client_check" / "j12_legal_actions_check.mjs"


def _client() -> TestClient:
    app = create_stacks_app(
        access_code=ACCESS_CODE,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=ALLOWED_ORIGINS,
        room_manager=StacksRoomManager(StacksEngineAdapter()),
    )
    return TestClient(app)


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


def _submit(client: TestClient, code: str, token: str, *, revision: int, type: str, payload: dict | None = None):
    body = dict(
        command_id=f"cmd-{type}-{revision}-{token[:6]}",
        idempotency_key=f"idem-{type}-{revision}-{token[:6]}",
        expected_revision=revision,
        type=type,
        payload=payload or {},
    )
    headers = {**ACCESS_HEADER, **_token_header(token)}
    resp = client.post(f"/api/stacks/rooms/{code}/commands", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _snapshot(client: TestClient, code: str, token: str) -> dict:
    resp = client.get(f"/api/stacks/rooms/{code}/snapshot", headers={**ACCESS_HEADER, **_token_header(token)})
    assert resp.status_code == 200, resp.text
    return resp.json()["view"]


def _entrance_doors(client: TestClient, code: str, token: str, hero_id: str) -> list[str]:
    view = _snapshot(client, code, token)
    room = view["rooms"][view["heroes"][hero_id]["room_id"]]
    return [d for d, c in room["connectors"].items() if c["state"] == "undiscovered"]


def _seed_with_two_doors_and_clue_family(*, upper_bound: int = 3000) -> int:
    """Scan seeds through the real engine for one whose entrance has >= 2
    breachable doors (so two heroes can genuinely split into different rooms)
    and whose first breach lands in mystery_chamber, the one family with a
    real puzzle template this wave (board task #5 -- wave-1's embellishment
    covered mystery_chamber and study alike with synthesized filler text;
    the real Mystery Chamber puzzle in systems/puzzles.py only instantiates
    for mystery_chamber, so this scan narrows to match). The resulting
    family/door count is read from real emitted events, never predicted from
    a bare RNG draw (contract S9 -- the real engine burns RNG draws
    generating the whole map topology before any breach d8 roll).
    """
    for seed in range(upper_bound):
        adapter = StacksEngineAdapter()
        state = adapter.create_run(seed=seed)
        adapter.apply(
            state,
            Command(
                command_id="scan-join",
                idempotency_key="scan-join",
                run_id=state.run_id,
                hero_id="hero_host",
                encounter_id=None,
                expected_revision=state.revision,
                type="join_run",
                payload={"display_name": "Host"},
            ),
        )
        room = state.rooms[state.heroes["hero_host"].room_id]
        doors = [d for d, c in room.connectors.items() if c.state == "undiscovered"]
        if len(doors) < 2:
            continue
        result = adapter.apply(
            state,
            Command(
                command_id="scan-breach",
                idempotency_key="scan-breach",
                run_id=state.run_id,
                hero_id="hero_host",
                encounter_id=None,
                expected_revision=state.revision,
                type="breach",
                payload={"direction": doors[0]},
            ),
        )
        family = next(e.payload["family"] for e in result.events if e.type == "die_rolled")
        if family == "mystery_chamber":
            return seed
    raise AssertionError("no seed found in range satisfying scenario constraints")


class GoldenFloorSliceTests(unittest.TestCase):
    """S33 golden floor: join, split, breach w/ visible d8, Energy spend +
    round-boundary refresh, all driven through the transport layer against
    the real engine."""

    def _build_run(self):
        seed = _seed_with_two_doors_and_clue_family()
        client = _client()
        room = _create_room(client, "Host", seed=seed)
        code = room["room_code"]
        host_token, host_hero, rev = room["player_token"], room["hero_id"], room["revision"]

        ally1 = _join_room(client, code, "Ally One")
        ally1_token, ally1_hero, rev = ally1["player_token"], ally1["hero_id"], ally1["revision"]

        ally2 = _join_room(client, code, "Ally Two")
        ally2_token, ally2_hero, rev = ally2["player_token"], ally2["hero_id"], ally2["revision"]

        doors = _entrance_doors(client, code, host_token, host_hero)
        self.assertGreaterEqual(len(doors), 2, "scenario seed must give the entrance >= 2 doors")
        return {
            "client": client,
            "code": code,
            "revision": rev,
            "doors": doors,
            "host": (host_token, host_hero),
            "ally1": (ally1_token, ally1_hero),
            "ally2": (ally2_token, ally2_hero),
        }

    def test_join_split_breach_visible_d8_energy_round_boundary(self):
        ctx = self._build_run()
        client, code, doors = ctx["client"], ctx["code"], ctx["doors"]
        host_token, host_hero = ctx["host"]
        ally1_token, ally1_hero = ctx["ally1"]
        ally2_token, ally2_hero = ctx["ally2"]
        rev = ctx["revision"]

        entrance_room_id = _snapshot(client, code, host_token)["heroes"][host_hero]["room_id"]

        # Host breaches into an unexplored room -- visible d8 + family must agree.
        host_breach = _submit(client, code, host_token, revision=rev, type="breach", payload={"direction": doors[0]})
        rev = host_breach["revision"]
        die = next(e for e in host_breach["events"] if e["type"] == "die_rolled")
        revealed = next(e for e in host_breach["events"] if e["type"] == "room_revealed")
        self.assertIn(die["payload"]["value"], range(1, 9))
        self.assertEqual(ROOM_FAMILY_BY_D8[die["payload"]["value"]], die["payload"]["family"])
        self.assertEqual(revealed["payload"]["family"], die["payload"]["family"])
        host_room_id = revealed["payload"]["room_id"]

        # Ally One breaches a *different* door -- the party is now split
        # across three distinct rooms (host's new room, ally1's new room,
        # ally2 still at the entrance).
        ally1_breach = _submit(
            client, code, ally1_token, revision=rev, type="breach", payload={"direction": doors[1]}
        )
        rev = ally1_breach["revision"]
        ally1_room_id = next(e for e in ally1_breach["events"] if e["type"] == "room_revealed")["payload"]["room_id"]

        self.assertEqual(len({host_room_id, ally1_room_id, entrance_room_id}), 3, "party must occupy 3 distinct rooms")

        # Ally Two spends Energy without leaving the entrance (non-movement action).
        ally2_inspect = _submit(client, code, ally2_token, revision=rev, type="inspect")
        rev = ally2_inspect["revision"]

        view = _snapshot(client, code, host_token)
        self.assertEqual(view["heroes"][host_hero]["room_id"], host_room_id)
        self.assertEqual(view["heroes"][ally1_hero]["room_id"], ally1_room_id)
        self.assertEqual(view["heroes"][ally2_hero]["room_id"], entrance_room_id)
        self.assertEqual(view["heroes"][host_hero]["energy"], 2)   # 5 - 3 (breach)
        self.assertEqual(view["heroes"][ally1_hero]["energy"], 2)  # 5 - 3 (breach)
        self.assertEqual(view["heroes"][ally2_hero]["energy"], 4)  # 5 - 1 (inspect)

        # Round only advances once ALL living/conscious heroes have submitted
        # a turn (S8.2: HeroState.submitted_turn), not merely on 0 Energy.
        host_pass = _submit(client, code, host_token, revision=rev, type="pass")
        rev = host_pass["revision"]
        self.assertFalse(any(e["type"] == "world_round_advanced" for e in host_pass["events"]))

        ally1_pass = _submit(client, code, ally1_token, revision=rev, type="pass")
        rev = ally1_pass["revision"]
        self.assertFalse(any(e["type"] == "world_round_advanced" for e in ally1_pass["events"]))
        self.assertEqual(_snapshot(client, code, host_token)["world_round"], 1)

        ally2_pass = _submit(client, code, ally2_token, revision=rev, type="pass")
        rev = ally2_pass["revision"]
        advanced = next(e for e in ally2_pass["events"] if e["type"] == "world_round_advanced")
        self.assertEqual(advanced["payload"]["world_round"], 2)
        self.assertEqual(set(advanced["payload"]["refreshed_hero_ids"]), {host_hero, ally1_hero, ally2_hero})

        # All Energy refreshed to max at the round boundary.
        view = _snapshot(client, code, host_token)
        self.assertEqual(view["world_round"], 2)
        for hero_id in (host_hero, ally1_hero, ally2_hero):
            self.assertEqual(view["heroes"][hero_id]["energy"], view["heroes"][hero_id]["max_energy"])


class ReconnectAndPrivacyTests(unittest.TestCase):
    def _build_split_run(self):
        seed = _seed_with_two_doors_and_clue_family()
        client = _client()
        room = _create_room(client, "Host", seed=seed)
        code = room["room_code"]
        host_token, host_hero, rev = room["player_token"], room["hero_id"], room["revision"]
        ally = _join_room(client, code, "Ally")
        ally_token, ally_hero, rev = ally["player_token"], ally["hero_id"], ally["revision"]

        doors = _entrance_doors(client, code, host_token, host_hero)
        breach = _submit(client, code, host_token, revision=rev, type="breach", payload={"direction": doors[0]})
        self.assertTrue(any(e["type"] == "private_clue_assigned" for e in breach["events"]))
        return client, code, host_token, host_hero, ally_token, ally_hero, breach["revision"]

    def test_reconnect_mid_run_restores_identical_viewer_snapshot(self):
        client, code, host_token, host_hero, ally_token, ally_hero, rev = self._build_split_run()

        with client.websocket_connect(
            f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={host_token}&since_revision={rev}"
        ) as ws:
            reconnect = ws.receive_json()
            # Fetched while still connected so presence ("connected": True)
            # matches what the reconnect snapshot itself reports.
            rest_view = _snapshot(client, code, host_token)
        self.assertEqual(reconnect["kind"], "reconnect_summary")
        ws_view = reconnect["snapshot"]["view"]
        self.assertEqual(ws_view, rest_view)
        self.assertIsNotNone(ws_view["heroes"][host_hero]["private_clue"])

    def test_projection_privacy_over_real_engine(self):
        client, code, host_token, host_hero, ally_token, ally_hero, rev = self._build_split_run()

        host_view = _snapshot(client, code, host_token)
        self.assertIsNotNone(host_view["heroes"][host_hero]["private_clue"])

        ally_view = _snapshot(client, code, ally_token)
        self.assertNotIn("private_clue", ally_view["heroes"][host_hero])
        for room_payload in ally_view["rooms"].values():
            self.assertNotIn("secrets", room_payload)
        for room_payload in host_view["rooms"].values():
            self.assertNotIn("secrets", room_payload)

        with client.websocket_connect(f"/ws/stacks/{code}?access_code={ACCESS_CODE}&token={ally_token}") as ws:
            first = ws.receive_json()
        missed_types = [e["type"] for e in first["missed_events"]]
        self.assertNotIn("private_clue_assigned", missed_types)
        for event in first["missed_events"]:
            self.assertNotIn("clue", event["payload"])


class LegalActionsLockoutRegressionTests(unittest.TestCase):
    """J12 (P0 session-ending bug): from a fresh entrance room the real
    client's own reducer/selector code must expose at least one legal
    Move/Breach/Inspect/Pass action, and that action must be genuinely
    executable through the real transport -- not merely present in the
    projection. Covers both halves of the playtest report's suspects: the
    legal-actions projection itself (verified directly here against the real
    engine) and the client wiring (verified by shelling out to Node against
    the actual store.js/selectors.js/commands.js modules, not a Python
    reimplementation of their logic).
    """

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not available on PATH")

    def _run_js_check(self, payload: dict) -> dict:
        result = subprocess.run(
            ["node", str(J12_CHECK_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail(f"j12_legal_actions_check.mjs produced non-JSON stdout (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")
        self.assertEqual(
            result.returncode,
            0,
            f"j12_legal_actions_check.mjs reported failure: {parsed.get('reason')}\nfull output: {parsed}\nstderr: {result.stderr}",
        )
        self.assertTrue(parsed.get("ok"))
        return parsed

    def test_fresh_entrance_room_has_a_legal_action_via_real_client_code_path(self):
        # join -> create hero, exactly like a fresh player, against the real
        # engine over the real REST transport (mirrors GoldenFloorSliceTests
        # above, but stops right after join -- the entrance room, turn one,
        # before any move/breach has happened, which is exactly the state
        # J12's playtest report reproduced from).
        client = _client()
        room = _create_room(client, "Host", seed=7)
        code, token, hero_id, revision = room["room_code"], room["player_token"], room["hero_id"], room["revision"]

        snapshot_resp = client.get(f"/api/stacks/rooms/{code}/snapshot", headers={**ACCESS_HEADER, **_token_header(token)})
        self.assertEqual(snapshot_resp.status_code, 200, snapshot_resp.text)
        snapshot_body = snapshot_resp.json()

        # Server-side projection sanity (backend/lan_playground/
        # stacks_projections.py's legal_actions, folded into project() by
        # the salvaged commit): fails loudly here, not just in the JS check,
        # if a future change ever regresses the projection itself.
        view = snapshot_body["view"]
        self.assertIn("legal_actions", view, "snapshot view is missing legal_actions -- J12 projection regression")
        legal = view["legal_actions"]
        self.assertEqual(legal["hero_id"], hero_id)
        any_legal_server_side = bool(legal["can_pass"] or legal["can_inspect"] or legal["can_move_to"] or legal["can_breach_directions"])
        self.assertTrue(any_legal_server_side, f"no legal action in server projection for a fresh entrance room: {legal}")

        # Real client code path: reduceServerMessage(snapshot) -> the exact
        # store state screens/map.js and selectHintText read from.
        snapshot_message = {"kind": "snapshot", "view": view, "revision": snapshot_body["revision"]}
        js_result = self._run_js_check({"heroId": hero_id, "snapshotMessage": snapshot_message})
        self.assertEqual(js_result["heroId"], hero_id)
        command = js_result["command"]
        self.assertIn(command["type"], {"move", "breach", "inspect", "pass"})

        # Prove the client-selected action is genuinely executable, not just
        # legal-looking: submit the exact envelope the real command builder
        # produced through the real transport and confirm the server accepts
        # it (never a CommandError).
        submit_body = {
            "command_id": command["command_id"],
            "idempotency_key": command["idempotency_key"],
            "expected_revision": revision,
            "type": command["type"],
            "payload": command["payload"],
        }
        submit_resp = client.post(
            f"/api/stacks/rooms/{code}/commands",
            json=submit_body,
            headers={**ACCESS_HEADER, **_token_header(token)},
        )
        self.assertEqual(
            submit_resp.status_code,
            200,
            f"client-selected legal action {command['type']!r} was rejected by the real engine: {submit_resp.text}",
        )
        self.assertGreater(submit_resp.json()["revision"], revision)

    def test_regression_guard_empty_legal_actions_fails_the_js_check(self):
        # Proves the harness script itself actually fails closed: feed it a
        # snapshot with no legal_actions field at all (exactly what a
        # pre-fix snapshot looked like before the salvaged commit folded
        # legal_actions() into project()) and confirm it reports failure
        # rather than silently passing.
        client = _client()
        room = _create_room(client, "Host", seed=7)
        code, token, hero_id = room["room_code"], room["player_token"], room["hero_id"]
        snapshot_resp = client.get(f"/api/stacks/rooms/{code}/snapshot", headers={**ACCESS_HEADER, **_token_header(token)})
        view = dict(snapshot_resp.json()["view"])
        view.pop("legal_actions", None)
        broken_snapshot_message = {"kind": "snapshot", "view": view, "revision": view["revision"]}

        result = subprocess.run(
            ["node", str(J12_CHECK_SCRIPT)],
            input=json.dumps({"heroId": hero_id, "snapshotMessage": broken_snapshot_message}),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0, "harness must fail when legal_actions is absent from the snapshot (the J12 regression shape)")
        parsed = json.loads(result.stdout)
        self.assertFalse(parsed["ok"])


class DeterministicReplayTests(unittest.TestCase):
    """Same seed + same ordered command sequence, driven twice through two
    independent StacksEngineAdapter instances (bypassing transport, since
    only the adapter's fidelity to the real engine is under test here) =>
    identical wire event logs and identical real domain state hashes."""

    def _run_scenario(self, seed: int):
        adapter = StacksEngineAdapter()
        state = adapter.create_run(seed=seed)

        def send(hero_id, ctype, payload=None, tag=""):
            cmd = Command(
                command_id=f"{ctype}-{hero_id}-{tag}",
                idempotency_key=f"{ctype}-{hero_id}-{tag}",
                run_id=state.run_id,
                hero_id=hero_id,
                encounter_id=None,
                expected_revision=state.revision,
                type=ctype,
                payload=payload or {},
            )
            return adapter.apply(state, cmd)

        send("hero_host", "join_run", {"display_name": "Host"})
        send("hero_ally", "join_run", {"display_name": "Ally"})

        room = state.rooms[state.heroes["hero_host"].room_id]
        doors = [d for d, c in room.connectors.items() if c.state == "undiscovered"]
        self.assertGreaterEqual(len(doors), 2)

        send("hero_host", "breach", {"direction": doors[0]})
        send("hero_ally", "breach", {"direction": doors[1]})
        send("hero_host", "pass")
        send("hero_ally", "pass")

        domain_state = adapter._domain_states[state.run_id]
        return state, domain_state

    def test_same_seed_same_event_log_same_state_hash(self):
        seed = _seed_with_two_doors_and_clue_family()
        state_a, domain_a = self._run_scenario(seed)
        state_b, domain_b = self._run_scenario(seed)

        # run_id is a fresh uuid4 per create_run() (an adapter identity
        # detail, not part of the replayed simulation), so exclude it before
        # comparing -- everything else in the hashed dict must match exactly.
        self.assertEqual(_state_hash_without_run_id(domain_a), _state_hash_without_run_id(domain_b))
        self.assertEqual(state_a.revision, state_b.revision)
        self.assertEqual(state_a.world_round, state_b.world_round)

        def strip_run_id(events):
            return [
                (e.event_id, e.caused_by, e.actor_hero_id, e.room_id, e.type, e.visibility, e.visible_to, e.payload)
                for e in events
            ]

        self.assertEqual(strip_run_id(state_a.event_log), strip_run_id(state_b.event_log))

        for viewer in (None, "hero_host", "hero_ally"):
            view_a = dict(adapter_project_without_run_id(state_a, viewer))
            view_b = dict(adapter_project_without_run_id(state_b, viewer))
            self.assertEqual(view_a, view_b)

    def test_different_seed_diverges(self):
        seed = _seed_with_two_doors_and_clue_family()
        state_a, domain_a = self._run_scenario(seed)
        state_b, domain_b = self._run_scenario(seed + 1)
        self.assertNotEqual(_state_hash_without_run_id(domain_a), _state_hash_without_run_id(domain_b))


def _state_hash_without_run_id(domain_state) -> str:
    import hashlib
    import json

    d = domain_state.to_dict()
    d.pop("run_id", None)
    canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def adapter_project_without_run_id(state, viewer):
    from backend.lan_playground.stacks_projections import project

    view = dict(project(state, viewer))
    view.pop("run_id", None)
    return view


if __name__ == "__main__":
    unittest.main()
