"""Shop service transactions: buy/sell/repair/identify/treat (infinite_stacks.md
§9.6). Every `attempt_*` function is a pure state transition -- `(result,
new_shop_instance, new_shopper_state)` -- never mutating its arguments, same
discipline as `heroes.inventory.attempt_pickup`. A rejected attempt (service
not offered, out of stock, insufficient gold, nothing to repair/sell) returns
the *same* instance/state back unchanged plus a `TransactionResult` naming
the reason, rather than raising -- callers (wave-5 domain wiring) decide how
to surface that to a player.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from . import economy
from .models import ShopArchetype, ShopInstance, ShopService, ShopperState


@dataclass(frozen=True)
class TransactionResult:
    accepted: bool
    reason: str | None = None  # populated exactly when accepted is False
    gold_delta: int = 0  # signed: negative == shopper paid out, positive == shopper received


def _held(shopper: ShopperState, item_id: str) -> int:
    return shopper.held_items.get(item_id, 0)


def _with_held(shopper: ShopperState, item_id: str, delta: int) -> dict[str, int]:
    held = dict(shopper.held_items)
    new_count = held.get(item_id, 0) + delta
    if new_count <= 0:
        held.pop(item_id, None)
    else:
        held[item_id] = new_count
    return held


def attempt_buy(
    archetype: ShopArchetype, instance: ShopInstance, shopper: ShopperState, item_id: str
) -> tuple[TransactionResult, ShopInstance, ShopperState]:
    if not economy.offers(archetype, ShopService.BUY):
        return TransactionResult(False, "service_not_offered"), instance, shopper
    remaining = instance.stock.get(item_id, 0)
    if remaining <= 0:
        return TransactionResult(False, "out_of_stock"), instance, shopper
    price = economy.buy_price(archetype, item_id)
    if shopper.gold < price:
        return TransactionResult(False, "insufficient_gold"), instance, shopper

    new_instance = instance.with_stock(item_id, remaining - 1)
    new_shopper = replace(
        shopper, gold=shopper.gold - price, held_items=_with_held(shopper, item_id, 1)
    )
    return TransactionResult(True, gold_delta=-price), new_instance, new_shopper


def attempt_sell(
    archetype: ShopArchetype, instance: ShopInstance, shopper: ShopperState, item_id: str
) -> tuple[TransactionResult, ShopInstance, ShopperState]:
    if not economy.offers(archetype, ShopService.SELL):
        return TransactionResult(False, "service_not_offered"), instance, shopper
    if _held(shopper, item_id) <= 0:
        return TransactionResult(False, "not_held"), instance, shopper
    if archetype.listing_for(item_id) is None:
        return TransactionResult(False, "shop_does_not_buy_this_item"), instance, shopper

    price = economy.sell_price(archetype, item_id)
    new_wear = dict(shopper.wear)
    new_wear.pop(item_id, None)
    new_shopper = replace(
        shopper, gold=shopper.gold + price, held_items=_with_held(shopper, item_id, -1), wear=new_wear
    )
    current_stock = instance.stock.get(item_id, 0)
    new_instance = instance.with_stock(item_id, current_stock + 1)
    return TransactionResult(True, gold_delta=price), new_instance, new_shopper


def attempt_repair(
    archetype: ShopArchetype, instance: ShopInstance, shopper: ShopperState, item_id: str
) -> tuple[TransactionResult, ShopInstance, ShopperState]:
    if not economy.offers(archetype, ShopService.REPAIR):
        return TransactionResult(False, "service_not_offered"), instance, shopper
    if _held(shopper, item_id) <= 0:
        return TransactionResult(False, "not_held"), instance, shopper
    wear_level = shopper.wear.get(item_id, 0)
    if wear_level <= 0:
        return TransactionResult(False, "nothing_to_repair"), instance, shopper
    cost = economy.repair_price(archetype, wear_level)
    if shopper.gold < cost:
        return TransactionResult(False, "insufficient_gold"), instance, shopper

    new_wear = dict(shopper.wear)
    new_wear.pop(item_id, None)
    new_shopper = replace(shopper, gold=shopper.gold - cost, wear=new_wear)
    return TransactionResult(True, gold_delta=-cost), instance, new_shopper


def attempt_identify(
    archetype: ShopArchetype, instance: ShopInstance, shopper: ShopperState, item_id: str
) -> tuple[TransactionResult, ShopInstance, ShopperState]:
    if not economy.offers(archetype, ShopService.IDENTIFY):
        return TransactionResult(False, "service_not_offered"), instance, shopper
    if _held(shopper, item_id) <= 0:
        return TransactionResult(False, "not_held"), instance, shopper
    if item_id in shopper.identified:
        return TransactionResult(False, "already_identified"), instance, shopper
    cost = economy.identify_price(archetype)
    if shopper.gold < cost:
        return TransactionResult(False, "insufficient_gold"), instance, shopper

    new_shopper = replace(
        shopper, gold=shopper.gold - cost, identified=shopper.identified | {item_id}
    )
    return TransactionResult(True, gold_delta=-cost), instance, new_shopper


def attempt_treat(
    archetype: ShopArchetype, instance: ShopInstance, shopper: ShopperState
) -> tuple[TransactionResult, ShopInstance, ShopperState]:
    """Treatment isn't item-scoped (§9.6: medicine/antidotes/revival supplies
    are goods; *treatment* is a service performed on the hero). This package
    has no hero-condition model of its own, so it only proves the economic
    half: a flat, always-a-cost service (wave-5 domain wiring supplies the
    condition being treated and applies its cure effect)."""

    if not economy.offers(archetype, ShopService.TREAT):
        return TransactionResult(False, "service_not_offered"), instance, shopper
    cost = economy.treatment_price(archetype)
    if shopper.gold < cost:
        return TransactionResult(False, "insufficient_gold"), instance, shopper

    new_shopper = replace(shopper, gold=shopper.gold - cost)
    return TransactionResult(True, gold_delta=-cost), instance, new_shopper
