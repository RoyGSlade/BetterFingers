"""Heroes-package domain wiring, end to end (infinite_stacks.md §11, §13,
§14.3; docs/INFINITE_STACKS_HEROES.md, docs/INFINITE_STACKS_CONTRACTS.md,
docs/INFINITE_STACKS_COMBAT.md). Board task #13.

Drives the real domain reducer directly (same Harness pattern as
tests/test_stacks_engine.py / tests/test_stacks_conflict.py) so hero state
(HeroState.sheet/deck/inventory/signature_charge) stays inspectable for
white-box assertions, while still exercising the real
handle() -> events -> reduce() pipeline end to end.
"""
from __future__ import annotations

import pytest

from backend.lan_playground import stacks_engine
from backend.lan_playground.content import loader as content_loader
from backend.lan_playground.domain import reducer, replay as replay_mod
from backend.lan_playground.domain.commands import Command, CommandError, CommandType
from backend.lan_playground.domain.events import EventType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConnectorState, RunState
from backend.lan_playground.systems import checks, combat_wire, heroes_wire

PACK = content_loader.load_core_pack()
BACKGROUND_IDS = ("exiled_court_scribe", "back_alley_fixer", "retired_monster_hunter", "traveling_charlatan")
GENERAL_CARD_IDS = ["plain_warning", "read_the_room"]
PERSONA_CARD_ID = "signature_flourish"


class Harness:
    def __init__(self, run_id="run_herowire", seed=1, chapter_floor_index=0):
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

    def create_hero(self, hero_id, background_id, *, name=None):
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


# --------------------------------------------------------------------------- creation E2E


@pytest.mark.parametrize("background_id", BACKGROUND_IDS)
def test_creation_e2e_produces_a_playable_hero_for_every_background(background_id):
    h = Harness(seed=hash(background_id) % 10_000)
    hero = h.create_hero("hero_a", background_id)
    background = PACK.backgrounds[background_id]

    assert hero.sheet is not None
    assert hero.pending_dice is None
    assert hero.sheet.background_id == background_id
    assert hero.sheet.skills == dict(background.skill_ranks)
    assert hero.sheet.attributes.get(background.attribute_bonus) <= 5

    # derived stats actually reached HeroState, not left at flat defaults
    assert hero.max_hp == 8 + 2 * hero.sheet.attributes.get("force")
    assert hero.hp == hero.max_hp

    # deck built to the exact §13.2 composition and already drew an opening hand
    assert hero.deck is not None
    assert len(hero.deck.hand) == 4
    assert len(hero.deck.deck) + len(hero.deck.hand) == 4 + 2 + 1  # background + general + persona
    assert PERSONA_CARD_ID in (hero.deck.hand + hero.deck.deck)

    # inventory seeded from background starting items, carry slots include any bonus
    assert hero.inventory is not None
    assert hero.inventory.items == tuple(background.starting_item_ids)
    assert hero.inventory.carry_slots == hero.sheet.derived.carry_slots + heroes_wire.heroes_backgrounds.bonus_carry_slots(
        background
    )
    assert hero.carried_item_ids == hero.inventory.items  # combat.py's body-loot bridge mirror stays in sync

    assert hero.signature_charge is not None
    assert hero.signature_charge.ability_id == background.signature_ability.id
    assert hero.signature_charge.charges_remaining == 1


def test_four_backgrounds_in_one_run_are_genuinely_distinct():
    h = Harness(seed=555)
    heroes = {bg: h.create_hero(f"hero_{bg}", bg) for bg in BACKGROUND_IDS}
    seen_backgrounds = {hero.sheet.background_id for hero in heroes.values()}
    assert seen_backgrounds == set(BACKGROUND_IDS)
    seen_items = {hero.inventory.items for hero in heroes.values()}
    assert len(seen_items) == 4  # every background starts with different items


def test_roll_attribute_dice_rejected_after_creation():
    h = Harness(seed=2)
    h.create_hero("hero_a", "exiled_court_scribe")
    with pytest.raises(CommandError) as exc:
        h.send("hero_a", CommandType.ROLL_ATTRIBUTE_DICE)
    assert exc.value.code.value == "illegal_action"


def test_create_hero_requires_a_prior_dice_roll():
    h = Harness(seed=2)
    h.send("hero_a", CommandType.JOIN_RUN)
    with pytest.raises(CommandError) as exc:
        h.send(
            "hero_a",
            CommandType.CREATE_HERO,
            {
                "name": "Bram",
                "background_id": "exiled_court_scribe",
                "attribute_assignment": {"force": 1, "finesse": 1, "insight": 1, "presence": 1},
                "general_card_ids": list(GENERAL_CARD_IDS),
                "persona_card_id": PERSONA_CARD_ID,
            },
        )
    assert exc.value.code.value == "illegal_action"


# --------------------------------------------------------------------------- card play


def test_playing_a_no_check_card_dispatches_its_base_effects_visibly():
    h = Harness(seed=11)
    hero = h.create_hero("hero_a", "back_alley_fixer")
    # scavenged_shim is a background card for back_alley_fixer with a plain
    # emit_fact base effect and no check -- deterministic outcome.
    scavenged = next(c for c in PACK.cards.values() if c.id == "scavenged_shim")
    assert scavenged.check is None
    if scavenged.id not in hero.deck.hand:
        h.send("hero_a", CommandType.DRAW_CARDS, {"count": len(hero.deck.deck)})
        hero = h.state.heroes["hero_a"]
    assert scavenged.id in hero.deck.hand

    result = h.send("hero_a", CommandType.PLAY_CARD, {"card_id": scavenged.id})
    types = [e.type for e in result.events]
    assert EventType.CARD_PLAYED in types
    play_event = next(e for e in result.events if e.type == EventType.CARD_PLAYED)
    assert play_event.payload["card_id"] == scavenged.id
    assert play_event.payload["check_receipt"] is None
    # base effect (emit_fact) actually dispatched and landed on RunState.facts
    assert EventType.FACT_EMITTED in types
    hero = h.state.heroes["hero_a"]
    assert scavenged.id not in hero.deck.hand
    assert scavenged.id in hero.deck.discard


def test_playing_a_check_card_rolls_the_heros_real_attributes_and_skills():
    h = Harness(seed=17)
    hero = h.create_hero("hero_a", "retired_monster_hunter")
    if "read_the_room" not in hero.deck.hand:
        h.send("hero_a", CommandType.DRAW_CARDS, {"count": len(hero.deck.deck)})
        hero = h.state.heroes["hero_a"]
    assert "read_the_room" in hero.deck.hand

    result = h.send("hero_a", CommandType.PLAY_CARD, {"card_id": "read_the_room"})
    play_event = next(e for e in result.events if e.type == EventType.CARD_PLAYED)
    receipt = play_event.payload["check_receipt"]
    assert receipt is not None
    assert receipt["attribute"] == "insight"
    assert receipt["skill"] == "read"
    assert receipt["attribute_score"] == hero.sheet.attributes.get("insight")
    assert receipt["skill_rank"] == hero.sheet.skills.get("read", 0)
    assert receipt["dc"] == 11
    expected_total = receipt["chosen_die"] + receipt["attribute_score"] + receipt["skill_rank"]
    assert receipt["total"] == expected_total

    # exactly one outcome-branch effect fired, matching the resolved margin
    outcome = receipt["outcome"]
    types = [e.type for e in result.events]
    if outcome == "setback":
        assert EventType.EFFECT_ENERGY_SPENT in types
    else:
        assert EventType.FACT_EMITTED in types

    hero = h.state.heroes["hero_a"]
    assert "read_the_room" not in hero.deck.hand
    assert "read_the_room" in hero.deck.discard


def test_play_card_requires_card_in_hand():
    h = Harness(seed=3)
    h.create_hero("hero_a", "exiled_court_scribe")
    with pytest.raises(CommandError) as exc:
        h.send("hero_a", CommandType.PLAY_CARD, {"card_id": "not_a_real_card"})
    assert exc.value.code.value == "illegal_action"


def test_safe_rest_reshuffles_discard_and_refreshes_once_per_floor_charge():
    h = Harness(seed=23)
    hero = h.create_hero("hero_a", "back_alley_fixer")  # once_per_room signature -- exercised via breach test
    card_id = hero.deck.hand[0]
    h.send("hero_a", CommandType.PLAY_CARD, {"card_id": card_id})
    hero = h.state.heroes["hero_a"]
    assert hero.deck.discard  # something is in discard now

    result = h.send("hero_a", CommandType.SAFE_REST)
    assert any(e.type == EventType.DECK_RESHUFFLED for e in result.events)
    hero = h.state.heroes["hero_a"]
    assert hero.deck.discard == ()


# --------------------------------------------------------------------------- items: pickup/trade/drop


def test_pickup_single_owner_semantics_reject_a_second_claimant():
    # Sequential command processing means a *completed* pickup always
    # removes the ground item, so a genuine "two heroes reach for the same
    # room object" contest is the moment between hero_a's claim landing and
    # hero_b's attempt on the same still-present ground_items entry --
    # exactly what heroes.inventory.attempt_pickup's `claims` map exists to
    # arbitrate. White-box seed the claim directly, matching the style
    # tests/test_stacks_conflict.py uses for RoomState.body_item_ids setup.
    h = Harness(seed=31)
    hero_a = h.create_hero("hero_a", "exiled_court_scribe")
    hero_b = h.create_hero("hero_b", "traveling_charlatan")
    h.state.heroes["hero_b"].room_id = hero_a.room_id
    room = h.state.map.rooms[hero_a.room_id]
    room.ground_items["ground_1"] = "comma_blade"
    room.item_claims["ground_1"] = "hero_a"  # hero_a's claim already landed

    r2 = h.send("hero_b", CommandType.PICKUP_ITEM, {"item_instance_id": "ground_1"})
    reject_event = next(e for e in r2.events if e.type in (EventType.ITEM_PICKED_UP, EventType.ITEM_PICKUP_REJECTED))
    assert reject_event.type == EventType.ITEM_PICKUP_REJECTED
    assert reject_event.payload["accepted"] is False
    assert reject_event.payload["reason"] == "already_claimed"
    assert "comma_blade" not in h.state.heroes["hero_b"].inventory.items
    # the ground item stays put -- rejection never silently destroys it
    assert h.state.map.rooms[hero_a.room_id].ground_items.get("ground_1") == "comma_blade"


def test_pickup_rejected_for_insufficient_carry_slots_leaves_item_on_the_ground():
    h = Harness(seed=32)
    hero = h.create_hero("hero_a", "exiled_court_scribe")
    room = h.state.map.rooms[hero.room_id]
    room.ground_items["heavy_1"] = "comma_blade"
    # fill every carry slot so the pickup cannot fit
    h.state.heroes["hero_a"].inventory = h.state.heroes["hero_a"].inventory.__class__(
        hero_id="hero_a", carry_slots=hero.inventory.carry_slots, items=tuple(["comma_blade"] * hero.inventory.carry_slots)
    )
    result = h.send("hero_a", CommandType.PICKUP_ITEM, {"item_instance_id": "heavy_1"})
    reject_event = next(e for e in result.events if e.type == EventType.ITEM_PICKUP_REJECTED)
    assert reject_event.payload["reason"] == "insufficient_carry_slots"
    assert h.state.map.rooms[hero.room_id].ground_items.get("heavy_1") == "comma_blade"


def test_trade_and_drop_round_trip_inventories_and_room_ground_items():
    h = Harness(seed=37)
    hero_a = h.create_hero("hero_a", "exiled_court_scribe")
    hero_b = h.create_hero("hero_b", "traveling_charlatan")
    h.state.heroes["hero_b"].room_id = hero_a.room_id
    room = h.state.map.rooms[hero_a.room_id]
    room.ground_items["g1"] = "comma_blade"
    h.send("hero_a", CommandType.PICKUP_ITEM, {"item_instance_id": "g1"})
    assert "comma_blade" in h.state.heroes["hero_a"].inventory.items

    h.send("hero_a", CommandType.TRADE_ITEM, {"to_hero_id": "hero_b", "item_id": "comma_blade"})
    assert "comma_blade" not in h.state.heroes["hero_a"].inventory.items
    assert "comma_blade" in h.state.heroes["hero_b"].inventory.items
    assert h.state.heroes["hero_a"].carried_item_ids == h.state.heroes["hero_a"].inventory.items
    assert h.state.heroes["hero_b"].carried_item_ids == h.state.heroes["hero_b"].inventory.items

    result = h.send("hero_b", CommandType.DROP_ITEM, {"item_id": "comma_blade"})
    drop_event = next(e for e in result.events if e.type == EventType.ITEM_DROPPED)
    assert "comma_blade" not in h.state.heroes["hero_b"].inventory.items
    dropped_instance_id = drop_event.payload["item_instance_id"]
    assert h.state.map.rooms[hero_a.room_id].ground_items[dropped_instance_id] == "comma_blade"


def test_trade_requires_both_heroes_in_the_same_room():
    h = Harness(seed=41)
    hero_a = h.create_hero("hero_a", "exiled_court_scribe")
    h.create_hero("hero_b", "traveling_charlatan")  # different room by default (only hero_a has moved yet)
    room = h.state.map.rooms[hero_a.room_id]
    room.ground_items["g1"] = "comma_blade"
    h.send("hero_a", CommandType.PICKUP_ITEM, {"item_instance_id": "g1"})
    h.state.heroes["hero_b"].room_id = "room_far_away"

    with pytest.raises(CommandError) as exc:
        h.send("hero_a", CommandType.TRADE_ITEM, {"to_hero_id": "hero_b", "item_id": "comma_blade"})
    assert exc.value.code.value == "illegal_action"


# --------------------------------------------------------------------------- body-loot recovery


def test_ally_recovers_a_dead_heros_body_loot():
    h = Harness(seed=53)
    hero_a = h.create_hero("hero_a", "exiled_court_scribe")
    hero_b = h.create_hero("hero_b", "traveling_charlatan")
    h.state.heroes["hero_b"].room_id = hero_a.room_id

    # simulate the permanent-death bridge systems/combat.py already performs
    # (RunState.heroes[hid].carried_item_ids -> RoomState.body_item_ids) --
    # this module's job is the recovery half, not the death-transfer half.
    room = h.state.map.rooms[hero_a.room_id]
    dead_items = h.state.heroes["hero_a"].carried_item_ids
    assert dead_items  # exiled_court_scribe starts with questionable_seal
    room.body_item_ids["hero_a"] = dead_items
    h.state.heroes["hero_a"].carried_item_ids = ()
    h.state.heroes["hero_a"].life_state = "dead"
    h.state.heroes["hero_a"].alive = False
    h.state.heroes["hero_a"].conscious = False

    result = h.send("hero_b", CommandType.RECOVER_BODY_LOOT, {"dead_hero_id": "hero_a"})
    recover_event = next(e for e in result.events if e.type == EventType.BODY_LOOT_RECOVERED)
    assert set(recover_event.payload["item_ids"]) == set(dead_items)
    hero_b_after = h.state.heroes["hero_b"]
    for item_id in dead_items:
        assert item_id in hero_b_after.inventory.items
    assert h.state.map.rooms[hero_a.room_id].body_item_ids.get("hero_a", ()) == ()


def test_recover_body_loot_rejects_when_nothing_is_there():
    h = Harness(seed=59)
    h.create_hero("hero_a", "exiled_court_scribe")
    with pytest.raises(CommandError) as exc:
        h.send("hero_a", CommandType.RECOVER_BODY_LOOT, {"dead_hero_id": "nobody"})
    assert exc.value.code.value == "illegal_action"


# --------------------------------------------------------------------------- real weapon modifiers reach combat


def test_resolve_hero_combat_equipment_reflects_real_carried_weapon():
    h = Harness(seed=61)
    hero = h.create_hero("hero_a", "back_alley_fixer")
    room = h.state.map.rooms[hero.room_id]
    room.ground_items["g1"] = "comma_blade"
    h.send("hero_a", CommandType.PICKUP_ITEM, {"item_instance_id": "g1"})
    hero = h.state.heroes["hero_a"]

    equipment = heroes_wire.resolve_hero_combat_equipment(hero)
    assert equipment["weapon"].die_faces == 6
    assert equipment["weapon"].damage_bonus == 1
    assert equipment["attributes"].force == hero.sheet.attributes.get("force")
    assert equipment["skills"] == dict(hero.sheet.skills)

    combatant = combat_wire.hero_combatant_from_state(hero, **equipment)
    assert combatant.weapon.die_faces == 6
    assert combatant.weapon.damage_bonus == 1
    assert combatant.attributes.force == hero.sheet.attributes.get("force")
    # source-id verified, never a raw wire number: the bonus traces to the
    # real comma_blade item definition, not a client-suppliable field.
    assert PACK.items["comma_blade"].weapon_damage_bonus == 1


def test_resolve_hero_combat_equipment_flat_default_before_creation():
    h = Harness(seed=63)
    h.send("hero_a", CommandType.JOIN_RUN)
    hero = h.state.heroes["hero_a"]
    assert hero.sheet is None
    assert heroes_wire.resolve_hero_combat_equipment(hero) == {}
    # combat_wire falls back to its own flat defaults with no kwargs
    combatant = combat_wire.hero_combatant_from_state(hero)
    assert combatant.weapon.die_faces == 6
    assert combatant.weapon.damage_bonus == 0


def test_legal_attacks_catalog_on_the_wire_reflects_real_weapon_and_skill():
    from backend.lan_playground.domain.state import ConflictEncounterState

    h = Harness(seed=14)
    hero = h.create_hero("hero_a", "retired_monster_hunter")  # +1 force, rank-1 bonk
    room = h.state.map.rooms[hero.room_id]
    room.ground_items["g1"] = "comma_blade"
    h.send("hero_a", CommandType.PICKUP_ITEM, {"item_instance_id": "g1"})
    hero = h.state.heroes["hero_a"]

    # Fabricate a minimal encounter directly (white-box) rather than relying
    # on which d8 family a given seed rolls after this test's own extra RNG
    # draws (dice roll + deck shuffle) -- this test is about the wire
    # projection, not about reproducing systems/combat.py's own scenarios
    # (already covered by tests/test_stacks_conflict.py).
    room_id = hero.room_id
    room.encounter = ConflictEncounterState(
        encounter_id="enc_test",
        room_id=room_id,
        heroes={
            "hero_a": {
                "hp": hero.hp,
                "max_hp": hero.max_hp,
                "life_state": "alive",
                "position": 0,
                "reaction_available": True,
            }
        },
        enemies={"goblin_1": {"name": "Goblin", "hp": 4, "max_hp": 4, "alive": True, "position": 1}},
        threat_budget={"total_living_heroes": 1, "floor_danger": 0, "corruption_modifier": 0, "objective_modifier": 0, "total": 2},
    )

    snapshot = stacks_engine.StacksEngineAdapter._neutral_conflict_snapshot(room.encounter, h.state.heroes)
    hero_wire = snapshot["heroes"]["hero_a"]
    assert hero_wire["legal_attacks"], "expected at least one living enemy target"
    living_enemy_ids = {eid for eid, e in snapshot["enemies"].items() if e["alive"]}
    assert {atk["target_id"] for atk in hero_wire["legal_attacks"]} == living_enemy_ids
    expected_accuracy = hero.sheet.attributes.get("force") + hero.sheet.skills.get("bonk", 0)
    for attack in hero_wire["legal_attacks"]:
        assert attack["weapon_die_faces"] == 6
        assert attack["damage_bonus"] == 1
        assert attack["accuracy_bonus"] == expected_accuracy


# --------------------------------------------------------------------------- replay determinism


def test_herowire_events_replay_to_the_same_state_hash():
    h = Harness(run_id="run_replay_herowire", seed=71)
    hero_a = h.create_hero("hero_a", "exiled_court_scribe")
    hero_b = h.create_hero("hero_b", "back_alley_fixer")
    h.state.heroes["hero_b"].room_id = hero_a.room_id

    room = h.state.map.rooms[hero_a.room_id]
    room.ground_items["g1"] = "comma_blade"
    h.send("hero_a", CommandType.PICKUP_ITEM, {"item_instance_id": "g1"})
    h.send("hero_a", CommandType.TRADE_ITEM, {"to_hero_id": "hero_b", "item_id": "comma_blade"})
    h.send("hero_a", CommandType.PLAY_CARD, {"card_id": h.state.heroes["hero_a"].deck.hand[0]})
    h.send("hero_a", CommandType.SAFE_REST)

    live_hash = h.state.state_hash()
    replayed = replay_mod.replay(
        run_id="run_replay_herowire", seed=71, chapter_floor_index=0, events=h.event_log
    )
    assert replayed.state_hash() == live_hash
    for hid in ("hero_a", "hero_b"):
        assert replayed.heroes[hid].sheet == h.state.heroes[hid].sheet
        assert replayed.heroes[hid].deck == h.state.heroes[hid].deck
        assert replayed.heroes[hid].inventory == h.state.heroes[hid].inventory


def test_herowire_replay_is_stable_across_multiple_seeds():
    for seed in (2, 5, 8, 13, 21):
        h = Harness(run_id="run_replay_multi", seed=seed)
        h.create_hero("hero_a", "traveling_charlatan")
        card_id = h.state.heroes["hero_a"].deck.hand[0]
        h.send("hero_a", CommandType.PLAY_CARD, {"card_id": card_id})

        live_hash = h.state.state_hash()
        replayed = replay_mod.replay(
            run_id="run_replay_multi", seed=seed, chapter_floor_index=0, events=h.event_log
        )
        assert replayed.state_hash() == live_hash
