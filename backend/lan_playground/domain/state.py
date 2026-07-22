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
from ..shops.models import ShopInstance

# §9.6/§17.1 GEAR-001 starting wealth: decided as data this wave (board task
# #18) since infinite_stacks.md names no figure. 20 affords one shop's
# treatment service or a mid-priced item from the core pack's price range
# (4-22) without trivializing every purchase -- a single named constant so
# nothing scatters a magic number across the domain/systems wiring.
STARTING_GOLD = 20


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
class StudyRoomState:
    """Runtime state for a wave-6B Study-family room instantiated from
    `content.rooms.RoomTemplate`/`content.npcs.NPCTemplate` (wave6b/slice-wiring,
    docs/INFINITE_STACKS_STUDY_SLICE.md, wavebasedgame.md §3.2-3.4). Mirrors
    `PuzzleRoomState`'s discipline: reconstructible from (room_template_id,
    npc_ids) alone, `to_dict()`/`from_dict()` for `RunState.state_hash()`
    replay fidelity, and per-hero private ledgers for disclosure.

    `object_state_ids` is the live current-state id per `RoomObject.id`
    (starts at each object's authored `initial_state`, advances only via a
    real `StateTransition`). `promoted_object_ids`/`promoted_fact_ids` are
    PER-VIEWER (keyed by hero_id) records of which HIDDEN/NOTICED object
    states or narration facts have been promoted to that viewer's visible
    set -- the disclosure-filter seam §19.4/§20.2 requires: a fact promoted
    for one viewer must never leak into another viewer's projection or
    narration packet. `npc_disclosed_atom_ids` is the same idea for NPC
    `KnowledgeAtom`s (mirrors `PuzzleRoomState.private_clue_assignments`).
    """

    room_template_id: str
    npc_id: str | None = None
    object_state_ids: dict[str, str] = field(default_factory=dict)
    promoted_object_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)  # hero_id -> object_ids noticed/free
    promoted_fact_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)    # hero_id -> fact_ids disclosed
    fired_interaction_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)  # object_id -> interaction_ids used (one-shot tracking)
    npc_disposition: str = ""
    npc_objective_states: dict[str, str] = field(default_factory=dict)  # objective_id -> "active"|"changed"
    npc_disclosed_atom_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)  # hero_id -> atom_ids
    payoff_triggered: bool = False
    resolved: bool = False  # lattice_contribution registered for this room

    def to_dict(self) -> dict:
        return {
            "room_template_id": self.room_template_id,
            "npc_id": self.npc_id,
            "object_state_ids": dict(sorted(self.object_state_ids.items())),
            "promoted_object_ids": {k: list(v) for k, v in sorted(self.promoted_object_ids.items())},
            "promoted_fact_ids": {k: list(v) for k, v in sorted(self.promoted_fact_ids.items())},
            "fired_interaction_ids": {k: list(v) for k, v in sorted(self.fired_interaction_ids.items())},
            "npc_disposition": self.npc_disposition,
            "npc_objective_states": dict(sorted(self.npc_objective_states.items())),
            "npc_disclosed_atom_ids": {k: list(v) for k, v in sorted(self.npc_disclosed_atom_ids.items())},
            "payoff_triggered": self.payoff_triggered,
            "resolved": self.resolved,
        }

    @staticmethod
    def from_dict(d: dict) -> "StudyRoomState":
        return StudyRoomState(
            room_template_id=d["room_template_id"],
            npc_id=d.get("npc_id"),
            object_state_ids=dict(d.get("object_state_ids", {})),
            promoted_object_ids={k: tuple(v) for k, v in d.get("promoted_object_ids", {}).items()},
            promoted_fact_ids={k: tuple(v) for k, v in d.get("promoted_fact_ids", {}).items()},
            fired_interaction_ids={k: tuple(v) for k, v in d.get("fired_interaction_ids", {}).items()},
            npc_disposition=d.get("npc_disposition", ""),
            npc_objective_states=dict(d.get("npc_objective_states", {})),
            npc_disclosed_atom_ids={k: tuple(v) for k, v in d.get("npc_disclosed_atom_ids", {}).items()},
            payoff_triggered=d.get("payoff_triggered", False),
            resolved=d.get("resolved", False),
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
    # Wave-5 addition (board task #16, stacks-enemyroll; domain registration
    # requested via chat 2026-07-19): an open reaction-interrupt window
    # (§14.5) between hit-determination and damage-application. Plain
    # JSON-safe dict, same pass-through discipline as turn_budget/
    # threat_budget -- systems/combat.py owns its shape.
    pending_reaction: dict | None = None

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
            "pending_reaction": dict(self.pending_reaction) if self.pending_reaction is not None else None,
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
            pending_reaction=dict(d["pending_reaction"]) if d.get("pending_reaction") is not None else None,
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
    study: StudyRoomState | None = None
    body_item_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)  # §13.6: dead hero's items stay with the body
    # Wave-4 herowire additions (board task #13, §13.6): items lying in the
    # room available for pickup (item_instance_id -> item_id) and the
    # single-owner pickup contest ledger heroes.inventory.attempt_pickup
    # needs (item_instance_id -> claiming hero_id).
    ground_items: dict[str, str] = field(default_factory=dict)
    item_claims: dict[str, str] = field(default_factory=dict)
    # Wave-5 shopwire addition (board task #18, §9.6): the seeded shop
    # instantiated on a d8=6 breach, embedded directly the same way heroes'
    # dataclasses are (a one-way domain -> shops dependency, mirroring
    # domain -> heroes) -- systems/shops_wire.py is the sole place that reads
    # `shops.models`/`shops.services`/`shops.economy` to act on it.
    shop: ShopInstance | None = None

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
            "study": self.study.to_dict() if self.study is not None else None,
            "body_item_ids": {k: list(v) for k, v in sorted(self.body_item_ids.items())},
            "ground_items": dict(sorted(self.ground_items.items())),
            "item_claims": dict(sorted(self.item_claims.items())),
            "shop": (
                {"archetype_id": self.shop.archetype_id, "stock": dict(sorted(self.shop.stock.items()))}
                if self.shop is not None
                else None
            ),
        }

    @staticmethod
    def from_dict(d: dict) -> "RoomState":
        shop_d = d.get("shop")
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
            study=StudyRoomState.from_dict(d["study"]) if d.get("study") else None,
            body_item_ids={k: tuple(v) for k, v in d.get("body_item_ids", {}).items()},
            ground_items=dict(d.get("ground_items", {})),
            item_claims=dict(d.get("item_claims", {})),
            shop=ShopInstance(archetype_id=shop_d["archetype_id"], stock=dict(shop_d["stock"])) if shop_d else None,
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

# Wave-6 playtest-response addition (board task #21, docs/PLAYTEST_FINDINGS_2026-07-19.md
# E1/A5): generalizes heroes.backgrounds.SignatureCharge (a single once-per-X
# charge tied only to a background) into an arbitrary per-hero collection of
# content-authored abilities, keyed by ability_id. heroes/backgrounds.py's
# SignatureCharge is untouched (heroes/ package stays read-only) -- this is a
# parallel, domain-owned model that systems/abilities.py builds/refreshes/spends.
# `trigger`/`frequency` mirror content.schemas.Ability's authoring vocabulary
# (posted 2026-07-20): trigger is "manual"|"passive"|"on_room_enter"|
# "on_encounter_start" (only these four are dispatched by the engine this
# wave); frequency is "unlimited" (no charge tracking -- charges_remaining/
# max_charges stay None) or "once_per_floor"/"once_per_room"/"once_per_fight"
# (only ever paired with trigger=="manual", 1 charge per scope, same as
# SignatureCharge).
@dataclass(frozen=True)
class AbilityState:
    ability_id: str
    trigger: str
    frequency: str
    charges_remaining: int | None = None
    max_charges: int | None = None

    def to_dict(self) -> dict:
        return {
            "ability_id": self.ability_id,
            "trigger": self.trigger,
            "frequency": self.frequency,
            "charges_remaining": self.charges_remaining,
            "max_charges": self.max_charges,
        }

    @staticmethod
    def from_dict(d: dict) -> "AbilityState":
        return AbilityState(
            ability_id=d["ability_id"],
            trigger=d["trigger"],
            frequency=d["frequency"],
            charges_remaining=d["charges_remaining"],
            max_charges=d["max_charges"],
        )


# Wave-6 addition (board task #21, A5): a temporary modifier's visible
# lifetime. `duration` is one of ACTIVE_EFFECT_DURATIONS below; expiry is
# driven by systems/turns.py's existing round-advance/turn-submitted hooks
# (until_end_of_turn/until_end_of_round) and systems/combat.py's
# encounter-ended hook (until_end_of_encounter, scoped to `encounter_id` so a
# split party's other active encounter is unaffected). `label` is a plain
# display string (no separate authored Prose per effect instance this wave --
# see the vocabulary posted to the collab room 2026-07-20).
ACTIVE_EFFECT_DURATIONS = ("until_end_of_turn", "until_end_of_round", "until_end_of_encounter")


@dataclass(frozen=True)
class ActiveEffectState:
    effect_id: str
    source_id: str
    label: str
    duration: str
    applied_world_round: int
    encounter_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "effect_id": self.effect_id,
            "source_id": self.source_id,
            "label": self.label,
            "duration": self.duration,
            "applied_world_round": self.applied_world_round,
            "encounter_id": self.encounter_id,
        }

    @staticmethod
    def from_dict(d: dict) -> "ActiveEffectState":
        return ActiveEffectState(
            effect_id=d["effect_id"],
            source_id=d["source_id"],
            label=d["label"],
            duration=d["duration"],
            applied_world_round=d["applied_world_round"],
            encounter_id=d.get("encounter_id"),
        )


# Wave-6 addition (board task #21, playtest F1): a validated avatar/color pair
# chosen at character creation, never a free-form client string. Fixed lists
# so the server can reject anything else at create_hero; stacks-facelift maps
# each avatar_id to real art in gameassets/.../avatars and applies the color
# as a hue/tint, posted to the collab room 2026-07-20.
AVATAR_IDS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
AVATAR_COLORS: tuple[str, ...] = (
    "crimson", "azure", "gold", "violet", "emerald", "slate", "coral", "ivory",
)


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
    # Wave-5 shopwire additions (board task #18, §9.6, §16.4-16.5). Bridges
    # heroes.inventory.InventoryState (the single owner of "does this hero
    # hold this item") to shops.models.ShopperState's economy fields without
    # merging the two: systems/shops_wire.py builds a transient ShopperState
    # from these fields plus `inventory` for each transaction and writes the
    # result back here, never storing a ShopperState itself on HeroState.
    gold: int = STARTING_GOLD
    item_wear: dict[str, int] = field(default_factory=dict)          # item_id -> Wear level, pricing only
    identified_item_ids: tuple[str, ...] = ()                         # items this hero has paid to identify
    # Persistent §16.4/16.5 statuses/injuries (distinct from combat's own
    # in-encounter StatusInstance dict on ConflictEncounterState, which is
    # ephemeral to a single fight) -- content.schemas.Condition ids currently
    # afflicting this hero, e.g. from a played card's apply_condition effect.
    active_condition_ids: tuple[str, ...] = ()
    # Wave-6 additions (board task #21, docs/PLAYTEST_FINDINGS_2026-07-19.md
    # A5/E1/F1). `abilities` is empty until content.schemas.Ability-sourced
    # pack data lands (stacks-carddesign, packs/core/abilities.yaml) -- every
    # pre-wave-6 hero simply never populates it. `active_effects` starts empty
    # and is mutated only by systems/effects.py's apply_active_effect op and
    # the turns.py/combat.py boundary-expiry hooks. `avatar_id`/`color` are
    # set once at create_hero and never change after.
    abilities: dict[str, AbilityState] = field(default_factory=dict)
    active_effects: tuple[ActiveEffectState, ...] = ()
    avatar_id: int | None = None
    color: str | None = None

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
            "gold": self.gold,
            "item_wear": dict(sorted(self.item_wear.items())),
            "identified_item_ids": list(self.identified_item_ids),
            "active_condition_ids": list(self.active_condition_ids),
            "abilities": {aid: a.to_dict() for aid, a in sorted(self.abilities.items())},
            "active_effects": [e.to_dict() for e in self.active_effects],
            "avatar_id": self.avatar_id,
            "color": self.color,
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
    # Wave-5 shopwire addition (board task #18): room_id -> clue_ids a hero has
    # `share_clue`'d to the party (systems/puzzles.py). PARTY-visibility, so
    # every current hero's projection may include these; a hero's *unshared*
    # private clues stay exactly where they already lived (PuzzleRoomState.
    # private_clue_assignments), never duplicated here.
    party_shared_clues: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # wave6b/slice-wiring additions (docs/INFINITE_STACKS_STUDY_SLICE.md,
    # wavebasedgame.md §2.1/§3.2): resolved-room Meaning Lattice contributions
    # (room_id -> {component_value: amount}), the floor's assigned recipe id
    # (None until a Study-family room is first instantiated this floor), and
    # whether the recipe's stair/objective reveal has already fired -- NOT a
    # room-count gate (§2.1 locked decision 1); satisfaction is always
    # re-derived from `resolved_lattice_contributions` via
    # `content.lattice.LatticeRecipe.is_satisfied`.
    resolved_lattice_contributions: dict[str, dict[str, int]] = field(default_factory=dict)
    floor_lattice_recipe_id: str | None = None
    stair_revealed: bool = False
    # ContentGapRecord persistence (director ruling, board note 31/32): the
    # event log IS persistence until wave 8, so every `content_gap_logged`
    # event's payload is also mirrored here as a plain, JSON-safe ledger --
    # owner/debug-visible only, NEVER included in a player-facing projection.
    content_gaps: tuple[dict, ...] = field(default_factory=tuple)

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
        # Wave-5 (board task #16, stacks-enemyroll): an open reaction-interrupt
        # window must block world-round advance, not auto-resolve.
        if self.map is not None and any(
            r.encounter is not None and r.encounter.status == "active" and r.encounter.pending_reaction is not None
            for r in self.map.rooms.values()
        ):
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
            "party_shared_clues": {k: list(v) for k, v in sorted(self.party_shared_clues.items())},
            "resolved_lattice_contributions": {
                rid: dict(sorted(amounts.items())) for rid, amounts in sorted(self.resolved_lattice_contributions.items())
            },
            "floor_lattice_recipe_id": self.floor_lattice_recipe_id,
            "stair_revealed": self.stair_revealed,
            "content_gaps": [dict(g) for g in self.content_gaps],
        }

    def state_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def clone(self) -> "RunState":
        return copy.deepcopy(self)
