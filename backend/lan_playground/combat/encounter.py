"""Orchestration glue for a combat encounter: round progression, reinforcement
arrival, downed-hero death-check cadence, and victory/defeat checks.

This module does NOT decide tactics -- which attack/maneuver/reaction to use
each turn is a policy decision made by the caller (a player command in a
future wave, a scripted test today). `encounter.py` only owns the mechanical
bookkeeping every fight needs regardless of who's deciding: whose turn it
is, when the round rolls over, when scheduled reinforcements show up, and
when the fight is over. That keeps it a thin, testable seam rather than a
duplicate of the wave-3 reducer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import initiative, lifecycle, threat
from .events import CombatEventType, EventSequencer, Visibility
from .models import EnemyCombatant, HeroCombatant, LifeState

Combatant = HeroCombatant | EnemyCombatant


@dataclass
class Encounter:
    encounter_id: str
    heroes: dict[str, HeroCombatant]
    enemies: dict[str, EnemyCombatant]
    sequencer: EventSequencer
    combat_round: int = 1
    order: list[initiative.InitiativeEntry] = field(default_factory=list)
    reinforcement_waves: list[threat.ReinforcementWave] = field(default_factory=list)


def start_encounter(
    encounter_id: str,
    heroes: list[HeroCombatant],
    enemies: list[EnemyCombatant],
    rng,
    *,
    caused_by: str = "encounter_start",
) -> tuple[Encounter, list[dict]]:
    sequencer = EventSequencer(encounter_id)
    encounter = Encounter(
        encounter_id=encounter_id,
        heroes={h.hero_id: h for h in heroes},
        enemies={e.instance_id: e for e in enemies},
        sequencer=sequencer,
        combat_round=1,
    )
    events = [
        sequencer.emit(
            combat_round=1,
            caused_by=caused_by,
            type=CombatEventType.ENCOUNTER_STARTED,
            visibility=Visibility.PUBLIC,
            payload={
                "hero_ids": [h.hero_id for h in heroes],
                "enemy_instance_ids": [e.instance_id for e in enemies],
            },
        )
    ]
    order, roll_events = initiative.roll_initiative(
        [*heroes, *enemies], rng, combat_round=1, sequencer=sequencer, caused_by=caused_by
    )
    encounter.order = order
    events.extend(roll_events)
    events.append(initiative.start_combat_round(order, combat_round=1, sequencer=sequencer, caused_by=caused_by))
    return encounter, events


def living_heroes(encounter: Encounter) -> list[HeroCombatant]:
    return [h for h in encounter.heroes.values() if h.life_state != LifeState.DEAD]


def active_heroes(encounter: Encounter) -> list[HeroCombatant]:
    return [h for h in encounter.heroes.values() if h.life_state == LifeState.ALIVE]


def downed_heroes(encounter: Encounter) -> list[HeroCombatant]:
    return [h for h in encounter.heroes.values() if h.life_state == LifeState.DOWNED]


def living_enemies(encounter: Encounter) -> list[EnemyCombatant]:
    return [e for e in encounter.enemies.values() if e.alive]


def is_victory(encounter: Encounter) -> bool:
    return len(living_enemies(encounter)) == 0


def is_party_wiped(encounter: Encounter) -> bool:
    return lifecycle.party_wiped(list(encounter.heroes.values()))


def run_downed_turn_checks(encounter: Encounter, rng, *, caused_by: str) -> list[dict]:
    """§16.2: "at the beginning of a Downed hero's world turn" -- called once
    per round for every hero still Downed (Stable heroes don't re-roll)."""
    events: list[dict] = []
    for hero in downed_heroes(encounter):
        events.extend(
            lifecycle.death_check(
                hero, rng, combat_round=encounter.combat_round, sequencer=encounter.sequencer, caused_by=caused_by
            )
        )
    return events


def schedule_reinforcements(
    encounter: Encounter,
    budget_remaining: int,
    candidate_enemies: list[EnemyCombatant],
    *,
    arrival_combat_round: int,
    caused_by: str,
) -> list[dict]:
    wave, events = threat.schedule_reinforcements(
        budget_remaining, candidate_enemies, arrival_combat_round=arrival_combat_round,
        combat_round=encounter.combat_round, sequencer=encounter.sequencer, caused_by=caused_by,
    )
    encounter.reinforcement_waves.append(wave)
    return events


def arrive_due_reinforcements(encounter: Encounter, rng, *, caused_by: str) -> list[dict]:
    events: list[dict] = []
    due = threat.due_reinforcements(encounter.reinforcement_waves, encounter.combat_round)
    for wave in due:
        for enemy in wave.enemies:
            encounter.enemies[enemy.instance_id] = enemy
        events.extend(
            threat.mark_arrived(wave, combat_round=encounter.combat_round, sequencer=encounter.sequencer, caused_by=caused_by)
        )
        encounter.order, joiner_events = initiative.integrate_joiners(
            encounter.order, wave.enemies, rng, combat_round=encounter.combat_round,
            sequencer=encounter.sequencer, caused_by=caused_by,
        )
        events.extend(joiner_events)
    return events


def advance_round(
    encounter: Encounter,
    rng,
    *,
    joiners: list[Combatant] | None = None,
    caused_by: str,
) -> list[dict]:
    """Roll the round forward: integrate any joining heroes (§14.1 "joiners
    enter at next initiative cycle"), let due reinforcements arrive, refresh
    every living hero's reaction, and open the new round."""
    encounter.combat_round += 1
    events: list[dict] = []

    if joiners:
        encounter.order, joiner_events = initiative.integrate_joiners(
            encounter.order, joiners, rng, combat_round=encounter.combat_round,
            sequencer=encounter.sequencer, caused_by=caused_by,
        )
        for c in joiners:
            if isinstance(c, HeroCombatant):
                encounter.heroes[c.hero_id] = c
            else:
                encounter.enemies[c.instance_id] = c
        events.extend(joiner_events)

    events.extend(arrive_due_reinforcements(encounter, rng, caused_by=caused_by))

    for hero in encounter.heroes.values():
        hero.reaction_available = True
        hero.exposed_until_next_turn = False

    events.append(
        initiative.start_combat_round(
            encounter.order, combat_round=encounter.combat_round, sequencer=encounter.sequencer, caused_by=caused_by
        )
    )
    events.extend(run_downed_turn_checks(encounter, rng, caused_by=caused_by))
    return events


def end_encounter(encounter: Encounter, *, outcome: str, caused_by: str) -> list[dict]:
    if outcome not in ("victory", "party_wiped", "alternative_resolution"):
        raise ValueError(f"unknown encounter outcome {outcome!r}")
    return [
        encounter.sequencer.emit(
            combat_round=encounter.combat_round,
            caused_by=caused_by,
            type=CombatEventType.ENCOUNTER_ENDED,
            visibility=Visibility.PUBLIC,
            payload={"outcome": outcome},
        )
    ]
