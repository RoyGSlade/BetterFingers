"""Visible d8 room roll and deterministic legal-subtype selection (§7.2).

The engine never alters the displayed die: `roll_family(rng)` returns the raw
1-8 face and its family name, full stop. Subtype selection is a separate step
that only chooses among the family's legal subtypes -- it cannot change which
family the room belongs to.
"""
from __future__ import annotations

from ..domain.rng import StacksRNG

FAMILY_BY_D8 = {
    1: "mystery_chamber",
    2: "passage",
    3: "study",
    4: "wild_place",
    5: "conflict",
    6: "shop",
    7: "social_encounter",
    8: "anomaly",
}

# Illustrative legal subtypes per family (infinite_stacks.md §9). Content packs
# may extend this table later; the engine only guarantees "a legal member of
# the rolled family, varied on repeats" per §7.2.
SUBTYPES_BY_FAMILY = {
    "mystery_chamber": ["four_object_puzzle", "sealed_vault", "damaged_index"],
    "passage": [
        "forked_corridor",
        "elevation_stairs",
        "collapsing_bridge",
        "unstable_loop",
        "sacrifice_shortcut",
        "trapped_hall",
    ],
    "study": ["damaged_page", "enemy_research", "item_identification", "clue_translation"],
    "wild_place": ["garden", "battlefield", "frozen_sea", "rooftop", "ruins"],
    "conflict": ["standard_fight", "pursuit", "protect_objective", "capture_target"],
    "shop": ["traveling_merchant", "abandoned_counter", "hostile_auction", "false_storefront"],
    "social_encounter": ["information_broker", "misunderstanding", "alliance_offer", "impostor"],
    "anomaly": ["temporal_split", "true_memory_boon", "duplicate_hero", "safe_room_with_cost"],
}


def roll_family(rng: StacksRNG) -> tuple[int, str]:
    face = rng.roll_d8()
    return face, FAMILY_BY_D8[face]


def select_subtype(rng: StacksRNG, family: str, used_subtypes: list[str]) -> str:
    legal = SUBTYPES_BY_FAMILY[family]
    unused = [s for s in legal if s not in used_subtypes]
    pool = unused if unused else legal
    return rng.choice(pool)


def roll_family_and_subtype(
    rng: StacksRNG, used_subtypes_by_family: dict[str, list[str]]
) -> tuple[int, str, str]:
    face, family = roll_family(rng)
    subtype = select_subtype(rng, family, used_subtypes_by_family.get(family, []))
    return face, family, subtype
