"""Shops package tests (infinite_stacks.md §9.6, §6.2, §17.1). See
docs/INFINITE_STACKS_SHOPS.md.

backend.lan_playground.shops is standalone this wave -- no domain/reducer
wiring exists yet (wave 5), so these tests drive the package's own modules
directly. The run-summary fold tests are the one place this file imports
`domain`/`systems` -- only to *build* a real recorded event log via the
actual reducer pipeline (same Harness pattern tests/test_stacks_conflict.py
uses), never inside the shops package itself.
"""
from __future__ import annotations

import random
from typing import Any

import pytest
import yaml

from backend.lan_playground.content import loader as content_loader
from backend.lan_playground.content import validators as V
from backend.lan_playground.domain import reducer
from backend.lan_playground.domain.commands import Command, CommandType
from backend.lan_playground.domain.events import EventType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConnectorState, RunState
from backend.lan_playground.shops import content_loader as shop_content_loader
from backend.lan_playground.shops import economy, run_summary, seeding, services
from backend.lan_playground.shops import models as M

CORE_ITEMS = content_loader.load_core_pack().items
CORE_SHOPS = shop_content_loader.load_core_shops()


# ---------------------------------------------------------------------------
# Fixture builders (independent of content packs, for models/economy/services)
# ---------------------------------------------------------------------------


def make_archetype(**overrides: Any) -> M.ShopArchetype:
    defaults: dict[str, Any] = dict(
        id="test_shop",
        name="Test Shop",
        persona=M.MerchantPersona(name="Test Merchant", tagline="Buy things.", tone="neutral"),
        services=frozenset({M.ShopService.BUY, M.ShopService.SELL, M.ShopService.REPAIR, M.ShopService.IDENTIFY, M.ShopService.TREAT}),
        guaranteed_inventory=(
            M.InventoryListing(item_id="widget", buy_price=10, stock=5),
            M.InventoryListing(item_id="gadget", buy_price=20, stock=2),
        ),
        rotating_pool=(
            M.InventoryListing(item_id="gizmo", buy_price=15, stock=1),
            M.InventoryListing(item_id="doohickey", buy_price=8, stock=1),
        ),
        rotating_slots=1,
        sell_price_ratio=0.5,
        repair_cost_per_wear=3,
        identify_price=5,
        treatment_price=7,
        rumor=M.Rumor(id="test_rumor", text="Something is up.", accessible_text="Rumor: something is up."),
        relationship_complication=M.RelationshipComplication(
            id="test_complication", description="A minor grudge.", accessible_text="Complication: a minor grudge."
        ),
    )
    defaults.update(overrides)
    return M.ShopArchetype(**defaults)


class FakeRNG:
    """Minimal ShopsRNG stand-in, mirrors test_stacks_heroes.py's FakeRNG."""

    def __init__(self, seed=0):
        self._random = random.Random(seed)

    def roll_d20(self) -> int:
        return self._random.randint(1, 20)

    def randint(self, a: int, b: int) -> int:
        return self._random.randint(a, b)

    def choice(self, seq):
        return self._random.choice(seq)

    def shuffled(self, seq):
        items = list(seq)
        self._random.shuffle(items)
        return items


# ---------------------------------------------------------------------------
# Models: shape invariants (ECON-001 enforced at the data layer)
# ---------------------------------------------------------------------------


def test_sell_price_ratio_must_be_strictly_below_one():
    with pytest.raises(M.ShopModelError):
        make_archetype(sell_price_ratio=1.0)


def test_rotating_slots_cannot_exceed_pool_size():
    with pytest.raises(M.ShopModelError):
        make_archetype(rotating_slots=99)


def test_shop_must_declare_at_least_one_service():
    with pytest.raises(M.ShopModelError):
        make_archetype(services=frozenset())


def test_duplicate_item_id_across_listings_rejected():
    with pytest.raises(M.ShopModelError):
        make_archetype(
            guaranteed_inventory=(M.InventoryListing(item_id="widget", buy_price=5),),
            rotating_pool=(M.InventoryListing(item_id="widget", buy_price=5),),
            rotating_slots=1,
        )


# ---------------------------------------------------------------------------
# Seeding: deterministic instantiation from an archetype + RNG (§9.6)
# ---------------------------------------------------------------------------


def test_same_seed_same_rotating_selection():
    archetype = make_archetype()
    a = seeding.instantiate_shop(archetype, StacksRNG(42))
    b = seeding.instantiate_shop(archetype, StacksRNG(42))
    assert a.stock == b.stock


def test_guaranteed_inventory_always_present_regardless_of_seed():
    archetype = make_archetype()
    for seed in (1, 2, 3, 4, 5):
        instance = seeding.instantiate_shop(archetype, StacksRNG(seed))
        assert instance.stock.get("widget") == 5
        assert instance.stock.get("gadget") == 2


def test_rotating_selection_respects_slot_count():
    archetype = make_archetype()
    instance = seeding.instantiate_shop(archetype, StacksRNG(7))
    rotating_present = [iid for iid in ("gizmo", "doohickey") if iid in instance.stock]
    assert len(rotating_present) == archetype.rotating_slots == 1


def test_real_stacks_rng_satisfies_shops_rng_protocol():
    from backend.lan_playground.shops.rng import ShopsRNG

    assert isinstance(StacksRNG(1), ShopsRNG)


# ---------------------------------------------------------------------------
# Economy: pricing math (§9.6, ECON-001)
# ---------------------------------------------------------------------------


def test_sell_price_strictly_below_buy_price_for_every_positive_price():
    archetype = make_archetype(sell_price_ratio=0.99)
    for item_id in ("widget", "gadget"):
        buy = economy.buy_price(archetype, item_id)
        sell = economy.sell_price(archetype, item_id)
        assert sell < buy


def test_sell_price_never_negative_even_at_low_buy_price():
    archetype = make_archetype(
        guaranteed_inventory=(M.InventoryListing(item_id="widget", buy_price=1, stock=1),),
        rotating_pool=(),
        rotating_slots=0,
    )
    assert economy.sell_price(archetype, "widget") == 0


def test_repair_price_scales_with_wear():
    archetype = make_archetype(repair_cost_per_wear=5)
    assert economy.repair_price(archetype, 0) == 0
    assert economy.repair_price(archetype, 1) == 5
    assert economy.repair_price(archetype, 4) == 20


def test_repair_price_rejects_negative_wear():
    archetype = make_archetype()
    with pytest.raises(M.ShopModelError):
        economy.repair_price(archetype, -1)


def test_unknown_listing_raises():
    archetype = make_archetype()
    with pytest.raises(economy.UnknownListingError):
        economy.buy_price(archetype, "not_a_real_item")


def test_total_wealth_counts_gold_plus_liquidation_value():
    archetype = make_archetype()
    shopper = M.ShopperState(gold=100, held_items={"widget": 2})
    expected = 100 + economy.sell_price(archetype, "widget") * 2
    assert economy.total_wealth(shopper, archetype) == expected


# ---------------------------------------------------------------------------
# Services: transactions (buy/sell/repair/identify/treat)
# ---------------------------------------------------------------------------


def test_buy_deducts_gold_grants_item_and_decrements_stock():
    archetype = make_archetype()
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=100)
    price = economy.buy_price(archetype, "widget")

    result, new_instance, new_shopper = services.attempt_buy(archetype, instance, shopper, "widget")

    assert result.accepted
    assert result.gold_delta == -price
    assert new_shopper.gold == 100 - price
    assert new_shopper.held_items["widget"] == 1
    assert new_instance.stock["widget"] == instance.stock["widget"] - 1


def test_buy_rejected_when_insufficient_gold():
    archetype = make_archetype()
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=0)

    result, new_instance, new_shopper = services.attempt_buy(archetype, instance, shopper, "widget")

    assert not result.accepted
    assert result.reason == "insufficient_gold"
    assert new_instance == instance
    assert new_shopper == shopper


def test_buy_rejected_when_out_of_stock():
    archetype = make_archetype(
        guaranteed_inventory=(M.InventoryListing(item_id="widget", buy_price=10, stock=1),),
        rotating_pool=(),
        rotating_slots=0,
    )
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=1000)

    result, instance, shopper = services.attempt_buy(archetype, instance, shopper, "widget")
    assert result.accepted
    result, instance, shopper = services.attempt_buy(archetype, instance, shopper, "widget")
    assert not result.accepted
    assert result.reason == "out_of_stock"


def test_buy_rejected_when_service_not_offered():
    archetype = make_archetype(services=frozenset({M.ShopService.SELL}))
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=1000)

    result, _, _ = services.attempt_buy(archetype, instance, shopper, "widget")
    assert not result.accepted
    assert result.reason == "service_not_offered"


def test_sell_grants_gold_below_buy_price_and_removes_item():
    archetype = make_archetype()
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=0, held_items={"widget": 1})
    sell = economy.sell_price(archetype, "widget")

    result, new_instance, new_shopper = services.attempt_sell(archetype, instance, shopper, "widget")

    assert result.accepted
    assert result.gold_delta == sell
    assert new_shopper.gold == sell
    assert "widget" not in new_shopper.held_items
    assert new_instance.stock["widget"] == instance.stock["widget"] + 1


def test_sell_rejected_when_not_held():
    archetype = make_archetype()
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=0)

    result, _, _ = services.attempt_sell(archetype, instance, shopper, "widget")
    assert not result.accepted
    assert result.reason == "not_held"


def test_repair_clears_wear_and_charges_gold():
    archetype = make_archetype(repair_cost_per_wear=4)
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=100, held_items={"widget": 1}, wear={"widget": 3})

    result, _, new_shopper = services.attempt_repair(archetype, instance, shopper, "widget")

    assert result.accepted
    assert result.gold_delta == -12
    assert new_shopper.gold == 88
    assert new_shopper.wear.get("widget", 0) == 0


def test_repair_rejected_when_nothing_to_repair():
    archetype = make_archetype()
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=100, held_items={"widget": 1})

    result, _, _ = services.attempt_repair(archetype, instance, shopper, "widget")
    assert not result.accepted
    assert result.reason == "nothing_to_repair"


def test_identify_charges_flat_price_once():
    archetype = make_archetype(identify_price=9)
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=100, held_items={"widget": 1})

    result, instance, shopper = services.attempt_identify(archetype, instance, shopper, "widget")
    assert result.accepted
    assert shopper.gold == 91
    assert "widget" in shopper.identified

    result, _, _ = services.attempt_identify(archetype, instance, shopper, "widget")
    assert not result.accepted
    assert result.reason == "already_identified"


def test_treat_charges_flat_price_and_is_not_item_scoped():
    archetype = make_archetype(treatment_price=14)
    instance = seeding.instantiate_shop(archetype, StacksRNG(1))
    shopper = M.ShopperState(gold=20)

    result, _, new_shopper = services.attempt_treat(archetype, instance, shopper)
    assert result.accepted
    assert new_shopper.gold == 6

    result, _, _ = services.attempt_treat(archetype, instance, new_shopper)
    assert not result.accepted
    assert result.reason == "insufficient_gold"


# ---------------------------------------------------------------------------
# ECON-001 anti-loop property test: no sequence of shop actions may ever
# increase total wealth (infinite_stacks.md §6.2, §17.1).
# ---------------------------------------------------------------------------


def _run_random_sequence(seed: int, archetype: M.ShopArchetype, instance: M.ShopInstance) -> None:
    rng = random.Random(seed)
    shopper = M.ShopperState(gold=200)
    item_ids = [listing.item_id for listing in archetype.all_listings()]
    actions = ("buy", "sell", "repair", "identify", "treat", "wear_up")

    for _ in range(20):
        before = economy.total_wealth(shopper, archetype)
        action = rng.choice(actions)
        item_id = rng.choice(item_ids)

        if action == "buy":
            _, instance, shopper = services.attempt_buy(archetype, instance, shopper, item_id)
        elif action == "sell":
            _, instance, shopper = services.attempt_sell(archetype, instance, shopper, item_id)
        elif action == "repair":
            _, instance, shopper = services.attempt_repair(archetype, instance, shopper, item_id)
        elif action == "identify":
            _, instance, shopper = services.attempt_identify(archetype, instance, shopper, item_id)
        elif action == "treat":
            _, instance, shopper = services.attempt_treat(archetype, instance, shopper)
        else:  # wear_up: not a shop action, simulates external Wear accrual
            if item_id in shopper.held_items:
                new_wear = dict(shopper.wear)
                new_wear[item_id] = new_wear.get(item_id, 0) + 1
                from dataclasses import replace

                shopper = replace(shopper, wear=new_wear)

        after = economy.total_wealth(shopper, archetype)
        assert after <= before, f"seed={seed} action={action} item={item_id}: wealth increased {before} -> {after}"


@pytest.mark.parametrize("seed", range(1, 1001))
def test_no_action_sequence_increases_total_wealth(seed):
    archetype = make_archetype()
    instance = seeding.instantiate_shop(archetype, StacksRNG(seed))
    _run_random_sequence(seed, archetype, instance)


# ---------------------------------------------------------------------------
# Run-summary fold: pure fold over a real recorded domain event log
# ---------------------------------------------------------------------------


class _Harness:
    """Minimal domain-reducer harness, same pattern as
    tests/test_stacks_conflict.py's Harness -- used only to *record* a real
    event log to fold over, never imported by the shops package itself."""

    def __init__(self, run_id="run_shops_summary", seed=14, chapter_floor_index=0):
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

    def encounter(self, room_id):
        return self.state.map.rooms[room_id].encounter


def _record_a_victory_event_log() -> list[dict]:
    """Seed 14 (same seed tests/test_stacks_conflict.py documents) breaches
    into a conflict room with a single, poorly-armed immediate enemy when
    only one hero has joined -- fight it to victory so the recorded log
    contains a real ROOM_BREACHED, CONFLICT_ENCOUNTER_STARTED,
    CONFLICT_TURN_RESOLVED, and CONFLICT_ENCOUNTER_ENDED(outcome=victory)."""

    h = _Harness()
    h.send("hero_a", CommandType.JOIN_RUN)
    entrance = h.state.map.entrance_room_id
    direction = h.door_direction(entrance)
    result = h.send("hero_a", CommandType.BREACH, {"direction": direction.value})
    family = next(e.payload["family"] for e in result.events if e.type == EventType.ROOM_BREACHED)
    assert family == "conflict", f"expected seed 14's first breach to be conflict, got {family}"
    room_id = h.state.heroes["hero_a"].room_id

    for _ in range(20):
        enc = h.encounter(room_id)
        if enc.status != "active":
            break
        enemy_id = next((eid for eid, e in enc.enemies.items() if e["alive"]), None)
        if enemy_id and enc.current_actor_id == "hero_a":
            h.send("hero_a", CommandType.COMBAT_ATTACK, {"target_id": enemy_id, "attribute": "force", "skill": None})
        enc = h.encounter(room_id)
        if enc.status != "active":
            break
        h.send("hero_a", CommandType.COMBAT_END_TURN)

    enc = h.encounter(room_id)
    assert enc.status == "victory"
    return [e.to_dict() for e in h.event_log]


def test_run_summary_fold_over_real_recorded_event_log():
    event_log = _record_a_victory_event_log()
    stats = run_summary.fold_run_summary(event_log)

    assert stats["rooms_resolved"] == 1
    assert stats["encounters_won"] == 1
    assert stats["encounters_lost"] == 0
    assert stats["heroes_dead"] == 0
    assert stats["fragments_recovered"] == 0  # RUN-001 groundwork: no source event exists yet
    assert stats["items_gained"] == 0  # groundwork: herowire's pickup events don't exist yet
    assert set(stats["puzzle_stats"]) == {"instantiated", "solved", "rejected", "forced", "hints_used"}


def test_run_summary_fold_is_pure_and_repeatable():
    event_log = _record_a_victory_event_log()
    first = run_summary.fold_run_summary(event_log)
    second = run_summary.fold_run_summary(event_log)
    assert first == second


def test_run_summary_fold_tolerates_unknown_event_types():
    event_log = [
        {"type": "some_future_event_type", "payload": {"whatever": 1}},
        {"type": None, "payload": {}},
        {"payload": {}},  # missing "type" entirely
    ]
    stats = run_summary.fold_run_summary(event_log)
    assert stats["rooms_resolved"] == 0


def test_run_summary_fold_counts_heroes_downed_transition_once():
    event_log = [
        {"type": "conflict_turn_resolved", "payload": {"hero_updates": {"hero_a": {"life_state": "downed"}}}},
        {"type": "conflict_turn_resolved", "payload": {"hero_updates": {"hero_a": {"life_state": "downed"}}}},
        {"type": "conflict_turn_resolved", "payload": {"hero_updates": {"hero_a": {"life_state": "stable"}}}},
        {"type": "conflict_turn_resolved", "payload": {"hero_updates": {"hero_a": {"life_state": "downed"}}}},
    ]
    stats = run_summary.fold_run_summary(event_log)
    assert stats["heroes_downed"] == 2


def test_run_summary_fold_counts_party_wipe():
    event_log = [
        {
            "type": "conflict_encounter_ended",
            "payload": {"outcome": "party_wiped", "hero_updates": {}, "newly_dead_hero_ids": ["hero_a"]},
        }
    ]
    stats = run_summary.fold_run_summary(event_log)
    assert stats["encounters_lost"] == 1
    assert stats["heroes_dead"] == 1


# ---------------------------------------------------------------------------
# Content pack: shops.yaml (>=2 archetypes, real item ids, load/validate)
# ---------------------------------------------------------------------------


def test_core_shops_pack_has_at_least_two_archetypes():
    assert len(CORE_SHOPS) >= 2


def test_core_shops_reference_only_real_item_ids():
    for shop in CORE_SHOPS.values():
        for listing in shop.all_listings():
            assert listing.item_id in CORE_ITEMS, f"shop {shop.id} references unknown item {listing.item_id!r}"


def test_core_pack_and_shops_validate_together_clean():
    pack, shops = shop_content_loader.validate_core_pack_and_shops()
    assert shops == CORE_SHOPS
    assert pack.items == CORE_ITEMS


def test_core_shops_each_declare_a_rumor_and_a_complication():
    for shop in CORE_SHOPS.values():
        assert shop.rumor.text.strip()
        assert shop.relationship_complication.description.strip()


def test_missing_shops_yaml_returns_empty_dict(tmp_path):
    assert shop_content_loader.load_shops(tmp_path) == {}


def test_shop_with_unknown_item_ref_fails_validation():
    pack = content_loader.load_core_pack()
    bad_archetype = make_archetype(
        id="bad_shop",
        guaranteed_inventory=(M.InventoryListing(item_id="nonexistent_item_xyz", buy_price=5),),
        rotating_pool=(),
        rotating_slots=0,
    )
    shops = {"bad_shop": bad_archetype}

    findings = shop_content_loader.check_shop_item_references(shops, pack)
    assert any(f.rule == "unknown_reference" and "nonexistent_item_xyz" in f.message for f in findings)

    with pytest.raises(V.ValidationError):
        shop_content_loader.validate_shops_strict(shops, pack)


def _minimal_shop_yaml() -> dict[str, Any]:
    return {
        "shops": [
            {
                "id": "fixture_shop",
                "name": "Fixture Shop",
                "persona": {"name": "Fixture Merchant", "tagline": "Buys and sells.", "tone": "neutral"},
                "services": ["buy", "sell"],
                "sell_price_ratio": 0.5,
                "repair_cost_per_wear": 0,
                "identify_price": 0,
                "treatment_price": 0,
                "guaranteed_inventory": [{"item_id": "field_suture", "buy_price": 10, "stock": 1}],
                "rotating_pool": [],
                "rotating_slots": 0,
                "rumor": {"id": "fixture_rumor", "text": "text", "accessible_text": "accessible"},
                "relationship_complication": {
                    "id": "fixture_complication",
                    "description": "desc",
                    "accessible_text": "accessible",
                },
            }
        ]
    }


def test_fixture_shops_yaml_loads_clean(tmp_path):
    (tmp_path / "shops.yaml").write_text(yaml.safe_dump(_minimal_shop_yaml()), encoding="utf-8")
    shops = shop_content_loader.load_shops(tmp_path)
    assert set(shops) == {"fixture_shop"}
    assert shops["fixture_shop"].guaranteed_inventory[0].item_id == "field_suture"


def test_shops_yaml_unknown_field_rejected(tmp_path):
    files = _minimal_shop_yaml()
    files["shops"][0]["totally_made_up_field"] = "x"
    (tmp_path / "shops.yaml").write_text(yaml.safe_dump(files), encoding="utf-8")

    with pytest.raises(shop_content_loader.LoaderError):
        shop_content_loader.load_shops(tmp_path)


def test_shops_yaml_duplicate_id_rejected(tmp_path):
    files = _minimal_shop_yaml()
    files["shops"].append(dict(files["shops"][0]))
    (tmp_path / "shops.yaml").write_text(yaml.safe_dump(files), encoding="utf-8")

    with pytest.raises(shop_content_loader.LoaderError):
        shop_content_loader.load_shops(tmp_path)


def test_shops_yaml_invalid_service_rejected(tmp_path):
    files = _minimal_shop_yaml()
    files["shops"][0]["services"] = ["buy", "not_a_real_service"]
    (tmp_path / "shops.yaml").write_text(yaml.safe_dump(files), encoding="utf-8")

    with pytest.raises(shop_content_loader.LoaderError):
        shop_content_loader.load_shops(tmp_path)
