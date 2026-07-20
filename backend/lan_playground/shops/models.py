"""Content-shape and runtime dataclasses for shops (infinite_stacks.md §9.6).

`ShopArchetype` is the *authored* shape a content pack declares (persona,
services offered, seeded inventory, one rumor, one relationship
complication, and the pricing knobs `economy.py` reads). `ShopInstance` is
the *seeded runtime* shape (`seeding.instantiate_shop`) -- a concrete stock
count per item id, deterministic from an archetype + an injected
`shops.rng.ShopsRNG`.

This module owns the shape rather than `content/schemas.py` because
`content/schemas.py` is off-limits to this lane for wave 4 (see
docs/INFINITE_STACKS_SHOPS.md for the coordination note) -- `content/loader.py`
constructs these dataclasses directly from parsed YAML instead, the same
"shop content passed in as data" discipline the rest of this package follows,
just with the parse step living on the content side of the seam. Nothing in
this module imports `content` (or anything outside the standard library), so
the dependency only ever points one way: `content.loader` -> `shops.models`,
never back.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ShopModelError(ValueError):
    """Raised when authored/seeded shop data violates the shape contract."""


def validate_id(value: str, *, kind: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ShopModelError(
            f"{kind} id {value!r} must be a lowercase snake_case string matching {_ID_RE.pattern!r}"
        )
    return value


class ShopService(str, Enum):
    """§9.6: "buy and sell rules ... services such as repair, treatment,
    identification". BUY/SELL are always implicitly available once a shop
    has any inventory; they're still listed explicitly so a shop that only
    offers services (no goods) can decline them structurally."""

    BUY = "buy"
    SELL = "sell"
    REPAIR = "repair"
    IDENTIFY = "identify"
    TREAT = "treat"


@dataclass(frozen=True)
class MerchantPersona:
    """§19.3-adjacent, presentation-only: never read by economy.py or
    services.py. A dialogue/LLM layer may use these fields to color prose;
    they never gate or modify a price (§9.6: "Dialogue may change discounts
    only through declared actions and visible modifiers")."""

    name: str
    tagline: str
    tone: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ShopModelError("MerchantPersona.name must not be empty")
        if not self.tagline.strip():
            raise ShopModelError("MerchantPersona.tagline must not be empty")
        if not self.tone.strip():
            raise ShopModelError("MerchantPersona.tone must not be empty")


@dataclass(frozen=True)
class Rumor:
    id: str
    text: str
    accessible_text: str

    def __post_init__(self) -> None:
        validate_id(self.id, kind="rumor")
        if not self.text.strip():
            raise ShopModelError(f"rumor {self.id!r} text must not be empty")
        if not self.accessible_text.strip():
            raise ShopModelError(f"rumor {self.id!r} accessible_text must not be empty")


@dataclass(frozen=True)
class RelationshipComplication:
    id: str
    description: str
    accessible_text: str

    def __post_init__(self) -> None:
        validate_id(self.id, kind="relationship_complication")
        if not self.description.strip():
            raise ShopModelError(f"relationship complication {self.id!r} description must not be empty")
        if not self.accessible_text.strip():
            raise ShopModelError(f"relationship complication {self.id!r} accessible_text must not be empty")


@dataclass(frozen=True)
class InventoryListing:
    """One priced entry a shop can stock. `item_id` is a `content/packs/*/items.yaml`
    id -- this package never validates that the id actually exists (it has no
    content import); cross-referencing against a loaded pack is
    `content.validators.check_shop_item_references`'s job.

    `buy_price` is authoritative game data (§9.6) -- the *only* price a
    player pays to acquire this item from this shop; `stock` is the seeded
    quantity available (`None` means effectively unlimited, e.g. common
    consumables)."""

    item_id: str
    buy_price: int
    stock: int | None = None

    def __post_init__(self) -> None:
        validate_id(self.item_id, kind="item")
        if self.buy_price <= 0:
            raise ShopModelError(f"listing {self.item_id!r} buy_price must be positive")
        if self.stock is not None and self.stock < 0:
            raise ShopModelError(f"listing {self.item_id!r} stock must be >= 0 or None")


@dataclass(frozen=True)
class ShopArchetype:
    """The authored shape (§9.6, §23.3 "Shop archetypes"). `guaranteed_inventory`
    is always seeded; `rotating_pool` is a candidate pool `seeding.instantiate_shop`
    draws `rotating_slots` items from (deterministic given the same RNG draw
    sequence) -- this is what "seeded shop instances from pack data" (board
    task #15) means concretely: two instances of the same archetype seeded
    with different RNG state can carry a different rotating selection, while
    the guaranteed inventory and all pricing stay identical (pure data, no
    randomness in the price itself)."""

    id: str
    name: str
    persona: MerchantPersona
    services: frozenset[ShopService]
    guaranteed_inventory: tuple[InventoryListing, ...]
    rotating_pool: tuple[InventoryListing, ...]
    rotating_slots: int
    sell_price_ratio: float
    repair_cost_per_wear: int
    identify_price: int
    treatment_price: int
    rumor: Rumor
    relationship_complication: RelationshipComplication

    def __post_init__(self) -> None:
        validate_id(self.id, kind="shop")
        if not self.services:
            raise ShopModelError(f"shop {self.id!r} must declare at least one service")
        if not self.guaranteed_inventory and not self.rotating_pool:
            raise ShopModelError(f"shop {self.id!r} must seed at least one inventory listing")
        if self.rotating_slots < 0:
            raise ShopModelError(f"shop {self.id!r} rotating_slots must be >= 0")
        if self.rotating_slots > len(self.rotating_pool):
            raise ShopModelError(
                f"shop {self.id!r} rotating_slots ({self.rotating_slots}) exceeds "
                f"rotating_pool size ({len(self.rotating_pool)})"
            )
        # ECON-001 (infinite_stacks.md §6.2, §17.1): sell price is derived from
        # buy_price at a strictly-less-than-1 ratio -- see economy.sell_price,
        # which additionally clamps per-item so this invariant holds even at
        # the rounding edge. Validated here so a content author cannot author
        # an archetype that defeats the anti-loop guarantee at the data layer.
        if not (0.0 <= self.sell_price_ratio < 1.0):
            raise ShopModelError(
                f"shop {self.id!r} sell_price_ratio must be in [0.0, 1.0) (ECON-001 anti-loop)"
            )
        if self.repair_cost_per_wear < 0:
            raise ShopModelError(f"shop {self.id!r} repair_cost_per_wear must be >= 0")
        if self.identify_price < 0:
            raise ShopModelError(f"shop {self.id!r} identify_price must be >= 0")
        if self.treatment_price < 0:
            raise ShopModelError(f"shop {self.id!r} treatment_price must be >= 0")
        all_ids = [listing.item_id for listing in (*self.guaranteed_inventory, *self.rotating_pool)]
        if len(all_ids) != len(set(all_ids)):
            raise ShopModelError(f"shop {self.id!r} lists the same item id in more than one listing")

    def all_listings(self) -> tuple[InventoryListing, ...]:
        return self.guaranteed_inventory + self.rotating_pool

    def listing_for(self, item_id: str) -> InventoryListing | None:
        for listing in self.all_listings():
            if listing.item_id == item_id:
                return listing
        return None


@dataclass(frozen=True)
class ShopInstance:
    """A seeded, runtime shop: which items are actually in stock (guaranteed
    + the rotating draw) and how many of each remain. Mutated only through
    `services.py`'s pure attempt_* functions, which return a new instance
    rather than mutating this one (same "clone before applying" discipline
    `domain.reducer` uses)."""

    archetype_id: str
    stock: Mapping[str, int]  # item_id -> remaining units; absent key == not stocked this instance

    def with_stock(self, item_id: str, quantity: int) -> "ShopInstance":
        new_stock = dict(self.stock)
        if quantity <= 0:
            new_stock.pop(item_id, None)
        else:
            new_stock[item_id] = quantity
        return ShopInstance(archetype_id=self.archetype_id, stock=new_stock)


@dataclass(frozen=True)
class ShopperState:
    """A player-side wallet + held items, scoped to this package's pure
    economy math only (no relation to `heroes.inventory.InventoryState` --
    that owns slot/encumbrance semantics; this owns gold and per-item Wear
    for pricing purposes only). Wave-5 domain wiring is expected to bridge
    the two, not merge them (`heroes.inventory` stays the single owner of
    "does this hero have this item")."""

    gold: int
    held_items: Mapping[str, int] = field(default_factory=dict)  # item_id -> count held
    wear: Mapping[str, int] = field(default_factory=dict)  # item_id -> Wear level, 0 == pristine
    identified: frozenset[str] = frozenset()  # item_ids this shopper has paid to identify

    def __post_init__(self) -> None:
        if self.gold < 0:
            raise ShopModelError("ShopperState.gold must be >= 0")
        for item_id, count in self.held_items.items():
            if count < 0:
                raise ShopModelError(f"ShopperState.held_items[{item_id!r}] must be >= 0")
        for item_id, wear_level in self.wear.items():
            if wear_level < 0:
                raise ShopModelError(f"ShopperState.wear[{item_id!r}] must be >= 0")
