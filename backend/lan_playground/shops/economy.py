"""Pure pricing math (infinite_stacks.md §9.6, §6.2, §17.1).

ECON-001 anti-loop rule: no sequence of shop actions may increase a
shopper's total wealth. This module is the single place price numbers are
computed, so the invariant only has to be proven once (see
tests/test_stacks_shops.py's property test, which exercises 1000+ random
action sequences against `total_wealth`).

Two design choices make the property provable rather than merely tested:

1. `sell_price` is derived *only* from a listing's `buy_price` and the
   archetype's `sell_price_ratio` -- never from Wear, identification state,
   or anything a player action could inflate. Wear/identification cost gold
   to fix/reveal but never change what an item resells for.
2. `sell_price` is clamped to be strictly less than `buy_price` by
   construction (`min(floor(buy_price * ratio), buy_price - 1)`), so a
   content author picking a ratio close to 1.0 can't accidentally produce
   sell_price == buy_price at small buy_price values through rounding.
"""
from __future__ import annotations

from .models import ShopArchetype, ShopModelError, ShopService, ShopperState


class UnknownListingError(ShopModelError):
    pass


def _listing_or_raise(archetype: ShopArchetype, item_id: str):
    listing = archetype.listing_for(item_id)
    if listing is None:
        raise UnknownListingError(f"shop {archetype.id!r} does not stock item {item_id!r}")
    return listing


def buy_price(archetype: ShopArchetype, item_id: str) -> int:
    return _listing_or_raise(archetype, item_id).buy_price


def sell_price(archetype: ShopArchetype, item_id: str) -> int:
    """ECON-001: strictly below buy_price for every buy_price >= 1."""

    price = buy_price(archetype, item_id)
    return max(0, min(int(price * archetype.sell_price_ratio), price - 1))


def repair_price(archetype: ShopArchetype, wear_level: int) -> int:
    """§6.2/§17.1 GEAR-001: repair cost scales with Wear. wear_level is
    caller-supplied (this package tracks no item-instance Wear of its own --
    see `ShopperState.wear`); 0 Wear repairs for free (a no-op, never a
    priced action)."""

    if wear_level < 0:
        raise ShopModelError("wear_level must be >= 0")
    return archetype.repair_cost_per_wear * wear_level


def identify_price(archetype: ShopArchetype) -> int:
    return archetype.identify_price


def treatment_price(archetype: ShopArchetype) -> int:
    return archetype.treatment_price


def offers(archetype: ShopArchetype, service: ShopService) -> bool:
    return service in archetype.services


def total_wealth(shopper: ShopperState, archetype: ShopArchetype) -> int:
    """Gold-in-hand plus the liquidation value (this shop's sell_price) of
    every held item this shop actually stocks. Items this shop doesn't stock
    contribute 0 -- they can't be sold here, so they carry no wealth *at this
    shop* (a multi-shop wealth figure is a wave-5 domain concern; this
    package only proves the single-shop anti-loop invariant, per board task
    #15's acceptance criteria)."""

    liquid = 0
    for item_id, count in shopper.held_items.items():
        listing = archetype.listing_for(item_id)
        if listing is not None:
            liquid += sell_price(archetype, item_id) * count
    return shopper.gold + liquid
