"""Exploration Energy costs and world-round refresh (infinite_stacks.md §8).

A hero may take any number of exploration actions in a round as long as they
can afford the Energy cost. A hero's round participation ends when they submit
`pass` (0 Energy) -- that is this engine's reading of "submitted a turn,
passed, or timed out" (§8.2): every other action keeps the round open for that
hero. Round refresh happens once every living, conscious hero has passed.
"""
from __future__ import annotations

from ..domain.commands import Command, CommandError, ErrorCode
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.state import RunState
from . import abilities as ability_systems

ENERGY_COSTS = {
    "move": 1,
    "breach": 3,
    "observe": 1,
    "inspect": 1,
    "major_skill_interaction": 2,
    "treat_light_condition": 1,
    "shop_action": 1,
    "assist": 1,
    "pass": 0,
    # wave6b/slice-wiring (docs/INFINITE_STACKS_STUDY_SLICE.md): a single
    # object interaction costs the same as "inspect" (a minor exploration
    # action); a social approach/converse turn costs the same as a major
    # skill interaction since it may resolve a d20 social check.
    "interact": 1,
    "converse": 2,
}

STARTING_ENERGY = 5


def _require_free_to_act(state: RunState, hero_id: str | None):
    if hero_id is None or hero_id not in state.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown hero {hero_id}")
    hero = state.heroes[hero_id]
    if not hero.conscious:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} is Downed/Stable and cannot take exploration actions")
    if state.map is not None:
        room = state.map.rooms.get(hero.room_id)
        if room is not None and room.encounter is not None and room.encounter.status == "active" and hero_id in room.encounter.heroes:
            raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} is in an active encounter -- use combat commands")
    return hero


def require_energy(state: RunState, hero_id: str, action: str) -> int:
    cost = ENERGY_COSTS[action]
    hero = _require_free_to_act(state, hero_id)
    if hero.submitted_turn:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} already passed this round")
    if hero.energy < cost:
        raise CommandError(
            ErrorCode.ILLEGAL_ACTION,
            f"{hero_id} has {hero.energy} Energy, needs {cost} for {action}",
        )
    return cost


def handle_pass(command: Command, state: RunState, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    hero = _require_free_to_act(state, hero_id)
    if hero.submitted_turn:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} already passed this round")
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.TURN_SUBMITTED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
            payload={},
        ),
    )


def apply_turn_submitted(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.submitted_turn = True
    # Wave-6 (board task #21, playtest A5): until_end_of_turn active effects
    # expire the moment their owner's turn ends, not at the next world round.
    hero.active_effects = ability_systems.expire_boundary(hero.active_effects, boundary="turn")
    return state


def build_round_advance_events(state: RunState, rng, command_id: str, seq: int) -> tuple[Event, ...]:
    """§8.2 round completion: (1) scheduled hazards/enemies act -- every
    active Conflict encounter's combat round advances in lockstep here
    (§7.4/§14.1's "one combat round == one world round") -- (2)-(3) folded
    into that same combat-round-advance step, then (4) Energy refreshes via
    WORLD_ROUND_ADVANCED below."""
    if not state.round_complete():
        return ()
    from . import combat as combat_systems

    combat_round_events = combat_systems.build_round_advance_combat_events(state, rng, command_id, seq)
    seq += len(combat_round_events)
    world_round_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command_id,
        type=EventType.WORLD_ROUND_ADVANCED,
        visibility=Visibility.PUBLIC,
        payload={"completed_round": state.world_round, "next_round": state.world_round + 1},
    )
    return combat_round_events + (world_round_event,)


def apply_world_round_advanced(state: RunState, event: Event) -> RunState:
    for hero in state.heroes.values():
        if hero.alive and hero.conscious:
            hero.energy = hero.max_energy
            hero.submitted_turn = False
            hero.movement_locked = False
        # Wave-6 (board task #21, playtest A5): until_end_of_round active
        # effects expire for EVERY hero at the world-round boundary,
        # regardless of consciousness -- a Downed hero's effects don't
        # linger past the round they were meant for.
        hero.active_effects = ability_systems.expire_boundary(hero.active_effects, boundary="round")
    state.world_round = event.payload["next_round"]
    return state


def apply_energy_spent(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.energy -= event.payload["amount"]
    return state


EVENT_APPLIERS = {
    EventType.TURN_SUBMITTED: apply_turn_submitted,
    EventType.WORLD_ROUND_ADVANCED: apply_world_round_advanced,
    EventType.ENERGY_SPENT: apply_energy_spent,
}
