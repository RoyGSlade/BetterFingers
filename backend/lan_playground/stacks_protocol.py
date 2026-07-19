"""The Lost Meaning: Infinite Stacks -- command/event envelopes and state shapes.

Pure data definitions for docs/INFINITE_STACKS_CONTRACTS.md SS1-3, SS6: the
Command/Event envelopes, the wave-1 RunState/HeroState/RoomState aggregates,
and the error types those commands can raise. Nothing here touches FastAPI,
threading, or the network -- this module only defines shapes, so it is safe
for stacks_projections.py, stacks_engine.py, and any future engine-adapter
rewrite to import without pulling in transport concerns.

Extracted from stacks_api.py (board task #3 follow-up) to keep each module
under the infinite_stacks.md S22.2 soft 500-line cap.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Literal

DISPLAY_NAME_MAX_CHARS = 40
DIRECTIONS: tuple[str, ...] = ("north", "east", "south", "west")
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
DELTA = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}

# d8 -> room family, infinite_stacks.md S7.2 / contract doc S8.
ROOM_FAMILY_BY_D8: dict[int, str] = {
    1: "mystery_chamber",
    2: "passage",
    3: "study",
    4: "wild_place",
    5: "conflict",
    6: "shop",
    7: "social_encounter",
    8: "anomaly",
}

# Families that stub a private, viewer-scoped clue on inspect/breach so the
# projection-privacy mechanism has something concrete to prove and test against
# ahead of the real content pack's clue system landing.
FAMILIES_WITH_PRIVATE_CLUE = frozenset({"mystery_chamber", "study"})


# --------------------------------------------------------------------------
# Wave-1 state shapes (docs/INFINITE_STACKS_CONTRACTS.md SS2-6)
# --------------------------------------------------------------------------


@dataclass
class Connector:
    state: Literal["open", "locked", "undiscovered", "none"]
    target_room_id: str | None = None


@dataclass
class Room:
    room_id: str
    x: int
    y: int
    connectors: dict[str, Connector]
    family: str | None
    subtype: str | None
    discovered: bool
    entered: bool
    required: bool
    # RoomState.secrets (contract S4/S6): per-hero private clue text, stripped
    # from every projection unless viewer is the authorized hero.
    secrets: dict[str, str] = field(default_factory=dict)


@dataclass
class Hero:
    hero_id: str
    name: str
    room_id: str
    energy: int
    max_energy: int
    hp: int
    max_hp: int
    conscious: bool
    alive: bool
    ready: bool = False
    connected: bool = False
    # Own-viewer-only field (contract S4: "no player view receives another
    # player's ... private clue"). Wave-1 HeroState in the contract has no
    # hand/draft fields yet (combat/cards are out of scope this wave); this is
    # the one private field the stub actually populates, via inspect/breach.
    private_clue: str | None = None


@dataclass(frozen=True)
class Command:
    command_id: str
    idempotency_key: str
    run_id: str
    hero_id: str | None
    encounter_id: str | None
    expected_revision: int
    type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class Event:
    event_id: str
    run_id: str
    world_round: int
    caused_by: str
    actor_hero_id: str | None
    room_id: str | None
    type: str
    visibility: Literal["public", "private", "party"]
    visible_to: str | None  # hero_id, only set when visibility == "private"
    payload: dict[str, Any]

    def visible_to_viewer(self, viewer: str | None) -> bool:
        if self.visibility == "public":
            return True
        if self.visibility == "party":
            return viewer is not None
        return viewer is not None and viewer == self.visible_to


@dataclass
class _IdemRecord:
    events: tuple[Event, ...]
    revision: int


@dataclass
class RunState:
    run_id: str
    seed: int
    revision: int
    world_round: int
    chapter_floor_index: int
    required_rooms: int
    maximum_rooms: int
    heroes: dict[str, Hero]
    rooms: dict[str, Room]
    pending_turns: dict[str, bool]
    event_log: list[Event]
    _applied: dict[tuple[str, str], _IdemRecord]
    _rng: random.Random
    _next_seq: int = 0

    @classmethod
    def initial(cls, run_id: str, seed: int, chapter_floor_index: int = 0) -> "RunState":
        entrance = Room(
            room_id="room_0_0",
            x=0,
            y=0,
            connectors={d: Connector(state="undiscovered") for d in DIRECTIONS},
            family="entrance",
            subtype=None,
            discovered=True,
            entered=True,
            required=False,
        )
        required_rooms = min(6 + chapter_floor_index, 12)
        return cls(
            run_id=run_id,
            seed=seed,
            revision=0,
            world_round=1,
            chapter_floor_index=chapter_floor_index,
            required_rooms=required_rooms,
            maximum_rooms=required_rooms + 3,
            heroes={},
            rooms={"room_0_0": entrance},
            pending_turns={},
            event_log=[],
            _applied={},
            _rng=random.Random(seed),
        )

    def next_event_id(self) -> str:
        self._next_seq += 1
        return f"evt_{self.world_round}_{self._next_seq:04d}"


# --------------------------------------------------------------------------
# Command errors (contract S2): stale_revision/illegal_action always carry a
# legal-action summary, never a bare error.
# --------------------------------------------------------------------------


class CommandError(Exception):
    def __init__(self, code: str, legal_actions: dict[str, Any] | None = None, message: str = ""):
        super().__init__(code)
        self.code = code
        self.legal_actions = legal_actions
        self.message = message


class RunNotFoundError(Exception):
    pass


@dataclass
class ApplyResult:
    events: tuple[Event, ...]
    revision: int
    replayed: bool
