"""Event envelope per docs/INFINITE_STACKS_CONTRACTS.md §3.

Events are the only source of state mutation. They store the *results* of any
randomness (rolled die faces, check totals) so replay never re-touches the RNG
stream for an event that already happened.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Visibility(str, Enum):
    PUBLIC = "public"
    PARTY = "party"
    PRIVATE = "private"   # payload["viewer_hero_id"] names the authorized viewer


class EventType(str, Enum):
    MAP_GENERATED = "map_generated"
    HERO_JOINED = "hero_joined"
    HERO_MOVED = "hero_moved"
    ROOM_BREACHED = "room_breached"       # d8 roll + subtype selection + entry
    CONNECTOR_OBSERVED = "connector_observed"
    ROOM_INSPECTED = "room_inspected"
    ENERGY_SPENT = "energy_spent"
    TURN_SUBMITTED = "turn_submitted"
    WORLD_ROUND_ADVANCED = "world_round_advanced"
    CHECK_RESOLVED = "check_resolved"


@dataclass(frozen=True)
class Event:
    event_id: str
    run_id: str
    world_round: int
    caused_by: str
    type: EventType
    visibility: Visibility = Visibility.PUBLIC
    actor_hero_id: str | None = None
    room_id: str | None = None
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "world_round": self.world_round,
            "caused_by": self.caused_by,
            "type": self.type.value,
            "visibility": self.visibility.value,
            "actor_hero_id": self.actor_hero_id,
            "room_id": self.room_id,
            "payload": self.payload,
        }


def make_event_id(world_round: int, seq: int) -> str:
    return f"evt_{world_round}_{seq:04d}"
