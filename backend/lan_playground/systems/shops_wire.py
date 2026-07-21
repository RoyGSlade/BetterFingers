"""Wires the pure `backend.lan_playground.shops` package into the domain
reducer (infinite_stacks.md §9.6, §6.2, §16.4-16.6; wave 5, board task #18).
DOMAIN SCHEMA OWNER this wave -- new command/event vocabulary posted to the
collab room 2026-07-19.

Breaching a d8=6 `shop` room (`systems/exploration.py`'s `handle_breach`
calls `build_instantiate_events` below, mirroring `systems/puzzles.py`/
`systems/combat.py`'s own room-family hooks) seeds a real
`shops.models.ShopInstance` from a randomly-chosen core-pack archetype and
persists it on `RoomState.shop`, same pattern as `RoomState.puzzle`/
`.encounter`.

Bridge, don't merge (package owner's explicit warning, docs/
INFINITE_STACKS_SHOPS.md §5): `heroes.inventory.InventoryState` stays the
single owner of "does this hero hold this item"; `HeroState.gold`/
`item_wear`/`identified_item_ids` (new this wave, domain/state.py) are the
hero-side halves of `shops.models.ShopperState`'s economy fields.
`_shopper_state_for`/the per-action appliers below are the only place a
transient `ShopperState` gets built, fed through `shops.services`'s pure
`attempt_*` functions, and torn back down into those HeroState fields plus
(for buy/sell) a real `heroes.inventory` mutation -- a `ShopperState` is never
itself stored on `HeroState`.

`shop_treat` gains the real condition model this wave: `content.schemas.
Condition.treatments` (already authored, §16.4) names which
`HeroState.active_condition_ids` entry (systems/effects.py's new
apply_condition/remove_condition handlers) it clears, and its `effects` are
dispatched through `systems/effects.py` exactly like a puzzle consequence or
a played card -- `shops.services.attempt_treat` only proves the economic
half (a flat, always-a-cost service); this module supplies which condition
is being treated and applies its cure effect.
"""
from __future__ import annotations

import functools

from ..content import schemas as S
from ..domain.commands import Command, CommandError, ErrorCode
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.rng import StacksRNG
from ..domain.state import HeroState, RoomState, RunState
from ..heroes.inventory import InventoryState
from ..shops import content_loader as shop_content_loader
from ..shops import seeding, services
from ..shops.models import ShopArchetype, ShopInstance, ShopperState
from . import effects, turns


@functools.lru_cache(maxsize=1)
def _core_pack() -> S.ContentPack:
    from ..content import loader as content_loader

    return content_loader.load_core_pack()


@functools.lru_cache(maxsize=1)
def _core_shops() -> dict[str, ShopArchetype]:
    return shop_content_loader.load_core_shops()


def _hero(state: RunState, hero_id: str | None) -> HeroState:
    if hero_id is None or hero_id not in state.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown hero {hero_id}")
    return state.heroes[hero_id]


def _require_sheet(hero: HeroState) -> None:
    if hero.sheet is None:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero.hero_id} has not completed character creation")


def _archetype_for(instance: ShopInstance) -> ShopArchetype:
    archetype = _core_shops().get(instance.archetype_id)
    if archetype is None:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"unknown shop archetype {instance.archetype_id!r}")
    return archetype


def _shop_room(state: RunState, hero_id: str | None) -> tuple[HeroState, RoomState, ShopInstance, ShopArchetype]:
    hero = _hero(state, hero_id)
    room = state.map.rooms[hero.room_id]
    if room.shop is None:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"no active shop in {hero.room_id}")
    return hero, room, room.shop, _archetype_for(room.shop)


def _shopper_state_for(hero: HeroState) -> ShopperState:
    held_items: dict[str, int] = {}
    if hero.inventory is not None:
        for item_id in hero.inventory.items:
            held_items[item_id] = held_items.get(item_id, 0) + 1
    return ShopperState(
        gold=hero.gold,
        held_items=held_items,
        wear=dict(hero.item_wear),
        identified=frozenset(hero.identified_item_ids),
    )


def _inventory_to_dict(inv: InventoryState) -> dict:
    return {"hero_id": inv.hero_id, "carry_slots": inv.carry_slots, "items": list(inv.items)}


def _inventory_from_dict(d: dict) -> InventoryState:
    return InventoryState(hero_id=d["hero_id"], carry_slots=d["carry_slots"], items=tuple(d["items"]))


# ---------------------------------------------------------------- instantiate on breach


def build_instantiate_events(
    command: Command,
    state: RunState,
    rng: StacksRNG,
    room_id: str,
    breaching_hero_id: str,
    seq: int,
) -> tuple[Event, ...]:
    """Called from systems/exploration.py's handle_breach exactly when the
    rolled family is `shop`. Two RNG draws (which archetype, then the
    rotating-pool shuffle inside `seeding.instantiate_shop`) -- both fully
    resolved into the event payload (the `hero_created`/`mystery_puzzle_
    instantiated` precedent for an RNG-consuming instantiation step), so
    replay never touches the RNG stream again for this event."""

    archetype_ids = sorted(_core_shops())
    archetype_id = rng.choice(archetype_ids)
    archetype = _core_shops()[archetype_id]
    instance = seeding.instantiate_shop(archetype, rng)

    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.SHOP_INSTANTIATED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=breaching_hero_id,
            room_id=room_id,
            payload={"room_id": room_id, "archetype_id": archetype_id, "stock": dict(instance.stock)},
        ),
    )


def apply_shop_instantiated(state: RunState, event: Event) -> RunState:
    room = state.map.rooms[event.payload["room_id"]]
    room.shop = ShopInstance(archetype_id=event.payload["archetype_id"], stock=dict(event.payload["stock"]))
    return state


# ---------------------------------------------------------------- shared transaction helpers


def _energy_event(command: Command, state: RunState, hero: HeroState, seq: int, action: str) -> Event:
    return Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero.hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["shop_action" if action != "treat" else "treat_light_condition"], "action": action},
    )


def _rejected_event(
    command: Command, state: RunState, hero: HeroState, seq: int, *, action: str, reason: str, item_id: str | None = None
) -> Event:
    return Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.SHOP_TRANSACTION_REJECTED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero.hero_id,
        room_id=hero.room_id,
        payload={"action": action, "reason": reason, "item_id": item_id},
    )


def _item_id_payload(payload: dict) -> str:
    item_id = payload.get("item_id")
    if not isinstance(item_id, str):
        raise CommandError(ErrorCode.SCHEMA_ERROR, "item_id must be a string")
    return item_id


# ---------------------------------------------------------------- shop_buy


def validate_shop_buy(state: RunState, hero_id: str | None, payload: dict):
    hero, room, instance, archetype = _shop_room(state, hero_id)
    _require_sheet(hero)
    item_id = _item_id_payload(payload)
    turns.require_energy(state, hero_id, "shop_action")
    return hero, room, instance, archetype, item_id


def handle_shop_buy(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    hero, room, instance, archetype, item_id = validate_shop_buy(state, hero_id, command.payload)
    pack = _core_pack()
    shopper = _shopper_state_for(hero)
    result, new_instance, new_shopper = services.attempt_buy(archetype, instance, shopper, item_id)

    events: list[Event] = [_energy_event(command, state, hero, seq, "buy")]

    if result.accepted:
        item = pack.items.get(item_id)
        slot_cost = item.slot_cost if item is not None else 1
        if hero.inventory is None or hero.inventory.free_slots(pack.items) < slot_cost:
            events.append(
                _rejected_event(command, state, hero, seq + 1, action="buy", reason="insufficient_carry_slots", item_id=item_id)
            )
            return tuple(events)
        new_inventory = InventoryState(
            hero_id=hero.inventory.hero_id, carry_slots=hero.inventory.carry_slots, items=hero.inventory.items + (item_id,)
        )
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + 1),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.SHOP_ITEM_BOUGHT,
                visibility=Visibility.PUBLIC,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={
                    "item_id": item_id,
                    "gold_delta": result.gold_delta,
                    "new_gold": new_shopper.gold,
                    "new_stock": dict(new_instance.stock),
                    "inventory": _inventory_to_dict(new_inventory),
                },
            )
        )
    else:
        events.append(_rejected_event(command, state, hero, seq + 1, action="buy", reason=result.reason, item_id=item_id))
    return tuple(events)


def apply_shop_item_bought(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.gold = event.payload["new_gold"]
    hero.inventory = _inventory_from_dict(event.payload["inventory"])
    hero.carried_item_ids = tuple(hero.inventory.items)
    room = state.map.rooms[hero.room_id]
    room.shop = ShopInstance(archetype_id=room.shop.archetype_id, stock=dict(event.payload["new_stock"]))
    return state


# ---------------------------------------------------------------- shop_sell


def validate_shop_sell(state: RunState, hero_id: str | None, payload: dict):
    hero, room, instance, archetype = _shop_room(state, hero_id)
    _require_sheet(hero)
    item_id = _item_id_payload(payload)
    turns.require_energy(state, hero_id, "shop_action")
    return hero, room, instance, archetype, item_id


def handle_shop_sell(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    hero, room, instance, archetype, item_id = validate_shop_sell(state, hero_id, command.payload)
    shopper = _shopper_state_for(hero)
    result, new_instance, new_shopper = services.attempt_sell(archetype, instance, shopper, item_id)

    events: list[Event] = [_energy_event(command, state, hero, seq, "sell")]
    if result.accepted:
        items = list(hero.inventory.items)
        items.remove(item_id)
        new_inventory = InventoryState(hero_id=hero.inventory.hero_id, carry_slots=hero.inventory.carry_slots, items=tuple(items))
        new_wear = dict(hero.item_wear)
        new_wear.pop(item_id, None)
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + 1),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.SHOP_ITEM_SOLD,
                visibility=Visibility.PUBLIC,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={
                    "item_id": item_id,
                    "gold_delta": result.gold_delta,
                    "new_gold": new_shopper.gold,
                    "new_stock": dict(new_instance.stock),
                    "inventory": _inventory_to_dict(new_inventory),
                    "item_wear": dict(sorted(new_wear.items())),
                },
            )
        )
    else:
        events.append(_rejected_event(command, state, hero, seq + 1, action="sell", reason=result.reason, item_id=item_id))
    return tuple(events)


def apply_shop_item_sold(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.gold = event.payload["new_gold"]
    hero.inventory = _inventory_from_dict(event.payload["inventory"])
    hero.carried_item_ids = tuple(hero.inventory.items)
    hero.item_wear = dict(event.payload["item_wear"])
    room = state.map.rooms[hero.room_id]
    room.shop = ShopInstance(archetype_id=room.shop.archetype_id, stock=dict(event.payload["new_stock"]))
    return state


# ---------------------------------------------------------------- shop_repair


def validate_shop_repair(state: RunState, hero_id: str | None, payload: dict):
    hero, room, instance, archetype = _shop_room(state, hero_id)
    _require_sheet(hero)
    item_id = _item_id_payload(payload)
    turns.require_energy(state, hero_id, "shop_action")
    return hero, room, instance, archetype, item_id


def handle_shop_repair(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    hero, room, instance, archetype, item_id = validate_shop_repair(state, hero_id, command.payload)
    shopper = _shopper_state_for(hero)
    result, new_instance, new_shopper = services.attempt_repair(archetype, instance, shopper, item_id)

    events: list[Event] = [_energy_event(command, state, hero, seq, "repair")]
    if result.accepted:
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + 1),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.SHOP_ITEM_REPAIRED,
                visibility=Visibility.PUBLIC,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={
                    "item_id": item_id,
                    "gold_delta": result.gold_delta,
                    "new_gold": new_shopper.gold,
                    "item_wear": dict(sorted(new_shopper.wear.items())),
                },
            )
        )
    else:
        events.append(_rejected_event(command, state, hero, seq + 1, action="repair", reason=result.reason, item_id=item_id))
    return tuple(events)


def apply_shop_item_repaired(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.gold = event.payload["new_gold"]
    hero.item_wear = dict(event.payload["item_wear"])
    return state


# ---------------------------------------------------------------- shop_identify


def validate_shop_identify(state: RunState, hero_id: str | None, payload: dict):
    hero, room, instance, archetype = _shop_room(state, hero_id)
    _require_sheet(hero)
    item_id = _item_id_payload(payload)
    turns.require_energy(state, hero_id, "shop_action")
    return hero, room, instance, archetype, item_id


def handle_shop_identify(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    hero, room, instance, archetype, item_id = validate_shop_identify(state, hero_id, command.payload)
    shopper = _shopper_state_for(hero)
    result, new_instance, new_shopper = services.attempt_identify(archetype, instance, shopper, item_id)

    events: list[Event] = [_energy_event(command, state, hero, seq, "identify")]
    if result.accepted:
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + 1),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.SHOP_ITEM_IDENTIFIED,
                visibility=Visibility.PUBLIC,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={
                    "item_id": item_id,
                    "gold_delta": result.gold_delta,
                    "new_gold": new_shopper.gold,
                    "identified_item_ids": sorted(new_shopper.identified),
                },
            )
        )
    else:
        events.append(_rejected_event(command, state, hero, seq + 1, action="identify", reason=result.reason, item_id=item_id))
    return tuple(events)


def apply_shop_item_identified(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.gold = event.payload["new_gold"]
    hero.identified_item_ids = tuple(event.payload["identified_item_ids"])
    return state


# ---------------------------------------------------------------- shop_treat


def validate_shop_treat(state: RunState, hero_id: str | None, payload: dict):
    hero, room, instance, archetype = _shop_room(state, hero_id)
    _require_sheet(hero)
    condition_id = payload.get("condition_id")
    if condition_id not in hero.active_condition_ids:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} does not have condition {condition_id!r}")
    condition = _core_pack().conditions.get(condition_id)
    if condition is None:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown condition {condition_id!r}")
    treatment_id = payload.get("treatment_id")
    treatment = next((t for t in condition.treatments if t.id == treatment_id), None)
    if treatment is None:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"condition {condition_id!r} has no treatment {treatment_id!r}")
    turns.require_energy(state, hero_id, "treat_light_condition")
    return hero, room, instance, archetype, condition, treatment


def handle_shop_treat(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    hero, room, instance, archetype, condition, treatment = validate_shop_treat(state, hero_id, command.payload)
    shopper = _shopper_state_for(hero)
    result, new_instance, new_shopper = services.attempt_treat(archetype, instance, shopper)

    events: list[Event] = [_energy_event(command, state, hero, seq, "treat")]
    if not result.accepted:
        events.append(
            _rejected_event(command, state, hero, seq + 1, action="treat", reason=result.reason, item_id=None)
        )
        return tuple(events)

    events.append(
        Event(
            event_id=make_event_id(state.world_round, seq + 1),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.SHOP_CONDITION_TREATED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
            payload={
                "condition_id": condition.id,
                "treatment_id": treatment.id,
                "gold_delta": result.gold_delta,
                "new_gold": new_shopper.gold,
            },
        )
    )
    effect_ir = S.compile_effects(list(treatment.effects))
    events.extend(
        effects.dispatch(
            effect_ir, command=command, state=state, rng=rng, seq=seq + len(events), actor_hero_id=hero_id, room_id=hero.room_id
        )
    )
    return tuple(events)


def apply_shop_condition_treated(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.gold = event.payload["new_gold"]
    return state


# ---------------------------------------------------------------- rejection (shared applier)


def apply_shop_transaction_rejected(state: RunState, event: Event) -> RunState:
    return state


# ---------------------------------------------------------------- legal actions


def legal_action_names(state: RunState, hero_id: str) -> list[str]:
    hero = state.heroes.get(hero_id)
    if hero is None or hero.sheet is None or state.map is None:
        return []
    room = state.map.rooms.get(hero.room_id)
    if room is None or room.shop is None:
        return []
    archetype = _core_shops().get(room.shop.archetype_id)
    if archetype is None:
        return []
    actions = []
    for service in ("buy", "sell", "repair", "identify", "treat"):
        if any(s.value == service for s in archetype.services):
            actions.append(f"shop_{service}")
    return actions


EVENT_APPLIERS = {
    EventType.SHOP_INSTANTIATED: apply_shop_instantiated,
    EventType.SHOP_ITEM_BOUGHT: apply_shop_item_bought,
    EventType.SHOP_ITEM_SOLD: apply_shop_item_sold,
    EventType.SHOP_ITEM_REPAIRED: apply_shop_item_repaired,
    EventType.SHOP_ITEM_IDENTIFIED: apply_shop_item_identified,
    EventType.SHOP_CONDITION_TREATED: apply_shop_condition_treated,
    EventType.SHOP_TRANSACTION_REJECTED: apply_shop_transaction_rejected,
}
