"""Instantiate a seeded `ShopInstance` from a `ShopArchetype` (infinite_stacks.md
§9.6: "Shops have limited seeded inventories").

The guaranteed inventory always seeds in at full declared stock. If the
archetype declares a `rotating_pool` larger than `rotating_slots`, the RNG
draws exactly `rotating_slots` distinct listings from the pool -- same seed,
same rng call sequence, same draw, every time (determinism/replay contract,
docs/INFINITE_STACKS_CONTRACTS.md §9). No price is ever randomized; only
*which* rotating listings are present this instance is seeded.
"""
from __future__ import annotations

from .models import ShopArchetype, ShopInstance
from .rng import ShopsRNG


def instantiate_shop(archetype: ShopArchetype, rng: ShopsRNG) -> ShopInstance:
    stock: dict[str, int] = {}
    for listing in archetype.guaranteed_inventory:
        stock[listing.item_id] = listing.stock if listing.stock is not None else _UNLIMITED
    drawn = rng.shuffled(list(archetype.rotating_pool))[: archetype.rotating_slots]
    for listing in drawn:
        stock[listing.item_id] = listing.stock if listing.stock is not None else _UNLIMITED

    return ShopInstance(archetype_id=archetype.id, stock=stock)


# Sentinel quantity for "unlimited seeded stock" (§9.6 leaves restock/scarcity
# per-listing rather than per-shop; a listing with no declared `stock` is
# always available). Large enough that no plausible test/property sequence
# exhausts it, small enough it can't silently overflow anything downstream.
_UNLIMITED = 1_000_000
