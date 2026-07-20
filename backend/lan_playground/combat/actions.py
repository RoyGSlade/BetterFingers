"""Turn structure (§14.2) and attack resolution (§14.3).

A combat turn budgets movement, one quick interaction, one main action, and
one reaction (reactions.py owns the reaction itself, since it can fire on
someone else's turn). `TurnBudget` enforces "one of each" per turn; callers
create a fresh one in `start_turn` and discard it at the end of the turn --
only `reaction_available` on the combatant persists turn-to-turn (cleared by
reactions.use_reaction, refreshed at the top of the combatant's next turn).

`attack()` also owns the §14.5 reaction interrupt window: a caller-supplied
`reaction_hook` fires between hit determination and damage application
whenever the defender is a `HeroCombatant` with a reaction available (or has
an eligible `protector`). This module never decides *which* reaction to use
-- that policy is entirely the hook's business (a test's scripted policy
today; a player command in a future wave) -- it only guarantees the hook
sees the attack roll before damage lands and that its verdict is what
actually gets applied. See `ReactionWindow`/`ReactionOutcome` below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

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


@dataclass
class ReactionWindow:
    """Snapshot handed to a `reaction_hook` after hit determination (and the
    provisional damage roll, if any) but before damage is applied. Nothing
    here has been mutated yet -- `defender`/`protectors` reaction flags are
    still whatever they were before the attack."""

    attacker: Combatant
    defender: HeroCombatant
    protectors: tuple[HeroCombatant, ...]
    hit: bool
    margin: int                # total - defender.defense; matches AttackResult.margin
    incoming_attack_total: int  # the attacker's resolved total (dodge opposes this)
    provisional_damage: int     # rolled damage if hit, else 0 -- not yet applied
    rng: CombatRNG
    combat_round: int
    sequencer: EventSequencer
    caused_by: str
    natural_20: bool = False
    natural_1: bool = False


@dataclass
class ReactionOutcome:
    """What a `reaction_hook` decides: the final hit/damage/target after any
    reaction resolves. `damage_target=None` means damage (if any) still lands
    on the original defender; set it to a protector to redirect (§14.5
    Protect)."""

    events: list[dict]
    hit: bool
    damage: int
    damage_target: HeroCombatant | None = None


ReactionHook = Callable[[ReactionWindow], "ReactionOutcome | None"]


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
    reaction_hook: ReactionHook | None = None,
    protectors: Sequence[HeroCombatant] = (),
) -> AttackResult:
    """§14.3: `d20 + attribute + skill + weapon.accuracy_bonus + equipment
    bonuses` vs `Defense = 10 + Finesse + equipment`; damage = weapon die +
    explicit bonuses. Consumes the attacker's main action.

    §14.5 reaction interrupt window: if `defender` is a `HeroCombatant` with
    a reaction available (or a `protectors` entry does), `reaction_hook` is
    called after hit determination and before damage is applied. Returning
    `None` means no reaction was taken and resolution proceeds unchanged;
    returning a `ReactionOutcome` overrides hit/damage/target with whatever
    the hook (and the reaction functions it called) decided.
    """
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
    total = (
        chosen + attribute_score + skill_rank + weapon.accuracy_bonus
        + attacker.equipment_accuracy_bonus + accuracy_modifier
    )
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
        damage = round(
            (damage_roll + weapon.damage_bonus + attacker.equipment_damage_bonus + extra_damage_bonus)
            * damage_multiplier
        )

    final_hit, final_damage, final_target = hit, damage, defender
    if reaction_hook is not None and isinstance(defender, HeroCombatant):
        eligible = defender.reaction_available or any(p.reaction_available for p in protectors)
        if eligible:
            window = ReactionWindow(
                attacker=attacker,
                defender=defender,
                protectors=tuple(protectors),
                hit=hit,
                margin=margin,
                incoming_attack_total=total,
                provisional_damage=damage,
                rng=rng,
                combat_round=combat_round,
                sequencer=sequencer,
                caused_by=caused_by,
                natural_20=(chosen == 20),
                natural_1=(chosen == 1),
            )
            outcome = reaction_hook(window)
            if outcome is not None:
                events.extend(outcome.events)
                final_hit = outcome.hit
                final_damage = outcome.damage
                final_target = outcome.damage_target or defender

    if final_damage > 0:
        events.extend(
            apply_damage(
                final_target,
                final_damage,
                combat_round=combat_round,
                sequencer=sequencer,
                caused_by=caused_by,
                target_id=_combatant_id(final_target),
                actor_id=attacker.hero_id,
                source=action_label,
            )
        )

    return AttackResult(
        events=events,
        hit=final_hit,
        total=total,
        margin=margin,
        damage=final_damage,
        natural_20=(chosen == 20),
        natural_1=(chosen == 1),
    )


# ---------------------------------------------------------------- enemy attack-type intents (§14.3/§14.6, task #16)


class _PendingReactionSentinel:
    def __repr__(self) -> str:
        return "PENDING_REACTION"


PENDING_REACTION = _PendingReactionSentinel()
"""Pass as `reaction_hook` to `resolve_enemy_attack` to open the reaction
window (when eligible) without resolving it: returns a `PendingAttack`
instead of an `AttackResult`, for a caller that wants to defer the decision
to a later live command rather than an in-process callback."""


@dataclass
class PendingAttack:
    """Returned by `resolve_enemy_attack` when `reaction_hook=PENDING_REACTION`
    and the window is open. The attack roll (and provisional damage, if any)
    is already resolved and baked into `events` -- replay-safe, no further
    RNG draws happen for this attack. Damage has not been applied. Call
    `resolve_pending_attack` with a `ReactionOutcome` (or `None` to decline)
    once the decision is known, whenever it arrives."""

    events: list[dict]
    window: ReactionWindow
    action_label: str


def _finish_attack(events: list[dict], window: ReactionWindow, outcome: ReactionOutcome | None, action_label: str) -> AttackResult:
    final_hit, final_damage, final_target = window.hit, window.provisional_damage, window.defender
    if outcome is not None:
        events = list(events) + list(outcome.events)
        final_hit = outcome.hit
        final_damage = outcome.damage
        final_target = outcome.damage_target or window.defender
    if final_damage > 0:
        events = list(events) + apply_damage(
            final_target,
            final_damage,
            combat_round=window.combat_round,
            sequencer=window.sequencer,
            caused_by=window.caused_by,
            target_id=_combatant_id(final_target),
            actor_id=_combatant_id(window.attacker),
            source=action_label,
        )
    return AttackResult(
        events=events,
        hit=final_hit,
        total=window.incoming_attack_total,
        margin=window.margin,
        damage=final_damage,
        natural_20=window.natural_20,
        natural_1=window.natural_1,
    )


def resolve_pending_attack(pending: PendingAttack, outcome: ReactionOutcome | None) -> AttackResult:
    """Finishes an attack that opened a window via `PENDING_REACTION`.
    `outcome=None` means no reaction was taken (§21.4 safe default) --
    resolution proceeds exactly as if the window had never opened."""
    return _finish_attack(pending.events, pending.window, outcome, pending.action_label)


def resolve_enemy_attack(
    attacker: EnemyCombatant,
    defender: Combatant,
    *,
    damage_amount: int,
    rng: CombatRNG,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    action_label: str = "attack",
    advantage_sources: int = 0,
    disadvantage_sources: int = 0,
    reaction_hook: "ReactionHook | _PendingReactionSentinel | None" = None,
    protectors: Sequence[HeroCombatant] = (),
) -> AttackResult | PendingAttack:
    """§14.3 to-hit for enemy attack-type intents: `d20 (+ adv/disadv) +
    attacker.accuracy_bonus` vs `defender.defense`. Enemies don't carry
    weapon dice (docs/INFINITE_STACKS_COMBAT.md §12, out of scope) -- damage
    on a hit is the flat, content-authored `amount` from the intent's
    `damage` op (unchanged from the wave-2 contract), applied through the
    same §14.5 reaction interrupt window `attack()` opens for hero attacks.

    `reaction_hook=None` (default): no window is offered regardless of
    `defender.reaction_available` -- resolves immediately, mirroring
    `attack()`'s own behaviour when no hook is passed (this is what
    scripted/pure-package callers with no live player use).
    `reaction_hook=PENDING_REACTION`: opens the window when eligible and
    returns a `PendingAttack` instead of resolving -- the live command
    wiring uses this so a real player's choice can arrive as its own
    command, possibly much later.
    Otherwise `reaction_hook` is called synchronously exactly like
    `attack()`'s, for scripted test policies that want to react in-process.
    """
    net = _net_advantage(advantage_sources, disadvantage_sources)
    if net == 0:
        rolls = (rng.roll_d20(),)
        chosen = rolls[0]
    else:
        rolls = (rng.roll_d20(), rng.roll_d20())
        chosen = max(rolls) if net > 0 else min(rolls)

    total = chosen + attacker.accuracy_bonus
    defender_id = _combatant_id(defender)
    margin = total - defender.defense
    hit = total >= defender.defense

    events = [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.ATTACK_RESOLVED,
            actor_id=attacker.instance_id,
            target_id=defender_id,
            visibility=Visibility.PUBLIC,
            payload={
                "action": action_label,
                "die_rolls": list(rolls),
                "chosen_die": chosen,
                "accuracy_bonus": attacker.accuracy_bonus,
                "total": total,
                "defense": defender.defense,
                "margin": margin,
                "hit": hit,
                "natural_20": chosen == 20,
                "natural_1": chosen == 1,
            },
        )
    ]

    damage = damage_amount if hit else 0
    window = ReactionWindow(
        attacker=attacker,
        defender=defender,
        protectors=tuple(protectors),
        hit=hit,
        margin=margin,
        incoming_attack_total=total,
        provisional_damage=damage,
        rng=rng,
        combat_round=combat_round,
        sequencer=sequencer,
        caused_by=caused_by,
        natural_20=(chosen == 20),
        natural_1=(chosen == 1),
    )

    if reaction_hook is not None and isinstance(defender, HeroCombatant):
        eligible = defender.reaction_available or any(p.reaction_available for p in protectors)
        if eligible:
            if reaction_hook is PENDING_REACTION:
                return PendingAttack(events=events, window=window, action_label=action_label)
            outcome = reaction_hook(window)
            return _finish_attack(events, window, outcome, action_label)

    return _finish_attack(events, window, None, action_label)
