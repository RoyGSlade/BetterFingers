"""Authoritative core per infinite_stacks.md §22.1:

    validate(command, state, viewer) -> accepted command or error
    handle(command, state, rng)      -> ordered events
    reduce(state, event)             -> new state
    project(state, viewer)           -> authorized view

`apply()` composes all four plus the world-round-advance check (§8.2) into the
single entry point real callers (transport, tests, replay) use.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..systems import checks, effects, exploration, puzzles, turns
from .commands import Command, CommandError, CommandType, ErrorCode
from .events import Event
from .rng import StacksRNG
from .state import HeroState, RoomState, RunState

_VALIDATORS = {
    CommandType.JOIN_RUN: lambda state, hero_id, payload: exploration.validate_join_run(state, hero_id),
    CommandType.MOVE: lambda state, hero_id, payload: exploration.validate_move(state, hero_id, payload),
    CommandType.BREACH: lambda state, hero_id, payload: exploration.validate_breach(state, hero_id, payload),
    CommandType.OBSERVE: lambda state, hero_id, payload: exploration.validate_observe(state, hero_id, payload),
    CommandType.INSPECT: lambda state, hero_id, payload: exploration.validate_inspect(state, hero_id, payload),
    CommandType.PASS: lambda state, hero_id, payload: None,
    CommandType.CHECK: lambda state, hero_id, payload: turns.require_energy(state, hero_id, "major_skill_interaction"),
    CommandType.INSPECT_OBJECT: lambda state, hero_id, payload: puzzles.validate_inspect_object(state, hero_id, payload),
    CommandType.SUBMIT_SOLUTION: lambda state, hero_id, payload: puzzles.validate_submit_solution(state, hero_id, payload),
    CommandType.REQUEST_HINT: lambda state, hero_id, payload: puzzles.validate_request_hint(state, hero_id, payload),
}

_HANDLERS = {
    CommandType.JOIN_RUN: exploration.handle_join_run,
    CommandType.MOVE: exploration.handle_move,
    CommandType.BREACH: exploration.handle_breach,
    CommandType.OBSERVE: exploration.handle_observe,
    CommandType.INSPECT: exploration.handle_inspect,
    CommandType.PASS: lambda command, state, rng, seq: turns.handle_pass(command, state, seq),
    CommandType.CHECK: checks.handle_check,
    CommandType.INSPECT_OBJECT: puzzles.handle_inspect_object,
    CommandType.SUBMIT_SOLUTION: puzzles.handle_submit_solution,
    CommandType.REQUEST_HINT: puzzles.handle_request_hint,
}

EVENT_APPLIERS = {
    **turns.EVENT_APPLIERS,
    **exploration.EVENT_APPLIERS,
    **checks.EVENT_APPLIERS,
    **puzzles.EVENT_APPLIERS,
    **effects.EVENT_APPLIERS,
}


def validate(command: Command, state: RunState, viewer: str | None) -> None:
    """Raise CommandError on any rejection; return None when accepted."""
    if command.run_id != state.run_id:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"command targets run {command.run_id}, state is {state.run_id}")

    if command.type != CommandType.JOIN_RUN and command.expected_revision != state.revision:
        legal = exploration.legal_action_summary(state, command.hero_id) if command.hero_id in state.heroes else []
        raise CommandError(
            ErrorCode.STALE_REVISION,
            f"expected revision {command.expected_revision}, state is at {state.revision}",
            legal_actions=legal,
        )

    if command.hero_id is not None and viewer is not None and viewer != command.hero_id:
        raise CommandError(ErrorCode.NOT_YOUR_TURN, f"viewer {viewer} may not act for hero {command.hero_id}")

    validator = _VALIDATORS.get(command.type)
    if validator is None:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"unknown command type {command.type}")
    try:
        validator(state, command.hero_id, command.payload)
    except CommandError as exc:
        if not exc.legal_actions and command.hero_id in state.heroes:
            exc.legal_actions = exploration.legal_action_summary(state, command.hero_id)
        raise


def handle(command: Command, state: RunState, rng: StacksRNG, seq: int = 0) -> tuple[Event, ...]:
    handler = _HANDLERS.get(command.type)
    if handler is None:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"unknown command type {command.type}")
    return handler(command, state, rng, seq)


def reduce(state: RunState, event: Event) -> RunState:
    """Pure and total: never mutates `state`. Appliers mutate a private clone."""
    applier = EVENT_APPLIERS.get(event.type)
    if applier is None:
        raise ValueError(f"no applier registered for event type {event.type}")
    new_state = applier(state.clone(), event)
    new_state.revision += 1
    return new_state


@dataclass
class ProjectedRoom:
    room_id: str
    x: int
    y: int
    connectors: dict
    family: str | None
    subtype: str | None
    discovered: bool
    entered: bool
    is_exit: bool


@dataclass
class ProjectedView:
    run_id: str
    revision: int
    world_round: int
    heroes: dict
    rooms: dict[str, ProjectedRoom]
    resolved_room_count: int
    required_rooms: int


def project(state: RunState, viewer: str | None) -> ProjectedView:
    """Authorized view for `viewer` (a hero_id, or None for a spectator/system view).

    Wave-1 has no private RoomState.secrets yet (content lane owns that later);
    every hero and every discovered room is visible to every party member, per
    the shared-map model in §21.3. This function is the seam future secret
    fields plug into -- do not add ad hoc filtering elsewhere.
    """
    heroes = {hid: h.to_dict() for hid, h in state.heroes.items()}
    rooms: dict[str, ProjectedRoom] = {}
    if state.map is not None:
        for rid, room in state.map.rooms.items():
            if not room.discovered:
                continue
            rooms[rid] = ProjectedRoom(
                room_id=room.room_id,
                x=room.x,
                y=room.y,
                connectors={d.value: s.value for d, s in room.connectors.items()},
                family=room.family,
                subtype=room.subtype,
                discovered=room.discovered,
                entered=room.entered,
                is_exit=room.is_exit,
            )
    return ProjectedView(
        run_id=state.run_id,
        revision=state.revision,
        world_round=state.world_round,
        heroes=heroes,
        rooms=rooms,
        resolved_room_count=state.map.resolved_room_count() if state.map else 0,
        required_rooms=state.map.required_rooms if state.map else 0,
    )


@dataclass
class ApplyResult:
    state: RunState
    events: tuple[Event, ...]
    next_seq: int


def apply(command: Command, state: RunState, rng: StacksRNG, viewer: str | None = None, seq: int = 0) -> ApplyResult:
    """Full pipeline: validate -> handle -> reduce (+ world-round-advance check)."""
    validate(command, state, viewer)
    action_events = handle(command, state, rng, seq)
    next_seq = seq + len(action_events)

    new_state = state
    for event in action_events:
        new_state = reduce(new_state, event)

    round_events = turns.build_round_advance_events(new_state, command.command_id, next_seq)
    next_seq += len(round_events)
    for event in round_events:
        new_state = reduce(new_state, event)

    return ApplyResult(state=new_state, events=action_events + round_events, next_seq=next_seq)
