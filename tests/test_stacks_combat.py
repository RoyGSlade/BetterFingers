"""Combat core tests (infinite_stacks.md §14-16). See docs/INFINITE_STACKS_COMBAT.md.

backend.lan_playground.combat is standalone this wave -- no reducer/transport
wiring exists yet (wave 3), so these tests drive the package's own modules
and combat/encounter.py's orchestration helpers directly.
"""
from __future__ import annotations

import pytest

from backend.lan_playground.combat import (
    actions,
    encounter as encounter_mod,
    events as events_mod,
    initiative,
    intents,
    lifecycle,
    maneuvers,
    reactions,
    statuses,
    threat,
)
from backend.lan_playground.combat.models import (
    Attributes,
    EnemyCombatant,
    HeroCombatant,
    LifeState,
    Weapon,
)
from backend.lan_playground.content import loader as content_loader

# --------------------------------------------------------------------------- helpers


def make_hero(hero_id, *, force=2, finesse=2, insight=2, presence=2, skills=None,
              die_faces=6, damage_bonus=0, accuracy_bonus=0, equipment_defense_bonus=0,
              equipment_accuracy_bonus=0, equipment_damage_bonus=0, max_hp=None):
    attrs = Attributes(force=force, finesse=finesse, insight=insight, presence=presence)
    hp = max_hp if max_hp is not None else 8 + 2 * force
    return HeroCombatant(
        hero_id=hero_id,
        name=hero_id,
        attributes=attrs,
        max_hp=hp,
        skills=dict(skills or {}),
        equipment_defense_bonus=equipment_defense_bonus,
        equipment_accuracy_bonus=equipment_accuracy_bonus,
        equipment_damage_bonus=equipment_damage_bonus,
        weapon=Weapon(die_faces=die_faces, damage_bonus=damage_bonus, accuracy_bonus=accuracy_bonus),
    )


def make_enemy(instance_id, *, def_id=None, hp=10, defense=12, threat_cost=2,
                threat_tier="standard", resists=(), weaknesses=(), converts=None, initiative_bonus=0):
    return EnemyCombatant(
        instance_id=instance_id,
        def_id=def_id or instance_id,
        name=instance_id,
        family="test",
        max_hp=hp,
        defense=defense,
        threat_cost=threat_cost,
        threat_tier=threat_tier,
        initiative_bonus=initiative_bonus,
        resists=resists,
        weaknesses=weaknesses,
        converts=converts or {},
    )


def new_sequencer(encounter_id="enc_test"):
    return events_mod.EventSequencer(encounter_id)


class ScriptedRNG:
    """Pops scripted values in order; falls back to a fixed value once the
    queue for that draw kind is exhausted, so long-running loop tests don't
    need to script every single roll."""

    def __init__(self, d20=None, randints=None, fallback_d20=10, fallback_randint_is_min=True):
        self._d20 = list(d20 or [])
        self._randints = list(randints or [])
        self._fallback_d20 = fallback_d20
        self._fallback_randint_is_min = fallback_randint_is_min

    def roll_d20(self):
        return self._d20.pop(0) if self._d20 else self._fallback_d20

    def randint(self, a, b):
        if self._randints:
            return self._randints.pop(0)
        return a if self._fallback_randint_is_min else b

    def choice(self, seq):
        return seq[0]

    def shuffled(self, seq):
        return list(seq)


class MinRollRNG:
    """Every d20 comes up 1; every damage/randint draw comes up at the
    minimum. Used to rig encounters so the outcome is guaranteed regardless
    of roll variance -- the test proves the *state machine*, not luck."""

    def roll_d20(self):
        return 1

    def randint(self, a, b):
        return a

    def choice(self, seq):
        return seq[0]

    def shuffled(self, seq):
        return list(seq)


# --------------------------------------------------------------------------- initiative


def test_initiative_deterministic_tie_rules():
    hero_a = make_hero("hero_a", finesse=3)
    hero_b = make_hero("hero_b", finesse=1)
    enemy_a = make_enemy("enemy_a", initiative_bonus=3)
    enemy_b = make_enemy("enemy_b", initiative_bonus=3)

    rng = ScriptedRNG(d20=[10, 10, 10, 10])  # everyone rolls the same die
    seq = new_sequencer()
    order, events = initiative.roll_initiative(
        [hero_a, hero_b, enemy_a, enemy_b], rng, combat_round=1, sequencer=seq, caused_by="test"
    )
    ids = [e.combatant_id for e in order]
    # hero_a (bonus 3, total 13) ties enemy_a/enemy_b (bonus 3, total 13) -> heroes-first tiebreak puts hero_a
    # ahead of both enemies; enemy_a vs enemy_b tie broken by id ascending; hero_b (bonus 1, total 11) is last.
    assert ids == ["hero_a", "enemy_a", "enemy_b", "hero_b"]
    assert len(events) == 4
    assert all(e["type"] == "initiative_rolled" for e in events)


def test_initiative_events_carry_roll_and_total():
    hero = make_hero("hero_a", finesse=4)
    rng = ScriptedRNG(d20=[7])
    seq = new_sequencer()
    order, events = initiative.roll_initiative([hero], rng, combat_round=1, sequencer=seq, caused_by="test")
    assert order[0].total == 11
    assert events[0]["payload"] == {"roll": 7, "bonus": 4, "total": 11}


def test_integrate_joiners_enters_at_next_cycle_not_mid_round():
    hero_a = make_hero("hero_a", finesse=5)
    joiner = make_hero("hero_b", finesse=5)
    rng = ScriptedRNG(d20=[10, 10])
    seq = new_sequencer()
    order, _ = initiative.roll_initiative([hero_a], rng, combat_round=1, sequencer=seq, caused_by="test")
    assert [e.combatant_id for e in order] == ["hero_a"]

    merged, events = initiative.integrate_joiners(
        order, [joiner], rng, combat_round=2, sequencer=seq, caused_by="test"
    )
    assert {e.combatant_id for e in merged} == {"hero_a", "hero_b"}
    assert any(e["type"] == "joiner_entered" and e["actor_id"] == "hero_b" for e in events)


# --------------------------------------------------------------------------- actions / attack


def test_turn_budget_enforces_one_of_each():
    hero = make_hero("hero_a")
    budget = actions.TurnBudget(hero_id="hero_a")
    budget.mark_movement()
    with pytest.raises(actions.TurnBudgetError):
        budget.mark_movement()
    budget.mark_quick_interaction()
    with pytest.raises(actions.TurnBudgetError):
        budget.mark_quick_interaction()
    budget.mark_main_action()
    with pytest.raises(actions.TurnBudgetError):
        budget.mark_main_action()


def test_attack_hits_and_deals_weapon_die_plus_bonus_damage():
    hero = make_hero("hero_a", force=3, skills={"bonk": 2}, die_faces=6, damage_bonus=1)
    enemy = make_enemy("enemy_a", defense=10, hp=20)
    rng = ScriptedRNG(d20=[10], randints=[4])  # attack roll 10, damage die 4
    seq = new_sequencer()
    budget = actions.TurnBudget(hero_id="hero_a")
    result = actions.attack(
        hero, enemy, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=seq, caused_by="test", budget=budget,
    )
    # total = 10 (die) + 3 (force) + 2 (bonk) = 15 >= 10 defense -> hit
    assert result.hit is True
    assert result.total == 15
    assert result.damage == 4 + 1  # weapon die + damage_bonus
    assert enemy.hp == 20 - 5
    assert budget.main_action_used is True
    assert any(e["type"] == "attack_resolved" for e in result.events)
    assert any(e["type"] == "damage_applied" for e in result.events)


def test_attack_miss_deals_no_damage():
    hero = make_hero("hero_a", force=1, skills={})
    enemy = make_enemy("enemy_a", defense=30, hp=20)
    rng = ScriptedRNG(d20=[2])
    seq = new_sequencer()
    budget = actions.TurnBudget(hero_id="hero_a")
    result = actions.attack(
        hero, enemy, attribute="force", skill=None, rng=rng,
        combat_round=1, sequencer=seq, caused_by="test", budget=budget,
    )
    assert result.hit is False
    assert result.damage == 0
    assert enemy.hp == 20
    assert not any(e["type"] == "damage_applied" for e in result.events)


def test_attack_defense_formula_matches_spec():
    hero = make_hero("hero_a", finesse=3, equipment_defense_bonus=2)
    assert hero.defense == 10 + 3 + 2


def test_equipment_accuracy_and_damage_bonus_fold_into_attack_math():
    hero = make_hero(
        "hero_a", force=2, skills={"bonk": 1}, die_faces=6, damage_bonus=1, accuracy_bonus=1,
        equipment_accuracy_bonus=3, equipment_damage_bonus=2,
    )
    enemy = make_enemy("enemy_a", defense=10, hp=50)
    rng = ScriptedRNG(d20=[5], randints=[3])
    budget = actions.TurnBudget(hero_id="hero_a")
    result = actions.attack(
        hero, enemy, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=budget,
    )
    # total = 5(die) + 2(force) + 1(bonk) + 1(weapon accuracy) + 3(equipment accuracy) = 12 >= 10 -> hit
    assert result.total == 12
    assert result.hit is True
    # damage = 3(die) + 1(weapon damage) + 2(equipment damage) = 6
    assert result.damage == 6


# --------------------------------------------------------------------------- maneuvers


def _attack_budget():
    return actions.TurnBudget(hero_id="attacker")


def test_maneuver_disarm_reduces_damage_and_removes_held_item():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3}, die_faces=8, damage_bonus=4)
    defender = make_hero("hero_b")
    defender.held_item = "torch"
    rng = ScriptedRNG(d20=[15], randints=[8])
    result = maneuvers.disarm(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=_attack_budget(),
    )
    assert result.hit is True
    assert result.attack.damage == round((8 + 4) * 0.5)
    assert defender.held_item is None
    assert result.secondary_effect == "torch"


def test_maneuver_trip_inflicts_prone_on_hit():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3})
    defender = make_enemy("enemy_a", defense=8)
    rng = ScriptedRNG(d20=[15], randints=[3])
    result = maneuvers.trip(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=_attack_budget(),
    )
    assert result.hit is True
    assert statuses.has_status(defender, "prone")


def test_maneuver_drive_back_moves_target_full_damage():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3}, die_faces=8, damage_bonus=0)
    defender = make_enemy("enemy_a", defense=8)
    defender.position = 0
    rng = ScriptedRNG(d20=[15], randints=[5])
    result = maneuvers.drive_back(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=_attack_budget(), push_distance=2,
    )
    assert result.hit is True
    assert defender.position == 2
    assert result.attack.damage == 5  # full weapon-die damage, not halved


def test_maneuver_break_targets_named_component():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3})
    defender = make_enemy("enemy_a", defense=8, hp=30)
    rng = ScriptedRNG(d20=[15], randints=[4])
    result = maneuvers.break_object(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=_attack_budget(), component="shield",
    )
    assert result.hit is True
    assert result.secondary_effect == "shield"
    assert any(e["type"] == "maneuver_resolved" and e["payload"]["component"] == "shield" for e in result.events)


def test_maneuver_crushing_blow_adds_weapon_die_on_hit_and_exposes_on_miss():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3}, die_faces=6, damage_bonus=0)
    defender = make_enemy("enemy_a", defense=8, hp=100)
    rng = ScriptedRNG(d20=[15], randints=[3, 3])  # two weapon dice on a hit
    result = maneuvers.crushing_blow(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=_attack_budget(),
    )
    assert result.hit is True
    assert result.attack.damage == 6  # two d6 draws of 3 each

    attacker2 = make_hero("hero_c", force=1, skills={})
    defender2 = make_enemy("enemy_b", defense=30)
    rng_miss = ScriptedRNG(d20=[2])
    result_miss = maneuvers.crushing_blow(
        attacker2, defender2, attribute="force", skill=None, rng=rng_miss,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=_attack_budget(),
    )
    assert result_miss.hit is False
    assert attacker2.exposed_until_next_turn is True


def test_maneuver_rattle_replaces_damage_with_condition():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3})
    defender = make_enemy("enemy_a", defense=8, hp=20)
    rng = ScriptedRNG(d20=[15], randints=[6])
    result = maneuvers.rattle(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=_attack_budget(),
        condition="frightened",
    )
    assert result.hit is True
    assert result.attack.damage == 0
    assert defender.hp == 20  # no physical damage
    assert statuses.has_status(defender, "frightened")


def test_maneuver_resisted_suppresses_secondary_effect():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3})
    defender = make_enemy("enemy_a", defense=8, resists=("trip",))
    rng = ScriptedRNG(d20=[15], randints=[3])
    result = maneuvers.trip(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=_attack_budget(),
    )
    assert result.hit is True
    assert result.resisted is True
    assert not statuses.has_status(defender, "prone")


def test_maneuver_weakness_amplifies_effect():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3})
    defender = make_enemy("enemy_a", defense=8, weaknesses=("drive_back",))
    rng = ScriptedRNG(d20=[15], randints=[3])
    result = maneuvers.drive_back(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=_attack_budget(), push_distance=2,
    )
    assert result.weakness_triggered is True
    assert defender.position == 4  # doubled push distance


# --------------------------------------------------------------------------- reactions


def test_reaction_dodge_avoids_hit_on_success():
    hero = make_hero("hero_a", finesse=5)
    rng = ScriptedRNG(d20=[18])
    success, events = reactions.dodge(
        hero, incoming_attack_total=15, rng=rng, combat_round=1, sequencer=new_sequencer(), caused_by="test",
        new_position=7,
    )
    assert success is True
    assert hero.position == 7
    assert hero.reaction_available is False
    assert any(e["type"] == "moved" for e in events)


def test_reaction_block_reduces_damage_and_may_wear_item():
    hero = make_hero("hero_a")
    rng = ScriptedRNG(randints=[10])  # wear_roll = 10 <= 25 -> took_wear True
    reduced, events = reactions.block(
        hero, incoming_damage=8, item_id="buckler", block_amount=3, rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", wear_chance=0.25,
    )
    assert reduced == 5
    assert events[0]["payload"]["took_wear"] is True


def test_reaction_protect_redirects_declared():
    protector = make_hero("hero_a")
    ally = make_hero("hero_b")
    events = reactions.protect(protector, ally, combat_round=1, sequencer=new_sequencer(), caused_by="test")
    assert protector.reaction_available is False
    assert events[0]["payload"]["reaction"] == "protect"
    assert events[0]["target_id"] == "hero_b"


def test_reaction_counter_requires_permission_and_miss_by_5_or_more():
    hero = make_hero("hero_a", force=4, skills={"bonk": 2})
    enemy = make_enemy("enemy_a", defense=6)

    denied_result, denied_events = reactions.counter(
        hero, enemy, incoming_attack_margin=-3, permitted=True, attribute="force", skill="bonk",
        rng=ScriptedRNG(), combat_round=1, sequencer=new_sequencer(), caused_by="test",
    )
    assert denied_result is None
    assert denied_events[0]["payload"]["outcome"] == "not_available"

    hero2 = make_hero("hero_b", force=4, skills={"bonk": 2})
    rng = ScriptedRNG(d20=[15], randints=[4])
    result, events = reactions.counter(
        hero2, enemy, incoming_attack_margin=-6, permitted=True, attribute="force", skill="bonk",
        rng=rng, combat_round=1, sequencer=new_sequencer(), caused_by="test",
    )
    assert result is not None
    assert result.hit is True


def test_reaction_escape_opposes_hold():
    hero = make_hero("hero_a", finesse=4)
    rng = ScriptedRNG(d20=[15])
    success, events = reactions.escape(
        hero, hold_dc=17, rng=rng, combat_round=1, sequencer=new_sequencer(), caused_by="test",
    )
    assert success is True  # 15 + 4 = 19 >= 17
    assert events[0]["payload"]["outcome"] == "freed"


def test_reaction_prepared_trigger_fires_when_condition_met():
    hero = make_hero("hero_a")
    reactions.set_prepared_trigger(
        hero, {"type": "attack", "target": "enemy_a"}, combat_round=1, sequencer=new_sequencer(), caused_by="test",
    )
    assert hero.prepared_trigger is not None

    fired = []
    events = reactions.execute_prepared_trigger(
        hero, condition_met=True, combat_round=2, sequencer=new_sequencer(), caused_by="test",
        executor=lambda: fired.append("ran") or [],
    )
    assert hero.prepared_trigger is None
    assert fired == ["ran"]
    assert any(e["payload"]["outcome"] == "triggered" for e in events)


def test_reaction_only_one_per_round():
    hero = make_hero("hero_a", finesse=3)
    reactions.use_reaction(hero)
    assert hero.reaction_available is False
    with pytest.raises(reactions.ReactionUnavailableError):
        reactions.use_reaction(hero)
    reactions.refresh_reaction(hero)
    assert hero.reaction_available is True


# --------------------------------------------------------------------------- reaction interrupt window (§14.5, task #14)


def test_interrupt_window_block_reduces_damage_mid_resolution_and_may_wear_item():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3}, die_faces=6, damage_bonus=2)
    defender = make_hero("hero_b", finesse=1)
    rng = ScriptedRNG(d20=[15], randints=[4, 10])  # attack roll, damage die, then block's wear_roll

    def hook(window):
        reduced, events = reactions.block(
            window.defender, window.provisional_damage, item_id="buckler", block_amount=3,
            rng=window.rng, combat_round=window.combat_round, sequencer=window.sequencer,
            caused_by=window.caused_by, wear_chance=0.25,
        )
        return actions.ReactionOutcome(events=events, hit=window.hit, damage=reduced)

    budget = actions.TurnBudget(hero_id="hero_a")
    result = actions.attack(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=budget, reaction_hook=hook,
    )
    assert result.hit is True
    assert result.damage == (4 + 2) - 3  # provisional damage reduced by block_amount
    assert defender.hp == defender.max_hp - result.damage
    block_event = next(e for e in result.events if e["payload"].get("reaction") == "block")
    assert block_event["payload"]["took_wear"] is True
    assert defender.reaction_available is False


def test_interrupt_window_dodge_negates_hit_and_repositions_on_success():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3}, die_faces=6, damage_bonus=2)
    defender = make_hero("hero_b", finesse=10)
    rng = ScriptedRNG(d20=[15, 18], randints=[4])  # attack roll, dodge roll, damage die

    def hook(window):
        success, events = reactions.dodge(
            window.defender, window.incoming_attack_total, window.rng,
            combat_round=window.combat_round, sequencer=window.sequencer, caused_by=window.caused_by,
            new_position=9,
        )
        if success:
            return actions.ReactionOutcome(events=events, hit=False, damage=0)
        return actions.ReactionOutcome(events=events, hit=window.hit, damage=window.provisional_damage)

    budget = actions.TurnBudget(hero_id="hero_a")
    result = actions.attack(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=budget, reaction_hook=hook,
    )
    assert result.hit is False
    assert result.damage == 0
    assert defender.hp == defender.max_hp
    assert defender.position == 9
    assert defender.reaction_available is False
    assert any(e["payload"].get("reaction") == "dodge" for e in result.events)


def test_interrupt_window_dodge_failure_still_lands_and_applies_damage():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3}, die_faces=6, damage_bonus=2)
    defender = make_hero("hero_b", finesse=1)
    rng = ScriptedRNG(d20=[15, 1], randints=[4])  # attack roll, dodge roll (fails), damage die

    def hook(window):
        success, events = reactions.dodge(
            window.defender, window.incoming_attack_total, window.rng,
            combat_round=window.combat_round, sequencer=window.sequencer, caused_by=window.caused_by,
        )
        if success:
            return actions.ReactionOutcome(events=events, hit=False, damage=0)
        return actions.ReactionOutcome(events=events, hit=window.hit, damage=window.provisional_damage)

    budget = actions.TurnBudget(hero_id="hero_a")
    result = actions.attack(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=budget, reaction_hook=hook,
    )
    assert result.hit is True
    assert result.damage == 4 + 2
    assert defender.hp == defender.max_hp - (4 + 2)


def test_interrupt_window_protect_redirects_damage_to_protector():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3}, die_faces=6, damage_bonus=0)
    defender = make_hero("hero_b", finesse=1)
    protector = make_hero("hero_c", finesse=1)
    rng = ScriptedRNG(d20=[15], randints=[4])

    def hook(window):
        assert window.protectors == (protector,)
        p = window.protectors[0]
        events = reactions.protect(
            p, window.defender, combat_round=window.combat_round, sequencer=window.sequencer,
            caused_by=window.caused_by,
        )
        return actions.ReactionOutcome(events=events, hit=window.hit, damage=window.provisional_damage, damage_target=p)

    budget = actions.TurnBudget(hero_id="hero_a")
    result = actions.attack(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=budget,
        reaction_hook=hook, protectors=[protector],
    )
    assert result.hit is True
    assert defender.hp == defender.max_hp  # original target untouched, damage redirected
    assert protector.hp == protector.max_hp - result.damage
    assert protector.reaction_available is False


def test_interrupt_window_offered_via_protector_even_when_defenders_own_reaction_is_spent():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3})
    defender = make_hero("hero_b", finesse=1)
    defender.reaction_available = False
    protector = make_hero("hero_c", finesse=1)
    rng = ScriptedRNG(d20=[15], randints=[4])
    called = []

    def hook(window):
        called.append(window.protectors)
        return None

    budget = actions.TurnBudget(hero_id="hero_a")
    actions.attack(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=budget,
        reaction_hook=hook, protectors=[protector],
    )
    assert called == [(protector,)]


def test_interrupt_window_counter_fires_on_miss_by_5_or_more():
    attacker = make_hero("hero_a", force=1, skills={})
    defender = make_hero("hero_b", finesse=1, force=4, skills={"bonk": 2})
    rng = ScriptedRNG(d20=[2, 15], randints=[4])  # attack roll misses badly, counter roll, counter damage die

    def hook(window):
        if window.hit or window.margin > -5:
            return None
        _, events = reactions.counter(
            window.defender, window.attacker, window.margin, permitted=True,
            attribute="force", skill="bonk", rng=window.rng,
            combat_round=window.combat_round, sequencer=window.sequencer, caused_by=window.caused_by,
        )
        return actions.ReactionOutcome(events=events, hit=window.hit, damage=window.provisional_damage)

    budget = actions.TurnBudget(hero_id="hero_a")
    result = actions.attack(
        attacker, defender, attribute="force", skill=None, rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=budget, reaction_hook=hook,
    )
    assert result.hit is False
    assert result.damage == 0
    assert any(e["payload"].get("action") == "counter" for e in result.events)
    assert attacker.hp == attacker.max_hp - 4  # counter-attack damage landed on the original attacker
    assert defender.reaction_available is False


def test_interrupt_window_hook_returning_none_leaves_resolution_unchanged():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3}, die_faces=6, damage_bonus=1)
    defender = make_hero("hero_b", finesse=1)
    rng = ScriptedRNG(d20=[15], randints=[4])
    result = actions.attack(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=actions.TurnBudget(hero_id="hero_a"),
        reaction_hook=lambda window: None,
    )
    assert result.hit is True
    assert result.damage == 4 + 1
    assert defender.reaction_available is True  # the window was offered but no reaction was taken


def test_interrupt_window_not_offered_when_no_reaction_available():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3})
    defender = make_hero("hero_b", finesse=1)
    defender.reaction_available = False
    rng = ScriptedRNG(d20=[15], randints=[4])
    called = []
    result = actions.attack(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=actions.TurnBudget(hero_id="hero_a"),
        reaction_hook=lambda window: called.append(True) or None,
    )
    assert called == []
    assert result.hit is True


def test_interrupt_window_never_fires_for_enemy_defenders():
    attacker = make_hero("hero_a", force=5, skills={"bonk": 3})
    defender = make_enemy("enemy_a", defense=8, hp=20)
    rng = ScriptedRNG(d20=[15], randints=[4])
    called = []
    result = actions.attack(
        attacker, defender, attribute="force", skill="bonk", rng=rng,
        combat_round=1, sequencer=new_sequencer(), caused_by="test", budget=actions.TurnBudget(hero_id="hero_a"),
        reaction_hook=lambda window: called.append(True) or None,
    )
    assert called == []
    assert result.hit is True


# --------------------------------------------------------------------------- statuses


def test_status_apply_then_treat_removes_it():
    hero = make_hero("hero_a")
    seq = new_sequencer()
    events = statuses.apply_status(
        hero, "bleeding", combat_round=1, sequencer=seq, caused_by="test", target_id="hero_a"
    )
    assert statuses.has_status(hero, "bleeding")
    assert events[0]["type"] == "status_applied"

    events = statuses.treat_status(
        hero, "bleeding", combat_round=2, sequencer=seq, caused_by="test", target_id="hero_a"
    )
    assert not statuses.has_status(hero, "bleeding")
    assert events[0]["type"] == "status_treated"


def test_status_reapplying_same_status_escalates():
    hero = make_hero("hero_a")
    seq = new_sequencer()
    statuses.apply_status(hero, "burning", combat_round=1, sequencer=seq, caused_by="test", target_id="hero_a")
    events = statuses.apply_status(
        hero, "burning", combat_round=2, sequencer=seq, caused_by="test", target_id="hero_a"
    )
    assert hero.statuses["burning"].escalated is True
    assert events[0]["type"] == "status_escalated"


def test_status_third_distinct_status_consolidates_oldest():
    hero = make_hero("hero_a")
    seq = new_sequencer()
    statuses.apply_status(hero, "bleeding", combat_round=1, sequencer=seq, caused_by="test", target_id="hero_a")
    statuses.apply_status(hero, "prone", combat_round=2, sequencer=seq, caused_by="test", target_id="hero_a")
    assert set(hero.statuses) == {"bleeding", "prone"}

    events = statuses.apply_status(
        hero, "sickened", combat_round=3, sequencer=seq, caused_by="test", target_id="hero_a"
    )
    # "bleeding" was applied first (round 1) -> it is the one replaced.
    assert set(hero.statuses) == {"prone", "sickened"}
    assert events[0]["type"] == "status_consolidated"
    assert events[0]["payload"] == {"replaced_status_id": "bleeding", "applied_status_id": "sickened"}


def test_status_damage_amount_only_defined_for_bleeding_and_burning():
    assert statuses.status_damage_amount("burning") == 1
    assert statuses.status_damage_amount("bleeding") == 1
    assert statuses.status_damage_amount("prone") is None


def test_all_nine_statuses_have_one_primary_effect_and_treatment():
    assert len(statuses.STATUS_DEFINITIONS) == 9
    for status_id, definition in statuses.STATUS_DEFINITIONS.items():
        assert definition["primary_effect"], status_id
        assert definition["treatment"], status_id


# --------------------------------------------------------------------------- lifecycle


def test_hero_downed_at_zero_hp():
    hero = make_hero("hero_a", force=1, max_hp=5)
    seq = new_sequencer()
    events = lifecycle.apply_damage(
        hero, 5, combat_round=1, sequencer=seq, caused_by="test", target_id="hero_a"
    )
    assert hero.life_state == LifeState.DOWNED
    assert hero.hp == 0
    assert any(e["type"] == "hero_downed" for e in events)


def test_death_check_three_successes_reaches_stable():
    hero = make_hero("hero_a", force=10, max_hp=1)
    hero.life_state = LifeState.DOWNED
    hero.hp = 0
    seq = new_sequencer()
    rng = ScriptedRNG(d20=[5, 5, 5])  # 5 + force(10) = 15 >= 10 every time -> success
    for _ in range(3):
        events = lifecycle.death_check(hero, rng, combat_round=1, sequencer=seq, caused_by="test")
    assert hero.life_state == LifeState.STABLE
    assert hero.stabilization_successes == 3
    assert any(e["type"] == "hero_stabilized" for e in events)


def test_death_check_three_failures_reaches_permanent_death():
    hero = make_hero("hero_a", force=1, max_hp=1)
    hero.life_state = LifeState.DOWNED
    hero.hp = 0
    seq = new_sequencer()
    rng = ScriptedRNG(d20=[1, 1, 1])  # 1 + force(1) = 2 < 10 every time -> failure
    for _ in range(3):
        events = lifecycle.death_check(hero, rng, combat_round=1, sequencer=seq, caused_by="test")
    assert hero.life_state == LifeState.DEAD
    assert hero.death_failures == 3
    assert any(e["type"] == "hero_died" for e in events)


def test_damage_while_downed_adds_a_death_check_failure():
    hero = make_hero("hero_a", force=5, max_hp=10)
    hero.life_state = LifeState.DOWNED
    hero.hp = 0
    seq = new_sequencer()
    events = lifecycle.apply_damage(
        hero, 3, combat_round=1, sequencer=seq, caused_by="test", target_id="hero_a"
    )
    assert hero.life_state == LifeState.DOWNED
    assert hero.death_failures == 1
    assert any(
        e["type"] == "death_check_resolved" and e["payload"].get("reason") == "damage_while_downed"
        for e in events
    )


def test_stabilize_directly_and_revive():
    hero = make_hero("hero_a", force=2, max_hp=10)
    hero.life_state = LifeState.DOWNED
    hero.hp = 0
    seq = new_sequencer()
    lifecycle.stabilize_directly(hero, combat_round=1, sequencer=seq, caused_by="test", reason="ally_aid")
    assert hero.life_state == LifeState.STABLE

    events = lifecycle.revive(hero, combat_round=2, sequencer=seq, caused_by="test", to_hp=1)
    assert hero.life_state == LifeState.ALIVE
    assert hero.hp == 1
    assert hero.stabilization_successes == 0
    assert hero.death_failures == 0
    assert any(e["type"] == "hero_revived" for e in events)


def test_party_wiped_true_only_when_no_hero_alive():
    a = make_hero("hero_a")
    b = make_hero("hero_b")
    a.life_state = LifeState.DOWNED
    assert lifecycle.party_wiped([a, b]) is False
    b.life_state = LifeState.DEAD
    assert lifecycle.party_wiped([a, b]) is True


# --------------------------------------------------------------------------- status ticks (§16.4 round boundary, task #14)


def test_tick_status_damage_applies_bleeding_and_burning_via_apply_damage():
    hero_a = make_hero("hero_a", max_hp=20)
    hero_b = make_hero("hero_b", max_hp=20)
    enemy = make_enemy("enemy_a", hp=20)
    seq = new_sequencer()
    statuses.apply_status(hero_a, "bleeding", combat_round=1, sequencer=seq, caused_by="test", target_id="hero_a")
    statuses.apply_status(hero_b, "burning", combat_round=1, sequencer=seq, caused_by="test", target_id="hero_b")
    statuses.apply_status(enemy, "burning", combat_round=1, sequencer=seq, caused_by="test", target_id="enemy_a")
    encounter = encounter_mod.Encounter(
        encounter_id="enc_tick", heroes={"hero_a": hero_a, "hero_b": hero_b}, enemies={"enemy_a": enemy},
        sequencer=seq, combat_round=1,
    )
    events = encounter_mod.tick_status_damage(encounter, caused_by="test")
    assert hero_a.hp == 19
    assert hero_b.hp == 19
    assert enemy.hp == 19
    damage_events = [e for e in events if e["type"] == "damage_applied"]
    assert len(damage_events) == 3
    # deterministic order: heroes (id-sorted) before enemies (id-sorted)
    assert [e["target_id"] for e in damage_events] == ["hero_a", "hero_b", "enemy_a"]
    assert all(e["payload"]["source"] in ("bleeding_tick", "burning_tick") for e in damage_events)


def test_tick_skips_combatants_without_bleeding_or_burning():
    hero = make_hero("hero_a", max_hp=20)
    seq = new_sequencer()
    statuses.apply_status(hero, "prone", combat_round=1, sequencer=seq, caused_by="test", target_id="hero_a")
    encounter = encounter_mod.Encounter(
        encounter_id="enc_tick_none", heroes={"hero_a": hero}, enemies={}, sequencer=seq, combat_round=1,
    )
    events = encounter_mod.tick_status_damage(encounter, caused_by="test")
    assert hero.hp == 20
    assert events == []


def test_tick_on_downed_hero_adds_death_check_failure():
    hero = make_hero("hero_a", max_hp=10)
    hero.life_state = LifeState.DOWNED
    hero.hp = 0
    seq = new_sequencer()
    statuses.apply_status(hero, "bleeding", combat_round=1, sequencer=seq, caused_by="test", target_id="hero_a")
    encounter = encounter_mod.Encounter(
        encounter_id="enc_tick_downed", heroes={"hero_a": hero}, enemies={}, sequencer=seq, combat_round=1,
    )
    events = encounter_mod.tick_status_damage(encounter, caused_by="test")
    assert hero.life_state == LifeState.DOWNED
    assert hero.death_failures == 1
    assert any(
        e["type"] == "death_check_resolved" and e["payload"].get("reason") == "damage_while_downed"
        for e in events
    )


def test_advance_round_auto_ticks_statuses_at_the_round_boundary():
    hero = make_hero("hero_a", max_hp=20, finesse=3)
    encounter, _ = encounter_mod.start_encounter("enc_tick_auto", [hero], [], MinRollRNG())
    statuses.apply_status(
        hero, "burning", combat_round=encounter.combat_round, sequencer=encounter.sequencer, caused_by="test",
        target_id="hero_a",
    )
    events = encounter_mod.advance_round(encounter, MinRollRNG(), caused_by="test")
    assert hero.hp == 19
    assert any(
        e["type"] == "damage_applied" and e["payload"]["source"] == "burning_tick" for e in events
    )


# --------------------------------------------------------------------------- threat budget


def test_threat_budget_formula_uses_total_living_heroes_not_present_heroes():
    budget = threat.calculate_threat_budget(4, floor_danger=1, corruption_modifier=2, objective_modifier=-1)
    assert budget.total == 2 * 4 + 1 + 2 - 1


def test_roster_cost_sums_living_enemies_only():
    e1 = make_enemy("e1", threat_cost=1)
    e2 = make_enemy("e2", threat_cost=3)
    e2.alive = False
    assert threat.roster_cost([e1, e2]) == 1


def test_reinforcement_spending_only_affords_what_budget_allows():
    candidates = [make_enemy("e1", threat_cost=2), make_enemy("e2", threat_cost=3), make_enemy("e3", threat_cost=2)]
    wave, events = threat.schedule_reinforcements(
        4, candidates, arrival_combat_round=3, combat_round=1, sequencer=new_sequencer(), caused_by="test",
    )
    # e1 (cost 2) fits, e2 (cost 3) doesn't (2+3=5>4), e3 (cost 2) fits (2+2=4<=4)
    assert [e.instance_id for e in wave.enemies] == ["e1", "e3"]
    assert wave.cost == 4
    assert events[0]["type"] == "reinforcements_scheduled"


# --------------------------------------------------------------------------- intents (data-driven from real content)


def test_intents_are_data_driven_from_real_enemies_yaml():
    pack = content_loader.load_core_pack()
    firestarter_def = pack.enemies["goblin_firestarter"]
    enemy, intent_defs = intents.build_enemy_combatant(firestarter_def, instance_id="enemy_1")
    assert enemy.threat_cost == 1
    assert {i.id for i in intent_defs} == {"mark_shelf", "ignite_shelf"}

    chosen = intents.select_intent(intent_defs, frozenset())
    assert chosen.id == "mark_shelf"  # only the "always" intent matches with no facts yet

    chosen_after_mark = intents.select_intent(intent_defs, frozenset({"shelf_marked"}))
    assert chosen_after_mark.id == "ignite_shelf"  # conditional intent beats the "always" fallback

    target = make_hero("hero_a", max_hp=20)
    seq = new_sequencer()
    telegraph_events = intents.telegraph_intent(
        enemy, chosen_after_mark, combat_round=1, sequencer=seq, caused_by="test"
    )
    assert telegraph_events[0]["type"] == "intent_telegraphed"
    assert telegraph_events[0]["payload"]["counterplay"]

    effect_events = intents.resolve_intent_effects(
        chosen_after_mark, enemy, target, combat_round=1, sequencer=seq, caused_by="test"
    )
    assert statuses.has_status(target, "burning")
    assert any(e["type"] == "status_applied" for e in effect_events)


def test_intent_selection_is_deterministic_not_rng_driven():
    pack = content_loader.load_core_pack()
    bruiser_def = pack.enemies["goblin_bruiser"]
    enemy, intent_defs = intents.build_enemy_combatant(bruiser_def, instance_id="enemy_1")
    # "hero_near_exit" trigger should win over the "always" heavy_swing fallback.
    chosen = intents.select_intent(intent_defs, frozenset({"hero_near_exit"}))
    assert chosen.id == "shove_back"
    chosen_default = intents.select_intent(intent_defs, frozenset())
    assert chosen_default.id == "heavy_swing"


# --------------------------------------------------------------------------- full encounters


def _basic_intent_defs(damage_amount):
    return (
        intents.EnemyIntentDef(
            id="basic_attack",
            trigger="always",
            effects=({"op": "damage", "args": {"amount": damage_amount}},),
            counterplay="Dodge, Block, or reduce the threat before it lands.",
            telegraph_text="The enemy prepares to strike.",
            accessible_text="Intent: Basic Attack. The enemy prepares to strike the nearest hero.",
        ),
    )


def _run_simple_fight(encounter, rng, *, max_rounds, hero_intents):
    """Deterministic scripted policy: each active hero attacks the first
    living enemy; each living enemy runs its single 'basic_attack' intent
    against the first active hero. Loop until victory, party wipe, or
    max_rounds is reached (returned to the caller as a safety check)."""
    all_events: list[dict] = []
    while encounter.combat_round <= max_rounds:
        living_ids = {h.hero_id for h in encounter_mod.active_heroes(encounter)} | {
            e.instance_id for e in encounter_mod.living_enemies(encounter)
        }
        for entry in initiative.active_order(encounter.order, living_ids):
            cid = entry.combatant_id
            if cid in encounter.heroes:
                hero = encounter.heroes[cid]
                if hero.life_state != LifeState.ALIVE:
                    continue
                targets = encounter_mod.living_enemies(encounter)
                if not targets:
                    continue
                budget, start_event = actions.start_turn(
                    cid, combat_round=encounter.combat_round, sequencer=encounter.sequencer, caused_by="test"
                )
                all_events.append(start_event)
                result = actions.attack(
                    hero, targets[0], attribute="force", skill="bonk", rng=rng,
                    combat_round=encounter.combat_round, sequencer=encounter.sequencer, caused_by="test",
                    budget=budget,
                )
                all_events.extend(result.events)
            else:
                enemy = encounter.enemies[cid]
                if not enemy.alive:
                    continue
                targets = encounter_mod.active_heroes(encounter)
                if not targets:
                    continue
                intent_defs = hero_intents(enemy)
                chosen = intents.select_intent(intent_defs, frozenset())
                all_events.extend(
                    intents.telegraph_intent(
                        enemy, chosen, combat_round=encounter.combat_round, sequencer=encounter.sequencer,
                        caused_by="test",
                    )
                )
                all_events.extend(
                    intents.resolve_intent_effects(
                        chosen, enemy, targets[0], combat_round=encounter.combat_round,
                        sequencer=encounter.sequencer, caused_by="test",
                    )
                )
            if encounter_mod.is_victory(encounter) or encounter_mod.is_party_wiped(encounter):
                break
        if encounter_mod.is_victory(encounter) or encounter_mod.is_party_wiped(encounter):
            break
        all_events.extend(encounter_mod.advance_round(encounter, rng, caused_by="test"))
    return all_events


def test_full_party_fight_to_victory():
    heroes = [
        make_hero(f"hero_{i}", force=5, skills={"bonk": 3}, die_faces=4, damage_bonus=6)
        for i in range(4)
    ]
    # attack total minimum = 1(die) + 5(force) + 3(bonk) = 9 >= enemy defense(8) -> always hits
    # damage minimum = 1(die) + 6(bonus) = 7 > enemy hp(6) -> always one-shots
    enemies = [make_enemy(f"enemy_{i}", hp=6, defense=8, threat_cost=1, threat_tier="minion") for i in range(4)]

    budget = threat.calculate_threat_budget(len(heroes))
    assert threat.roster_cost(enemies) <= budget.total

    rng = MinRollRNG()
    encounter, start_events = encounter_mod.start_encounter("enc_victory", heroes, enemies, rng)
    fight_events = _run_simple_fight(encounter, rng, max_rounds=20, hero_intents=lambda e: _basic_intent_defs(1))

    assert encounter_mod.is_victory(encounter)
    assert not encounter_mod.is_party_wiped(encounter)
    assert all(h.life_state == LifeState.ALIVE for h in heroes)
    assert any(e["type"] == "enemy_defeated" for e in start_events + fight_events)


def test_full_party_fight_to_total_party_kill():
    heroes = [make_hero(f"hero_{i}", force=1, finesse=1, skills={}, die_faces=4) for i in range(4)]
    # attack total max = 20(die) + 1(force) = 21 < enemy defense(25) -> heroes can never hit
    enemies = [make_enemy("enemy_boss", hp=200, defense=25, threat_cost=5, threat_tier="elite")]

    rng = MinRollRNG()  # also drives death checks: 1 + force(1) = 2 < 10 -> always fails
    encounter, _ = encounter_mod.start_encounter("enc_tpk", heroes, enemies, rng)
    _run_simple_fight(encounter, rng, max_rounds=30, hero_intents=lambda e: _basic_intent_defs(50))

    assert encounter_mod.is_party_wiped(encounter)
    assert not encounter_mod.is_victory(encounter)
    assert all(h.life_state in (LifeState.DOWNED, LifeState.DEAD) for h in heroes)


def test_solo_hero_survives_full_party_threat_via_barricade_until_joiner_arrives():
    solo_hero = make_hero("hero_solo", force=3, finesse=3, max_hp=50)
    joiner = make_hero("hero_joiner", force=3, finesse=6)

    party_budget = threat.calculate_threat_budget(4)  # threat is from the FULL living party, not who's present
    assert party_budget.total == 8

    immediate_enemy = make_enemy("enemy_scout", hp=6, defense=10, threat_cost=2, threat_tier="standard")
    reinforcements = [make_enemy(f"enemy_reinforcement_{i}", hp=10, defense=12, threat_cost=2) for i in range(3)]

    rng = MinRollRNG()
    encounter, _ = encounter_mod.start_encounter("enc_solo", [solo_hero], [immediate_enemy], rng)

    remaining_budget = party_budget.total - threat.roster_cost([immediate_enemy])
    encounter_mod.schedule_reinforcements(
        encounter, remaining_budget, reinforcements, arrival_combat_round=6, caused_by="test",
    )
    wave = encounter.reinforcement_waves[0]

    barricade_events = threat.delay_reinforcements(
        wave, 4, hero_id="hero_solo", combat_round=encounter.combat_round, sequencer=encounter.sequencer,
        caused_by="test",
    )
    assert any(e["type"] == "barricade_established" for e in barricade_events)
    assert wave.arrival_combat_round == 10

    # Solo hero survives long enough (the immediate scout is weak and dies fast; no reinforcements
    # are due yet) for a joiner to arrive at the next initiative cycle, per §14.1.
    for _ in range(3):
        if encounter_mod.is_victory(encounter):
            break
        encounter_mod.advance_round(encounter, rng, caused_by="test")

    assert solo_hero.life_state == LifeState.ALIVE
    encounter_mod.advance_round(encounter, rng, joiners=[joiner], caused_by="test")
    assert "hero_joiner" in encounter.heroes
    assert {e.combatant_id for e in encounter.order} >= {"hero_solo", "hero_joiner", "enemy_scout"}
    assert wave.arrival_combat_round > encounter.combat_round  # still delayed, hasn't hit yet


# --------------------------------------------------------------------------- determinism


def _seeded_scenario(seed):
    from backend.lan_playground.domain.rng import StacksRNG  # prove protocol compatibility with the real engine RNG

    rng = StacksRNG(seed)
    heroes = [make_hero(f"hero_{i}", force=3, skills={"bonk": 1}, die_faces=6) for i in range(2)]
    enemies = [make_enemy(f"enemy_{i}", hp=12, defense=11, threat_cost=2) for i in range(2)]
    encounter, start_events = encounter_mod.start_encounter(f"enc_det_{seed}", heroes, enemies, rng)
    fight_events = _run_simple_fight(encounter, rng, max_rounds=25, hero_intents=lambda e: _basic_intent_defs(2))
    return start_events + fight_events


def test_same_seed_produces_identical_event_sequence():
    run_a = _seeded_scenario(99)
    run_b = _seeded_scenario(99)
    assert run_a == run_b
    assert len(run_a) > 0


def test_different_seed_can_diverge():
    run_a = _seeded_scenario(1)
    run_b = _seeded_scenario(2)
    assert run_a != run_b
