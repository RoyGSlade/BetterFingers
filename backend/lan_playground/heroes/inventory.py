"""Slot-based inventory (infinite_stacks.md §13.6): encumbrance, single-owner
pickup, drop/trade, and the dead-hero-items-stay-with-body data hook.

Item definitions are passed in as data (`item_lookup: Mapping[str, ItemLike]`,
e.g. `pack.items` from a loaded content pack) -- this module never imports
`content.schemas`/`content.loader`.

"A dead hero's carried items remain with the body unless a specific effect
destroys or steals them" (§13.6) and "single-owner pickup" both need a notion
of *which room object a hero picked an item up from* that is distinct from
the item's content-pack definition id (two heroes might each find their own
copy of `field_suture` on the same floor -- that's not a conflict; two heroes
reaching for the *same ground object* is). `item_instance_id` is that room
object id; `item_id` is always the content-pack definition id.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, MutableMapping, Protocol, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from ..content.schemas import Item


class InventoryError(ValueError):
    pass


class ItemLike(Protocol):
    """Structural shape this module needs from an item -- exactly
    `content.schemas.Item`'s public fields, duck-typed."""

    id: str
    slot_cost: int


@dataclass(frozen=True)
class InventoryState:
    hero_id: str
    carry_slots: int  # 4 + Force (§11.1), plus any background bonus (§backgrounds.bonus_carry_slots)
    items: tuple[str, ...] = ()  # item ids held, pickup order

    def used_slots(self, item_lookup: "dict[str, ItemLike | Item]") -> int:
        return sum(item_lookup[item_id].slot_cost for item_id in self.items)

    def free_slots(self, item_lookup: "dict[str, ItemLike | Item]") -> int:
        return self.carry_slots - self.used_slots(item_lookup)


@dataclass(frozen=True)
class PickupResult:
    accepted: bool
    reason: str | None = None  # populated exactly when accepted is False


def attempt_pickup(
    claims: MutableMapping[str, str],
    *,
    item_instance_id: str,
    item_id: str,
    hero_id: str,
    inventory: InventoryState,
    item_lookup: "dict[str, ItemLike | Item]",
) -> tuple[PickupResult, InventoryState]:
    """Single-owner pickup (§13.6): the first hero to claim a ground item
    instance owns it; a second hero attempting the same instance is rejected
    with a reason rather than silently failing or duplicating the item.
    `claims` is caller-owned mutable state (one entry per contested room
    object) so this stays a pure function of its arguments plus that map."""

    existing_owner = claims.get(item_instance_id)
    if existing_owner is not None and existing_owner != hero_id:
        return PickupResult(accepted=False, reason="already_claimed"), inventory

    if item_id not in item_lookup:
        raise KeyError(f"unknown item id {item_id!r}")
    slot_cost = item_lookup[item_id].slot_cost
    if inventory.free_slots(item_lookup) < slot_cost:
        return PickupResult(accepted=False, reason="insufficient_carry_slots"), inventory

    claims[item_instance_id] = hero_id
    new_inventory = InventoryState(
        hero_id=inventory.hero_id,
        carry_slots=inventory.carry_slots,
        items=inventory.items + (item_id,),
    )
    return PickupResult(accepted=True), new_inventory


def drop_item(inventory: InventoryState, item_id: str) -> InventoryState:
    if item_id not in inventory.items:
        raise InventoryError(f"hero {inventory.hero_id!r} is not carrying {item_id!r}")
    items = list(inventory.items)
    items.remove(item_id)
    return InventoryState(hero_id=inventory.hero_id, carry_slots=inventory.carry_slots, items=tuple(items))


def trade_item(
    giver: InventoryState,
    receiver: InventoryState,
    item_id: str,
    item_lookup: "dict[str, ItemLike | Item]",
) -> tuple[InventoryState, InventoryState]:
    """Direct hero-to-hero trade (only legal when both heroes share a room --
    that adjacency check is the caller's job, this only enforces slots and
    ownership)."""

    if item_id not in giver.items:
        raise InventoryError(f"hero {giver.hero_id!r} is not carrying {item_id!r}")
    if item_id not in item_lookup:
        raise KeyError(f"unknown item id {item_id!r}")
    slot_cost = item_lookup[item_id].slot_cost
    if receiver.free_slots(item_lookup) < slot_cost:
        raise InventoryError(
            f"hero {receiver.hero_id!r} has insufficient carry slots to receive {item_id!r}"
        )
    new_giver = drop_item(giver, item_id)
    new_receiver = InventoryState(
        hero_id=receiver.hero_id, carry_slots=receiver.carry_slots, items=receiver.items + (item_id,)
    )
    return new_giver, new_receiver


@dataclass(frozen=True)
class BodyLoot:
    """§13.6 data hook: what a dead hero's body carries. Wave-4 domain calls
    this at the moment a hero permanently dies and persists the result onto
    the room/body object -- items are never auto-transferred or destroyed by
    this package."""

    hero_id: str
    item_ids: tuple[str, ...]


def hero_died_with_items(inventory: InventoryState) -> BodyLoot:
    return BodyLoot(hero_id=inventory.hero_id, item_ids=inventory.items)
