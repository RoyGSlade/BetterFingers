"""d20 checks and outcome margins (infinite_stacks.md §12).

Advantage/disadvantage sources cancel one-for-one; at most one of
Advantage/Disadvantage applies after cancellation (§12.2). Opposed-check ties
favor whichever side holds the current state (§12.4) -- the caller says which
side that is.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..domain.commands import Command
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.rng import StacksRNG
from ..domain.state import RunState
from . import turns


class Outcome(str, Enum):
    STRONG_SUCCESS = "strong_success"      # margin >= 5
    CLEAN_SUCCESS = "clean_success"        # 0 <= margin <= 4
    COST_PROGRESS = "cost_progress"        # -4 <= margin <= -1
    SETBACK = "setback"                    # margin <= -5


@dataclass(frozen=True)
class CheckResult:
    die_rolls: tuple[int, ...]   # one roll normally, two if advantage/disadvantage applied
    chosen_die: int
    attribute_score: int
    skill_rank: int
    modifiers: int
    dc: int
    total: int
    margin: int
    outcome: Outcome
    natural_20: bool
    natural_1: bool


def net_advantage(advantage_sources: int, disadvantage_sources: int) -> int:
    """Return +1 (advantage), -1 (disadvantage), or 0 after one-for-one cancellation."""
    net = advantage_sources - disadvantage_sources
    if net > 0:
        return 1
    if net < 0:
        return -1
    return 0


def outcome_for_margin(margin: int) -> Outcome:
    if margin >= 5:
        return Outcome.STRONG_SUCCESS
    if margin >= 0:
        return Outcome.CLEAN_SUCCESS
    if margin >= -4:
        return Outcome.COST_PROGRESS
    return Outcome.SETBACK


def perform_check(
    rng: StacksRNG,
    attribute_score: int,
    skill_rank: int,
    dc: int,
    advantage_sources: int = 0,
    disadvantage_sources: int = 0,
    modifiers: int = 0,
) -> CheckResult:
    net = net_advantage(advantage_sources, disadvantage_sources)
    if net == 0:
        rolls = (rng.roll_d20(),)
        chosen = rolls[0]
    else:
        rolls = (rng.roll_d20(), rng.roll_d20())
        chosen = max(rolls) if net > 0 else min(rolls)

    total = chosen + attribute_score + skill_rank + modifiers
    margin = total - dc
    return CheckResult(
        die_rolls=rolls,
        chosen_die=chosen,
        attribute_score=attribute_score,
        skill_rank=skill_rank,
        modifiers=modifiers,
        dc=dc,
        total=total,
        margin=margin,
        outcome=outcome_for_margin(margin),
        natural_20=(chosen == 20),
        natural_1=(chosen == 1),
    )


def opposed_check(
    rng: StacksRNG,
    current_state_holder: str,
    side_a_name: str,
    side_a_attribute: int,
    side_a_skill: int,
    side_b_name: str,
    side_b_attribute: int,
    side_b_skill: int,
) -> tuple[str, CheckResult, CheckResult]:
    """Both sides roll a flat d20+attribute+skill; highest total wins. Ties favor
    `current_state_holder` (§12.4) rather than re-rolling."""
    result_a = perform_check(rng, side_a_attribute, side_a_skill, dc=0)
    result_b = perform_check(rng, side_b_attribute, side_b_skill, dc=0)
    if result_a.total > result_b.total:
        winner = side_a_name
    elif result_b.total > result_a.total:
        winner = side_b_name
    else:
        winner = current_state_holder
    return winner, result_a, result_b


# ---------------------------------------------------------------- command binding

def handle_check(command: Command, state: RunState, rng: StacksRNG, seq: int) -> tuple[Event, ...]:
    """A `check` command spends the Energy for a major skill interaction (§8.1)
    and resolves a standard d20 check (§12.1) from caller-supplied inputs."""
    hero_id = command.hero_id
    turns.require_energy(state, hero_id, "major_skill_interaction")
    hero = state.heroes[hero_id]
    payload = command.payload

    result = perform_check(
        rng,
        attribute_score=payload.get("attribute_score", 0),
        skill_rank=payload.get("skill_rank", 0),
        dc=payload.get("dc", 11),
        advantage_sources=payload.get("advantage_sources", 0),
        disadvantage_sources=payload.get("disadvantage_sources", 0),
        modifiers=payload.get("modifiers", 0),
    )

    energy_event = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.ENERGY_SPENT,
        visibility=Visibility.PARTY,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={"amount": turns.ENERGY_COSTS["major_skill_interaction"], "action": "check"},
    )
    check_event = Event(
        event_id=make_event_id(state.world_round, seq + 1),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.CHECK_RESOLVED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=hero.room_id,
        payload={
            "die_rolls": list(result.die_rolls),
            "chosen_die": result.chosen_die,
            "total": result.total,
            "dc": result.dc,
            "margin": result.margin,
            "outcome": result.outcome.value,
            "natural_20": result.natural_20,
            "natural_1": result.natural_1,
        },
    )
    return (energy_event, check_event)


def apply_check_resolved(state: RunState, event: Event) -> RunState:
    return state


EVENT_APPLIERS = {
    EventType.CHECK_RESOLVED: apply_check_resolved,
}
