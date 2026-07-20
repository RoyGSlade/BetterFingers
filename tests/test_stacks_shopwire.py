"""Shops domain wiring, end to end (infinite_stacks.md §9.6, §6.2, §16.4-16.6;
docs/INFINITE_STACKS_SHOPS.md, docs/INFINITE_STACKS_CONTRACTS.md). Board task
#18.

Drives the real domain reducer directly (same Harness pattern as
tests/test_stacks_herowire.py / tests/test_stacks_conflict.py) so shop/hero
state stays inspectable for white-box assertions, while still exercising the
real handle() -> events -> reduce() pipeline: breach into a d8=6 shop room,
buy/sell/repair/identify/treat through the domain commands, and replay.
"""
from __future__ import annotations

import pytest

from backend.lan_playground.content import loader as content_loader
from backend.lan_playground.domain import reducer, replay as replay_mod
from backend.lan_playground.domain.commands import Command, CommandError, CommandType
from backend.lan_playground.domain.events import EventType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import STARTING_GOLD, ConnectorState, RunState
from backend.lan_playground.shops import content_loader as shop_content_loader
from backend.lan_playground.systems import effects, shops_wire

PACK = content_loader.load_core_pack()
CORE_SHOPS = shop_content_loader.load_core_shops()
BACKGROUND_IDS = ("exiled_court_scribe", "back_alley_fixer", "retired_monster_hunter", "traveling_charlatan")
GENERAL_CARD_IDS = ["plain_warning", "read_the_room"]
PERSONA_CARD_ID = "signature_flourish"

# Seed 2's first breach (after one hero completes character creation) lands
# on a `shop` room seeded from the `marginalia_exchange` archetype (buy/sell/
# repair/identify, no treat). Seed 17's does the same for
# `apothecary_of_second_thoughts` (buy/sell/identify/treat, no repair).
# Locked in by a one-off seed search (see handoff) rather than re-derived on
# every run -- same style tests/test_stacks_conflict.py already uses for its
# documented seed-14 conflict room.
NO_TREAT_SHOP_SEED = 2
TREAT_SHOP_SEED = 17


class Harness:
    def __init__(self, run_id="run_shopwire", seed=1, chapter_floor_index=0):
        self.state = RunState.initial(run_id=run_id, seed=seed, chapter_floor_index=chapter_floor_index)
        self.rng = StacksRNG(seed)
        self.seq = 0
        self.event_log: list = []
        self._n = 0

    def send(self, hero_id, ctype, payload=None):
        self._n += 1
        cmd = Command(
            command_id=f"cmd_{self._n}",
            idempotency_key=f"cmd_{self._n}",
            run_id=self.state.run_id,
            type=ctype,
            hero_id=hero_id,
            expected_revision=self.state.revision,
            payload=payload or {},
        )
        result = reducer.apply(cmd, self.state, self.rng, viewer=hero_id, seq=self.seq)
        self.state = result.state
        self.seq = result.next_seq
        self.event_log.extend(result.events)
        return result

    def door_direction(self, room_id):
        room = self.state.map.rooms[room_id]
        for d, c in room.connectors.items():
            if c == ConnectorState.DOOR:
                return d
        return None

    def open_direction_to(self, room_id, target_room_id):
        room = self.state.map.rooms[room_id]
        for d, c in room.connectors.items():
            if c == ConnectorState.OPEN:
                dx, dy = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}[d.value]
                if f"room_{room.x + dx}_{room.y + dy}" == target_room_id:
                    return d
        return None

    def create_hero(self, hero_id, background_id="exiled_court_scribe", *, name=None):
        self.send(hero_id, CommandType.JOIN_RUN)
        self.send(hero_id, CommandType.ROLL_ATTRIBUTE_DICE)
        dice = self.state.heroes[hero_id].pending_dice
        assignment = {"force": dice[0], "finesse": dice[1], "insight": dice[2], "presence": dice[3]}
        self.send(
            hero_id,
            CommandType.CREATE_HERO,
            {
                "name": name or hero_id,
                "background_id": background_id,
                "attribute_assignment": assignment,
                "general_card_ids": list(GENERAL_CARD_IDS),
                "persona_card_id": PERSONA_CARD_ID,
            },
        )
        return self.state.heroes[hero_id]

    def breach_into_shop(self, hero_id):
        entrance = self.state.map.entrance_room_id
        direction = self.door_direction(entrance)
        result = self.send(hero_id, CommandType.BREACH, {"direction": direction.value})
        family = next(e.payload["family"] for e in result.events if e.type == EventType.ROOM_BREACHED)
        assert family == "shop", f"expected the documented seed's first breach to be a shop, got {family}"
        return self.state.heroes[hero_id].room_id

    def apply_condition(self, hero_id, condition_id):
        """Test-only setup helper: dispatches the real apply_condition effect
        op (systems/effects.py) directly, the same call any future card/
        enemy-intent/puzzle-consequence caller would make -- not a stub, a
        legitimate reuse of `effects.dispatch()`."""

        hero = self.state.heroes[hero_id]
        events = effects.dispatch(
            [{"op": "apply_condition", "args": {"condition_id": condition_id}}],
            command=Command(
                command_id=f"cond_{hero_id}_{condition_id}",
                idempotency_key=f"cond_{hero_id}_{condition_id}",
                run_id=self.state.run_id,
                type=CommandType.PASS,
                hero_id=hero_id,
            ),
            state=self.state,
            rng=self.rng,
            seq=self.seq,
            actor_hero_id=hero_id,
            room_id=hero.room_id,
        )
        for event in events:
            self.state = reducer.reduce(self.state, event)
            self.seq += 1
        self.event_log.extend(events)


def _shop_and_archetype(h: Harness, hero_id: str):
    hero = h.state.heroes[hero_id]
    shop = h.state.map.rooms[hero.room_id].shop
    return shop, CORE_SHOPS[shop.archetype_id]


def _cheapest_item_id(archetype) -> str:
    return min(archetype.all_listings(), key=lambda listing: listing.buy_price).item_id


# --------------------------------------------------------------------------- instantiate on breach


def test_breach_into_d8_6_instantiates_a_seeded_shop():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    hero = h.state.heroes["hero_a"]
    room = h.state.map.rooms[hero.room_id]

    assert room.shop is not None
    assert room.shop.archetype_id in CORE_SHOPS
    archetype = CORE_SHOPS[room.shop.archetype_id]
    for listing in archetype.guaranteed_inventory:
        assert room.shop.stock.get(listing.item_id, 0) > 0


def test_hero_starts_with_positive_starting_gold_as_data():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    hero = h.create_hero("hero_a")
    assert hero.gold == STARTING_GOLD > 0


def test_projection_never_leaks_another_shops_unseeded_future_stock():
    """The seeded ShopInstance only ever carries the guaranteed inventory
    plus exactly `rotating_slots` of the rotating pool -- never the full
    candidate pool (that would leak which items *could* have stocked this
    room but weren't seeded, an "unseeded future stock" leak)."""

    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    shop, archetype = _shop_and_archetype(h, "hero_a")

    rotating_ids = {listing.item_id for listing in archetype.rotating_pool}
    drawn_rotating = set(shop.stock) & rotating_ids
    assert len(drawn_rotating) == archetype.rotating_slots
    guaranteed_ids = {listing.item_id for listing in archetype.guaranteed_inventory}
    assert set(shop.stock) == guaranteed_ids | drawn_rotating


# --------------------------------------------------------------------------- buy / sell


def test_buy_moves_a_real_item_into_heroes_inventory_and_spends_gold():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    hero = h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    shop, archetype = _shop_and_archetype(h, "hero_a")
    item_id = archetype.guaranteed_inventory[0].item_id
    price = archetype.listing_for(item_id).buy_price
    gold_before = h.state.heroes["hero_a"].gold
    stock_before = shop.stock[item_id]

    result = h.send("hero_a", CommandType.SHOP_BUY, {"item_id": item_id})
    bought = next(e for e in result.events if e.type == EventType.SHOP_ITEM_BOUGHT)
    assert bought.payload["gold_delta"] == -price

    hero = h.state.heroes["hero_a"]
    assert item_id in hero.inventory.items
    assert hero.gold == gold_before - price
    new_shop, _ = _shop_and_archetype(h, "hero_a")
    assert new_shop.stock[item_id] == stock_before - 1


def test_sell_returns_the_item_to_stock_and_pays_strictly_less_than_bought_for():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    _, archetype = _shop_and_archetype(h, "hero_a")
    item_id = archetype.guaranteed_inventory[0].item_id
    buy_price = archetype.listing_for(item_id).buy_price

    h.send("hero_a", CommandType.SHOP_BUY, {"item_id": item_id})
    gold_after_buy = h.state.heroes["hero_a"].gold
    stock_after_buy = h.state.map.rooms[h.state.heroes["hero_a"].room_id].shop.stock[item_id]

    result = h.send("hero_a", CommandType.SHOP_SELL, {"item_id": item_id})
    sold = next(e for e in result.events if e.type == EventType.SHOP_ITEM_SOLD)
    sell_price = sold.payload["gold_delta"]

    assert 0 < sell_price < buy_price, "ECON-001: selling back must always be a strict loss"
    hero = h.state.heroes["hero_a"]
    assert item_id not in hero.inventory.items
    assert hero.gold == gold_after_buy + sell_price
    new_shop, _ = _shop_and_archetype(h, "hero_a")
    assert new_shop.stock[item_id] == stock_after_buy + 1


def test_buy_rejected_with_insufficient_gold_spends_nothing():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    hero = h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    _, archetype = _shop_and_archetype(h, "hero_a")
    expensive = max(archetype.all_listings(), key=lambda listing: listing.buy_price)
    assert expensive.buy_price > hero.gold, "fixture assumption: pricier than starting gold"

    result = h.send("hero_a", CommandType.SHOP_BUY, {"item_id": expensive.item_id})
    rejected = next(e for e in result.events if e.type == EventType.SHOP_TRANSACTION_REJECTED)
    assert rejected.payload["reason"] == "insufficient_gold"
    hero = h.state.heroes["hero_a"]
    assert hero.gold == STARTING_GOLD
    assert expensive.item_id not in hero.inventory.items


def test_sell_rejected_when_hero_does_not_hold_the_item():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    _, archetype = _shop_and_archetype(h, "hero_a")
    item_id = archetype.guaranteed_inventory[0].item_id

    result = h.send("hero_a", CommandType.SHOP_SELL, {"item_id": item_id})
    rejected = next(e for e in result.events if e.type == EventType.SHOP_TRANSACTION_REJECTED)
    assert rejected.payload["reason"] == "not_held"


def test_shop_buy_illegal_outside_an_active_shop_room():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    with pytest.raises(CommandError) as exc_info:
        h.send("hero_a", CommandType.SHOP_BUY, {"item_id": "anything"})
    assert exc_info.value.code.value == "illegal_action"


# --------------------------------------------------------------------------- repair / identify


def test_repair_clears_wear_and_charges_gold_scaled_to_wear():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    _, archetype = _shop_and_archetype(h, "hero_a")
    item_id = _cheapest_item_id(archetype)
    h.send("hero_a", CommandType.SHOP_BUY, {"item_id": item_id})
    h.send("hero_a", CommandType.PASS)  # refresh Energy for the next shop action

    hero = h.state.heroes["hero_a"]
    hero.item_wear[item_id] = 2  # test-only: nothing yet accrues Wear (known gap, see handoff)
    expected_cost = archetype.repair_cost_per_wear * 2
    gold_before = hero.gold

    result = h.send("hero_a", CommandType.SHOP_REPAIR, {"item_id": item_id})
    repaired = next(e for e in result.events if e.type == EventType.SHOP_ITEM_REPAIRED)
    assert repaired.payload["gold_delta"] == -expected_cost

    hero = h.state.heroes["hero_a"]
    assert hero.gold == gold_before - expected_cost
    assert hero.item_wear.get(item_id, 0) == 0


def test_identify_charges_flat_price_once_then_rejects_a_repeat():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    _, archetype = _shop_and_archetype(h, "hero_a")
    item_id = _cheapest_item_id(archetype)
    h.send("hero_a", CommandType.SHOP_BUY, {"item_id": item_id})
    h.send("hero_a", CommandType.PASS)  # refresh Energy for the next two shop actions

    result = h.send("hero_a", CommandType.SHOP_IDENTIFY, {"item_id": item_id})
    identified = next(e for e in result.events if e.type == EventType.SHOP_ITEM_IDENTIFIED)
    assert identified.payload["gold_delta"] == -archetype.identify_price
    assert item_id in h.state.heroes["hero_a"].identified_item_ids

    result = h.send("hero_a", CommandType.SHOP_IDENTIFY, {"item_id": item_id})
    rejected = next(e for e in result.events if e.type == EventType.SHOP_TRANSACTION_REJECTED)
    assert rejected.payload["reason"] == "already_identified"


# --------------------------------------------------------------------------- treat (real condition model)


def test_treat_consumes_gold_and_applies_the_conditions_real_treatment_effect():
    h = Harness(seed=TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    _, archetype = _shop_and_archetype(h, "hero_a")
    assert any(s.value == "treat" for s in archetype.services)

    condition_id = "sickened"
    h.apply_condition("hero_a", condition_id)
    hero = h.state.heroes["hero_a"]
    assert condition_id in hero.active_condition_ids
    gold_before = hero.gold
    treatment = PACK.conditions[condition_id].treatments[0]

    result = h.send("hero_a", CommandType.SHOP_TREAT, {"condition_id": condition_id, "treatment_id": treatment.id})
    treated = next(e for e in result.events if e.type == EventType.SHOP_CONDITION_TREATED)
    assert treated.payload["gold_delta"] == -archetype.treatment_price
    assert any(e.type == EventType.CONDITION_REMOVED for e in result.events), (
        "shop_treat must dispatch the treatment's real remove_condition effect, not just charge gold"
    )

    hero = h.state.heroes["hero_a"]
    assert hero.gold == gold_before - archetype.treatment_price
    assert condition_id not in hero.active_condition_ids


def test_treat_rejected_for_a_condition_the_hero_does_not_have():
    h = Harness(seed=TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    with pytest.raises(CommandError) as exc_info:
        h.send("hero_a", CommandType.SHOP_TREAT, {"condition_id": "bleeding", "treatment_id": "bandage_treatment"})
    assert exc_info.value.code.value == "illegal_action"


def test_treat_unavailable_at_a_shop_that_does_not_offer_it():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    _, archetype = _shop_and_archetype(h, "hero_a")
    assert not any(s.value == "treat" for s in archetype.services)

    h.apply_condition("hero_a", "bleeding")
    result = h.send("hero_a", CommandType.SHOP_TREAT, {"condition_id": "bleeding", "treatment_id": "bandage_treatment"})
    rejected = next(e for e in result.events if e.type == EventType.SHOP_TRANSACTION_REJECTED)
    assert rejected.payload["reason"] == "service_not_offered"
    assert "bleeding" in h.state.heroes["hero_a"].active_condition_ids


# --------------------------------------------------------------------------- persistence across leave/re-enter


def test_shop_state_persists_across_leave_and_re_enter():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    entrance = h.state.map.entrance_room_id
    shop_room_id = h.breach_into_shop("hero_a")
    _, archetype = _shop_and_archetype(h, "hero_a")
    item_id = archetype.guaranteed_inventory[0].item_id

    h.send("hero_a", CommandType.SHOP_BUY, {"item_id": item_id})
    stock_after_buy = h.state.map.rooms[shop_room_id].shop.stock[item_id]

    h.send("hero_a", CommandType.PASS)  # release movement_locked via round refresh
    back_direction = h.open_direction_to(shop_room_id, entrance)
    h.send("hero_a", CommandType.MOVE, {"direction": back_direction.value})
    assert h.state.heroes["hero_a"].room_id == entrance

    h.send("hero_a", CommandType.PASS)
    forward_direction = h.open_direction_to(entrance, shop_room_id)
    h.send("hero_a", CommandType.MOVE, {"direction": forward_direction.value})
    assert h.state.heroes["hero_a"].room_id == shop_room_id

    assert h.state.map.rooms[shop_room_id].shop.stock[item_id] == stock_after_buy


# --------------------------------------------------------------------------- share_clue


def test_share_clue_is_party_visible_and_requires_ownership():
    h = Harness(seed=17)
    h.create_hero("hero_a")
    h.create_hero("hero_b")
    h.state.heroes["hero_b"].room_id = h.state.heroes["hero_a"].room_id

    entrance = h.state.map.entrance_room_id
    direction = h.door_direction(entrance)
    result = h.send("hero_a", CommandType.BREACH, {"direction": direction.value})
    family = next(e.payload["family"] for e in result.events if e.type == EventType.ROOM_BREACHED)
    assert family == "mystery_chamber", "seed 17's first breach (2 heroes created first) is the documented Mystery Chamber room"

    room_id = h.state.heroes["hero_a"].room_id
    puzzle = h.state.map.rooms[room_id].puzzle
    owned_clue_id = puzzle.private_clue_assignments["hero_a"][0]

    with pytest.raises(CommandError):
        h.send("hero_b", CommandType.SHARE_CLUE, {"clue_id": owned_clue_id})

    result = h.send("hero_a", CommandType.SHARE_CLUE, {"clue_id": owned_clue_id})
    shared = next(e for e in result.events if e.type == EventType.CLUE_SHARED)
    assert shared.payload["clue_id"] == owned_clue_id
    assert h.state.party_shared_clues[room_id] == (owned_clue_id,)

    # sharing again is a no-op, not a duplicate entry
    h.send("hero_a", CommandType.SHARE_CLUE, {"clue_id": owned_clue_id})
    assert h.state.party_shared_clues[room_id] == (owned_clue_id,)


# --------------------------------------------------------------------------- legal actions


def test_legal_actions_list_shop_services_only_while_in_an_active_shop_room():
    h = Harness(seed=NO_TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    from backend.lan_playground.systems import exploration

    before = exploration.legal_action_summary(h.state, "hero_a")
    assert not any(a.startswith("shop_") for a in before)

    h.breach_into_shop("hero_a")
    after = exploration.legal_action_summary(h.state, "hero_a")
    assert "shop_buy" in after
    assert "shop_sell" in after
    assert "shop_treat" not in after  # marginalia_exchange does not offer treat


# --------------------------------------------------------------------------- replay determinism


def test_shopwire_events_replay_to_the_same_state_hash():
    h = Harness(run_id="run_replay_shopwire", seed=TREAT_SHOP_SEED)
    h.create_hero("hero_a")
    h.breach_into_shop("hero_a")
    _, archetype = _shop_and_archetype(h, "hero_a")
    item_id = _cheapest_item_id(archetype)

    h.send("hero_a", CommandType.SHOP_BUY, {"item_id": item_id})
    h.send("hero_a", CommandType.SHOP_SELL, {"item_id": item_id})
    h.send("hero_a", CommandType.PASS)  # refresh Energy for the remaining shop actions
    h.send("hero_a", CommandType.SHOP_IDENTIFY, {"item_id": item_id})
    h.apply_condition("hero_a", "sickened")
    h.send("hero_a", CommandType.SHOP_TREAT, {"condition_id": "sickened", "treatment_id": "antidote_treatment"})

    live_hash = h.state.state_hash()
    replayed = replay_mod.replay(
        run_id="run_replay_shopwire", seed=TREAT_SHOP_SEED, chapter_floor_index=0, events=h.event_log
    )
    assert replayed.state_hash() == live_hash
    assert replayed.heroes["hero_a"].gold == h.state.heroes["hero_a"].gold
    assert replayed.heroes["hero_a"].inventory == h.state.heroes["hero_a"].inventory
    assert replayed.heroes["hero_a"].active_condition_ids == h.state.heroes["hero_a"].active_condition_ids
    room_id = h.state.heroes["hero_a"].room_id
    assert replayed.map.rooms[room_id].shop == h.state.map.rooms[room_id].shop


def test_shopwire_replay_is_stable_across_multiple_seeds():
    for seed in (NO_TREAT_SHOP_SEED, TREAT_SHOP_SEED):
        h = Harness(run_id="run_replay_multi_shopwire", seed=seed)
        h.create_hero("hero_a")
        h.breach_into_shop("hero_a")
        _, archetype = _shop_and_archetype(h, "hero_a")
        item_id = archetype.guaranteed_inventory[0].item_id
        h.send("hero_a", CommandType.SHOP_BUY, {"item_id": item_id})

        live_hash = h.state.state_hash()
        replayed = replay_mod.replay(
            run_id="run_replay_multi_shopwire", seed=seed, chapter_floor_index=0, events=h.event_log
        )
        assert replayed.state_hash() == live_hash
