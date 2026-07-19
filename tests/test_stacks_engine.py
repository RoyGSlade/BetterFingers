"""Engine-core tests: command/event/reducer flow, determinism, checks (§22.1, §12)."""
from __future__ import annotations

import pytest

from backend.lan_playground.domain import reducer, replay as replay_mod
from backend.lan_playground.domain.commands import Command, CommandError, CommandType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConnectorState, RunState
from backend.lan_playground.systems import checks


class Harness:
    """Small test helper: tracks revision/seq bookkeeping around reducer.apply."""

    def __init__(self, run_id="run_test", seed=1, chapter_floor_index=0):
        self.state = RunState.initial(run_id=run_id, seed=seed, chapter_floor_index=chapter_floor_index)
        self.rng = StacksRNG(seed)
        self.seq = 0
        self.event_log: list = []
        self._cmd_n = 0

    def send(self, hero_id, ctype, payload=None, viewer=None):
        self._cmd_n += 1
        cmd = Command(
            command_id=f"cmd_{self._cmd_n}",
            idempotency_key=f"cmd_{self._cmd_n}",
            run_id=self.state.run_id,
            type=ctype,
            hero_id=hero_id,
            expected_revision=self.state.revision,
            payload=payload or {},
        )
        result = reducer.apply(cmd, self.state, self.rng, viewer=viewer if viewer is not None else hero_id, seq=self.seq)
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


def test_join_run_generates_map_and_places_hero_at_entrance():
    h = Harness(seed=7)
    h.send("hero_a", CommandType.JOIN_RUN)
    assert h.state.map is not None
    assert h.state.map.required_rooms == 6
    assert h.state.map.maximum_rooms == 9
    hero = h.state.heroes["hero_a"]
    assert hero.room_id == h.state.map.entrance_room_id
    assert hero.energy == 5


def test_second_hero_joins_existing_map_without_regenerating():
    h = Harness(seed=7)
    h.send("hero_a", CommandType.JOIN_RUN)
    first_map_id = id(h.state.map)
    room_count = len(h.state.map.rooms)
    h.send("hero_b", CommandType.JOIN_RUN)
    assert len(h.state.map.rooms) == room_count
    assert h.state.heroes["hero_b"].room_id == h.state.map.entrance_room_id


def test_duplicate_join_is_rejected():
    h = Harness(seed=7)
    h.send("hero_a", CommandType.JOIN_RUN)
    with pytest.raises(CommandError):
        h.send("hero_a", CommandType.JOIN_RUN)


def test_stale_revision_rejected_with_legal_actions():
    h = Harness(seed=7)
    h.send("hero_a", CommandType.JOIN_RUN)
    stale_cmd = Command(
        command_id="stale",
        idempotency_key="stale",
        run_id=h.state.run_id,
        type=CommandType.PASS,
        hero_id="hero_a",
        expected_revision=0,  # already advanced past this
        payload={},
    )
    with pytest.raises(CommandError) as exc_info:
        reducer.validate(stale_cmd, h.state, "hero_a")
    assert exc_info.value.code.value == "stale_revision"
    assert "pass" in exc_info.value.legal_actions


def test_wrong_viewer_rejected():
    h = Harness(seed=7)
    h.send("hero_a", CommandType.JOIN_RUN)
    cmd = Command(
        command_id="c",
        idempotency_key="c",
        run_id=h.state.run_id,
        type=CommandType.PASS,
        hero_id="hero_a",
        expected_revision=h.state.revision,
        payload={},
    )
    with pytest.raises(CommandError) as exc_info:
        reducer.validate(cmd, h.state, "hero_b")
    assert exc_info.value.code.value == "not_your_turn"


def test_four_heroes_split_breach_regroup_and_reach_exit():
    h = Harness(seed=123)
    hero_ids = ["hero_a", "hero_b", "hero_c", "hero_d"]
    for hid in hero_ids:
        h.send(hid, CommandType.JOIN_RUN)

    entrance = h.state.map.entrance_room_id
    for hid in hero_ids:
        assert h.state.heroes[hid].room_id == entrance

    # Split: each hero breaches a different door out of the entrance if available,
    # otherwise breaches whatever door remains (heroes can share a breach target --
    # splitting is legal, not mandatory that every hero get a unique room).
    reached_rooms = set()
    for hid in hero_ids:
        d = h.door_direction(entrance)
        if d is None:
            break
        h.send(hid, CommandType.BREACH, {"direction": d.value})
        reached_rooms.add(h.state.heroes[hid].room_id)

    assert len(reached_rooms) >= 2, "heroes should have split across multiple rooms"
    for room_id in reached_rooms:
        assert h.state.map.rooms[room_id].entered
        assert h.state.map.rooms[room_id].family is not None

    # Visible d8: every breach's ROOM_BREACHED event carries the raw 1-8 face
    # the client displayed, and it matches the room family it produced (§7.2).
    from backend.lan_playground.systems.room_generation import FAMILY_BY_D8

    breach_events = [e for e in h.event_log if e.type.value == "room_breached"]
    assert len(breach_events) >= 2
    for evt in breach_events:
        face = evt.payload["d8_face"]
        assert 1 <= face <= 8
        assert evt.payload["family"] == FAMILY_BY_D8[face]

    # Breaching locks movement for the rest of the round (§8.1); pass to close
    # out the round so movement unlocks before heroes try to regroup.
    starting_round = h.state.world_round
    for hid in hero_ids:
        if not h.state.heroes[hid].submitted_turn:
            h.send(hid, CommandType.PASS)
    assert h.state.world_round == starting_round + 1

    # Regroup: every hero moves back through their OPEN connector to the entrance.
    for hid in hero_ids:
        room_id = h.state.heroes[hid].room_id
        if room_id == entrance:
            continue
        back_dir = h.open_direction(room_id)
        h.send(hid, CommandType.MOVE, {"direction": back_dir.value})

    for hid in hero_ids:
        assert h.state.heroes[hid].room_id == entrance

    # Drive toward the exit: repeatedly breach/move along doors until every hero
    # stands in the exit room, or we've explored the whole generated map.
    exit_room_id = h.state.map.exit_room_id
    budget = 200
    while budget > 0 and not all(h.state.heroes[hid].room_id == exit_room_id for hid in hero_ids):
        budget -= 1
        progressed = False
        for hid in hero_ids:
            hero = h.state.heroes[hid]
            if hero.room_id == exit_room_id:
                continue
            room = h.state.map.rooms[hero.room_id]
            if hero.movement_locked or hero.energy < 1:
                h.send(hid, CommandType.PASS)
                progressed = True
                continue
            open_d = h.open_direction(hero.room_id)
            door_d = h.door_direction(hero.room_id)
            if open_d is not None and hero.energy >= 1:
                h.send(hid, CommandType.MOVE, {"direction": open_d.value})
                progressed = True
            elif door_d is not None and hero.energy >= 3:
                h.send(hid, CommandType.BREACH, {"direction": door_d.value})
                progressed = True
            else:
                h.send(hid, CommandType.PASS)
                progressed = True
        if not progressed:
            break

    assert h.state.map.rooms[exit_room_id].is_exit
    assert any(h.state.heroes[hid].room_id == exit_room_id for hid in hero_ids), (
        "at least one hero should be able to reach the generated exit room"
    )


def test_energy_spent_and_refresh_at_world_round_boundary():
    h = Harness(seed=99)
    h.send("hero_a", CommandType.JOIN_RUN)
    entrance = h.state.map.entrance_room_id
    d = h.door_direction(entrance)
    h.send("hero_a", CommandType.BREACH, {"direction": d.value})
    assert h.state.heroes["hero_a"].energy == 2  # 5 - 3
    assert h.state.world_round == 1

    h.send("hero_a", CommandType.PASS)
    # Only living/conscious hero has passed -> round should have advanced.
    assert h.state.world_round == 2
    assert h.state.heroes["hero_a"].energy == 5
    assert h.state.heroes["hero_a"].submitted_turn is False
    assert h.state.heroes["hero_a"].movement_locked is False


def test_round_waits_for_every_living_conscious_hero():
    h = Harness(seed=5)
    h.send("hero_a", CommandType.JOIN_RUN)
    h.send("hero_b", CommandType.JOIN_RUN)
    h.send("hero_a", CommandType.PASS)
    assert h.state.world_round == 1  # hero_b hasn't passed yet
    h.send("hero_b", CommandType.PASS)
    assert h.state.world_round == 2


def test_reduce_and_apply_never_mutate_the_input_state():
    """§22.1: reduce(state, event) -> new_state must be pure -- the caller's
    prior state reference (e.g. a transport-lane reconnect snapshot) must stay
    intact after apply()."""
    h = Harness(seed=42)
    h.send("hero_a", CommandType.JOIN_RUN)

    prior_state = h.state
    prior_hash = prior_state.state_hash()
    prior_heroes_snapshot = dict(prior_state.heroes)

    entrance = h.state.map.entrance_room_id
    d = h.door_direction(entrance)
    h.send("hero_a", CommandType.BREACH, {"direction": d.value})

    assert h.state is not prior_state
    assert prior_state.state_hash() == prior_hash, "prior state object was mutated by a later apply()"
    assert prior_state.heroes["hero_a"].energy == prior_heroes_snapshot["hero_a"].energy == 5
    assert prior_state.heroes["hero_a"].room_id == entrance


def test_deterministic_replay_reproduces_state_hash():
    def run_scenario(seed):
        h = Harness(run_id="run_replay", seed=seed)
        for hid in ("hero_a", "hero_b", "hero_c", "hero_d"):
            h.send(hid, CommandType.JOIN_RUN)
        entrance = h.state.map.entrance_room_id
        for hid in ("hero_a", "hero_b"):
            d = h.door_direction(entrance)
            if d:
                h.send(hid, CommandType.BREACH, {"direction": d.value})
        for hid in ("hero_a", "hero_b", "hero_c", "hero_d"):
            if not h.state.heroes[hid].submitted_turn:
                h.send(hid, CommandType.PASS)
        return h

    h = run_scenario(seed=2024)
    live_hash = h.state.state_hash()

    replayed = replay_mod.replay(
        run_id="run_replay", seed=2024, chapter_floor_index=0, events=h.event_log
    )
    assert replayed.state_hash() == live_hash
    assert replayed.world_round == h.state.world_round
    assert replayed.heroes.keys() == h.state.heroes.keys()
    for hid in replayed.heroes:
        assert replayed.heroes[hid].room_id == h.state.heroes[hid].room_id
        assert replayed.heroes[hid].energy == h.state.heroes[hid].energy


def test_replay_is_stable_across_multiple_seeds():
    for seed in (1, 2, 3, 42, 999):
        h = Harness(run_id="run_multi", seed=seed)
        for hid in ("hero_a", "hero_b"):
            h.send(hid, CommandType.JOIN_RUN)
        entrance = h.state.map.entrance_room_id
        d = h.door_direction(entrance)
        if d:
            h.send("hero_a", CommandType.BREACH, {"direction": d.value})
        h.send("hero_a", CommandType.PASS)
        h.send("hero_b", CommandType.PASS)

        replayed = replay_mod.replay("run_multi", seed, 0, h.event_log)
        assert replayed.state_hash() == h.state.state_hash(), f"replay mismatch for seed {seed}"


# ---------------------------------------------------------------- checks (§12)

def test_check_outcome_margins():
    rng = StacksRNG(1)
    assert checks.outcome_for_margin(5).value == "strong_success"
    assert checks.outcome_for_margin(10).value == "strong_success"
    assert checks.outcome_for_margin(0).value == "clean_success"
    assert checks.outcome_for_margin(4).value == "clean_success"
    assert checks.outcome_for_margin(-1).value == "cost_progress"
    assert checks.outcome_for_margin(-4).value == "cost_progress"
    assert checks.outcome_for_margin(-5).value == "setback"
    assert checks.outcome_for_margin(-20).value == "setback"


def test_check_total_matches_formula():
    rng = StacksRNG(3)
    result = checks.perform_check(rng, attribute_score=3, skill_rank=2, dc=11, modifiers=1)
    assert result.total == result.chosen_die + 3 + 2 + 1
    assert result.margin == result.total - 11
    assert len(result.die_rolls) == 1


def test_advantage_and_disadvantage_cancel_one_for_one():
    assert checks.net_advantage(1, 0) == 1
    assert checks.net_advantage(0, 1) == -1
    assert checks.net_advantage(1, 1) == 0
    assert checks.net_advantage(3, 3) == 0
    assert checks.net_advantage(2, 1) == 1
    assert checks.net_advantage(1, 2) == -1
    assert checks.net_advantage(3, 1) == 1  # still caps at a single net advantage


def test_advantage_rolls_two_keeps_higher():
    rng = StacksRNG(11)
    result = checks.perform_check(rng, attribute_score=0, skill_rank=0, dc=0, advantage_sources=1)
    assert len(result.die_rolls) == 2
    assert result.chosen_die == max(result.die_rolls)


def test_disadvantage_rolls_two_keeps_lower():
    rng = StacksRNG(11)
    result = checks.perform_check(rng, attribute_score=0, skill_rank=0, dc=0, disadvantage_sources=1)
    assert len(result.die_rolls) == 2
    assert result.chosen_die == min(result.die_rolls)


def test_opposed_check_ties_favor_current_state():
    class FixedRNG:
        def __init__(self, value):
            self.value = value

        def roll_d20(self):
            return self.value

    fixed = FixedRNG(10)
    winner, _, _ = checks.opposed_check(
        fixed, "defender", "attacker", side_a_attribute=0, side_a_skill=0,
        side_b_name="defender", side_b_attribute=0, side_b_skill=0,
    )
    assert winner == "defender"


def test_check_command_spends_major_skill_interaction_energy():
    h = Harness(seed=17)
    h.send("hero_a", CommandType.JOIN_RUN)
    starting_energy = h.state.heroes["hero_a"].energy
    h.send("hero_a", CommandType.CHECK, {"attribute_score": 2, "skill_rank": 1, "dc": 11})
    assert h.state.heroes["hero_a"].energy == starting_energy - 2
    check_events = [e for e in h.event_log if e.type.value == "check_resolved"]
    assert len(check_events) == 1
    assert check_events[0].payload["outcome"] in (
        "strong_success", "clean_success", "cost_progress", "setback",
    )
