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
    joiner (§14.1: at the *next* initiative cycle, never mid-round).

    Task #16: an enemy attack now pauses into a pending-reaction window
    (§14.5/§21.3-21.4) instead of dealing flat unconditional damage. This
    harness has no live UI/companion to answer it, so it proactively
    declines with an explicit `resolve_reaction{reaction:"pass"}` the
    instant one opens -- the closest faithful analog of the old flat-damage
    behaviour (the attack always lands), while genuinely round-tripping the
    new command. A real deployment would show the defending player a
    prompt instead of auto-declining (see docs/INFINITE_STACKS_COMBAT.md §7)."""
    for i in range(max_iterations):
        enc = h.encounter(room_id)
        if enc.status != "active" or predicate(enc):
            return enc
        pending = enc.pending_reaction
        if pending is not None and pending["defender_id"] in ("hero_a", hero_b_id):
            h.send(
                pending["defender_id"], CommandType.RESOLVE_REACTION,
                {"reaction_id": pending["reaction_id"], "reaction": "pass"},
            )
            continue
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


# --------------------------------------------------------------------------- §14.5/§21.3-21.4: live pending-reaction window (task #16)
#
# The bruiser reinforcement's `heavy_swing` is the only content-authored
# attack-type intent that can naturally open a window (seed 14's immediate
# enemy, goblin_firestarter, never deals direct damage -- see the module
# docstring), and it only arrives several combat rounds out. Rather than
# grind seeds to force a specific roll outcome, these tests white-box a
# `pending_reaction` directly onto a live encounter -- the same pattern the
# permadeath test above already uses ("one death-check failure away") --
# then drive it purely through the real `resolve_reaction` command/reducer
# path. `goblin_firestarter_0` (always present as the immediate enemy for a
# solo/duo breach) stands in as the attacker; its own intents are irrelevant
# here since the window is being answered, not opened.


def _plant_pending_reaction(h: Harness, room_id: str, **overrides) -> dict:
    enc = h.encounter(room_id)
    pending = {
        "reaction_id": "test_reaction_1",
        "attacker_id": "goblin_firestarter_0",
        "defender_id": "hero_a",
        "protector_ids": [],
        "hit": True,
        "margin": 5,
        "incoming_attack_total": 16,
        "provisional_damage": 3,
        "action_label": "heavy_swing",
        "source_intent_id": "heavy_swing",
        "remaining_effects": [],
    }
    pending.update(overrides)
    enc.current_actor_id = pending["attacker_id"]
    enc.pending_reaction = pending
    return pending


def test_pending_reaction_block_reduces_damage_and_may_wear():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    hp_before = h.encounter(room_id).heroes["hero_a"]["hp"]
    pending = _plant_pending_reaction(h, room_id)

    result = h.send("hero_a", CommandType.RESOLVE_REACTION, {"reaction_id": pending["reaction_id"], "reaction": "block"})
    combat_evts = [ce for e in result.events for ce in e.payload["combat_events"]]
    block_event = next(ce for ce in combat_evts if ce["payload"].get("reaction") == "block")
    reduced = block_event["payload"]["reduced_damage"]
    assert reduced < pending["provisional_damage"]  # Block reduced the incoming damage
    assert isinstance(block_event["payload"]["took_wear"], bool)  # item "may take Wear" (§14.5), roll is recorded either way

    enc = h.encounter(room_id)
    assert enc.pending_reaction is None
    assert enc.heroes["hero_a"]["hp"] == hp_before - reduced
    assert enc.heroes["hero_a"]["reaction_available"] is False  # Block consumes the reaction


def test_pending_reaction_dodge_negates_the_hit():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    hp_before = h.encounter(room_id).heroes["hero_a"]["hp"]
    # incoming_attack_total pinned absurdly low so dodge succeeds regardless
    # of the real StacksRNG's actual d20 draw -- deterministic without a
    # scripted RNG at the domain-command level.
    pending = _plant_pending_reaction(h, room_id, incoming_attack_total=-100)

    result = h.send("hero_a", CommandType.RESOLVE_REACTION, {"reaction_id": pending["reaction_id"], "reaction": "dodge"})
    combat_evts = [ce for e in result.events for ce in e.payload["combat_events"]]
    dodge_event = next(ce for ce in combat_evts if ce["payload"].get("reaction") == "dodge")
    assert dodge_event["payload"]["outcome"] == "avoided"

    enc = h.encounter(room_id)
    assert enc.pending_reaction is None
    assert enc.heroes["hero_a"]["hp"] == hp_before  # negated -- no damage landed
    assert enc.heroes["hero_a"]["reaction_available"] is False


def test_pending_reaction_protect_redirects_damage_to_protector():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    h.send("hero_b", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    _advance_until(h, room_id, "hero_b", lambda e: "hero_b" in e.heroes)
    enc = h.encounter(room_id)
    hero_a_hp_before = enc.heroes["hero_a"]["hp"]
    hero_b_hp_before = enc.heroes["hero_b"]["hp"]
    pending = _plant_pending_reaction(h, room_id, protector_ids=["hero_b"])

    result = h.send("hero_b", CommandType.RESOLVE_REACTION, {"reaction_id": pending["reaction_id"], "reaction": "protect"})
    combat_evts = [ce for e in result.events for ce in e.payload["combat_events"]]
    assert any(ce["payload"].get("reaction") == "protect" for ce in combat_evts)

    enc = h.encounter(room_id)
    assert enc.pending_reaction is None
    assert enc.heroes["hero_a"]["hp"] == hero_a_hp_before  # original defender untouched
    assert enc.heroes["hero_b"]["hp"] == hero_b_hp_before - pending["provisional_damage"]  # redirected
    assert enc.heroes["hero_b"]["reaction_available"] is False  # the PROTECTOR's reaction is spent
    assert enc.heroes["hero_a"]["reaction_available"] is True  # hero_a never acted


def test_pending_reaction_counter_fires_on_a_big_enough_miss():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    pending = _plant_pending_reaction(h, room_id, hit=False, margin=-6, provisional_damage=0)

    result = h.send("hero_a", CommandType.RESOLVE_REACTION, {"reaction_id": pending["reaction_id"], "reaction": "counter"})
    combat_evts = [ce for e in result.events for ce in e.payload["combat_events"]]
    assert any(ce["payload"].get("action") == "counter" for ce in combat_evts)

    enc = h.encounter(room_id)
    assert enc.pending_reaction is None
    assert enc.heroes["hero_a"]["reaction_available"] is False


def test_pending_reaction_counter_rejected_when_margin_too_small():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    pending = _plant_pending_reaction(h, room_id, hit=True, margin=2)

    from backend.lan_playground.domain.commands import CommandError
    try:
        h.send("hero_a", CommandType.RESOLVE_REACTION, {"reaction_id": pending["reaction_id"], "reaction": "counter"})
        raised = False
    except CommandError:
        raised = True
    assert raised


def test_pending_reaction_pass_is_the_deterministic_safe_default():
    """§21.4: an explicit pass -- whether from a live player declining, a
    transport-layer decision-timer expiry, or a disconnected hero's
    companion policy (§21.5) -- is the *same* command either way (director
    ruling): the reducer has no separate "timeout" or "companion" code
    path. Full provisional damage lands, exactly as if no reaction existed;
    unlike a spent reaction, declining does NOT consume it (§14.5: "the
    reaction is not consumed" when nothing is taken)."""
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    hp_before = h.encounter(room_id).heroes["hero_a"]["hp"]
    pending = _plant_pending_reaction(h, room_id)

    h.send("hero_a", CommandType.RESOLVE_REACTION, {"reaction_id": pending["reaction_id"], "reaction": "pass"})

    enc = h.encounter(room_id)
    assert enc.pending_reaction is None
    assert enc.heroes["hero_a"]["hp"] == hp_before - pending["provisional_damage"]  # full damage landed
    assert enc.heroes["hero_a"]["reaction_available"] is True  # declining doesn't spend it


def test_pending_reaction_blocks_world_round_advance_for_a_solo_last_submitter():
    """Director ruling: an open pending reaction must genuinely block
    `round_complete()`/world-round advance rather than auto-resolving --
    including the edge case where the defending hero is ALSO the only (or
    last) living-conscious hero who still needs to submit their world turn.
    Without the round_complete() guard, this exact command sequence would
    auto-resolve the window in the same apply() call that opened it, and
    the player would never see a prompt."""
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    h.state.heroes["hero_a"].submitted_turn = True  # simulates: hero_a already ended their combat turn this round
    pending = _plant_pending_reaction(h, room_id)

    assert h.state.round_complete() is False  # blocked purely by the pending reaction, not by submitted_turn
    world_round_before = h.state.world_round

    h.send("hero_a", CommandType.RESOLVE_REACTION, {"reaction_id": pending["reaction_id"], "reaction": "pass"})

    enc = h.encounter(room_id)
    assert enc.pending_reaction is None
    # Resolving was the only thing standing between this state and
    # round_complete(); once it clears, the world round is free to advance
    # in the same command that resolved it (matching every other
    # last-submitter command in this file, e.g. §7.4's TURN_SUBMITTED
    # cadence) -- proving the window opened and closed cleanly rather than
    # deadlocking the run.
    assert h.state.world_round == world_round_before + 1


def test_headless_consumer_that_never_resolves_a_pending_reaction_stalls_by_design():
    """Documents the flip side of the no-deadlock guarantee: the reducer
    guarantees FORWARD PROGRESS IS POSSIBLE once a resolve_reaction command
    arrives, never that one arrives on its own. A consumer that opens a
    window and then sends no further commands genuinely stalls -- by
    design, matching every other "waiting on a player" state this engine
    already has (nothing auto-passes silent players during ordinary
    exploration either). Real deployments must always have something
    sending the command: a live player, or -- per §21.4/§21.5 -- the
    transport layer's decision timer / companion policy, both of which are
    still just ordinary senders of the same `resolve_reaction` command
    (docs/INFINITE_STACKS_COMBAT.md §7)."""
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    room_id = _breach_into_conflict(h, "hero_a")
    h.state.heroes["hero_a"].submitted_turn = True
    _plant_pending_reaction(h, room_id)

    world_round_before = h.state.world_round
    for _ in range(5):
        assert h.state.round_complete() is False
    assert h.state.world_round == world_round_before
    assert h.encounter(room_id).pending_reaction is not None  # still waiting -- nothing ever answered it


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
