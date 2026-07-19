"""Turn structure (§14.2) and attack resolution (§14.3).

A combat turn budgets movement, one quick interaction, one main action, and
one reaction (reactions.py owns the reaction itself, since it can fire on
someone else's turn). `TurnBudget` enforces "one of each" per turn; callers
create a fresh one in `start_turn` and discard it at the end of the turn --
only `reaction_available` on the combatant persists turn-to-turn (cleared by
reactions.use_reaction, refreshed at the top of the combatant's next turn).
"""
from __future__ import annotations

from dataclasses import dataclass

from .events import CombatEventType, EventSequencer, Visibility
from .lifecycle import apply_damage
from .models import EnemyCombatant, HeroCombatant
from .rng import CombatRNG, roll_die

Combatant = HeroCombatant | EnemyCombatant


class TurnBudgetError(ValueError):
    pass


@dataclass
class TurnBudget:
    hero_id: str
    moved: bool = False
    quick_interaction_used: bool = False
    main_action_used: bool = False

    def mark_movement(self) -> None:
        if self.moved:
            raise TurnBudgetError(f"{self.hero_id} already used movement this turn")
        self.moved = True

    def mark_quick_interaction(self) -> None:
        if self.quick_interaction_used:
            raise TurnBudgetError(f"{self.hero_id} already used a quick interaction this turn")
        self.quick_interaction_used = True

    def mark_main_action(self) -> None:
        if self.main_action_used:
            raise TurnBudgetError(f"{self.hero_id} already used a main action this turn")
        self.main_action_used = True


def start_turn(hero_id: str, *, combat_round: int, sequencer: EventSequencer, caused_by: str) -> tuple[TurnBudget, dict]:
    budget = TurnBudget(hero_id=hero_id)
    event = sequencer.emit(
        combat_round=combat_round,
        caused_by=caused_by,
        type=CombatEventType.TURN_STARTED,
        actor_id=hero_id,
        target_id=hero_id,
        visibility=Visibility.PUBLIC,
        payload={},
    )
    return budget, event


def move(
    combatant: Combatant,
    new_position: int,
    budget: TurnBudget,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> list[dict]:
    budget.mark_movement()
    from_position = combatant.position
    combatant.position = new_position
    cid = _combatant_id(combatant)
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.MOVED,
            actor_id=cid,
            target_id=cid,
            visibility=Visibility.PUBLIC,
            payload={"from_position": from_position, "to_position": new_position},
        )
    ]


def quick_interaction(
    combatant: Combatant,
    budget: TurnBudget,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    description: str,
) -> list[dict]:
    budget.mark_quick_interaction()
    cid = _combatant_id(combatant)
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.QUICK_INTERACTION_USED,
            actor_id=cid,
            target_id=cid,
            visibility=Visibility.PUBLIC,
            payload={"description": description},
        )
    ]


def _combatant_id(c: Combatant) -> str:
    return c.hero_id if isinstance(c, HeroCombatant) else c.instance_id


def _net_advantage(advantage_sources: int, disadvantage_sources: int) -> int:
    net = advantage_sources - disadvantage_sources
    if net > 0:
        return 1
    if net < 0:
        return -1
    return 0


@dataclass
class AttackResult:
    events: list[dict]
    hit: bool
    total: int
    margin: int          # total - defender.defense; negative on a miss
    damage: int = 0
    natural_20: bool = False
    natural_1: bool = False


def attack(
    attacker: HeroCombatant,
    defender: Combatant,
    *,
    attribute: str,
    skill: str | None,
    rng: CombatRNG,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    budget: TurnBudget,
    advantage_sources: int = 0,
    disadvantage_sources: int = 0,
    accuracy_modifier: int = 0,   # e.g. -4 for a called maneuver (§14.4)
    extra_damage_bonus: int = 0,
    damage_multiplier: float = 1.0,   # called maneuvers may deal reduced/boosted damage
    bonus_damage_dice: int = 0,       # e.g. Crushing Blow adds one extra weapon die
    action_label: str = "attack",
) -> AttackResult:
    """§14.3: `d20 + attribute + skill + weapon.accuracy_bonus` vs
    `Defense = 10 + Finesse + equipment`; damage = weapon die + explicit
    bonuses. Consumes the attacker's main action."""
    budget.mark_main_action()

    net = _net_advantage(advantage_sources, disadvantage_sources)
    if net == 0:
        rolls = (rng.roll_d20(),)
        chosen = rolls[0]
    else:
        rolls = (rng.roll_d20(), rng.roll_d20())
        chosen = max(rolls) if net > 0 else min(rolls)

    attribute_score = attacker.attributes.get(attribute)
    skill_rank = attacker.skill_rank(skill) if skill else 0
    weapon = attacker.weapon
    total = chosen + attribute_score + skill_rank + weapon.accuracy_bonus + accuracy_modifier
    defender_id = _combatant_id(defender)
    margin = total - defender.defense
    hit = total >= defender.defense

    events = [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.ATTACK_RESOLVED,
            actor_id=attacker.hero_id,
            target_id=defender_id,
            visibility=Visibility.PUBLIC,
            payload={
                "action": action_label,
                "die_rolls": list(rolls),
                "chosen_die": chosen,
                "attribute": attribute,
                "skill": skill,
                "total": total,
                "defense": defender.defense,
                "margin": margin,
                "hit": hit,
                "natural_20": chosen == 20,
                "natural_1": chosen == 1,
            },
        )
    ]

    damage = 0
    if hit:
        damage_roll = roll_die(rng, weapon.die_faces)
        for _ in range(bonus_damage_dice):
            damage_roll += roll_die(rng, weapon.die_faces)
        damage = round((damage_roll + weapon.damage_bonus + extra_damage_bonus) * damage_multiplier)
    if damage > 0:
        events.extend(
            apply_damage(
                defender,
                damage,
                combat_round=combat_round,
                sequencer=sequencer,
                caused_by=caused_by,
                target_id=defender_id,
                actor_id=attacker.hero_id,
                source=action_label,
            )
        )

    return AttackResult(
        events=events,
        hit=hit,
        total=total,
        margin=margin,
        damage=damage,
        natural_20=(chosen == 20),
        natural_1=(chosen == 1),
    )
