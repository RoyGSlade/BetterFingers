"""Conflict-room combat wiring, end to end (infinite_stacks.md §7.4, §12.5,
§13.6, §14, §15, §16; docs/INFINITE_STACKS_COMBAT.md). Board task #9.

Drives the real domain reducer directly (same Harness pattern as
tests/test_stacks_engine.py) so combat state (`RoomState.encounter`) stays
inspectable for white-box scenario setup, while still exercising the real
`handle() -> events -> reduce()` pipeline for every mechanical fact: threat
budget, barricade/delay, joiners, Downed/Stable/Dead, and permanent-death
body/item persistence.

Seed 14 is used throughout: with `hero_a` as the first hero to `join_run`
(map generation is seeded once, on the first join), breaching the entrance's
only door lands in a `conflict` room with a single immediate enemy
(`goblin_firestarter`, threat cost 1, whose intents never deal direct HP
damage this wave) and a reinforcement wave of `goblin_bruiser` (cost 2,
`heavy_swing` unconditionally deals 3 damage -- enemy intents have no
accuracy roll, only hero attacks do) + `goblin_relesspider` (cost 3),
scheduled 3 combat rounds out. This gives fully deterministic enemy behavior
regardless of hero attack-roll variance, which the tests lean on.
"""
from __future__ import annotations

from backend.lan_playground.domain import reducer, replay as replay_mod
from backend.lan_playground.domain.commands import Command, CommandType
from backend.lan_playground.domain.events import EventType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConnectorState, RunState

SEED = 14


class Harness:
    def __init__(self, run_id="run_conflict", seed=SEED, chapter_floor_index=0):
        self.state = RunState.initial(run_id=run_id, seed=seed, chapter_floor_index=chapter_floor_index)
        self.rng = StacksRNG(seed)
        self.seq = 0
        self.event_log: list = []
        self._n = 0

    def send(self, hero_id, ctype, payload=None):
        self._n += 1
        cmd = Command(
            command_id=f"cmd_{self._n}",
            idempotency_key=f"cmd_{self._n}",
            run_id=self.state.run_id,
            type=ctype,
            hero_id=hero_id,
            expected_revision=self.state.revision,
            payload=payload or {},
        )
        result = reducer.apply(cmd, self.state, self.rng, viewer=hero_id, seq=self.seq)
        self.state = result.state
        self.seq = result.next_seq
        self.event_log.extend(result.events)
        return result

    def door_direction(self, room_id):
        room = self.state.map.rooms[room_id]
        for d, c in room.connectors.items():
            if c == ConnectorState.DOOR:
                return d
        return None

    def open_direction(self, room_id):
        room = self.state.map.rooms[room_id]
        for d, c in room.connectors.items():
            if c == ConnectorState.OPEN:
                return d
        return None

    def encounter(self, room_id):
        return self.state.map.rooms[room_id].encounter


def _breach_into_conflict(h: Harness, hero_id: str) -> str:
    entrance = h.state.map.entrance_room_id
    direction = h.door_direction(entrance)
    assert direction is not None
    result = h.send(hero_id, CommandType.BREACH, {"direction": direction.value})
    family = next(e.payload["family"] for e in result.events if e.type == EventType.ROOM_BREACHED)
    assert family == "conflict", f"expected seed {SEED}'s first breach to be conflict, got {family}"
    return h.state.heroes[hero_id].room_id


# --------------------------------------------------------------------------- §15: threat budget / barricade


def test_solo_entrant_faces_full_party_threat_and_barricades():
    h = Harness()
    for hid in ("hero_a", "hero_b", "hero_c", "hero_d"):
        h.send(hid, CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    enc = h.encounter(room_id)

    # §15.1: budget uses the TOTAL living party, not who is physically present.
    assert enc.threat_budget["total_living_heroes"] == 4
    assert enc.threat_budget["total"] == 2 * 4
    assert set(enc.heroes) == {"hero_a"}  # only the breacher is a combatant so far

    wave = enc.reinforcement_waves[0]
    original_arrival = wave["arrival_combat_round"]
    assert wave["enemies"], "budget should afford at least one delayed reinforcement"

    # §15.2: at least one retreat/barricade/hide/delay route exists.
    result = h.send("hero_a", CommandType.COMBAT_BARRICADE, {"extra_delay_rounds": 5})
    barricade_events = [
        ce
        for e in result.events
        for ce in e.payload["combat_events"]
        if ce["type"] == "barricade_established"
    ]
    assert barricade_events
    enc = h.encounter(room_id)
    assert enc.reinforcement_waves[0]["arrival_combat_round"] == original_arrival + 5

    h.send("hero_a", CommandType.COMBAT_END_TURN)
    for hid in ("hero_b", "hero_c", "hero_d"):
        h.send(hid, CommandType.PASS)

    # Survive well past the ORIGINAL arrival round -- the delay genuinely
    # held the reinforcements back, and the immediate enemy alone (firestarter)
    # never deals direct HP damage this wave.
    for _ in range(6):
        enc = h.encounter(room_id)
        if enc.status != "active":
            break
        if enc.current_actor_id == "hero_a":
            h.send("hero_a", CommandType.COMBAT_END_TURN)
        for hid in ("hero_b", "hero_c", "hero_d"):
            hero_state = h.state.heroes[hid]
            if not hero_state.submitted_turn:
                h.send(hid, CommandType.PASS)

    enc = h.encounter(room_id)
    assert enc.status == "active"
    assert enc.heroes["hero_a"]["life_state"] == "alive"
    assert enc.combat_round > original_arrival
    assert set(enc.enemies) == {"goblin_firestarter_0"}, "delayed reinforcements must not have arrived yet"


# --------------------------------------------------------------------------- §7.4/§14.1: split party + joiners


def _advance_until(h: Harness, room_id: str, hero_b_id: str, predicate, max_iterations=40):
    """Drives hero_a's combat turns and hero_b's exploration/combat turns
    until `predicate(encounter)` is true. hero_b travels toward the fight
    (§7.4: distant heroes keep exploring/traveling, not frozen) then
    integrates once the encounter's own round-advance processes them as a
    joiner (§14.1: at the *next* initiative cycle, never mid-round)."""
    for i in range(max_iterations):
        enc = h.encounter(room_id)
        if enc.status != "active" or predicate(enc):
            return enc
        if enc.current_actor_id == "hero_a":
            h.send("hero_a", CommandType.COMBAT_END_TURN)
            continue
        hero_b_state = h.state.heroes[hero_b_id]
        if hero_b_state.room_id != room_id:
            if i == 0:
                h.send(hero_b_id, CommandType.PASS)
            else:
                direction = h.open_direction(hero_b_state.room_id)
                h.send(hero_b_id, CommandType.MOVE, {"direction": direction.value})
            continue
        enc = h.encounter(room_id)
        if hero_b_id not in enc.heroes:
            h.send(hero_b_id, CommandType.PASS)
        elif enc.current_actor_id == hero_b_id:
            h.send(hero_b_id, CommandType.COMBAT_END_TURN)
    return h.encounter(room_id)


def test_distant_ally_travels_and_joins_at_next_initiative_cycle():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    h.send("hero_b", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")

    entrance = h.state.map.entrance_room_id
    assert h.state.heroes["hero_b"].room_id == entrance  # still distant right after the breach

    # hero_b spends a normal world turn exploring (pass) while combat is live
    # elsewhere, then travels in -- a distant hero is never frozen.
    enc = _advance_until(h, room_id, "hero_b", lambda e: "hero_b" in e.heroes)

    assert "hero_b" in enc.heroes
    combatant_ids = {c["combatant_id"] for c in enc.order}
    assert {"hero_a", "hero_b", "goblin_firestarter_0"} <= combatant_ids
    # Joined heroes still travel first (§14.1) -- confirm the JOINED_CONFLICT_ROOM
    # wire event fired for hero_b at some point in the log before integration.
    joined = [e for e in h.event_log if e.type == EventType.JOINED_CONFLICT_ROOM and e.payload["hero_id"] == "hero_b"]
    assert joined, "expected a joined_conflict_room event once hero_b physically arrived"


# --------------------------------------------------------------------------- §16.2-16.3: Downed + stabilize


def test_downed_ally_is_stabilized_by_a_present_hero():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    h.send("hero_b", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")

    # Get hero_b in and integrated before the bruiser reinforcement (arrives
    # combat_round 4) starts dealing real damage.
    _advance_until(h, room_id, "hero_b", lambda e: "hero_b" in e.heroes)

    enc = _advance_until(
        h, room_id, "hero_b", lambda e: e.heroes.get("hero_a", {}).get("life_state") == "downed"
    )
    assert enc.status == "active"
    assert enc.heroes["hero_a"]["life_state"] == "downed"
    assert enc.heroes["hero_a"]["hp"] == 0

    # It must be hero_b's turn now (hero_a, Downed, no longer takes normal
    # turns) -- stabilize using the correct-aid rule (§16.2-16.3), no need to
    # wait for 3 death-check successes.
    assert enc.current_actor_id == "hero_b"
    result = h.send("hero_b", CommandType.COMBAT_STABILIZE, {"target_hero_id": "hero_a"})
    stabilized_events = [
        ce for e in result.events for ce in e.payload["combat_events"] if ce["type"] == "hero_stabilized"
    ]
    assert stabilized_events

    enc = h.encounter(room_id)
    assert enc.heroes["hero_a"]["life_state"] == "stable"
    hero_a_domain = h.state.heroes["hero_a"]
    assert hero_a_domain.life_state == "stable"
    assert hero_a_domain.alive is True
    assert hero_a_domain.conscious is False  # Downed/Stable heroes cannot take normal exploration actions

    # A Stable hero genuinely cannot act via ordinary exploration commands.
    from backend.lan_playground.domain.commands import CommandError

    try:
        h.send("hero_a", CommandType.PASS)
        raised = False
    except CommandError:
        raised = True
    assert raised


# --------------------------------------------------------------------------- §16: win, loss, permanent death, §13.6 body


def test_encounter_won_defeats_enemy_and_persists_the_death_in_room_state():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    enc = h.encounter(room_id)
    assert enc.threat_budget["total_living_heroes"] == 1
    assert not enc.reinforcement_waves[0]["enemies"]  # too poor to afford any reinforcement solo

    for _ in range(20):
        enc = h.encounter(room_id)
        if enc.status != "active":
            break
        enemy_id = next((eid for eid, e in enc.enemies.items() if e["alive"]), None)
        if enemy_id and enc.current_actor_id == "hero_a":
            h.send("hero_a", CommandType.COMBAT_ATTACK, {"target_id": enemy_id, "attribute": "force", "skill": None})
        enc = h.encounter(room_id)
        if enc.status != "active":
            break
        h.send("hero_a", CommandType.COMBAT_END_TURN)

    enc = h.encounter(room_id)
    assert enc.status == "victory"
    assert enc.enemies["goblin_firestarter_0"]["alive"] is False

    ended = next(e for e in h.event_log if e.type == EventType.CONFLICT_ENCOUNTER_ENDED)
    assert ended.payload["outcome"] == "victory"

    # §4.1 "the dungeon remembers": re-reading the room's persisted encounter
    # later must still show the defeated enemy as dead, not respawned.
    assert h.state.map.rooms[room_id].encounter.enemies["goblin_firestarter_0"]["alive"] is False


def test_encounter_lost_with_permanent_death_and_body_item_persistence():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    h.send("hero_b", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    h.state.heroes["hero_a"].carried_item_ids = ("sword_of_testing", "lucky_coin")

    _advance_until(h, room_id, "hero_b", lambda e: "hero_b" in e.heroes)
    enc = _advance_until(
        h, room_id, "hero_b", lambda e: e.heroes.get("hero_a", {}).get("life_state") == "downed"
    )
    assert enc.heroes["hero_a"]["life_state"] == "downed"

    # White-box: one death-check failure away from permanent death (§16.2:
    # "three failed death checks" -- exercising the natural roll from here,
    # not skipping the mechanism itself).
    enc.heroes["hero_a"]["death_failures"] = 2
    h.state.heroes["hero_a"].death_failures = 2

    final_enc = _advance_until(
        h, room_id, "hero_b", lambda e: e.heroes.get("hero_a", {}).get("life_state") == "dead"
    )
    assert final_enc.heroes["hero_a"]["life_state"] == "dead"

    hero_a_domain = h.state.heroes["hero_a"]
    assert hero_a_domain.life_state == "dead"
    assert hero_a_domain.alive is False
    assert hero_a_domain.carried_item_ids == ()  # items left the hero...

    room = h.state.map.rooms[room_id]
    assert room.body_item_ids["hero_a"] == ("sword_of_testing", "lucky_coin")  # ...and stayed with the body

    died_events = [
        ce
        for e in h.event_log
        if e.type in (EventType.CONFLICT_TURN_RESOLVED, EventType.CONFLICT_ENCOUNTER_ENDED)
        for ce in e.payload["combat_events"]
        if ce["type"] == "hero_died"
    ]
    assert died_events
    newly_dead_events = [
        e
        for e in h.event_log
        if e.type in (EventType.CONFLICT_TURN_RESOLVED, EventType.CONFLICT_ENCOUNTER_ENDED)
        and "hero_a" in e.payload["newly_dead_hero_ids"]
    ]
    assert newly_dead_events


# --------------------------------------------------------------------------- replay determinism


def _scripted_events_for_seed(seed: int) -> list:
    h = Harness(seed=seed)
    h.send("hero_a", CommandType.JOIN_RUN)
    h.send("hero_b", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    _advance_until(h, room_id, "hero_b", lambda e: "hero_b" in e.heroes)
    _advance_until(h, room_id, "hero_b", lambda e: e.heroes.get("hero_a", {}).get("life_state") == "downed")
    return h


def test_replay_determinism_same_seed_same_event_log_and_state_hash():
    run_a = _scripted_events_for_seed(SEED)
    run_b = _scripted_events_for_seed(SEED)

    assert [e.to_dict() for e in run_a.event_log] == [e.to_dict() for e in run_b.event_log]
    assert run_a.state.state_hash() == run_b.state.state_hash()

    replayed = replay_mod.replay(run_a.state.run_id, SEED, 0, run_a.event_log)
    assert replayed.state_hash() == run_a.state.state_hash()
