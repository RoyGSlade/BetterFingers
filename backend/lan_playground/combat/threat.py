"""Threat budget and split-party danger (§15.1-15.2).

Budget is computed from the *total living party*, never just the heroes
physically present (§2/§15.1) -- a lone hero entering a room still faces a
four-person budget. The fairness counterweight (§15.2) is reinforcement
spending: content can hold part of the budget back as delayed arrivals so a
lone/outnumbered hero has a real retreat, barricade, hide, or delay route
instead of facing the full roster on turn one.
"""
from __future__ import annotations

from dataclasses import dataclass

from .events import CombatEventType, EventSequencer, Visibility
from .models import EnemyCombatant

THREAT_COST_BY_TIER = {
    "minion": 1,
    "standard": 2,
    "specialist": 3,
    # elite is authored in-range (4-5), not a fixed lookup value.
}


@dataclass(frozen=True)
class ThreatBudget:
    total_living_heroes: int
    floor_danger: int
    corruption_modifier: int
    objective_modifier: int
    total: int


def calculate_threat_budget(
    total_living_heroes: int,
    *,
    floor_danger: int = 0,
    corruption_modifier: int = 0,
    objective_modifier: int = 0,
) -> ThreatBudget:
    """§15.1: `budget = 2*total_living_heroes + floor_danger +
    corruption_modifier + objective_modifier`. Deliberately ignores how many
    heroes are physically in the room."""
    total = 2 * total_living_heroes + floor_danger + corruption_modifier + objective_modifier
    return ThreatBudget(
        total_living_heroes=total_living_heroes,
        floor_danger=floor_danger,
        corruption_modifier=corruption_modifier,
        objective_modifier=objective_modifier,
        total=total,
    )


def emit_threat_budget(
    budget: ThreatBudget, *, combat_round: int, sequencer: EventSequencer, caused_by: str
) -> list[dict]:
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.THREAT_BUDGET_CALCULATED,
            visibility=Visibility.PUBLIC,
            payload={
                "total_living_heroes": budget.total_living_heroes,
                "floor_danger": budget.floor_danger,
                "corruption_modifier": budget.corruption_modifier,
                "objective_modifier": budget.objective_modifier,
                "total": budget.total,
            },
        )
    ]


def roster_cost(enemies: list[EnemyCombatant]) -> int:
    return sum(e.threat_cost for e in enemies if e.alive)


@dataclass
class ReinforcementWave:
    enemies: list[EnemyCombatant]
    arrival_combat_round: int
    cost: int
    arrived: bool = False


def schedule_reinforcements(
    budget_remaining: int,
    candidate_enemies: list[EnemyCombatant],
    *,
    arrival_combat_round: int,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> tuple[ReinforcementWave, list[dict]]:
    """Greedily spend `budget_remaining` on `candidate_enemies` (in the
    order given) and schedule the affordable ones for a delayed arrival
    rather than dropping the whole budget into the room immediately."""
    scheduled: list[EnemyCombatant] = []
    spent = 0
    for enemy in candidate_enemies:
        if spent + enemy.threat_cost <= budget_remaining:
            scheduled.append(enemy)
            spent += enemy.threat_cost

    wave = ReinforcementWave(enemies=scheduled, arrival_combat_round=arrival_combat_round, cost=spent)
    events = [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.REINFORCEMENTS_SCHEDULED,
            visibility=Visibility.PARTY,
            payload={
                "enemy_instance_ids": [e.instance_id for e in scheduled],
                "arrival_combat_round": arrival_combat_round,
                "cost": spent,
                "budget_remaining_after": budget_remaining - spent,
            },
        )
    ]
    return wave, events


def delay_reinforcements(
    wave: ReinforcementWave,
    extra_delay_rounds: int,
    *,
    hero_id: str,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    description: str = "barricades the doorway",
) -> list[dict]:
    """§15.2: "at least one retreat, barricade, hide, or delay route exists."
    A barricade/delay action pushes a scheduled reinforcement wave's arrival
    back, buying time for rescue (§15.3) or a joiner's next initiative
    cycle."""
    if wave.arrived:
        raise ValueError("cannot delay a reinforcement wave that has already arrived")
    previous_arrival = wave.arrival_combat_round
    wave.arrival_combat_round += extra_delay_rounds
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.BARRICADE_ESTABLISHED,
            actor_id=hero_id,
            visibility=Visibility.PARTY,
            payload={
                "description": description,
                "previous_arrival_combat_round": previous_arrival,
                "new_arrival_combat_round": wave.arrival_combat_round,
                "extra_delay_rounds": extra_delay_rounds,
            },
        )
    ]


def due_reinforcements(waves: list[ReinforcementWave], current_combat_round: int) -> list[ReinforcementWave]:
    return [w for w in waves if not w.arrived and w.arrival_combat_round <= current_combat_round]


def mark_arrived(
    wave: ReinforcementWave, *, combat_round: int, sequencer: EventSequencer, caused_by: str
) -> list[dict]:
    wave.arrived = True
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.REINFORCEMENTS_ARRIVED,
            visibility=Visibility.PUBLIC,
            payload={"enemy_instance_ids": [e.instance_id for e in wave.enemies], "cost": wave.cost},
        )
    ]
