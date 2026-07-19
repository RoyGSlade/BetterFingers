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
}

STARTING_ENERGY = 5


def require_energy(state: RunState, hero_id: str, action: str) -> int:
    cost = ENERGY_COSTS[action]
    if hero_id not in state.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown hero {hero_id}")
    hero = state.heroes[hero_id]
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
    if hero_id not in state.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown hero {hero_id}")
    hero = state.heroes[hero_id]
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
    return state


def build_round_advance_events(state: RunState, command_id: str, seq: int) -> tuple[Event, ...]:
    if not state.round_complete():
        return ()
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command_id,
            type=EventType.WORLD_ROUND_ADVANCED,
            visibility=Visibility.PUBLIC,
            payload={"completed_round": state.world_round, "next_round": state.world_round + 1},
        ),
    )


def apply_world_round_advanced(state: RunState, event: Event) -> RunState:
    for hero in state.heroes.values():
        if hero.alive and hero.conscious:
            hero.energy = hero.max_energy
            hero.submitted_turn = False
            hero.movement_locked = False
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
