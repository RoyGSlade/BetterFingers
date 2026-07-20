"""Core state aggregates for the golden-floor slice (infinite_stacks.md §22.4).

All state is plain, JSON-serializable dataclasses so RunState.state_hash() can
hash a canonical representation for replay verification. Mutation always goes
through reducer.reduce(state, event) -> new_state; nothing here mutates a
RunState in place.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum

from ..heroes.backgrounds import SignatureCharge
from ..heroes.creation import HeroSheet
from ..heroes.deck import DeckState
from ..heroes.inventory import InventoryState


class Direction(str, Enum):
    NORTH = "north"
    EAST = "east"
    SOUTH = "south"
    WEST = "west"


OPPOSITE = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
}

DELTA = {
    Direction.NORTH: (0, 1),
    Direction.SOUTH: (0, -1),
    Direction.EAST: (1, 0),
    Direction.WEST: (-1, 0),
}


class ConnectorState(str, Enum):
    NONE = "none"               # no door in this direction
    DOOR = "door"                # door exists, target room not yet breached
    OPEN = "open"                # door exists, target room breached/entered


def room_id_for(x: int, y: int) -> str:
    return f"room_{x}_{y}"


@dataclass
class PuzzleObjectView:
    """One of the §10.2 four inspectable objects. Public shape only -- which
    clues a viewer may see through it is a runtime/per-hero decision made by
    systems/puzzles.py, not part of this static view."""

    id: str
    role: str  # PuzzleObjectRole value: anchor|key|contradiction|red_herring
    fallback: str
    accessible: str

    def to_dict(self) -> dict:
        return {"id": self.id, "role": self.role, "fallback": self.fallback, "accessible": self.accessible}

    @staticmethod
    def from_dict(d: dict) -> "PuzzleObjectView":
        return PuzzleObjectView(id=d["id"], role=d["role"], fallback=d["fallback"], accessible=d["accessible"])


@dataclass
class PuzzleRoomState:
    """Runtime state for a real Mystery Chamber puzzle instance (§10.1),
    reconstructed deterministically from (seed, difficulty) by
    systems/puzzles.py -- never re-rolled. `solution`/`accepted_solutions`
    live here because they are authoritative replay state, but they are never
    read by anything outside systems/puzzles.py's `submit_solution` handler
    and must never be copied into a wire projection (stacks_engine.py /
    stacks_projections.py)."""

    instance_id: str
    template_id: str
    seed: int
    difficulty: int
    objects: tuple[PuzzleObjectView, ...] = ()
    # The orderable items submit_solution's {solution: [item_id, ...]} refers to,
    # in a fixed lexicographic-by-item_id order that is provably independent of
    # the shuffled `solution` order below -- PUBLIC and safe to project as-is
    # (director-directed fix, 2026-07-19: without item ids on the wire no
    # client can ever construct a valid submit_solution payload).
    items: tuple[dict, ...] = ()  # [{"item_id": str, "fallback": str, "accessible": str}, ...]
    object_clue_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)
    clue_text: dict[str, tuple[str, str]] = field(default_factory=dict)  # clue_id -> (fallback, accessible)
    unclaimed_key_clue_ids: list[str] = field(default_factory=list)
    private_clue_assignments: dict[str, tuple[str, ...]] = field(default_factory=dict)  # hero_id -> clue_ids
    solution: tuple[str, ...] = ()
    accepted_solutions: tuple[tuple[str, ...], ...] = ()
    hint_steps: tuple[tuple[str, str], ...] = ()  # (fallback, accessible) per step
    attempt_limit: int | None = None
    failure_effects: tuple[dict, ...] = ()  # compiled {"op","args"} dicts, contract §5 IR
    success_effects: tuple[dict, ...] = ()
    attempts_used: int = 0
    hints_used: int = 0
    solved: bool = False
    forced: bool = False

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "template_id": self.template_id,
            "seed": self.seed,
            "difficulty": self.difficulty,
            "objects": [o.to_dict() for o in self.objects],
            "items": [dict(i) for i in self.items],
            "object_clue_ids": {k: list(v) for k, v in sorted(self.object_clue_ids.items())},
            "clue_text": {k: list(v) for k, v in sorted(self.clue_text.items())},
            "unclaimed_key_clue_ids": list(self.unclaimed_key_clue_ids),
            "private_clue_assignments": {k: list(v) for k, v in sorted(self.private_clue_assignments.items())},
            "solution": list(self.solution),
            "accepted_solutions": [list(s) for s in self.accepted_solutions],
            "hint_steps": [list(h) for h in self.hint_steps],
            "attempt_limit": self.attempt_limit,
            "failure_effects": [dict(e) for e in self.failure_effects],
            "success_effects": [dict(e) for e in self.success_effects],
            "attempts_used": self.attempts_used,
            "hints_used": self.hints_used,
            "solved": self.solved,
            "forced": self.forced,
        }

    @staticmethod
    def from_dict(d: dict) -> "PuzzleRoomState":
        return PuzzleRoomState(
            instance_id=d["instance_id"],
            template_id=d["template_id"],
            seed=d["seed"],
            difficulty=d["difficulty"],
            objects=tuple(PuzzleObjectView.from_dict(o) for o in d["objects"]),
            items=tuple(dict(i) for i in d.get("items", [])),
            object_clue_ids={k: tuple(v) for k, v in d["object_clue_ids"].items()},
            clue_text={k: tuple(v) for k, v in d["clue_text"].items()},
            unclaimed_key_clue_ids=list(d["unclaimed_key_clue_ids"]),
            private_clue_assignments={k: tuple(v) for k, v in d["private_clue_assignments"].items()},
            solution=tuple(d["solution"]),
            accepted_solutions=tuple(tuple(s) for s in d["accepted_solutions"]),
            hint_steps=tuple(tuple(h) for h in d["hint_steps"]),
            attempt_limit=d["attempt_limit"],
            failure_effects=tuple(d["failure_effects"]),
            success_effects=tuple(d["success_effects"]),
            attempts_used=d["attempts_used"],
            hints_used=d["hints_used"],
            solved=d["solved"],
            forced=d["forced"],
        )


@dataclass
class ConflictEncounterState:
    """Runtime state for a Conflict-room encounter (§14-16), wrapping the pure
    `backend.lan_playground.combat` package's combatant/initiative/threat data
    as plain JSON-safe dicts -- this dataclass never imports combat/** (the
    domain layer stays decoupled from that package's types); systems/combat.py
    is the sole place that (de)serializes these dicts into real combat.models
    objects to call the pure functions, then writes the results back here.

    `heroes`/`enemies` values are plain dicts with the HeroCombatant/
    EnemyCombatant fields systems/combat.py needs (hp, life_state, position,
    statuses, etc). `order` is a list of InitiativeEntry-shaped dicts.
    `sequencer_seq` preserves the combat package's own monotonic event-id
    counter across commands/replay so `cevt_<round>_<seq>` ids stay unique.
    """

    encounter_id: str
    room_id: str
    status: str = "active"  # active | victory | party_wiped
    combat_round: int = 1
    heroes: dict[str, dict] = field(default_factory=dict)
    enemies: dict[str, dict] = field(default_factory=dict)
    order: list[dict] = field(default_factory=list)
    current_actor_id: str | None = None   # whose turn it is right now; None = round settled, awaiting round-advance
    reinforcement_waves: list[dict] = field(default_factory=list)
    turn_budget: dict = field(default_factory=dict)
    threat_budget: dict = field(default_factory=dict)
    pending_joiner_hero_ids: list[str] = field(default_factory=list)
    sequencer_seq: int = 0

    def to_dict(self) -> dict:
        return {
            "encounter_id": self.encounter_id,
            "room_id": self.room_id,
            "status": self.status,
            "combat_round": self.combat_round,
            "heroes": {k: dict(v) for k, v in sorted(self.heroes.items())},
            "enemies": {k: dict(v) for k, v in sorted(self.enemies.items())},
            "order": [dict(e) for e in self.order],
            "current_actor_id": self.current_actor_id,
            "reinforcement_waves": [dict(w) for w in self.reinforcement_waves],
            "turn_budget": dict(self.turn_budget),
            "threat_budget": dict(self.threat_budget),
            "pending_joiner_hero_ids": list(self.pending_joiner_hero_ids),
            "sequencer_seq": self.sequencer_seq,
        }

    @staticmethod
    def from_dict(d: dict) -> "ConflictEncounterState":
        return ConflictEncounterState(
            encounter_id=d["encounter_id"],
            room_id=d["room_id"],
            status=d["status"],
            combat_round=d["combat_round"],
            heroes={k: dict(v) for k, v in d["heroes"].items()},
            enemies={k: dict(v) for k, v in d["enemies"].items()},
            order=[dict(e) for e in d["order"]],
            current_actor_id=d["current_actor_id"],
            reinforcement_waves=[dict(w) for w in d["reinforcement_waves"]],
            turn_budget=dict(d["turn_budget"]),
            threat_budget=dict(d["threat_budget"]),
            pending_joiner_hero_ids=list(d["pending_joiner_hero_ids"]),
            sequencer_seq=d["sequencer_seq"],
        )


@dataclass
class RoomState:
    room_id: str
    x: int
    y: int
    connectors: dict[Direction, ConnectorState] = field(default_factory=dict)
    family: str | None = None
    subtype: str | None = None
    discovered: bool = False   # observed to exist, content not necessarily rolled
    entered: bool = False      # breached: family/subtype rolled, room instantiated
    required: bool = False
    is_entrance: bool = False
    is_exit: bool = False
    puzzle: PuzzleRoomState | None = None
    encounter: ConflictEncounterState | None = None
    body_item_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)  # §13.6: dead hero's items stay with the body
    # Wave-4 herowire additions (board task #13, §13.6): items lying in the
    # room available for pickup (item_instance_id -> item_id) and the
    # single-owner pickup contest ledger heroes.inventory.attempt_pickup
    # needs (item_instance_id -> claiming hero_id).
    ground_items: dict[str, str] = field(default_factory=dict)
    item_claims: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "x": self.x,
            "y": self.y,
            "connectors": {d.value: s.value for d, s in sorted(self.connectors.items(), key=lambda kv: kv[0].value)},
            "family": self.family,
            "subtype": self.subtype,
            "discovered": self.discovered,
            "entered": self.entered,
            "required": self.required,
            "is_entrance": self.is_entrance,
            "is_exit": self.is_exit,
            "puzzle": self.puzzle.to_dict() if self.puzzle is not None else None,
            "encounter": self.encounter.to_dict() if self.encounter is not None else None,
            "body_item_ids": {k: list(v) for k, v in sorted(self.body_item_ids.items())},
            "ground_items": dict(sorted(self.ground_items.items())),
            "item_claims": dict(sorted(self.item_claims.items())),
        }

    @staticmethod
    def from_dict(d: dict) -> "RoomState":
        return RoomState(
            room_id=d["room_id"],
            x=d["x"],
            y=d["y"],
            connectors={Direction(k): ConnectorState(v) for k, v in d["connectors"].items()},
            family=d["family"],
            subtype=d["subtype"],
            discovered=d["discovered"],
            entered=d["entered"],
            required=d["required"],
            is_entrance=d["is_entrance"],
            is_exit=d["is_exit"],
            puzzle=PuzzleRoomState.from_dict(d["puzzle"]) if d.get("puzzle") else None,
            encounter=ConflictEncounterState.from_dict(d["encounter"]) if d.get("encounter") else None,
            body_item_ids={k: tuple(v) for k, v in d.get("body_item_ids", {}).items()},
            ground_items=dict(d.get("ground_items", {})),
            item_claims=dict(d.get("item_claims", {})),
        )


@dataclass
class MapState:
    required_rooms: int
    maximum_rooms: int
    entrance_room_id: str
    exit_room_id: str
    rooms: dict[str, RoomState] = field(default_factory=dict)
    used_subtypes: dict[str, list[str]] = field(default_factory=dict)

    def resolved_room_count(self) -> int:
        return sum(1 for r in self.rooms.values() if r.entered and not r.is_entrance)

    def to_dict(self) -> dict:
        return {
            "required_rooms": self.required_rooms,
            "maximum_rooms": self.maximum_rooms,
            "entrance_room_id": self.entrance_room_id,
            "exit_room_id": self.exit_room_id,
            "rooms": {rid: r.to_dict() for rid, r in sorted(self.rooms.items())},
            "used_subtypes": {k: list(v) for k, v in sorted(self.used_subtypes.items())},
        }

    @staticmethod
    def from_dict(d: dict) -> "MapState":
        return MapState(
            required_rooms=d["required_rooms"],
            maximum_rooms=d["maximum_rooms"],
            entrance_room_id=d["entrance_room_id"],
            exit_room_id=d["exit_room_id"],
            rooms={rid: RoomState.from_dict(rd) for rid, rd in d["rooms"].items()},
            used_subtypes={k: list(v) for k, v in d.get("used_subtypes", {}).items()},
        )


# Mirrors backend.lan_playground.combat.models.LifeState's string values exactly
# (alive|downed|stable|dead, §16.1) without importing the combat package --
# domain stores/compares these as plain strings so it stays decoupled from
# combat/**'s types; systems/combat.py is the only place that maps between them.
LIFE_STATE_ALIVE = "alive"
LIFE_STATE_DOWNED = "downed"
LIFE_STATE_STABLE = "stable"
LIFE_STATE_DEAD = "dead"


@dataclass
class HeroState:
    hero_id: str
    room_id: str
    energy: int = 5
    max_energy: int = 5
    hp: int = 12
    max_hp: int = 12
    conscious: bool = True
    alive: bool = True
    submitted_turn: bool = False
    movement_locked: bool = False   # set True after a breach; cleared at round refresh
    life_state: str = LIFE_STATE_ALIVE          # §16.1 Downed/Stable/Dead, persists across rooms
    death_failures: int = 0
    stabilization_successes: int = 0
    carried_item_ids: tuple[str, ...] = ()      # §13.6: kept as a synced mirror of inventory.items
    # Wave-4 herowire additions (board task #13, §11/§13). All None until the
    # hero completes character creation (roll_attribute_dice -> create_hero);
    # existing heroes created via plain join_run alone (older tests, puzzle/
    # conflict fixtures) simply never populate these and keep every prior
    # behavior (0/0 checks, flat combat defaults) unchanged.
    pending_dice: tuple[int, ...] | None = None   # rolled, not yet assigned to attributes
    sheet: HeroSheet | None = None
    deck: DeckState | None = None
    inventory: InventoryState | None = None
    signature_charge: SignatureCharge | None = None

    def sync_life_state(self, life_state: str) -> None:
        """Set life_state and derive conscious/alive so existing exploration
        code (round_complete, legal_action_summary) keeps working unchanged:
        Downed/Stable heroes are alive but not conscious (cannot take normal
        exploration actions); Dead heroes are neither."""
        self.life_state = life_state
        if life_state == LIFE_STATE_ALIVE:
            self.alive, self.conscious = True, True
        elif life_state in (LIFE_STATE_DOWNED, LIFE_STATE_STABLE):
            self.alive, self.conscious = True, False
        else:
            self.alive, self.conscious = False, False

    def to_dict(self) -> dict:
        return {
            "hero_id": self.hero_id,
            "room_id": self.room_id,
            "energy": self.energy,
            "max_energy": self.max_energy,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "conscious": self.conscious,
            "alive": self.alive,
            "submitted_turn": self.submitted_turn,
            "movement_locked": self.movement_locked,
            "life_state": self.life_state,
            "death_failures": self.death_failures,
            "stabilization_successes": self.stabilization_successes,
            "carried_item_ids": list(self.carried_item_ids),
            "pending_dice": list(self.pending_dice) if self.pending_dice is not None else None,
            "sheet": dataclasses.asdict(self.sheet) if self.sheet is not None else None,
            "deck": dataclasses.asdict(self.deck) if self.deck is not None else None,
            "inventory": dataclasses.asdict(self.inventory) if self.inventory is not None else None,
            "signature_charge": dataclasses.asdict(self.signature_charge) if self.signature_charge is not None else None,
        }


@dataclass
class RunState:
    run_id: str
    seed: int
    revision: int = 0
    world_round: int = 1
    chapter_floor_index: int = 0
    heroes: dict[str, HeroState] = field(default_factory=dict)
    map: MapState | None = None
    facts: tuple[str, ...] = field(default_factory=tuple)  # emit_fact op ledger (§5, §18.4 seam)

    @staticmethod
    def initial(run_id: str, seed: int, chapter_floor_index: int = 0) -> "RunState":
        return RunState(run_id=run_id, seed=seed, chapter_floor_index=chapter_floor_index)

    def living_conscious_hero_ids(self) -> list[str]:
        return [h.hero_id for h in self.heroes.values() if h.alive and h.conscious]

    def total_living_heroes(self) -> int:
        """§15.1: threat budget uses the total living party (Downed/Stable
        heroes still count -- only Dead ones don't), never just who is
        physically present in the room."""
        return sum(1 for h in self.heroes.values() if h.alive)

    def round_complete(self) -> bool:
        living = self.living_conscious_hero_ids()
        if not living:
            return False
        return all(self.heroes[hid].submitted_turn for hid in living)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "seed": self.seed,
            "revision": self.revision,
            "world_round": self.world_round,
            "chapter_floor_index": self.chapter_floor_index,
            "heroes": {hid: h.to_dict() for hid, h in sorted(self.heroes.items())},
            "map": self.map.to_dict() if self.map else None,
            "facts": list(self.facts),
        }

    def state_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def clone(self) -> "RunState":
        return copy.deepcopy(self)
