"""The six §14.5 reactions. Each hero normally has one reaction per round,
available until their next turn -- `HeroCombatant.reaction_available` is
cleared by `use_reaction` and refreshed by `refresh_reaction`, which the
orchestrator calls at the start of that hero's own turn (§14.2: "one
reaction available until the hero's next turn").
"""
from __future__ import annotations

from typing import Callable

from .actions import AttackResult, TurnBudget, attack
from .events import CombatEventType, EventSequencer, Visibility
from .models import EnemyCombatant, HeroCombatant

Combatant = HeroCombatant | EnemyCombatant


class ReactionUnavailableError(ValueError):
    pass


def _combatant_id(c: Combatant) -> str:
    return c.hero_id if isinstance(c, HeroCombatant) else c.instance_id


def use_reaction(hero: HeroCombatant) -> None:
    if not hero.reaction_available:
        raise ReactionUnavailableError(f"{hero.hero_id} has no reaction available this round")
    hero.reaction_available = False


def refresh_reaction(hero: HeroCombatant) -> None:
    hero.reaction_available = True


def _reaction_event(combat_round, sequencer, caused_by, hero_id, target_id, reaction, outcome, payload) -> dict:
    return sequencer.emit(
        combat_round=combat_round,
        caused_by=caused_by,
        type=CombatEventType.REACTION_RESOLVED,
        actor_id=hero_id,
        target_id=target_id,
        visibility=Visibility.PUBLIC,
        payload={"reaction": reaction, "outcome": outcome, **payload},
    )


def dodge(
    hero: HeroCombatant,
    incoming_attack_total: int,
    rng,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    new_position: int | None = None,
) -> tuple[bool, list[dict]]:
    """Oppose the attack with Finesse; move to a legal nearby position on
    success. Ties favor the current state (§12.4) -- the attack still
    lands."""
    use_reaction(hero)
    roll = rng.roll_d20()
    total = roll + hero.attributes.finesse
    success = total > incoming_attack_total
    events = [
        _reaction_event(
            combat_round, sequencer, caused_by, hero.hero_id, hero.hero_id, "dodge",
            "avoided" if success else "hit_lands",
            {"roll": roll, "total": total, "incoming_attack_total": incoming_attack_total},
        )
    ]
    if success and new_position is not None:
        from_position = hero.position
        hero.position = new_position
        events.append(
            sequencer.emit(
                combat_round=combat_round, caused_by=caused_by, type=CombatEventType.MOVED,
                actor_id=hero.hero_id, target_id=hero.hero_id, visibility=Visibility.PUBLIC,
                payload={"from_position": from_position, "to_position": new_position, "reason": "dodge"},
            )
        )
    return success, events


def block(
    hero: HeroCombatant,
    incoming_damage: int,
    *,
    item_id: str,
    block_amount: int,
    rng,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    wear_chance: float = 0.25,
) -> tuple[int, list[dict]]:
    """Reduce incoming damage with a shield or defensive item; the item may
    take Wear (deterministic roll against `wear_chance`, RNG-injected so
    replay stays exact)."""
    use_reaction(hero)
    reduced_damage = max(0, incoming_damage - block_amount)
    wear_roll = rng.randint(1, 100)
    took_wear = wear_roll <= round(wear_chance * 100)
    events = [
        _reaction_event(
            combat_round, sequencer, caused_by, hero.hero_id, hero.hero_id, "block", "blocked",
            {
                "item_id": item_id,
                "block_amount": block_amount,
                "incoming_damage": incoming_damage,
                "reduced_damage": reduced_damage,
                "wear_roll": wear_roll,
                "took_wear": took_wear,
            },
        )
    ]
    return reduced_damage, events


def protect(
    protector: HeroCombatant,
    ally: HeroCombatant,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> list[dict]:
    """Become the target of an attack aimed at a nearby ally. The caller
    (encounter orchestrator) is responsible for redirecting the next attack
    against `ally` to `protector` -- this call declares and consumes the
    reaction."""
    use_reaction(protector)
    return [
        _reaction_event(
            combat_round, sequencer, caused_by, protector.hero_id, ally.hero_id, "protect", "redirect_armed", {}
        )
    ]


def can_counter(incoming_attack_margin: int, permitted: bool) -> bool:
    """§14.5: "after an enemy misses by 5 or more, if a card or item permits
    it." """
    return permitted and incoming_attack_margin <= -5


def counter(
    hero: HeroCombatant,
    attacker: Combatant,
    incoming_attack_margin: int,
    *,
    permitted: bool,
    attribute: str,
    skill: str | None,
    rng,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> tuple[AttackResult | None, list[dict]]:
    use_reaction(hero)
    if not can_counter(incoming_attack_margin, permitted):
        return None, [
            _reaction_event(
                combat_round, sequencer, caused_by, hero.hero_id, _combatant_id(attacker), "counter",
                "not_available", {"incoming_attack_margin": incoming_attack_margin, "permitted": permitted},
            )
        ]
    # Countering is a reaction, not the hero's own turn -- give it a
    # throwaway budget so it never touches that hero's real per-turn budget.
    dummy_budget = TurnBudget(hero_id=hero.hero_id)
    result = attack(
        hero, attacker, attribute=attribute, skill=skill, rng=rng,
        combat_round=combat_round, sequencer=sequencer, caused_by=caused_by, budget=dummy_budget,
        action_label="counter",
    )
    return result, result.events


def escape(
    hero: HeroCombatant,
    hold_dc: int,
    *,
    attribute: str = "finesse",
    rng,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> tuple[bool, list[dict]]:
    """Oppose a grapple, swallow, restraint, or environmental hold."""
    use_reaction(hero)
    roll = rng.roll_d20()
    total = roll + hero.attributes.get(attribute)
    success = total >= hold_dc
    events = [
        _reaction_event(
            combat_round, sequencer, caused_by, hero.hero_id, hero.hero_id, "escape",
            "freed" if success else "still_held",
            {"roll": roll, "attribute": attribute, "total": total, "hold_dc": hold_dc},
        )
    ]
    return success, events


def set_prepared_trigger(
    hero: HeroCombatant,
    trigger_spec: dict,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> list[dict]:
    """Declares a prepared action during the hero's own turn -- this is a
    main action, not the reaction itself (`execute_prepared_trigger` below
    spends the reaction later, possibly on someone else's turn)."""
    hero.prepared_trigger = trigger_spec
    return [
        sequencer.emit(
            combat_round=combat_round, caused_by=caused_by, type=CombatEventType.REACTION_RESOLVED,
            actor_id=hero.hero_id, target_id=hero.hero_id, visibility=Visibility.PARTY,
            payload={"reaction": "prepared_trigger", "outcome": "set", "trigger_spec": trigger_spec},
        )
    ]


def execute_prepared_trigger(
    hero: HeroCombatant,
    *,
    condition_met: bool,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    executor: Callable[[], list[dict]] | None = None,
) -> list[dict]:
    use_reaction(hero)
    if not condition_met or hero.prepared_trigger is None:
        return [
            _reaction_event(
                combat_round, sequencer, caused_by, hero.hero_id, hero.hero_id, "prepared_trigger",
                "not_triggered", {},
            )
        ]
    spec = hero.prepared_trigger
    hero.prepared_trigger = None
    events = [
        _reaction_event(
            combat_round, sequencer, caused_by, hero.hero_id, hero.hero_id, "prepared_trigger", "triggered",
            {"trigger_spec": spec},
        )
    ]
    if executor is not None:
        events.extend(executor())
    return events
