"""Join, move, breach, observe, inspect (infinite_stacks.md §7, §8).

Each hero has an independent room position; splitting the party is legal
without a vote (§7.4) -- nothing here requires heroes to share a room.
Breaching ends movement for that hero's round (movement_locked), though
remaining Energy may still be spent on non-movement actions inside the room.
"""
from __future__ import annotations

from ..domain.commands import Command, CommandError, ErrorCode
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.rng import StacksRNG
from ..domain.state import DELTA, ConnectorState, Direction, MapState, RunState, room_id_for
from . import combat, heroes_wire, map_generation, puzzles, room_generation, turns


def _hero(state: RunState, hero_id: str | None) -> "HeroState":
    if hero_id is None or hero_id not in state.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown hero {hero_id}")
    return state.heroes[hero_id]


def _direction(payload: dict) -> Direction:
    raw = payload.get("direction")
    try:
        return Direction(raw)
    except ValueError:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"invalid direction {raw!r}")


def _target_room_id(state: RunState, hero_room_id: str, direction: Direction) -> str:
    room = state.map.rooms[hero_room_id]
    dx, dy = DELTA[direction]
    return room_id_for(room.x + dx, room.y + dy)


def legal_action_summary(state: RunState, hero_id: str) -> list[str]:
    hero = state.heroes.get(hero_id)
    if hero is None or hero.submitted_turn or state.map is None:
        return ["pass"] if hero and not hero.submitted_turn else []
    actions = ["pass"]
    room = state.map.rooms[hero.room_id]
    for direction, connector in room.connectors.items():
        if connector == ConnectorState.OPEN and not hero.movement_locked and hero.energy >= turns.ENERGY_COSTS["move"]:
            actions.append(f"move:{direction.value}")
        if connector == ConnectorState.DOOR and not hero.movement_locked and hero.energy >= turns.ENERGY_COSTS["breach"]:
            actions.append(f"breach:{direction.value}")
        if connector != ConnectorState.NONE and hero.energy >= turns.ENERGY_COSTS["observe"]:
            actions.append(f"observe:{direction.value}")
    if hero.energy >= turns.ENERGY_COSTS["inspect"]:
        actions.append("inspect")
    actions.extend(puzzles.legal_action_names(state, hero_id))
    actions.extend(heroes_wire.legal_action_names(state, hero_id))
    return actions


# ---------------------------------------------------------------- join_run

def validate_join_run(state: RunState, hero_id: str) -> None:
    if hero_id in state.heroes:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} already joined")


def handle_join_run(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    validate_join_run(state, hero_id)
    events: list[Event] = []

    if state.map is None:
        map_state = map_generation.generate_topology(rng, state.chapter_floor_index)
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.MAP_GENERATED,
                visibility=Visibility.PUBLIC,
                payload=map_state.to_dict(),
            )
        )
        seq += 1
        entrance_room_id = map_state.entrance_room_id
    else:
        entrance_room_id = state.map.entrance_room_id

    events.append(
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.HERO_JOINED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=hero_id,
            room_id=entrance_room_id,
            payload={"hero_id": hero_id, "room_id": entrance_room_id},
        )
    )
    return tuple(events)


def apply_map_generated(state: RunState, event: Event) -> RunState:
    state.map = MapState.from_dict(event.payload)
    return state


def apply_hero_joined(state: RunState, event: Event) -> RunState:
    from ..domain.state import HeroState

    state.heroes[event.payload["hero_id"]] = HeroState(
        hero_id=event.payload["hero_id"], room_id=event.payload["room_id"]
    )
    return state


# ---------------------------------------------------------------- move

def validate_move(state: RunState, hero_id: str, payload: dict) -> Direction:
    hero = _hero(state, hero_id)
    direction = _direction(payload)
    if hero.movement_locked:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "movement is locked for this round after breaching")
    room = state.map.rooms[hero.room_id]
    connector = room.connectors.get(direction, ConnectorState.NONE)
    if connector != ConnectorState.OPEN:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"no open connector {direction.value} from {hero.room_id}")
    turns.require_energy(state, hero_id, "move")
    return direction


def handle_move(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    direction = validate_move(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    target_room_id = _target_room_id(state, hero.room_id, direction)
    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["move"], "action": "move"},
    )
    move_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.HERO_MOVED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=target_room_id,
        payload={"from_room_id": hero.room_id, "to_room_id": target_room_id},
    )
    events: tuple[Event, ...] = (energy_event, move_event)

    target_room = state.map.rooms[target_room_id]
    encounter = target_room.encounter
    if (
        encounter is not None
        and encounter.status == "active"
        and hero_id not in encounter.heroes
        and hero_id not in encounter.pending_joiner_hero_ids
    ):
        # §7.4/§14.1: a hero who reaches an active Conflict room while it is
        # underway queues as a joiner rather than fighting immediately --
        # they integrate at the start of the next initiative cycle.
        events += (
            Event(
                event_id=make_event_id(state.world_round, seq + 2),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.JOINED_CONFLICT_ROOM,
                visibility=Visibility.PARTY,
                actor_hero_id=hero_id,
                room_id=target_room_id,
                payload={"hero_id": hero_id, "room_id": target_room_id},
            ),
        )
    return events


def apply_hero_moved(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.room_id = event.payload["to_room_id"]
    return state


# ---------------------------------------------------------------- breach

def validate_breach(state: RunState, hero_id: str, payload: dict) -> Direction:
    hero = _hero(state, hero_id)
    direction = _direction(payload)
    if hero.movement_locked:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "movement is locked for this round after breaching")
    room = state.map.rooms[hero.room_id]
    connector = room.connectors.get(direction, ConnectorState.NONE)
    if connector != ConnectorState.DOOR:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"no unbreached door {direction.value} from {hero.room_id}")
    turns.require_energy(state, hero_id, "breach")
    return direction


def handle_breach(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    direction = validate_breach(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    target_room_id = _target_room_id(state, hero.room_id, direction)

    face, family = room_generation.roll_family(rng)
    used_for_family = state.map.used_subtypes.get(family, [])
    subtype = room_generation.select_subtype(rng, family, used_for_family)

    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["breach"], "action": "breach"},
    )
    breach_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ROOM_BREACHED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=target_room_id,
        payload={
            "from_room_id": hero.room_id,
            "to_room_id": target_room_id,
            "d8_face": face,
            "family": family,
            "subtype": subtype,
        },
    )
    events: tuple[Event, ...] = (energy_event, breach_event)
    if family == "mystery_chamber":
        events += puzzles.build_instantiate_events(command, state, rng, target_room_id, hero_id, seq + 2)
    elif family == "conflict":
        events += combat.build_start_encounter_events(command, state, rng, target_room_id, hero_id, seq + 2)
    # §11.3 once_per_room signature charges refresh at this room boundary.
    events += heroes_wire.build_room_boundary_refresh_events(
        state, hero_id, target_room_id, seq + len(events), command.command_id
    )
    return events


def apply_room_breached(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    target_room = state.map.rooms[event.payload["to_room_id"]]
    source_room = state.map.rooms[event.payload["from_room_id"]]

    target_room.family = event.payload["family"]
    target_room.subtype = event.payload["subtype"]
    target_room.discovered = True
    target_room.entered = True

    for direction, connector in list(source_room.connectors.items()):
        dx, dy = DELTA[direction]
        if room_id_for(source_room.x + dx, source_room.y + dy) == target_room.room_id:
            source_room.connectors[direction] = ConnectorState.OPEN
            from ..domain.state import OPPOSITE

            target_room.connectors[OPPOSITE[direction]] = ConnectorState.OPEN
            break

    used = state.map.used_subtypes.setdefault(target_room.family, [])
    if event.payload["subtype"] not in used:
        used.append(event.payload["subtype"])

    hero.room_id = target_room.room_id
    hero.movement_locked = True
    return state


# ---------------------------------------------------------------- observe

def validate_observe(state: RunState, hero_id: str, payload: dict) -> Direction:
    hero = _hero(state, hero_id)
    direction = _direction(payload)
    room = state.map.rooms[hero.room_id]
    connector = room.connectors.get(direction, ConnectorState.NONE)
    if connector == ConnectorState.NONE:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"no connector {direction.value} from {hero.room_id}")
    turns.require_energy(state, hero_id, "observe")
    return direction


def handle_observe(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    direction = validate_observe(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    target_room_id = _target_room_id(state, hero.room_id, direction)
    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["observe"], "action": "observe"},
    )
    observe_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.CONNECTOR_OBSERVED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"direction": direction.value, "target_room_id": target_room_id},
    )
    return (energy_event, observe_event)


def apply_connector_observed(state: RunState, event: Event) -> RunState:
    target_room_id = event.payload["target_room_id"]
    if target_room_id in state.map.rooms:
        state.map.rooms[target_room_id].discovered = True
    return state


# ---------------------------------------------------------------- inspect

def validate_inspect(state: RunState, hero_id: str, payload: dict) -> None:
    hero = _hero(state, hero_id)
    room = state.map.rooms[hero.room_id]
    if not room.entered:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "cannot inspect an unentered room")
    turns.require_energy(state, hero_id, "inspect")


def handle_inspect(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    validate_inspect(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["inspect"], "action": "inspect"},
    )
    inspect_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ROOM_INSPECTED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"target": command.payload.get("target", "room")},
    )
    return (energy_event, inspect_event)


def apply_room_inspected(state: RunState, event: Event) -> RunState:
    return state


EVENT_APPLIERS = {
    EventType.MAP_GENERATED: apply_map_generated,
    EventType.HERO_JOINED: apply_hero_joined,
    EventType.HERO_MOVED: apply_hero_moved,
    EventType.ROOM_BREACHED: apply_room_breached,
    EventType.CONNECTOR_OBSERVED: apply_connector_observed,
    EventType.ROOM_INSPECTED: apply_room_inspected,
}
