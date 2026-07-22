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

    # Mystery Chamber puzzle rooms (infinite_stacks.md §9.1, §10; systems/puzzles.py)
    MYSTERY_PUZZLE_INSTANTIATED = "mystery_puzzle_instantiated"
    PRIVATE_CLUE_REVEALED = "private_clue_revealed"
    PUZZLE_OBJECT_INSPECTED = "puzzle_object_inspected"
    PUZZLE_HINT_REVEALED = "puzzle_hint_revealed"
    PUZZLE_SOLUTION_ACCEPTED = "puzzle_solution_accepted"
    PUZZLE_SOLUTION_REJECTED = "puzzle_solution_rejected"
    PUZZLE_FORCE_PROGRESS = "puzzle_force_progress"

    # Content-effect ops (contract doc §5; systems/effects.py)
    ROOM_REVEALED_BY_EFFECT = "room_revealed_by_effect"   # reveal_room op
    EFFECT_ENERGY_SPENT = "effect_energy_spent"           # spend_energy op
    FACT_EMITTED = "fact_emitted"                          # emit_fact op
    # grant_check op reuses CHECK_RESOLVED above

    # Conflict rooms / combat wiring (infinite_stacks.md §14-16; systems/combat.py).
    # These wrap the pure backend.lan_playground.combat package's own event
    # dicts (docs/INFINITE_STACKS_COMBAT.md §1 envelope) as payload data rather
    # than re-declaring one domain EventType per CombatEventType -- the same
    # "carry a whole resulting sub-state" pattern MAP_GENERATED already uses.
    CONFLICT_ENCOUNTER_STARTED = "conflict_encounter_started"
    CONFLICT_TURN_RESOLVED = "conflict_turn_resolved"
    CONFLICT_ENCOUNTER_ENDED = "conflict_encounter_ended"
    JOINED_CONFLICT_ROOM = "joined_conflict_room"

    # Heroes wiring (infinite_stacks.md §11, §13; wave 4, board task #13;
    # systems/heroes_wire.py). Character creation, deck lifecycle, and
    # inventory -- domain schema posted to the collab room 2026-07-19.
    ATTRIBUTE_DICE_ROLLED = "attribute_dice_rolled"
    HERO_CREATED = "hero_created"
    CARD_DRAWN = "card_drawn"
    CARD_PLAYED = "card_played"
    DECK_RESHUFFLED = "deck_reshuffled"
    SIGNATURE_CHARGE_REFRESHED = "signature_charge_refreshed"
    ITEM_PICKED_UP = "item_picked_up"
    ITEM_PICKUP_REJECTED = "item_pickup_rejected"
    ITEM_DROPPED = "item_dropped"
    ITEM_TRADED = "item_traded"
    BODY_LOOT_RECOVERED = "body_loot_recovered"

    # Content-effect ops, wave-5 additions (infinite_stacks.md §16.4-16.6;
    # systems/effects.py). Both ops already appear in authored content
    # (enemies.yaml's apply_condition, conditions.yaml/cards.yaml/items.yaml's
    # remove_condition) but had no dispatcher before this wave.
    CONDITION_APPLIED = "condition_applied"
    CONDITION_REMOVED = "condition_removed"

    # Shops wiring (infinite_stacks.md §9.6; wave 5, board task #18;
    # systems/shops_wire.py). Domain schema posted to the collab room
    # 2026-07-19.
    SHOP_INSTANTIATED = "shop_instantiated"
    SHOP_ITEM_BOUGHT = "shop_item_bought"
    SHOP_ITEM_SOLD = "shop_item_sold"
    SHOP_ITEM_REPAIRED = "shop_item_repaired"
    SHOP_ITEM_IDENTIFIED = "shop_item_identified"
    SHOP_CONDITION_TREATED = "shop_condition_treated"
    SHOP_TRANSACTION_REJECTED = "shop_transaction_rejected"

    # Server-side clue sharing (wave 5, board task #18; systems/puzzles.py)
    CLUE_SHARED = "clue_shared"

    # Abilities + active-effect durations (wave 6, board task #21;
    # docs/PLAYTEST_FINDINGS_2026-07-19.md E1/A5; systems/abilities.py,
    # systems/heroes_wire.py, systems/effects.py). Domain schema posted to the
    # collab room 2026-07-20.
    ABILITY_USED = "ability_used"
    ABILITY_CHARGE_REFRESHED = "ability_charge_refreshed"
    ACTIVE_EFFECT_APPLIED = "active_effect_applied"
    ACTIVE_EFFECT_EXPIRED = "active_effect_expired"

    # Study-room domain wiring (wave6b/slice-wiring, docs/
    # INFINITE_STACKS_STUDY_SLICE.md; systems/study_wire.py). Realizes
    # wavebasedgame.md §3.2's revised core loop over the Gothic Living Study
    # vertical slice: room/object/NPC content becomes real, event-sourced
    # domain state.
    STUDY_ROOM_INSTANTIATED = "study_room_instantiated"      # breach d8==3 (study) seeds a RoomTemplate+NPCTemplate
    OBJECT_STATE_CHANGED = "object_state_changed"            # a StateTransition fired
    FACT_PROMOTED = "fact_promoted"                            # a narration/object fact promoted for one viewer
    RESPONSE_ARTIFACT_EMITTED = "response_artifact_emitted"   # brain.response.ResponseArtifact, always-a-response (§2.3)
    CONTENT_GAP_LOGGED = "content_gap_logged"                 # ContentGapRecord persisted (director ruling, board note 31/32)
    SOCIAL_CHECK_RESOLVED = "social_check_resolved"           # brain.degrees.resolve_social_check + systems.checks resolution
    NPC_DISPOSITION_CHANGED = "npc_disposition_changed"
    NPC_OBJECTIVE_CHANGED = "npc_objective_changed"
    LATTICE_CONTRIBUTION_REGISTERED = "lattice_contribution_registered"  # a room resolved -> its LatticeContribution counted
    LATTICE_RECIPE_SATISFIED = "lattice_recipe_satisfied"
    STAIR_REVEALED = "stair_revealed"


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
