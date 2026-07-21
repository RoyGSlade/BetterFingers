"""Heroes package tests (infinite_stacks.md §11, §13). See docs/INFINITE_STACKS_HEROES.md.

backend.lan_playground.heroes is standalone this wave -- no domain/reducer
wiring exists yet (wave 4), so these tests drive the package's own modules
directly, using the real core content pack (content.loader.load_core_pack())
as the "parsed data passed in" the package expects.
"""
from __future__ import annotations

import random

import pytest

from backend.lan_playground.content import loader as content_loader
from backend.lan_playground.content import schemas as S
from backend.lan_playground.heroes import backgrounds, cards, creation, deck, inventory

PACK = content_loader.load_core_pack()
BACKGROUND_IDS = ("exiled_court_scribe", "back_alley_fixer", "retired_monster_hunter", "traveling_charlatan")


class FakeRNG:
    """Minimal HeroesRNG stand-in with fully scripted draws, for exact
    determinism/assignment assertions independent of the real StacksRNG."""

    def __init__(self, d4_sequence=None, seed=0):
        self._d4 = list(d4_sequence or [])
        self._random = random.Random(seed)

    def roll_d20(self) -> int:
        return self._random.randint(1, 20)

    def randint(self, a: int, b: int) -> int:
        if a == 1 and b == 4 and self._d4:
            return self._d4.pop(0)
        return self._random.randint(a, b)

    def choice(self, seq):
        return self._random.choice(seq)

    def shuffled(self, seq):
        items = list(seq)
        self._random.shuffle(items)
        return items


def _assign_in_rolled_order(dice: creation.DiceRoll) -> dict:
    names = creation.ATTRIBUTE_NAMES
    return {name: value for name, value in zip(names, dice.values)}


def build_hero_sheet(background_id: str, *, rng, hero_id="hero_1", name="Test Hero") -> creation.HeroSheet:
    background = PACK.backgrounds[background_id]
    dice = creation.roll_attribute_dice(rng)
    attrs = creation.assign_attributes(dice, _assign_in_rolled_order(dice))
    attrs = backgrounds.apply_background_bonus(attrs, background)
    return creation.HeroSheet(
        hero_id=hero_id,
        name=name,
        background_id=background_id,
        dice=dice,
        attributes=attrs,
        skills=backgrounds.starting_skill_ranks(background),
        starting_item_ids=backgrounds.starting_item_ids(background),
    )


def background_deck_ids(background_id: str) -> list[str]:
    return sorted(card.id for card in PACK.cards.values() if card.source == background_id)


LIVE_GENERAL_CARD_IDS = ["careful_approach", "steady_nerve"]
PERSONA_CARD_ID = "signature_flourish"


# --------------------------------------------------------------------------- drift guard: heroes/combat naming stays in sync


def test_attribute_and_skill_names_match_combat_models_exactly():
    """heroes.creation literal-duplicates combat.models' ATTRIBUTE_NAMES/
    SKILL_NAMES (neither package imports the other -- purity, per both
    packages' module docstrings) so a wave-4 HeroSheet -> HeroCombatant field
    copy is a straight copy, not a translation. Only a test (which is allowed
    to import both) can guard against the two silently drifting apart -- a
    rename in either package must fail this loudly, not corrupt the bridge."""

    from backend.lan_playground.combat.models import ATTRIBUTE_NAMES as COMBAT_ATTRIBUTE_NAMES
    from backend.lan_playground.combat.models import SKILL_NAMES as COMBAT_SKILL_NAMES

    assert creation.ATTRIBUTE_NAMES == COMBAT_ATTRIBUTE_NAMES
    assert creation.SKILL_NAMES == COMBAT_SKILL_NAMES


# --------------------------------------------------------------------------- §11.1 creation: dice + determinism


def test_roll_attribute_dice_deterministic_under_same_seed():
    from backend.lan_playground.domain.rng import StacksRNG  # prove protocol compatibility with the real engine RNG

    dice_a = creation.roll_attribute_dice(StacksRNG(777))
    dice_b = creation.roll_attribute_dice(StacksRNG(777))
    assert dice_a == dice_b
    assert len(dice_a.values) == 4
    assert all(1 <= v <= 4 for v in dice_a.values)


def test_roll_attribute_dice_different_seeds_can_diverge():
    from backend.lan_playground.domain.rng import StacksRNG

    values = {creation.roll_attribute_dice(StacksRNG(seed)).values for seed in range(20)}
    assert len(values) > 1


def test_dice_roll_rejects_wrong_length_or_out_of_range():
    with pytest.raises(creation.CreationError):
        creation.DiceRoll(values=(1, 2, 3))
    with pytest.raises(creation.CreationError):
        creation.DiceRoll(values=(1, 2, 3, 5))


# --------------------------------------------------------------------------- §11.1 attribute assignment freedom + cap


def test_player_may_assign_dice_to_any_attribute_freely():
    dice = creation.DiceRoll(values=(1, 2, 3, 4))
    # Reverse order is a legal assignment -- the player, not the roll, decides.
    assignment = {"force": 4, "finesse": 3, "insight": 2, "presence": 1}
    attrs = creation.assign_attributes(dice, assignment)
    assert (attrs.force, attrs.finesse, attrs.insight, attrs.presence) == (4, 3, 2, 1)


def test_assign_attributes_rejects_incomplete_or_extra_assignment():
    dice = creation.DiceRoll(values=(1, 2, 3, 4))
    with pytest.raises(creation.CreationError):
        creation.assign_attributes(dice, {"force": 1, "finesse": 2, "insight": 3})  # missing presence
    with pytest.raises(creation.CreationError):
        creation.assign_attributes(dice, {"force": 9, "finesse": 2, "insight": 3, "presence": 4})  # 9 wasn't rolled


def test_assign_attributes_rejects_reusing_a_die_twice():
    dice = creation.DiceRoll(values=(2, 2, 3, 4))  # duplicate die value is legal to roll
    # Using the value 3 for two attributes when only one 3 was rolled must fail.
    with pytest.raises(creation.CreationError):
        creation.assign_attributes(dice, {"force": 3, "finesse": 3, "insight": 2, "presence": 4})


def test_background_bonus_adds_one_and_caps_at_five():
    attrs = creation.Attributes(force=1, finesse=1, insight=1, presence=1)
    bumped = attrs.with_bonus("force")
    assert bumped.force == 2
    at_cap = creation.Attributes(force=5, finesse=1, insight=1, presence=1)
    assert at_cap.with_bonus("force").force == 5  # capped, not 6

    scribe = PACK.backgrounds["exiled_court_scribe"]
    result = backgrounds.apply_background_bonus(attrs, scribe)
    assert result.presence == 2  # scribe's bonus attribute is presence
    assert result.force == attrs.force  # nothing else changed


# --------------------------------------------------------------------------- §11.1 derived-stat table


def test_derived_stats_match_the_locked_formulas():
    attrs = creation.Attributes(force=3, finesse=2, insight=1, presence=4)
    derived = creation.compute_derived_stats(attrs)
    assert derived.max_hp == 8 + 2 * 3
    assert derived.defense == 10 + 2
    assert derived.initiative_modifier == 2
    assert derived.carry_slots == 4 + 3


def test_derived_stats_include_equipment_defense_bonus():
    attrs = creation.Attributes(force=1, finesse=1, insight=1, presence=1)
    derived = creation.compute_derived_stats(attrs, equipment_defense_bonus=2)
    assert derived.defense == 10 + 1 + 2


def test_hero_sheet_derived_property_matches_compute_derived_stats():
    rng = FakeRNG(d4_sequence=[4, 1, 2, 3])
    sheet = build_hero_sheet("retired_monster_hunter", rng=rng)
    assert sheet.derived == creation.compute_derived_stats(sheet.attributes)
    assert sheet.attributes.force == 5  # 4 rolled + 1 background bonus


# --------------------------------------------------------------------------- §11.3 each background: mechanically different legal deck/action set


@pytest.mark.parametrize("background_id", BACKGROUND_IDS)
def test_every_background_has_exactly_four_background_cards(background_id):
    ids = background_deck_ids(background_id)
    assert len(ids) == 4


def test_backgrounds_produce_different_attribute_bonus_and_skills():
    seen_bonus_attrs = set()
    seen_skill_sets = set()
    for background_id in BACKGROUND_IDS:
        background = PACK.backgrounds[background_id]
        seen_bonus_attrs.add(background.attribute_bonus)
        seen_skill_sets.add(frozenset(background.skill_ranks))
    assert len(seen_bonus_attrs) == 4  # every background bumps a different attribute
    assert len(seen_skill_sets) == 4  # every background grants a different skill pair


def test_each_background_yields_a_mechanically_different_legal_starting_deck():
    """§27 Phase-3 exit gate: every background must produce a buildable,
    distinct starting deck -- distinct card ids (background cards differ) and
    a distinct action-set fingerprint (the compiled effect ops differ)."""

    rng = FakeRNG(seed=1)
    decks = {}
    fingerprints = {}
    for background_id in BACKGROUND_IDS:
        state = deck.build_starting_deck(
            f"hero_{background_id}",
            background_card_ids=background_deck_ids(background_id),
            general_card_ids=LIVE_GENERAL_CARD_IDS,
            persona_card_id=PERSONA_CARD_ID,
            card_lookup=PACK.cards,
            rng=rng,
        )
        decks[background_id] = frozenset(state.deck)
        ops = []
        for card_id in sorted(state.deck):
            for op in cards.compile_card_effect_ops(PACK.cards[card_id]):
                ops.append((op["op"], tuple(sorted(op["args"].items()))))
        fingerprints[background_id] = tuple(sorted(ops))

    # Every background's deck is legal (7 cards: 4 background + 2 general + 1 persona).
    for background_id, ids in decks.items():
        assert len(ids) == 7, background_id

    # Every background's deck differs from every other (distinct background cards).
    all_decks = list(decks.values())
    for i in range(len(all_decks)):
        for j in range(i + 1, len(all_decks)):
            assert all_decks[i] != all_decks[j]

    # Every background's compiled action set (op multiset) is distinct too --
    # "mechanically different," not just different card names.
    all_fingerprints = list(fingerprints.values())
    assert len(set(all_fingerprints)) == len(all_fingerprints)


# --------------------------------------------------------------------------- §13.2 deck build-time gate: LIVE-only ops


def test_build_starting_deck_succeeds_when_every_card_is_live_only():
    state = deck.build_starting_deck(
        "hero_1",
        background_card_ids=background_deck_ids("exiled_court_scribe"),
        general_card_ids=LIVE_GENERAL_CARD_IDS,
        persona_card_id=PERSONA_CARD_ID,
        card_lookup=PACK.cards,
        rng=FakeRNG(seed=2),
    )
    assert len(state.deck) == 7
    assert state.hand == () and state.discard == () and state.exhausted == ()


def test_build_starting_deck_rejects_a_card_with_a_non_live_op_loudly_at_build_time():
    # comma_cut is real pack content (equipment-granted), and uses PLANNED
    # ops (damage/apply_condition) -- not wired this wave.
    with pytest.raises(cards.NonLiveEffectOpError):
        deck.build_starting_deck(
            "hero_1",
            background_card_ids=background_deck_ids("exiled_court_scribe"),
            general_card_ids=LIVE_GENERAL_CARD_IDS,
            persona_card_id=PERSONA_CARD_ID,
            equipment_card_ids=["comma_cut"],
            card_lookup=PACK.cards,
            rng=FakeRNG(seed=2),
        )


def test_compile_card_effect_ops_reports_the_offending_op():
    with pytest.raises(cards.NonLiveEffectOpError, match="damage"):
        cards.compile_card_effect_ops(PACK.cards["comma_cut"])


def test_compile_card_effect_ops_is_live_only_for_every_background_and_persona_card():
    """Defense-in-depth: every card that is mandatory deck content -- the 16
    background cards and the persona signature card -- must compile clean, so
    every background's starting deck is always buildable this wave. General
    cards are a player *selection* (§13.2 "two selected general cards") and
    are not all required to be LIVE yet -- only the ones actually offered as
    legal selections this wave (`LIVE_GENERAL_CARD_IDS`) are."""

    mandatory_sources = set(BACKGROUND_IDS) | {"persona"}
    for card in PACK.cards.values():
        if card.source not in mandatory_sources:
            continue
        cards.compile_card_effect_ops(card)  # must not raise
    for card_id in LIVE_GENERAL_CARD_IDS:
        cards.compile_card_effect_ops(PACK.cards[card_id])  # must not raise


def test_build_starting_deck_enforces_composition_counts():
    with pytest.raises(deck.DeckError):
        deck.build_starting_deck(
            "hero_1",
            background_card_ids=background_deck_ids("exiled_court_scribe")[:3],  # only 3, need 4
            general_card_ids=LIVE_GENERAL_CARD_IDS,
            persona_card_id=PERSONA_CARD_ID,
            card_lookup=PACK.cards,
            rng=FakeRNG(seed=3),
        )
    with pytest.raises(deck.DeckError):
        deck.build_starting_deck(
            "hero_1",
            background_card_ids=background_deck_ids("exiled_court_scribe"),
            general_card_ids=LIVE_GENERAL_CARD_IDS,
            persona_card_id=PERSONA_CARD_ID,
            equipment_card_ids=["comma_cut", "subtext_flash", "comma_cut"],  # 3 > max 2
            card_lookup=PACK.cards,
            rng=FakeRNG(seed=3),
        )


# --------------------------------------------------------------------------- §13.2 draw / discard / Exhaust / reshuffle cycles


def _built_deck(background_id="back_alley_fixer", seed=4):
    return deck.build_starting_deck(
        "hero_1",
        background_card_ids=background_deck_ids(background_id),
        general_card_ids=LIVE_GENERAL_CARD_IDS,
        persona_card_id=PERSONA_CARD_ID,
        card_lookup=PACK.cards,
        rng=FakeRNG(seed=seed),
    )


def test_draw_moves_cards_from_deck_to_hand():
    state = _built_deck()
    total = len(state.deck)
    state = deck.draw(state, 4)
    assert len(state.hand) == 4
    assert len(state.deck) == total - 4


def test_draw_yields_fewer_cards_when_deck_runs_low_without_auto_reshuffling():
    state = _built_deck()
    state = deck.draw(state, len(state.deck) + 3)
    assert len(state.hand) == 7  # every card in the 7-card starting deck
    assert state.deck == ()


def test_play_card_routes_to_discard_or_exhaust_per_card_definition():
    state = _built_deck("back_alley_fixer")
    state = deck.draw(state, 7)
    discard_card = "careful_approach"  # end_state: discard (general LIVE card)
    exhaust_card = "field_patch"  # end_state: exhaust (back_alley_fixer background card)
    state = deck.play_card(state, discard_card, PACK.cards)
    state = deck.play_card(state, exhaust_card, PACK.cards)
    assert discard_card in state.discard
    assert exhaust_card in state.exhausted
    assert discard_card not in state.hand and exhaust_card not in state.hand


def test_play_card_rejects_a_card_not_in_hand():
    state = _built_deck()
    with pytest.raises(deck.DeckError):
        deck.play_card(state, "careful_approach", PACK.cards)  # never drawn


def test_safe_rest_reshuffles_discard_into_deck_but_not_exhausted():
    state = _built_deck("back_alley_fixer")
    state = deck.draw(state, 7)
    state = deck.play_card(state, "careful_approach", PACK.cards)  # -> discard
    state = deck.play_card(state, "field_patch", PACK.cards)  # -> exhaust
    pre_exhausted = state.exhausted
    state = deck.safe_rest_reshuffle(state, FakeRNG(seed=9))
    assert "careful_approach" in state.deck
    assert state.discard == ()
    assert state.exhausted == pre_exhausted  # untouched by an ordinary safe rest


def test_exhausted_cards_need_the_stronger_recovery_rule_not_safe_rest():
    state = _built_deck("back_alley_fixer")
    state = deck.draw(state, 7)
    state = deck.play_card(state, "field_patch", PACK.cards)  # -> exhaust
    assert "field_patch" in state.exhausted

    # An ordinary safe rest cannot recover it.
    rested = deck.safe_rest_reshuffle(state, FakeRNG(seed=9))
    assert "field_patch" in rested.exhausted

    # The explicit, stronger recovery call can.
    recovered = deck.recover_exhausted_card(state, "field_patch")
    assert "field_patch" not in recovered.exhausted
    assert "field_patch" in recovered.discard

    with pytest.raises(deck.DeckError):
        deck.recover_exhausted_card(recovered, "field_patch")  # not Exhausted anymore


def test_reaction_cards_in_hand_are_flagged_for_other_turn_play():
    state = _built_deck("retired_monster_hunter")
    state = deck.draw(state, 7)
    reaction_ids = deck.reaction_cards_in_hand(state, PACK.cards)
    assert "steady_nerve" in reaction_ids  # general LIVE reaction-timed card, in every built deck
    for card_id in reaction_ids:
        assert PACK.cards[card_id].timing is S.CardTiming.REACTION


# --------------------------------------------------------------------------- §13.6 inventory: single-owner conflict + slot limits


def make_inventory(hero_id="hero_1", carry_slots=5):
    return inventory.InventoryState(hero_id=hero_id, carry_slots=carry_slots)


def test_pickup_succeeds_and_consumes_a_slot():
    claims: dict[str, str] = {}
    inv = make_inventory(carry_slots=5)
    result, inv = inventory.attempt_pickup(
        claims, item_instance_id="ground_1", item_id="field_suture", hero_id="hero_1",
        inventory=inv, item_lookup=PACK.items,
    )
    assert result.accepted and result.reason is None
    assert inv.items == ("field_suture",)
    assert inv.used_slots(PACK.items) == 1


def test_pickup_conflict_returns_a_rejection_reason_for_a_second_claimant():
    claims: dict[str, str] = {}
    inv_a = make_inventory("hero_a")
    inv_b = make_inventory("hero_b")
    result_a, inv_a = inventory.attempt_pickup(
        claims, item_instance_id="ground_1", item_id="field_suture", hero_id="hero_a",
        inventory=inv_a, item_lookup=PACK.items,
    )
    result_b, inv_b = inventory.attempt_pickup(
        claims, item_instance_id="ground_1", item_id="field_suture", hero_id="hero_b",
        inventory=inv_b, item_lookup=PACK.items,
    )
    assert result_a.accepted
    assert not result_b.accepted
    assert result_b.reason == "already_claimed"
    assert inv_b.items == ()  # rejected pickup leaves inventory unchanged


def test_pickup_rejects_when_carry_slots_are_full():
    claims: dict[str, str] = {}
    inv = make_inventory(carry_slots=1)
    result1, inv = inventory.attempt_pickup(
        claims, item_instance_id="a", item_id="field_suture", hero_id="hero_1",
        inventory=inv, item_lookup=PACK.items,
    )
    result2, inv = inventory.attempt_pickup(
        claims, item_instance_id="b", item_id="red_string_spool", hero_id="hero_1",
        inventory=inv, item_lookup=PACK.items,
    )
    assert result1.accepted
    assert not result2.accepted
    assert result2.reason == "insufficient_carry_slots"


def test_drop_and_trade_move_items_between_inventories_respecting_slots():
    inv_a = inventory.InventoryState(hero_id="hero_a", carry_slots=5, items=("field_suture",))
    inv_b = inventory.InventoryState(hero_id="hero_b", carry_slots=5)
    inv_a2, inv_b2 = inventory.trade_item(inv_a, inv_b, "field_suture", PACK.items)
    assert "field_suture" not in inv_a2.items
    assert "field_suture" in inv_b2.items

    with pytest.raises(inventory.InventoryError):
        inventory.trade_item(inv_a2, inv_b2, "field_suture", PACK.items)  # hero_a no longer has it

    dropped = inventory.drop_item(inv_b2, "field_suture")
    assert dropped.items == ()


def test_trade_rejects_when_receiver_has_no_free_slots():
    inv_a = inventory.InventoryState(hero_id="hero_a", carry_slots=5, items=("field_suture",))
    inv_b = inventory.InventoryState(hero_id="hero_b", carry_slots=1, items=("red_string_spool",))
    with pytest.raises(inventory.InventoryError):
        inventory.trade_item(inv_a, inv_b, "field_suture", PACK.items)


def test_dead_hero_items_stay_with_body_data_hook():
    inv = inventory.InventoryState(hero_id="hero_1", carry_slots=5, items=("field_suture", "index_hook"))
    loot = inventory.hero_died_with_items(inv)
    assert loot.hero_id == "hero_1"
    assert loot.item_ids == ("field_suture", "index_hook")


# --------------------------------------------------------------------------- §11.3 signature abilities as charges


def test_signature_charge_starts_full_and_can_be_spent_once():
    scribe = PACK.backgrounds["exiled_court_scribe"]
    charge = backgrounds.initial_signature_charge(scribe)
    assert charge.charges_remaining == 1
    spent = charge.spend()
    assert spent.charges_remaining == 0
    with pytest.raises(backgrounds.SignatureChargeError):
        spent.spend()


def test_signature_charge_refreshed_hook_restores_to_max():
    scribe = PACK.backgrounds["exiled_court_scribe"]
    charge = backgrounds.initial_signature_charge(scribe).spend()
    assert charge.charges_remaining == 0
    refreshed = charge.refreshed()
    assert refreshed.charges_remaining == refreshed.max_charges == 1


def test_traveling_charlatan_gets_a_concealed_item_slot_bonus():
    charlatan = PACK.backgrounds["traveling_charlatan"]
    scribe = PACK.backgrounds["exiled_court_scribe"]
    assert backgrounds.bonus_carry_slots(charlatan) == 1
    assert backgrounds.bonus_carry_slots(scribe) == 0


# --------------------------------------------------------------------------- full hero creation, end to end per background


@pytest.mark.parametrize("background_id", BACKGROUND_IDS)
def test_full_creation_flow_produces_a_playable_hero_sheet(background_id):
    rng = FakeRNG(d4_sequence=[3, 4, 2, 1])
    sheet = build_hero_sheet(background_id, rng=rng)
    background = PACK.backgrounds[background_id]

    assert sheet.background_id == background_id
    assert sheet.attributes.get(background.attribute_bonus) <= creation.MAX_ATTRIBUTE
    assert sheet.skills == dict(background.skill_ranks)
    assert sheet.starting_item_ids == tuple(background.starting_item_ids)
    for item_id in sheet.starting_item_ids:
        assert item_id in PACK.items  # every starting item is real pack content

    derived = sheet.derived
    assert derived.max_hp == 8 + 2 * sheet.attributes.force
    assert derived.carry_slots == 4 + sheet.attributes.force
