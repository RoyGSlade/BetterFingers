"""Effect-op dispatcher (docs/INFINITE_STACKS_CONTRACTS.md §5).

Compiles content-authored effect ops -- the `{"op": str, "args": dict}` IR
`content/schemas.py`'s `Effect.compile()` already produces -- into real
domain events via the normal `handle() -> events -> reduce()` pipeline.
This wires exactly the four wave-1-authored ops
(`reveal_room`, `spend_energy`, `grant_check`, `emit_fact`); `content/
schemas.py`'s `KNOWN_OPS` marks all four `OpStatus.LIVE` as of this wave.
Every other op in `KNOWN_OPS` stays `OpStatus.PLANNED` (cards/combat/
inventory are out of scope this wave, per contracts doc §10) and is silently
skipped by `dispatch()` below -- content validators, not this dispatcher, are
what guarantee only a known op ever reaches here.

`dispatch()` is called from systems/puzzles.py (puzzle success/failure
consequences) today; any future caller (cards, conditions, enemy intents)
reuses it unchanged once its own reducer wiring lands, since this module has
no knowledge of who invoked it.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from ..domain.commands import Command
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.state import ActiveEffectState, DELTA, Direction, RunState, room_id_for
from ..domain.rng import StacksRNG
from . import checks


def _reveal_room(
    command: Command, state: RunState, rng: StacksRNG, seq: int, actor_hero_id: str | None, room_id: str | None, args: dict
) -> tuple[Event, ...]:
    if room_id is None or state.map is None or room_id not in state.map.rooms:
        return ()
    try:
        direction = Direction(args["connector"])
    except ValueError:
        return ()
    room = state.map.rooms[room_id]
    dx, dy = DELTA[direction]
    target_room_id = room_id_for(room.x + dx, room.y + dy)
    if target_room_id not in state.map.rooms:
        return ()
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.ROOM_REVEALED_BY_EFFECT,
            visibility=Visibility.PUBLIC,
            actor_hero_id=actor_hero_id,
            room_id=target_room_id,
            payload={"room_id": target_room_id, "source_room_id": room_id},
        ),
    )


def _spend_energy(
    command: Command, state: RunState, rng: StacksRNG, seq: int, actor_hero_id: str | None, room_id: str | None, args: dict
) -> tuple[Event, ...]:
    if actor_hero_id is None or actor_hero_id not in state.heroes:
        return ()
    amount = int(args["amount"])
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.EFFECT_ENERGY_SPENT,
            visibility=Visibility.PARTY,
            actor_hero_id=actor_hero_id,
            room_id=room_id,
            payload={"amount": amount},
        ),
    )


def _grant_check(
    command: Command, state: RunState, rng: StacksRNG, seq: int, actor_hero_id: str | None, room_id: str | None, args: dict
) -> tuple[Event, ...]:
    if actor_hero_id is None or actor_hero_id not in state.heroes:
        return ()
    dc = int(args.get("dc", 11))
    # No character-sheet attributes/skills exist yet (Phase 3, out of scope --
    # contracts doc §10); a real check still resolves through checks.py with
    # a flat d20, so this is a genuine handler, not a stub -- attribute/skill
    # args are recorded on the event for the future hero-sheet lookup to fill in.
    result = checks.perform_check(rng, attribute_score=0, skill_rank=0, dc=dc)
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.CHECK_RESOLVED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=actor_hero_id,
            room_id=room_id,
            payload={
                "die_rolls": list(result.die_rolls),
                "chosen_die": result.chosen_die,
                "total": result.total,
                "dc": result.dc,
                "margin": result.margin,
                "outcome": result.outcome.value,
                "natural_20": result.natural_20,
                "natural_1": result.natural_1,
                "attribute": args.get("attribute"),
                "skill": args.get("skill"),
                "source": "effect:grant_check",
            },
        ),
    )


def _emit_fact(
    command: Command, state: RunState, rng: StacksRNG, seq: int, actor_hero_id: str | None, room_id: str | None, args: dict
) -> tuple[Event, ...]:
    fact_id = args["fact_id"]
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.FACT_EMITTED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=actor_hero_id,
            room_id=room_id,
            payload={"fact_id": fact_id},
        ),
    )


def _apply_condition(
    command: Command, state: RunState, rng: StacksRNG, seq: int, actor_hero_id: str | None, room_id: str | None, args: dict
) -> tuple[Event, ...]:
    """§16.4-16.5 persistent statuses/injuries (distinct from combat's own
    in-encounter StatusInstance dict, which is ephemeral to a single fight).
    A no-op if the hero already carries this condition -- applying a
    duplicate never emits a second event (§16.4: "a hero should rarely track
    more than two")."""

    if actor_hero_id is None or actor_hero_id not in state.heroes:
        return ()
    condition_id = args["condition_id"]
    if condition_id in state.heroes[actor_hero_id].active_condition_ids:
        return ()
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.CONDITION_APPLIED,
            visibility=Visibility.PARTY,
            actor_hero_id=actor_hero_id,
            room_id=room_id,
            payload={"condition_id": condition_id},
        ),
    )


def _remove_condition(
    command: Command, state: RunState, rng: StacksRNG, seq: int, actor_hero_id: str | None, room_id: str | None, args: dict
) -> tuple[Event, ...]:
    if actor_hero_id is None or actor_hero_id not in state.heroes:
        return ()
    condition_id = args["condition_id"]
    if condition_id not in state.heroes[actor_hero_id].active_condition_ids:
        return ()
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.CONDITION_REMOVED,
            visibility=Visibility.PARTY,
            actor_hero_id=actor_hero_id,
            room_id=room_id,
            payload={"condition_id": condition_id},
        ),
    )


_OP_HANDLERS: dict[str, Callable[..., tuple[Event, ...]]] = {
    "reveal_room": _reveal_room,
    "spend_energy": _spend_energy,
    "grant_check": _grant_check,
    "emit_fact": _emit_fact,
    "apply_condition": _apply_condition,
    "remove_condition": _remove_condition,
}

LIVE_OPS = frozenset(_OP_HANDLERS)


def dispatch(
    effects: Sequence[dict[str, Any]],
    *,
    command: Command,
    state: RunState,
    rng: StacksRNG,
    seq: int,
    actor_hero_id: str | None,
    room_id: str | None,
) -> tuple[Event, ...]:
    """Compile a sequence of `{"op": str, "args": dict}` effect dicts into
    real domain events. `state` is the pre-event state (handle() contract:
    read-only); events are applied by the caller via the normal reduce()
    loop, same as every other command handler's output."""

    events: list[Event] = []
    for effect in effects:
        handler = _OP_HANDLERS.get(effect.get("op"))
        if handler is None:
            continue
        events.extend(
            handler(command, state, rng, seq + len(events), actor_hero_id, room_id, dict(effect.get("args", {})))
        )
    return tuple(events)


def build_active_effect_event(
    command: Command,
    state: RunState,
    seq: int,
    *,
    actor_hero_id: str,
    room_id: str | None,
    source_id: str,
    label: str,
    duration: str,
) -> Event:
    """Wave-6 addition (board task #21, playtest A5): a temporary modifier's
    visible lifetime for the active-effects tray. Deliberately NOT a content
    effect op (never routed through `dispatch()`/`_OP_HANDLERS` -- content
    cannot author `apply_active_effect` directly this wave, keeping
    `LIVE_OPS` exactly the 6-op set posted to the collab room 2026-07-20).
    Callers (systems/heroes_wire.py's use_ability, systems/exploration.py's
    on_room_enter dispatch, systems/combat.py's on_encounter_start dispatch)
    build this alongside whatever real effect ops they already dispatch.
    `duration` is one of domain.state.ACTIVE_EFFECT_DURATIONS. Scoped to the
    acting hero's currently active encounter (if any) so until_end_of_encounter
    expiry (systems/combat.py) only ever clears effects tied to THAT encounter."""

    encounter_id = None
    if room_id is not None and state.map is not None:
        room = state.map.rooms.get(room_id)
        if room is not None and room.encounter is not None and room.encounter.status == "active":
            encounter_id = room.encounter.encounter_id
    return Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ACTIVE_EFFECT_APPLIED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=actor_hero_id,
        room_id=room_id,
        payload={
            "effect_id": f"{command.command_id}:{seq}",
            "source_id": source_id,
            "label": label,
            "duration": duration,
            "applied_world_round": state.world_round,
            "encounter_id": encounter_id,
        },
    )


def apply_active_effect_applied(state: RunState, event: Event) -> RunState:
    hero = state.heroes.get(event.actor_hero_id)
    if hero is None:
        return state
    hero.active_effects = hero.active_effects + (ActiveEffectState.from_dict(event.payload),)
    return state


def apply_room_revealed_by_effect(state: RunState, event: Event) -> RunState:
    target_room_id = event.payload["room_id"]
    if state.map is not None and target_room_id in state.map.rooms:
        state.map.rooms[target_room_id].discovered = True
    return state


def apply_effect_energy_spent(state: RunState, event: Event) -> RunState:
    hero = state.heroes.get(event.actor_hero_id)
    if hero is not None:
        hero.energy = max(0, hero.energy - event.payload["amount"])
    return state


def apply_fact_emitted(state: RunState, event: Event) -> RunState:
    fact_id = event.payload["fact_id"]
    if fact_id not in state.facts:
        state.facts = state.facts + (fact_id,)
    return state


def apply_condition_applied(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    condition_id = event.payload["condition_id"]
    if condition_id not in hero.active_condition_ids:
        hero.active_condition_ids = hero.active_condition_ids + (condition_id,)
    return state


def apply_condition_removed(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    condition_id = event.payload["condition_id"]
    if condition_id in hero.active_condition_ids:
        hero.active_condition_ids = tuple(c for c in hero.active_condition_ids if c != condition_id)
    return state


EVENT_APPLIERS = {
    EventType.ROOM_REVEALED_BY_EFFECT: apply_room_revealed_by_effect,
    EventType.EFFECT_ENERGY_SPENT: apply_effect_energy_spent,
    EventType.FACT_EMITTED: apply_fact_emitted,
    EventType.CONDITION_APPLIED: apply_condition_applied,
    EventType.CONDITION_REMOVED: apply_condition_removed,
    EventType.ACTIVE_EFFECT_APPLIED: apply_active_effect_applied,
}
