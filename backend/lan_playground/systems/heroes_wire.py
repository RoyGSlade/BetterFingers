"""Wires the pure `backend.lan_playground.heroes` package into the domain
reducer (infinite_stacks.md §11, §13; docs/INFINITE_STACKS_HEROES.md).
DOMAIN SCHEMA OWNER this wave (board task #13) -- new command/event
vocabulary posted to the collab room 2026-07-19.

Mirrors systems/combat.py's discipline: heroes/** stays pure and is never
edited here. Every RNG draw happens inside the handle_*() functions below
(the handle() contract, contracts doc §3); appliers only replay
already-decided results. Two exceptions need the *full* resolved object
serialized into the event payload rather than being cheaply re-derived,
because they draw from the shared RNG stream and cannot be replayed
independent of it: `heroes.deck.build_starting_deck` (shuffles the deck) and
`heroes.deck.safe_rest_reshuffle` (reshuffles it). Every other card/deck
operation here (`draw`, `play_card`) is a pure deterministic slice with no
RNG draw of its own, so its applier just replays the same heroes/** call.

`carried_item_ids` on `HeroState` is kept as a synced mirror of
`inventory.items` on every mutation here so `systems/combat.py`'s existing
body-loot-at-permanent-death code (which reads/clears `carried_item_ids`
directly) keeps working completely unchanged -- no cross-lane edit needed.
`recover_body_loot` below is the wave-4 "ally recovers a dead hero's items"
half of §13.6 this module owns.
"""
from __future__ import annotations

import functools
from typing import Any

from ..combat.models import Attributes as CombatAttributes
from ..combat.models import Weapon as CombatWeapon
from ..content import loader as content_loader
from ..content import schemas as S
from ..domain.commands import Command, CommandError, ErrorCode
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.rng import StacksRNG
from ..domain.state import HeroState, RunState
from ..heroes import backgrounds as heroes_backgrounds
from ..heroes import cards as heroes_cards
from ..heroes import creation as heroes_creation
from ..heroes import deck as heroes_deck
from ..heroes import inventory as heroes_inventory
from . import checks, effects, turns

_ATTRIBUTE_NAMES = heroes_creation.ATTRIBUTE_NAMES


@functools.lru_cache(maxsize=1)
def _core_pack():
    return content_loader.load_core_pack()


def _hero(state: RunState, hero_id: str | None) -> HeroState:
    if hero_id is None or hero_id not in state.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown hero {hero_id}")
    return state.heroes[hero_id]


def _require_sheet(hero: HeroState) -> heroes_creation.HeroSheet:
    if hero.sheet is None:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero.hero_id} has not completed character creation")
    return hero.sheet


# ---------------------------------------------------------------- (de)serialization

def _sheet_to_dict(sheet: heroes_creation.HeroSheet) -> dict:
    return {
        "hero_id": sheet.hero_id,
        "name": sheet.name,
        "background_id": sheet.background_id,
        "dice": list(sheet.dice.values),
        "attributes": {n: sheet.attributes.get(n) for n in _ATTRIBUTE_NAMES},
        "skills": dict(sheet.skills),
        "starting_item_ids": list(sheet.starting_item_ids),
    }


def _sheet_from_dict(d: dict) -> heroes_creation.HeroSheet:
    return heroes_creation.HeroSheet(
        hero_id=d["hero_id"],
        name=d["name"],
        background_id=d["background_id"],
        dice=heroes_creation.DiceRoll(values=tuple(d["dice"])),
        attributes=heroes_creation.Attributes(**d["attributes"]),
        skills=dict(d["skills"]),
        starting_item_ids=tuple(d["starting_item_ids"]),
    )


def _deck_to_dict(deck_state: heroes_deck.DeckState) -> dict:
    return {
        "hero_id": deck_state.hero_id,
        "deck": list(deck_state.deck),
        "hand": list(deck_state.hand),
        "discard": list(deck_state.discard),
        "exhausted": list(deck_state.exhausted),
    }


def _deck_from_dict(d: dict) -> heroes_deck.DeckState:
    return heroes_deck.DeckState(
        hero_id=d["hero_id"],
        deck=tuple(d["deck"]),
        hand=tuple(d["hand"]),
        discard=tuple(d["discard"]),
        exhausted=tuple(d["exhausted"]),
    )


def _inventory_to_dict(inv: heroes_inventory.InventoryState) -> dict:
    return {"hero_id": inv.hero_id, "carry_slots": inv.carry_slots, "items": list(inv.items)}


def _inventory_from_dict(d: dict) -> heroes_inventory.InventoryState:
    return heroes_inventory.InventoryState(hero_id=d["hero_id"], carry_slots=d["carry_slots"], items=tuple(d["items"]))


def _charge_to_dict(charge: heroes_backgrounds.SignatureCharge | None) -> dict | None:
    if charge is None:
        return None
    return {
        "ability_id": charge.ability_id,
        "frequency": charge.frequency,
        "charges_remaining": charge.charges_remaining,
        "max_charges": charge.max_charges,
    }


def _charge_from_dict(d: dict | None) -> heroes_backgrounds.SignatureCharge | None:
    if d is None:
        return None
    return heroes_backgrounds.SignatureCharge(**d)


def _sync_carried_item_ids(hero: HeroState) -> None:
    hero.carried_item_ids = tuple(hero.inventory.items) if hero.inventory is not None else ()


# ---------------------------------------------------------------- combat equipment seam

def resolve_hero_combat_equipment(hero: HeroState) -> dict[str, Any]:
    """Resolve real Attributes/skills/Weapon/equipment bonuses from a hero's
    sheet + inventory, shaped as kwargs for
    `systems/combat_wire.hero_combatant_from_state` (equipment-modifier seam
    published by stacks-combat-depth 2026-07-19). Every numeric value here
    comes from real `HeroState.sheet`/`inventory` + content-pack item data --
    never a raw wire number (wave-3 director ruling). Returns `{}` (today's
    flat zero-modifier defaults) if the hero has not completed character
    creation yet, so this is a safe no-op call for pre-wave-4 heroes."""

    if hero.sheet is None:
        return {}
    pack = _core_pack()
    sheet = hero.sheet
    attributes = CombatAttributes(**{n: sheet.attributes.get(n) for n in _ATTRIBUTE_NAMES})
    weapon = CombatWeapon()
    equipment_defense_bonus = 0
    equipment_accuracy_bonus = 0
    equipment_damage_bonus = 0
    carried = hero.inventory.items if hero.inventory is not None else ()
    for item_id in carried:
        item = pack.items.get(item_id)
        if item is None:
            continue
        equipment_defense_bonus += item.passive_defense_bonus
        if item.weapon_die_faces is not None:
            weapon = CombatWeapon(
                die_faces=item.weapon_die_faces,
                damage_bonus=item.weapon_damage_bonus,
                accuracy_bonus=item.weapon_accuracy_bonus,
            )
    return {
        "attributes": attributes,
        "skills": dict(sheet.skills),
        "weapon": weapon,
        "equipment_defense_bonus": equipment_defense_bonus,
        "equipment_accuracy_bonus": equipment_accuracy_bonus,
        "equipment_damage_bonus": equipment_damage_bonus,
    }


# ---------------------------------------------------------------- signature charge boundaries

def build_room_boundary_refresh_events(
    state: RunState, hero_id: str, room_id: str, seq: int, command_id: str
) -> tuple[Event, ...]:
    """§11.3 once_per_room signature abilities refresh at a room boundary.
    Called by systems/exploration.py's handle_breach for the breaching hero
    (that module owns the room-boundary moment; this module owns what
    happens to a signature charge at it). `room_id` is the room just
    breached into -- `state` is the pre-event snapshot handle() always
    receives, so `state.heroes[hero_id].room_id` is still the old room."""

    hero = state.heroes.get(hero_id)
    if hero is None or hero.signature_charge is None or hero.signature_charge.frequency != "once_per_room":
        return ()
    new_charge = hero.signature_charge.refreshed()
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command_id,
            type=EventType.SIGNATURE_CHARGE_REFRESHED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=hero_id,
            room_id=room_id,
            payload={"boundary": "room", "signature_charge": _charge_to_dict(new_charge)},
        ),
    )


def build_fight_boundary_refresh_events(
    state: RunState, hero_id: str, seq: int, command_id: str
) -> tuple[Event, ...]:
    """§11.3 once_per_fight signature abilities refresh at a fight boundary.
    Not called by anything in this wave's engine yet -- published for
    stacks-combat-depth to call from their encounter-start handler
    (systems/combat.py) and fold into their own returned event tuple,
    exactly the "post the exact hook you need" pattern for turns.py-adjacent
    boundaries this wave's board task calls for."""

    hero = state.heroes.get(hero_id)
    if hero is None or hero.signature_charge is None or hero.signature_charge.frequency != "once_per_fight":
        return ()
    new_charge = hero.signature_charge.refreshed()
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command_id,
            type=EventType.SIGNATURE_CHARGE_REFRESHED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
            payload={"boundary": "fight", "signature_charge": _charge_to_dict(new_charge)},
        ),
    )


def apply_signature_charge_refreshed(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.signature_charge = _charge_from_dict(event.payload["signature_charge"])
    return state


# ---------------------------------------------------------------- roll_attribute_dice

def validate_roll_attribute_dice(state: RunState, hero_id: str | None, payload: dict) -> None:
    hero = _hero(state, hero_id)
    if hero.sheet is not None:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} already completed character creation")


def handle_roll_attribute_dice(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    validate_roll_attribute_dice(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    dice = heroes_creation.roll_attribute_dice(rng)
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.ATTRIBUTE_DICE_ROLLED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
            payload={"dice": list(dice.values)},
        ),
    )


def apply_attribute_dice_rolled(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.pending_dice = tuple(event.payload["dice"])
    return state


# ---------------------------------------------------------------- create_hero

def validate_create_hero(state: RunState, hero_id: str | None, payload: dict) -> tuple:
    hero = _hero(state, hero_id)
    if hero.sheet is not None:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} already completed character creation")
    if hero.pending_dice is None:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} must roll_attribute_dice before create_hero")

    pack = _core_pack()
    background_id = payload.get("background_id")
    if background_id not in pack.backgrounds:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown background {background_id!r}")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CommandError(ErrorCode.SCHEMA_ERROR, "name must be a non-empty string")
    assignment = payload.get("attribute_assignment")
    if not isinstance(assignment, dict):
        raise CommandError(ErrorCode.SCHEMA_ERROR, "attribute_assignment must be a mapping")
    general_card_ids = payload.get("general_card_ids")
    if not isinstance(general_card_ids, (list, tuple)):
        raise CommandError(ErrorCode.SCHEMA_ERROR, "general_card_ids must be a list")
    persona_card_id = payload.get("persona_card_id")
    if not isinstance(persona_card_id, str):
        raise CommandError(ErrorCode.SCHEMA_ERROR, "persona_card_id must be a string")
    equipment_card_ids = payload.get("equipment_card_ids") or []
    if not isinstance(equipment_card_ids, (list, tuple)):
        raise CommandError(ErrorCode.SCHEMA_ERROR, "equipment_card_ids must be a list")

    return pack, background_id, name, assignment, list(general_card_ids), persona_card_id, list(equipment_card_ids)


def handle_create_hero(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    pack, background_id, name, assignment, general_card_ids, persona_card_id, equipment_card_ids = (
        validate_create_hero(state, hero_id, command.payload)
    )
    hero = state.heroes[hero_id]
    background = pack.backgrounds[background_id]

    dice = heroes_creation.DiceRoll(values=hero.pending_dice)
    try:
        attrs = heroes_creation.assign_attributes(dice, assignment)
    except heroes_creation.CreationError as exc:
        raise CommandError(ErrorCode.SCHEMA_ERROR, str(exc)) from exc
    attrs = heroes_backgrounds.apply_background_bonus(attrs, background)
    skills = heroes_backgrounds.starting_skill_ranks(background)
    starting_items = heroes_backgrounds.starting_item_ids(background)

    sheet = heroes_creation.HeroSheet(
        hero_id=hero_id,
        name=name,
        background_id=background_id,
        dice=dice,
        attributes=attrs,
        skills=skills,
        starting_item_ids=starting_items,
    )

    background_card_ids = sorted(c.id for c in pack.cards.values() if c.source == background_id)
    try:
        deck_state = heroes_deck.build_starting_deck(
            hero_id,
            background_card_ids=background_card_ids,
            general_card_ids=general_card_ids,
            persona_card_id=persona_card_id,
            equipment_card_ids=equipment_card_ids,
            card_lookup=pack.cards,
            rng=rng,
        )
    except (heroes_deck.DeckError, heroes_cards.NonLiveEffectOpError, KeyError) as exc:
        raise CommandError(ErrorCode.SCHEMA_ERROR, str(exc)) from exc
    deck_state = heroes_deck.draw(deck_state, 4)

    carry_slots = sheet.derived.carry_slots + heroes_backgrounds.bonus_carry_slots(background)
    inventory = heroes_inventory.InventoryState(hero_id=hero_id, carry_slots=carry_slots, items=starting_items)

    charge = heroes_backgrounds.initial_signature_charge(background)

    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.HERO_CREATED,
            visibility=Visibility.PUBLIC,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
            payload={
                "sheet": _sheet_to_dict(sheet),
                "deck": _deck_to_dict(deck_state),
                "inventory": _inventory_to_dict(inventory),
                "signature_charge": _charge_to_dict(charge),
                "max_hp": sheet.derived.max_hp,
                "defense": sheet.derived.defense,
            },
        ),
    )


def apply_hero_created(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.sheet = _sheet_from_dict(event.payload["sheet"])
    hero.deck = _deck_from_dict(event.payload["deck"])
    hero.inventory = _inventory_from_dict(event.payload["inventory"])
    hero.signature_charge = _charge_from_dict(event.payload["signature_charge"])
    hero.pending_dice = None
    hero.max_hp = event.payload["max_hp"]
    hero.hp = event.payload["max_hp"]
    _sync_carried_item_ids(hero)
    return state


# ---------------------------------------------------------------- draw_cards

def validate_draw_cards(state: RunState, hero_id: str | None, payload: dict) -> int:
    hero = _hero(state, hero_id)
    _require_sheet(hero)
    count = payload.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise CommandError(ErrorCode.SCHEMA_ERROR, "count must be a non-negative integer")
    return count


def handle_draw_cards(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    count = validate_draw_cards(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    new_deck = heroes_deck.draw(hero.deck, count)
    drawn = list(new_deck.hand[len(hero.deck.hand):])
    return (
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.CARD_DRAWN,
            visibility=Visibility.PRIVATE,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
            payload={"viewer_hero_id": hero_id, "count": count, "card_ids": drawn},
        ),
    )


def apply_card_drawn(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.deck = heroes_deck.draw(hero.deck, event.payload["count"])
    return state


# ---------------------------------------------------------------- play_card

def validate_play_card(state: RunState, hero_id: str | None, payload: dict) -> S.Card:
    hero = _hero(state, hero_id)
    _require_sheet(hero)
    card_id = payload.get("card_id")
    if hero.deck is None or card_id not in hero.deck.hand:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"card {card_id!r} is not in {hero_id}'s hand")
    pack = _core_pack()
    if card_id not in pack.cards:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown card {card_id!r}")
    return pack.cards[card_id]


def handle_play_card(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    card = validate_play_card(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    sheet = hero.sheet

    check_receipt: dict | None = None
    if card.check is not None:
        attribute_score = sheet.attributes.get(card.check.attribute)
        skill_rank = sheet.skills.get(card.check.skill, 0)
        result = checks.perform_check(
            rng,
            attribute_score=attribute_score,
            skill_rank=skill_rank,
            dc=card.check.dc,
            advantage_sources=command.payload.get("advantage_sources", 0),
            disadvantage_sources=command.payload.get("disadvantage_sources", 0),
        )
        outcome_effects = {
            checks.Outcome.STRONG_SUCCESS: card.check.outcomes.strong_success,
            checks.Outcome.CLEAN_SUCCESS: card.check.outcomes.success,
            checks.Outcome.COST_PROGRESS: card.check.outcomes.cost,
            checks.Outcome.SETBACK: card.check.outcomes.setback,
        }[result.outcome]
        effects_ir = S.compile_effects(list(outcome_effects))
        check_receipt = {
            "die_rolls": list(result.die_rolls),
            "chosen_die": result.chosen_die,
            "attribute_score": result.attribute_score,
            "skill_rank": result.skill_rank,
            "total": result.total,
            "dc": result.dc,
            "margin": result.margin,
            "outcome": result.outcome.value,
            "natural_20": result.natural_20,
            "natural_1": result.natural_1,
            "attribute": card.check.attribute,
            "skill": card.check.skill,
        }
    else:
        effects_ir = S.compile_effects(list(card.base_effects))

    play_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.CARD_PLAYED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={
            "card_id": card.id,
            "target_hero_id": command.payload.get("target_hero_id"),
            "target_enemy_id": command.payload.get("target_enemy_id"),
            "check_receipt": check_receipt,
            "end_state": card.end_state.value,
        },
    )
    events: list[Event] = [play_event]
    events.extend(
        effects.dispatch(
            effects_ir,
            command=command,
            state=state,
            rng=rng,
            seq=seq + len(events),
            actor_hero_id=hero_id,
            room_id=hero.room_id,
        )
    )
    return tuple(events)


def apply_card_played(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    pack = _core_pack()
    hero.deck = heroes_deck.play_card(hero.deck, event.payload["card_id"], pack.cards)
    return state


# ---------------------------------------------------------------- safe_rest

def validate_safe_rest(state: RunState, hero_id: str | None, payload: dict) -> None:
    hero = _hero(state, hero_id)
    _require_sheet(hero)


def handle_safe_rest(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    validate_safe_rest(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    new_deck = heroes_deck.safe_rest_reshuffle(hero.deck, rng)

    events: list[Event] = [
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=EventType.DECK_RESHUFFLED,
            visibility=Visibility.PRIVATE,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
            payload={"viewer_hero_id": hero_id, "deck": _deck_to_dict(new_deck)},
        )
    ]
    if hero.signature_charge is not None and hero.signature_charge.frequency == "once_per_floor":
        new_charge = hero.signature_charge.refreshed()
        events.append(
            Event(
                event_id=make_event_id(state.world_round, seq + len(events)),
                run_id=state.run_id,
                world_round=state.world_round,
                caused_by=command.command_id,
                type=EventType.SIGNATURE_CHARGE_REFRESHED,
                visibility=Visibility.PUBLIC,
                actor_hero_id=hero_id,
                room_id=hero.room_id,
                payload={"boundary": "safe_rest", "signature_charge": _charge_to_dict(new_charge)},
            )
        )
    return tuple(events)


def apply_deck_reshuffled(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.deck = _deck_from_dict(event.payload["deck"])
    return state


# ---------------------------------------------------------------- pickup_item

def validate_pickup_item(state: RunState, hero_id: str | None, payload: dict) -> str:
    hero = _hero(state, hero_id)
    _require_sheet(hero)
    room = state.map.rooms[hero.room_id]
    item_instance_id = payload.get("item_instance_id")
    if item_instance_id not in room.ground_items:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"no ground item {item_instance_id!r} in {hero.room_id}")
    turns.require_energy(state, hero_id, "inspect")
    return item_instance_id


def handle_pickup_item(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    item_instance_id = validate_pickup_item(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    room = state.map.rooms[hero.room_id]
    item_id = room.ground_items[item_instance_id]
    pack = _core_pack()

    claims_copy = dict(room.item_claims)
    result, new_inventory = heroes_inventory.attempt_pickup(
        claims_copy,
        item_instance_id=item_instance_id,
        item_id=item_id,
        hero_id=hero_id,
        inventory=hero.inventory,
        item_lookup=pack.items,
    )

    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["inspect"], "action": "pickup_item"},
    )
    pickup_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ITEM_PICKED_UP if result.accepted else EventType.ITEM_PICKUP_REJECTED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={
            "item_instance_id": item_instance_id,
            "item_id": item_id,
            "hero_id": hero_id,
            "accepted": result.accepted,
            "reason": result.reason,
            "claims": dict(claims_copy),
            "inventory": _inventory_to_dict(new_inventory) if result.accepted else None,
        },
    )
    return (energy_event, pickup_event)


def apply_item_picked_up(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    room = state.map.rooms[hero.room_id]
    room.item_claims = dict(event.payload["claims"])
    hero.inventory = _inventory_from_dict(event.payload["inventory"])
    _sync_carried_item_ids(hero)
    room.ground_items.pop(event.payload["item_instance_id"], None)
    return state


def apply_item_pickup_rejected(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    room = state.map.rooms[hero.room_id]
    room.item_claims = dict(event.payload["claims"])
    return state


# ---------------------------------------------------------------- drop_item

def validate_drop_item(state: RunState, hero_id: str | None, payload: dict) -> str:
    hero = _hero(state, hero_id)
    _require_sheet(hero)
    item_id = payload.get("item_id")
    if hero.inventory is None or item_id not in hero.inventory.items:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} is not carrying {item_id!r}")
    turns.require_energy(state, hero_id, "inspect")
    return item_id


def handle_drop_item(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    item_id = validate_drop_item(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    new_inventory = heroes_inventory.drop_item(hero.inventory, item_id)
    item_instance_id = command.payload.get("item_instance_id") or f"{command.command_id}:{item_id}"

    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["inspect"], "action": "drop_item"},
    )
    drop_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ITEM_DROPPED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={
            "item_id": item_id,
            "item_instance_id": item_instance_id,
            "inventory": _inventory_to_dict(new_inventory),
        },
    )
    return (energy_event, drop_event)


def apply_item_dropped(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.inventory = _inventory_from_dict(event.payload["inventory"])
    _sync_carried_item_ids(hero)
    room = state.map.rooms[hero.room_id]
    room.ground_items[event.payload["item_instance_id"]] = event.payload["item_id"]
    return state


# ---------------------------------------------------------------- trade_item

def validate_trade_item(state: RunState, hero_id: str | None, payload: dict) -> tuple[HeroState, str]:
    hero = _hero(state, hero_id)
    _require_sheet(hero)
    to_hero_id = payload.get("to_hero_id")
    receiver = _hero(state, to_hero_id)
    _require_sheet(receiver)
    if receiver.room_id != hero.room_id:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "trade requires both heroes in the same room")
    item_id = payload.get("item_id")
    if hero.inventory is None or item_id not in hero.inventory.items:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} is not carrying {item_id!r}")
    turns.require_energy(state, hero_id, "inspect")
    return receiver, item_id


def handle_trade_item(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    receiver, item_id = validate_trade_item(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    pack = _core_pack()
    try:
        new_giver, new_receiver = heroes_inventory.trade_item(hero.inventory, receiver.inventory, item_id, pack.items)
    except heroes_inventory.InventoryError as exc:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, str(exc)) from exc

    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["inspect"], "action": "trade_item"},
    )
    trade_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ITEM_TRADED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={
            "item_id": item_id,
            "from_hero_id": hero_id,
            "to_hero_id": receiver.hero_id,
            "giver_inventory": _inventory_to_dict(new_giver),
            "receiver_inventory": _inventory_to_dict(new_receiver),
        },
    )
    return (energy_event, trade_event)


def apply_item_traded(state: RunState, event: Event) -> RunState:
    giver = state.heroes[event.payload["from_hero_id"]]
    receiver = state.heroes[event.payload["to_hero_id"]]
    giver.inventory = _inventory_from_dict(event.payload["giver_inventory"])
    receiver.inventory = _inventory_from_dict(event.payload["receiver_inventory"])
    _sync_carried_item_ids(giver)
    _sync_carried_item_ids(receiver)
    return state


# ---------------------------------------------------------------- recover_body_loot

def validate_recover_body_loot(state: RunState, hero_id: str | None, payload: dict) -> tuple[str, list[str]]:
    hero = _hero(state, hero_id)
    _require_sheet(hero)
    room = state.map.rooms[hero.room_id]
    dead_hero_id = payload.get("dead_hero_id")
    available = room.body_item_ids.get(dead_hero_id, ())
    if not available:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"no recoverable body loot for {dead_hero_id!r} in {hero.room_id}")
    requested = payload.get("item_ids")
    if requested is None:
        item_ids = list(available)
    else:
        item_ids = list(requested)
        for iid in item_ids:
            if iid not in available:
                raise CommandError(ErrorCode.UNKNOWN_TARGET, f"{iid!r} is not on {dead_hero_id}'s body")
    turns.require_energy(state, hero_id, "inspect")
    return dead_hero_id, item_ids


def handle_recover_body_loot(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    dead_hero_id, item_ids = validate_recover_body_loot(state, hero_id, command.payload)
    hero = state.heroes[hero_id]
    pack = _core_pack()
    inventory = hero.inventory
    recovered: list[str] = []
    for item_id in item_ids:
        cost = pack.items[item_id].slot_cost if item_id in pack.items else 1
        if inventory.free_slots(pack.items) < cost:
            break
        inventory = heroes_inventory.InventoryState(
            hero_id=inventory.hero_id, carry_slots=inventory.carry_slots, items=inventory.items + (item_id,)
        )
        recovered.append(item_id)

    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["inspect"], "action": "recover_body_loot"},
    )
    recover_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.BODY_LOOT_RECOVERED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={
            "dead_hero_id": dead_hero_id,
            "item_ids": recovered,
            "inventory": _inventory_to_dict(inventory),
        },
    )
    return (energy_event, recover_event)


def apply_body_loot_recovered(state: RunState, event: Event) -> RunState:
    hero = state.heroes[event.actor_hero_id]
    hero.inventory = _inventory_from_dict(event.payload["inventory"])
    _sync_carried_item_ids(hero)
    room = state.map.rooms[hero.room_id]
    dead_hero_id = event.payload["dead_hero_id"]
    recovered = set(event.payload["item_ids"])
    remaining = tuple(iid for iid in room.body_item_ids.get(dead_hero_id, ()) if iid not in recovered)
    if remaining:
        room.body_item_ids[dead_hero_id] = remaining
    else:
        room.body_item_ids.pop(dead_hero_id, None)
    return state


# ---------------------------------------------------------------- legal actions


def legal_action_names(state: RunState, hero_id: str) -> list[str]:
    hero = state.heroes.get(hero_id)
    if hero is None:
        return []
    if hero.sheet is None:
        return ["create_hero"] if hero.pending_dice is not None else ["roll_attribute_dice"]

    actions: list[str] = ["safe_rest"]
    if hero.deck is not None and hero.deck.hand:
        actions.append("play_card")
    if hero.deck is not None and hero.deck.deck:
        actions.append("draw_cards")
    if state.map is not None:
        room = state.map.rooms.get(hero.room_id)
        if room is not None:
            actions.extend(f"pickup_item:{iid}" for iid in sorted(room.ground_items))
            actions.extend(
                f"recover_body_loot:{dead_id}" for dead_id, items in room.body_item_ids.items() if items
            )
    if hero.inventory is not None and hero.inventory.items:
        actions.append("drop_item")
        actions.append("trade_item")
    return actions


EVENT_APPLIERS = {
    EventType.ATTRIBUTE_DICE_ROLLED: apply_attribute_dice_rolled,
    EventType.HERO_CREATED: apply_hero_created,
    EventType.CARD_DRAWN: apply_card_drawn,
    EventType.CARD_PLAYED: apply_card_played,
    EventType.DECK_RESHUFFLED: apply_deck_reshuffled,
    EventType.SIGNATURE_CHARGE_REFRESHED: apply_signature_charge_refreshed,
    EventType.ITEM_PICKED_UP: apply_item_picked_up,
    EventType.ITEM_PICKUP_REJECTED: apply_item_pickup_rejected,
    EventType.ITEM_DROPPED: apply_item_dropped,
    EventType.ITEM_TRADED: apply_item_traded,
    EventType.BODY_LOOT_RECOVERED: apply_body_loot_recovered,
}
