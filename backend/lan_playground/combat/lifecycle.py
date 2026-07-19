"""HP / Downed / Stable / Dead state machine (infinite_stacks.md §16.1-16.3).

```
Healthy/Wounded -> Downed at 0 HP -> Stable (treatment or 3 death-check
successes) -> Revived (aid/item/ability/safe recovery)
Downed -> Dead after 3 death-check failures or an explicit fatal event
```

`apply_damage` is the single HP-mutation entry point every other combat
module (attacks, maneuvers, enemy intents, burning/bleeding ticks) calls
through, so "damage while Downed adds one death-check failure" (§16.2) is
enforced in exactly one place.
"""
from __future__ import annotations

from .events import CombatEventType, EventSequencer, Visibility
from .models import EnemyCombatant, HeroCombatant, LifeState
from .rng import CombatRNG

DEATH_CHECK_DC = 10
STABILIZATION_SUCCESSES_NEEDED = 3
DEATH_FAILURES_NEEDED = 3


def apply_damage(
    combatant: HeroCombatant | EnemyCombatant,
    amount: int,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    target_id: str,
    actor_id: str | None = None,
    source: str | None = None,
) -> list[dict]:
    if amount < 0:
        raise ValueError("damage amount must be >= 0")

    if isinstance(combatant, EnemyCombatant):
        return _apply_damage_to_enemy(
            combatant, amount, combat_round=combat_round, sequencer=sequencer,
            caused_by=caused_by, target_id=target_id, actor_id=actor_id, source=source,
        )
    return _apply_damage_to_hero(
        combatant, amount, combat_round=combat_round, sequencer=sequencer,
        caused_by=caused_by, target_id=target_id, actor_id=actor_id, source=source,
    )


def _damage_event(combat_round, sequencer, caused_by, actor_id, target_id, amount, source, new_hp) -> dict:
    return sequencer.emit(
        combat_round=combat_round,
        caused_by=caused_by,
        type=CombatEventType.DAMAGE_APPLIED,
        actor_id=actor_id,
        target_id=target_id,
        visibility=Visibility.PUBLIC,
        payload={"amount": amount, "source": source, "hp_remaining": new_hp},
    )


def _apply_damage_to_enemy(enemy, amount, *, combat_round, sequencer, caused_by, target_id, actor_id, source):
    if not enemy.alive:
        return []
    enemy.hp = max(0, enemy.hp - amount)
    events = [_damage_event(combat_round, sequencer, caused_by, actor_id, target_id, amount, source, enemy.hp)]
    if enemy.hp <= 0:
        enemy.alive = False
        events.append(
            sequencer.emit(
                combat_round=combat_round,
                caused_by=caused_by,
                type=CombatEventType.ENEMY_DEFEATED,
                actor_id=actor_id,
                target_id=target_id,
                visibility=Visibility.PUBLIC,
                payload={},
            )
        )
    return events


def _apply_damage_to_hero(hero, amount, *, combat_round, sequencer, caused_by, target_id, actor_id, source):
    if hero.life_state == LifeState.DEAD:
        return []

    was_downed_or_stable = hero.life_state in (LifeState.DOWNED, LifeState.STABLE)
    hero.hp = max(0, hero.hp - amount)
    events = [_damage_event(combat_round, sequencer, caused_by, actor_id, target_id, amount, source, hero.hp)]

    if was_downed_or_stable:
        # §16.2: "taking damage while Downed adds one failure" -- applied to
        # Stable too, since Stable is still unconscious at 0 HP.
        hero.life_state = LifeState.DOWNED
        events.append(
            sequencer.emit(
                combat_round=combat_round,
                caused_by=caused_by,
                type=CombatEventType.DEATH_CHECK_RESOLVED,
                actor_id=actor_id,
                target_id=target_id,
                visibility=Visibility.PARTY,
                payload={"forced": True, "success": False, "reason": "damage_while_downed"},
            )
        )
        hero.death_failures += 1
        events.extend(_check_death_thresholds(hero, combat_round, sequencer, caused_by, target_id))
    elif hero.hp <= 0 and hero.life_state == LifeState.ALIVE:
        hero.life_state = LifeState.DOWNED
        events.append(
            sequencer.emit(
                combat_round=combat_round,
                caused_by=caused_by,
                type=CombatEventType.HERO_DOWNED,
                actor_id=actor_id,
                target_id=target_id,
                visibility=Visibility.PARTY,
                payload={},
            )
        )
    return events


def _check_death_thresholds(hero, combat_round, sequencer, caused_by, target_id) -> list[dict]:
    events: list[dict] = []
    if hero.stabilization_successes >= STABILIZATION_SUCCESSES_NEEDED:
        hero.life_state = LifeState.STABLE
        events.append(
            sequencer.emit(
                combat_round=combat_round,
                caused_by=caused_by,
                type=CombatEventType.HERO_STABILIZED,
                target_id=target_id,
                visibility=Visibility.PARTY,
                payload={"reason": "death_checks"},
            )
        )
    elif hero.death_failures >= DEATH_FAILURES_NEEDED:
        hero.life_state = LifeState.DEAD
        events.append(
            sequencer.emit(
                combat_round=combat_round,
                caused_by=caused_by,
                type=CombatEventType.HERO_DIED,
                target_id=target_id,
                visibility=Visibility.PUBLIC,
                payload={"reason": "death_checks"},
            )
        )
    return events


def death_check(
    hero: HeroCombatant,
    rng: CombatRNG,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    extra_failures: int = 0,
) -> list[dict]:
    """§16.2: d20 + Force vs 10 at the start of a Downed hero's world turn.

    `extra_failures` covers "a clearly tagged severe trap or execution may
    add two failures" -- the caller supplies the count, this function never
    invents narrative severity on its own.
    """
    if hero.life_state != LifeState.DOWNED:
        raise ValueError(f"{hero.hero_id} is not Downed (life_state={hero.life_state.value})")

    roll = rng.roll_d20()
    total = roll + hero.attributes.force
    success = total >= DEATH_CHECK_DC

    if success:
        hero.stabilization_successes += 1
    else:
        hero.death_failures += 1
    hero.death_failures += extra_failures

    events = [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.DEATH_CHECK_RESOLVED,
            target_id=hero.hero_id,
            visibility=Visibility.PARTY,
            payload={
                "roll": roll,
                "force": hero.attributes.force,
                "total": total,
                "dc": DEATH_CHECK_DC,
                "success": success,
                "extra_failures": extra_failures,
            },
        )
    ]
    events.extend(_check_death_thresholds(hero, combat_round, sequencer, caused_by, hero.hero_id))
    return events


def stabilize_directly(
    hero: HeroCombatant,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    actor_id: str | None = None,
    reason: str = "ally_aid",
) -> list[dict]:
    """§16.2: "an ally using the correct aid can stabilize without waiting
    for three successes." """
    if hero.life_state != LifeState.DOWNED:
        raise ValueError(f"{hero.hero_id} is not Downed (life_state={hero.life_state.value})")
    hero.life_state = LifeState.STABLE
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.HERO_STABILIZED,
            actor_id=actor_id,
            target_id=hero.hero_id,
            visibility=Visibility.PARTY,
            payload={"reason": reason},
        )
    ]


def revive(
    hero: HeroCombatant,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    actor_id: str | None = None,
    to_hp: int = 1,
    proper_supplies: bool = True,
) -> list[dict]:
    """§16.3: a Stable hero can be revived to 1 HP with appropriate aid; a
    Downed hero can also be revived directly by medicine/skill/card/safe
    room rule. Reviving without proper supplies flags an injury risk in the
    payload -- authoring the resulting Injury is §16.5 scope, outside this
    combat package."""
    if hero.life_state not in (LifeState.DOWNED, LifeState.STABLE):
        raise ValueError(f"{hero.hero_id} cannot be revived from life_state={hero.life_state.value}")
    if to_hp < 1:
        raise ValueError("revival must restore at least 1 HP")

    hero.life_state = LifeState.ALIVE
    hero.hp = min(to_hp, hero.max_hp)
    hero.stabilization_successes = 0
    hero.death_failures = 0
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.HERO_REVIVED,
            actor_id=actor_id,
            target_id=hero.hero_id,
            visibility=Visibility.PARTY,
            payload={"hp": hero.hp, "proper_supplies": proper_supplies, "injury_risk": not proper_supplies},
        )
    ]


def party_wiped(heroes: list[HeroCombatant]) -> bool:
    """§2/§16.3: "the entire party Downed or Dead ... ends the run." No
    ALIVE hero remains able to act."""
    return not any(h.life_state == LifeState.ALIVE for h in heroes)


def party_has_survivor(heroes: list[HeroCombatant]) -> bool:
    return any(h.life_state != LifeState.DEAD for h in heroes)
