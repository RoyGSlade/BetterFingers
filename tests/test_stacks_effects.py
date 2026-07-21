"""Effect-op dispatcher tests (docs/INFINITE_STACKS_CONTRACTS.md §5, board task #5).

`systems/effects.py` compiles content-authored `{"op", "args"}` effect dicts
into real domain events. These tests exercise the dispatcher directly against
a real `RunState` (built through the normal command/reducer pipeline, same
`Harness` pattern as tests/test_stacks_engine.py) for each of the four ops
`content/schemas.py` now marks `OpStatus.LIVE`: `reveal_room`, `spend_energy`,
`grant_check`, `emit_fact`. End-to-end wiring through real Mystery Chamber
puzzle consequences is covered separately in tests/test_stacks_puzzle_rooms.py.
"""
from __future__ import annotations

from backend.lan_playground.content import schemas as S
from backend.lan_playground.domain import reducer
from backend.lan_playground.domain.commands import Command, CommandType
from backend.lan_playground.domain.events import EventType, Visibility
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConnectorState, Direction, RunState
from backend.lan_playground.systems import effects


class Harness:
    def __init__(self, run_id="run_effects", seed=1, chapter_floor_index=0):
        self.state = RunState.initial(run_id=run_id, seed=seed, chapter_floor_index=chapter_floor_index)
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


def _fake_command(command_id="effect-test-cmd") -> Command:
    return Command(
        command_id=command_id,
        idempotency_key=command_id,
        run_id="run_effects",
        type=CommandType.CHECK,
        hero_id=None,
        expected_revision=0,
        payload={},
    )


def _apply_all(state, events):
    for event in events:
        state = reducer.reduce(state, event)
    return state


# ---------------------------------------------------------------------------
# reveal_room
# ---------------------------------------------------------------------------


def test_reveal_room_discovers_the_target_room_without_rolling_it():
    h = Harness(seed=11)
    h.send("hero_a", CommandType.JOIN_RUN)
    entrance = h.state.map.entrance_room_id
    room = h.state.map.rooms[entrance]
    direction = next(d for d, c in room.connectors.items() if c == ConnectorState.DOOR)
    from backend.lan_playground.domain.state import DELTA, room_id_for

    dx, dy = DELTA[direction]
    target_room_id = room_id_for(room.x + dx, room.y + dy)
    assert h.state.map.rooms[target_room_id].discovered is False

    events = effects.dispatch(
        [{"op": "reveal_room", "args": {"connector": direction.value}}],
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_a",
        room_id=entrance,
    )
    assert len(events) == 1
    assert events[0].type == EventType.ROOM_REVEALED_BY_EFFECT
    assert events[0].visibility == Visibility.PUBLIC

    new_state = _apply_all(h.state, events)
    assert new_state.map.rooms[target_room_id].discovered is True
    assert new_state.map.rooms[target_room_id].family is None  # revealed, not rolled/breached


def test_reveal_room_beyond_the_generated_map_is_a_noop():
    """reveal_room doesn't require an existing DOOR connector (it can expose
    a room beyond normal §7.1 connectivity, e.g. a secret/anomaly effect) --
    but it must still no-op rather than fabricate a room where the generator
    placed none at all."""

    from backend.lan_playground.domain.state import DELTA, room_id_for

    h = Harness(seed=11)
    h.send("hero_a", CommandType.JOIN_RUN)
    room_id, off_map_direction = next(
        (rid, d)
        for rid, room in h.state.map.rooms.items()
        for d in Direction
        if room_id_for(room.x + DELTA[d][0], room.y + DELTA[d][1]) not in h.state.map.rooms
    )

    events = effects.dispatch(
        [{"op": "reveal_room", "args": {"connector": off_map_direction.value}}],
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_a",
        room_id=room_id,
    )
    assert events == ()


# ---------------------------------------------------------------------------
# spend_energy
# ---------------------------------------------------------------------------


def test_spend_energy_deducts_from_the_actor():
    h = Harness(seed=2)
    h.send("hero_a", CommandType.JOIN_RUN)
    starting = h.state.heroes["hero_a"].energy

    events = effects.dispatch(
        [{"op": "spend_energy", "args": {"amount": 2}}],
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_a",
        room_id=h.state.heroes["hero_a"].room_id,
    )
    assert len(events) == 1
    assert events[0].type == EventType.EFFECT_ENERGY_SPENT

    new_state = _apply_all(h.state, events)
    assert new_state.heroes["hero_a"].energy == starting - 2


def test_spend_energy_clamps_at_zero_never_goes_negative():
    h = Harness(seed=2)
    h.send("hero_a", CommandType.JOIN_RUN)

    events = effects.dispatch(
        [{"op": "spend_energy", "args": {"amount": 99}}],
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_a",
        room_id=h.state.heroes["hero_a"].room_id,
    )
    new_state = _apply_all(h.state, events)
    assert new_state.heroes["hero_a"].energy == 0


# ---------------------------------------------------------------------------
# grant_check
# ---------------------------------------------------------------------------


def test_grant_check_resolves_a_real_d20_check_via_checks_system():
    h = Harness(seed=3)
    h.send("hero_a", CommandType.JOIN_RUN)

    events = effects.dispatch(
        [{"op": "grant_check", "args": {"attribute": "insight", "skill": "read", "dc": 11}}],
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_a",
        room_id=h.state.heroes["hero_a"].room_id,
    )
    assert len(events) == 1
    event = events[0]
    assert event.type == EventType.CHECK_RESOLVED
    assert event.payload["dc"] == 11
    assert 1 <= event.payload["chosen_die"] <= 20
    assert event.payload["margin"] == event.payload["total"] - 11
    assert event.payload["outcome"] in ("strong_success", "clean_success", "cost_progress", "setback")

    # Applying must not raise -- CHECK_RESOLVED's applier is already
    # registered globally by systems/checks.py.
    _apply_all(h.state, events)


def test_grant_check_is_a_noop_for_an_unknown_actor():
    h = Harness(seed=3)
    events = effects.dispatch(
        [{"op": "grant_check", "args": {"dc": 11}}],
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_ghost",
        room_id=None,
    )
    assert events == ()


# ---------------------------------------------------------------------------
# emit_fact
# ---------------------------------------------------------------------------


def test_emit_fact_appends_to_the_run_facts_ledger():
    h = Harness(seed=4)
    h.send("hero_a", CommandType.JOIN_RUN)
    assert h.state.facts == ()

    events = effects.dispatch(
        [{"op": "emit_fact", "args": {"fact_id": "shelf_reordered"}}],
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_a",
        room_id=h.state.heroes["hero_a"].room_id,
    )
    new_state = _apply_all(h.state, events)
    assert new_state.facts == ("shelf_reordered",)


def test_emit_fact_is_deduplicated_in_the_ledger():
    h = Harness(seed=4)
    h.send("hero_a", CommandType.JOIN_RUN)

    events = effects.dispatch(
        [{"op": "emit_fact", "args": {"fact_id": "dup"}}, {"op": "emit_fact", "args": {"fact_id": "dup"}}],
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_a",
        room_id=h.state.heroes["hero_a"].room_id,
    )
    new_state = _apply_all(h.state, events)
    assert new_state.facts == ("dup",)


# ---------------------------------------------------------------------------
# Dispatcher plumbing
# ---------------------------------------------------------------------------


def test_unknown_or_planned_op_is_silently_skipped_not_erroring():
    h = Harness(seed=5)
    h.send("hero_a", CommandType.JOIN_RUN)

    events = effects.dispatch(
        [{"op": "damage", "args": {"amount": 3}}],  # PLANNED, not LIVE -- no handler yet
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_a",
        room_id=h.state.heroes["hero_a"].room_id,
    )
    assert events == ()


def test_live_ops_dispatcher_coverage_matches_content_schemas():
    live_in_schema = {name for name, spec in S.KNOWN_OPS.items() if spec.status is S.OpStatus.LIVE}
    assert live_in_schema == effects.LIVE_OPS == {
        "reveal_room",
        "spend_energy",
        "grant_check",
        "emit_fact",
        "apply_condition",
        "remove_condition",
    }


def test_dispatch_sequences_event_ids_without_collision():
    h = Harness(seed=6)
    h.send("hero_a", CommandType.JOIN_RUN)

    events = effects.dispatch(
        [
            {"op": "emit_fact", "args": {"fact_id": "a"}},
            {"op": "emit_fact", "args": {"fact_id": "b"}},
            {"op": "spend_energy", "args": {"amount": 1}},
        ],
        command=_fake_command(),
        state=h.state,
        rng=h.rng,
        seq=h.seq,
        actor_hero_id="hero_a",
        room_id=h.state.heroes["hero_a"].room_id,
    )
    assert len(events) == 3
    assert len({e.event_id for e in events}) == 3
