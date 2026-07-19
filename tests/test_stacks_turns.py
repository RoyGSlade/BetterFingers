"""Energy economy and world-round boundary tests (§8.1, §8.2)."""
from __future__ import annotations

import pytest

from backend.lan_playground.domain import reducer
from backend.lan_playground.domain.commands import Command, CommandError, CommandType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConnectorState, RunState
from backend.lan_playground.systems import turns


class Harness:
    def __init__(self, run_id="run_turns", seed=1):
        self.state = RunState.initial(run_id=run_id, seed=seed)
        self.rng = StacksRNG(seed)
        self.seq = 0
        self._cmd_n = 0

    def send(self, hero_id, ctype, payload=None):
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
        result = reducer.apply(cmd, self.state, self.rng, viewer=hero_id, seq=self.seq)
        self.state = result.state
        self.seq = result.next_seq
        return result

    def door_direction(self, room_id):
        room = self.state.map.rooms[room_id]
        for d, c in room.connectors.items():
            if c == ConnectorState.DOOR:
                return d
        return None


def test_energy_cost_table_matches_spec_defaults():
    assert turns.ENERGY_COSTS["move"] == 1
    assert turns.ENERGY_COSTS["breach"] == 3
    assert turns.ENERGY_COSTS["observe"] == 1
    assert turns.ENERGY_COSTS["inspect"] == 1
    assert turns.ENERGY_COSTS["major_skill_interaction"] == 2
    assert turns.ENERGY_COSTS["pass"] == 0
    assert turns.STARTING_ENERGY == 5


def test_hero_starts_round_with_five_energy():
    h = Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    assert h.state.heroes["hero_a"].energy == 5
    assert h.state.heroes["hero_a"].max_energy == 5


def test_move_costs_one_energy():
    h = Harness(seed=2)
    h.send("hero_a", CommandType.JOIN_RUN)
    entrance = h.state.map.entrance_room_id
    d = h.door_direction(entrance)
    h.send("hero_a", CommandType.BREACH, {"direction": d.value})
    h.send("hero_a", CommandType.PASS)  # close round, unlock movement
    room_id = h.state.heroes["hero_a"].room_id
    back_room = h.state.map.rooms[room_id]
    open_dirs = [dd for dd, cc in back_room.connectors.items() if cc == ConnectorState.OPEN]
    energy_before = h.state.heroes["hero_a"].energy
    h.send("hero_a", CommandType.MOVE, {"direction": open_dirs[0].value})
    assert h.state.heroes["hero_a"].energy == energy_before - 1


def test_breach_costs_three_energy_and_locks_movement():
    h = Harness(seed=3)
    h.send("hero_a", CommandType.JOIN_RUN)
    entrance = h.state.map.entrance_room_id
    d = h.door_direction(entrance)
    h.send("hero_a", CommandType.BREACH, {"direction": d.value})
    assert h.state.heroes["hero_a"].energy == 2
    assert h.state.heroes["hero_a"].movement_locked is True


def test_movement_locked_blocks_further_move_and_breach_same_round():
    h = Harness(seed=4)
    h.send("hero_a", CommandType.JOIN_RUN)
    h.send("hero_b", CommandType.JOIN_RUN)  # keep round open so hero_a's round doesn't advance
    entrance = h.state.map.entrance_room_id
    d = h.door_direction(entrance)
    h.send("hero_a", CommandType.BREACH, {"direction": d.value})
    with pytest.raises(CommandError):
        h.send("hero_a", CommandType.MOVE, {"direction": d.value})
    with pytest.raises(CommandError):
        h.send("hero_a", CommandType.BREACH, {"direction": d.value})


def test_observe_and_inspect_cost_one_energy_each():
    h = Harness(seed=5)
    h.send("hero_a", CommandType.JOIN_RUN)
    entrance = h.state.map.entrance_room_id
    d = h.door_direction(entrance)
    energy_before = h.state.heroes["hero_a"].energy
    h.send("hero_a", CommandType.OBSERVE, {"direction": d.value})
    assert h.state.heroes["hero_a"].energy == energy_before - 1

    energy_before = h.state.heroes["hero_a"].energy
    h.send("hero_a", CommandType.INSPECT, {})
    assert h.state.heroes["hero_a"].energy == energy_before - 1


def test_cannot_spend_more_energy_than_available():
    h = Harness(seed=6)
    h.send("hero_a", CommandType.JOIN_RUN)
    # Drain to 1 energy via four 1-cost inspects, then a breach (3E) must fail.
    for _ in range(4):
        h.send("hero_a", CommandType.INSPECT, {})
    assert h.state.heroes["hero_a"].energy == 1
    entrance = h.state.map.entrance_room_id
    d = h.door_direction(entrance)
    with pytest.raises(CommandError):
        h.send("hero_a", CommandType.BREACH, {"direction": d.value})


def test_pass_is_free_and_does_not_spend_energy():
    h = Harness(seed=7)
    h.send("hero_a", CommandType.JOIN_RUN)
    h.send("hero_b", CommandType.JOIN_RUN)
    energy_before = h.state.heroes["hero_a"].energy
    h.send("hero_a", CommandType.PASS)
    assert h.state.heroes["hero_a"].energy == energy_before


def test_round_refreshes_only_after_every_living_conscious_hero_acts():
    h = Harness(seed=8)
    for hid in ("hero_a", "hero_b", "hero_c"):
        h.send(hid, CommandType.JOIN_RUN)
    assert h.state.world_round == 1

    h.send("hero_a", CommandType.PASS)
    assert h.state.world_round == 1
    h.send("hero_b", CommandType.PASS)
    assert h.state.world_round == 1
    h.send("hero_c", CommandType.PASS)
    assert h.state.world_round == 2  # every living conscious hero has now passed

    for hid in ("hero_a", "hero_b", "hero_c"):
        assert h.state.heroes[hid].energy == 5
        assert h.state.heroes[hid].submitted_turn is False


def test_downed_hero_excluded_from_round_completion_gate():
    h = Harness(seed=9)
    for hid in ("hero_a", "hero_b"):
        h.send(hid, CommandType.JOIN_RUN)
    h.state.heroes["hero_b"].conscious = False  # simulate Downed
    h.send("hero_a", CommandType.PASS)
    assert h.state.world_round == 2, "round should advance without waiting on the Downed hero"


def test_dead_hero_excluded_from_round_completion_gate():
    h = Harness(seed=10)
    for hid in ("hero_a", "hero_b"):
        h.send(hid, CommandType.JOIN_RUN)
    h.state.heroes["hero_b"].alive = False
    h.send("hero_a", CommandType.PASS)
    assert h.state.world_round == 2


def test_already_passed_hero_cannot_act_again_this_round():
    h = Harness(seed=11)
    h.send("hero_a", CommandType.JOIN_RUN)
    h.send("hero_b", CommandType.JOIN_RUN)
    h.send("hero_a", CommandType.PASS)
    with pytest.raises(CommandError):
        h.send("hero_a", CommandType.INSPECT, {})
