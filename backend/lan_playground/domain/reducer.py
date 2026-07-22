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

from ..systems import (
    checks,
    combat,
    effects,
    exploration,
    heroes_wire,
    puzzles,
    shops_wire,
    study_interact_wire,
    study_social_wire,
    study_wire,
    turns,
)
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
    CommandType.COMBAT_ATTACK: lambda state, hero_id, payload: combat.validate_combat_attack(state, hero_id, payload),
    CommandType.COMBAT_MANEUVER: lambda state, hero_id, payload: combat.validate_combat_maneuver(state, hero_id, payload),
    CommandType.COMBAT_REACTION: lambda state, hero_id, payload: combat.validate_combat_reaction(state, hero_id, payload),
    CommandType.COMBAT_MOVE: lambda state, hero_id, payload: combat.validate_combat_move(state, hero_id, payload),
    CommandType.COMBAT_QUICK_INTERACTION: lambda state, hero_id, payload: combat.validate_combat_quick_interaction(
        state, hero_id, payload
    ),
    CommandType.COMBAT_STABILIZE: lambda state, hero_id, payload: combat.validate_combat_stabilize(state, hero_id, payload),
    CommandType.COMBAT_BARRICADE: lambda state, hero_id, payload: combat.validate_combat_barricade(state, hero_id, payload),
    CommandType.COMBAT_END_TURN: lambda state, hero_id, payload: combat.validate_combat_end_turn(state, hero_id, payload),
    CommandType.RESOLVE_REACTION: lambda state, hero_id, payload: combat.validate_resolve_reaction(state, hero_id, payload),
    CommandType.ROLL_ATTRIBUTE_DICE: lambda state, hero_id, payload: heroes_wire.validate_roll_attribute_dice(
        state, hero_id, payload
    ),
    CommandType.CREATE_HERO: lambda state, hero_id, payload: heroes_wire.validate_create_hero(state, hero_id, payload),
    CommandType.PLAY_CARD: lambda state, hero_id, payload: heroes_wire.validate_play_card(state, hero_id, payload),
    CommandType.DRAW_CARDS: lambda state, hero_id, payload: heroes_wire.validate_draw_cards(state, hero_id, payload),
    CommandType.SAFE_REST: lambda state, hero_id, payload: heroes_wire.validate_safe_rest(state, hero_id, payload),
    CommandType.PICKUP_ITEM: lambda state, hero_id, payload: heroes_wire.validate_pickup_item(state, hero_id, payload),
    CommandType.DROP_ITEM: lambda state, hero_id, payload: heroes_wire.validate_drop_item(state, hero_id, payload),
    CommandType.TRADE_ITEM: lambda state, hero_id, payload: heroes_wire.validate_trade_item(state, hero_id, payload),
    CommandType.RECOVER_BODY_LOOT: lambda state, hero_id, payload: heroes_wire.validate_recover_body_loot(
        state, hero_id, payload
    ),
    CommandType.SHOP_BUY: lambda state, hero_id, payload: shops_wire.validate_shop_buy(state, hero_id, payload),
    CommandType.SHOP_SELL: lambda state, hero_id, payload: shops_wire.validate_shop_sell(state, hero_id, payload),
    CommandType.SHOP_REPAIR: lambda state, hero_id, payload: shops_wire.validate_shop_repair(state, hero_id, payload),
    CommandType.SHOP_IDENTIFY: lambda state, hero_id, payload: shops_wire.validate_shop_identify(state, hero_id, payload),
    CommandType.SHOP_TREAT: lambda state, hero_id, payload: shops_wire.validate_shop_treat(state, hero_id, payload),
    CommandType.SHARE_CLUE: lambda state, hero_id, payload: puzzles.validate_share_clue(state, hero_id, payload),
    CommandType.USE_ABILITY: lambda state, hero_id, payload: heroes_wire.validate_use_ability(state, hero_id, payload),
    CommandType.INTERACT: lambda state, hero_id, payload: study_interact_wire.validate_interact(state, hero_id, payload),
    CommandType.CONVERSE: lambda state, hero_id, payload: study_social_wire.validate_converse(state, hero_id, payload),
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
    CommandType.COMBAT_ATTACK: combat.handle_combat_attack,
    CommandType.COMBAT_MANEUVER: combat.handle_combat_maneuver,
    CommandType.COMBAT_REACTION: combat.handle_combat_reaction,
    CommandType.COMBAT_MOVE: combat.handle_combat_move,
    CommandType.COMBAT_QUICK_INTERACTION: combat.handle_combat_quick_interaction,
    CommandType.COMBAT_STABILIZE: combat.handle_combat_stabilize,
    CommandType.COMBAT_BARRICADE: combat.handle_combat_barricade,
    CommandType.COMBAT_END_TURN: combat.handle_combat_end_turn,
    CommandType.RESOLVE_REACTION: combat.handle_resolve_reaction,
    CommandType.ROLL_ATTRIBUTE_DICE: heroes_wire.handle_roll_attribute_dice,
    CommandType.CREATE_HERO: heroes_wire.handle_create_hero,
    CommandType.PLAY_CARD: heroes_wire.handle_play_card,
    CommandType.DRAW_CARDS: heroes_wire.handle_draw_cards,
    CommandType.SAFE_REST: heroes_wire.handle_safe_rest,
    CommandType.PICKUP_ITEM: heroes_wire.handle_pickup_item,
    CommandType.DROP_ITEM: heroes_wire.handle_drop_item,
    CommandType.TRADE_ITEM: heroes_wire.handle_trade_item,
    CommandType.RECOVER_BODY_LOOT: heroes_wire.handle_recover_body_loot,
    CommandType.SHOP_BUY: shops_wire.handle_shop_buy,
    CommandType.SHOP_SELL: shops_wire.handle_shop_sell,
    CommandType.SHOP_REPAIR: shops_wire.handle_shop_repair,
    CommandType.SHOP_IDENTIFY: shops_wire.handle_shop_identify,
    CommandType.SHOP_TREAT: shops_wire.handle_shop_treat,
    CommandType.SHARE_CLUE: puzzles.handle_share_clue,
    CommandType.USE_ABILITY: heroes_wire.handle_use_ability,
    CommandType.INTERACT: study_interact_wire.handle_interact,
    CommandType.CONVERSE: study_social_wire.handle_converse,
}

EVENT_APPLIERS = {
    **turns.EVENT_APPLIERS,
    **exploration.EVENT_APPLIERS,
    **checks.EVENT_APPLIERS,
    **puzzles.EVENT_APPLIERS,
    **effects.EVENT_APPLIERS,
    **combat.EVENT_APPLIERS,
    **heroes_wire.EVENT_APPLIERS,
    **shops_wire.EVENT_APPLIERS,
    **study_wire.EVENT_APPLIERS,
    **study_interact_wire.EVENT_APPLIERS,
    **study_social_wire.EVENT_APPLIERS,
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

    round_events = turns.build_round_advance_events(new_state, rng, command.command_id, next_seq)
    next_seq += len(round_events)
    for event in round_events:
        new_state = reduce(new_state, event)

    return ApplyResult(state=new_state, events=action_events + round_events, next_seq=next_seq)
