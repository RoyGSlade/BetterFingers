"""The Lost Meaning: Infinite Stacks -- viewer-filtered projections.

Read-side functions over ``RunState`` (docs/INFINITE_STACKS_CONTRACTS.md S4):
``project`` builds the authorized view for a given viewer, ``events_since``
replays the same visibility filter over the event log for reconnect, and
``legal_actions`` is the summary attached to every ``CommandError`` (S2 --
"never a bare error") and used for the pre-command affordance check on the
client. ``event_wire`` is the one JSON shape both the REST command response
and the WebSocket event broadcast use, so the two transports can never drift.

Pure functions only: no locks, no sockets, no mutation of the ``RunState``
passed in. Split out of stacks_api.py (board task #3 follow-up) to keep each
module under the infinite_stacks.md S22.2 soft 500-line cap.
"""

from __future__ import annotations

from typing import Any

from backend.lan_playground.stacks_protocol import Event, RunState


def legal_actions(state: RunState, hero_id: str | None) -> dict[str, Any]:
    base: dict[str, Any] = {"revision": state.revision, "world_round": state.world_round}
    if hero_id is None or hero_id not in state.heroes:
        base["hero_id"] = hero_id
        return base
    hero = state.heroes[hero_id]
    room = state.rooms[hero.room_id]
    base.update(
        hero_id=hero_id,
        room_id=hero.room_id,
        energy=hero.energy,
        can_pass=hero.conscious,
        can_inspect=hero.conscious and hero.energy >= 1,
        can_move_to=[
            c.target_room_id
            for c in room.connectors.values()
            if c.state == "open" and c.target_room_id and hero.energy >= 1
        ]
        if hero.conscious
        else [],
        can_breach_directions=[
            d for d, c in room.connectors.items() if c.state == "undiscovered" and hero.energy >= 3
        ]
        if hero.conscious
        else [],
        can_observe_directions=[d for d, c in room.connectors.items() if c.state == "open" and hero.energy >= 1]
        if hero.conscious
        else [],
    )
    return base


def events_since(state: RunState, viewer: str | None, since_revision: int) -> list[Event]:
    # revision N is produced by event_log[N-1] (apply() bumps revision by
    # exactly one command at a time in this stub); events are filtered
    # per-viewer the same way live pushes are.
    missed = state.event_log[since_revision:]
    return [e for e in missed if e.visible_to_viewer(viewer)]


def project(state: RunState, viewer: str | None) -> dict[str, Any]:
    heroes_view: dict[str, Any] = {}
    for hero_id, hero in state.heroes.items():
        entry = {
            "hero_id": hero.hero_id,
            "name": hero.name,
            "room_id": hero.room_id,
            "energy": hero.energy,
            "max_energy": hero.max_energy,
            "hp": hero.hp,
            "max_hp": hero.max_hp,
            "conscious": hero.conscious,
            "alive": hero.alive,
            "ready": hero.ready,
            "connected": hero.connected,
        }
        if viewer is not None and viewer == hero_id:
            entry["private_clue"] = hero.private_clue
        heroes_view[hero_id] = entry

    rooms_view: dict[str, Any] = {}
    for room_id, room in state.rooms.items():
        if not room.discovered:
            continue
        rooms_view[room_id] = {
            "room_id": room.room_id,
            "x": room.x,
            "y": room.y,
            "family": room.family,
            "subtype": room.subtype,
            "discovered": room.discovered,
            "entered": room.entered,
            "required": room.required,
            "connectors": {
                d: {"state": c.state, "target_room_id": c.target_room_id} for d, c in room.connectors.items()
            },
            # room.secrets is intentionally never included here.
        }

    return {
        "run_id": state.run_id,
        "revision": state.revision,
        "world_round": state.world_round,
        "required_rooms": state.required_rooms,
        "maximum_rooms": state.maximum_rooms,
        "heroes": heroes_view,
        "rooms": rooms_view,
        "viewer": viewer,
    }


def event_wire(event: Event) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "run_id": event.run_id,
        "world_round": event.world_round,
        "caused_by": event.caused_by,
        "actor_hero_id": event.actor_hero_id,
        "room_id": event.room_id,
        "type": event.type,
        "visibility": event.visibility,
        "payload": event.payload,
    }
