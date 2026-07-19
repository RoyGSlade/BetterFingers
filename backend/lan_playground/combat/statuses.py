"""The nine §16.4 light statuses: one primary effect, a visible duration, a
treatment rule each. A hero should rarely track more than two at once --
applying a third replaces/escalates/consolidates per the rule below.

`damage_per_tick` (burning/bleeding only) is read by the caller (encounter.py)
which owns HP mutation via lifecycle.apply_damage -- this module never touches
HP directly so it stays independent of the Downed/death-check state machine.
"""
from __future__ import annotations

from .events import CombatEventType, EventSequencer, Visibility
from .models import EnemyCombatant, HeroCombatant, StatusInstance

# §16.4 -- every status has exactly one primary effect + a visible duration +
# a treatment rule. `natural_duration_rounds=None` means "lasts until its
# source/treatment removes it" rather than ticking down on its own.
STATUS_DEFINITIONS: dict[str, dict] = {
    "bleeding": {
        "primary_effect": "Lose 1 HP after taking a strenuous (main) action.",
        "natural_duration_rounds": None,
        "treatment": "Bandage, medicine, or safe rest.",
        "damage_per_tick": 1,
    },
    "burning": {
        "primary_effect": "Take damage at the end of the combat round.",
        "natural_duration_rounds": None,
        "treatment": "Water, a roll/douse action, or an extinguish action.",
        "damage_per_tick": 1,
    },
    "frightened": {
        "primary_effect": "Cannot willingly approach the fright source.",
        "natural_duration_rounds": None,
        "treatment": "Rally, gain distance, or remove the source.",
    },
    "confused": {
        "primary_effect": "First targeted action shows two possible targets.",
        "natural_duration_rounds": None,
        "treatment": "Read/Wordcraft aid, or the room ends.",
    },
    "silenced": {
        "primary_effect": "Cannot use speech-tagged cards.",
        "natural_duration_rounds": None,
        "treatment": "Break the source, a writing tool, or the room ends.",
    },
    "sickened": {
        "primary_effect": "Disadvantage on Force recovery checks.",
        "natural_duration_rounds": None,
        "treatment": "Antidote, or diagnosis and treatment.",
    },
    "exhausted": {
        "primary_effect": "Begin next world round with 3 Energy instead of 5.",
        "natural_duration_rounds": None,
        "treatment": "Full safe rest.",
    },
    "marked": {
        "primary_effect": "The named enemy gains an effect against this hero.",
        "natural_duration_rounds": None,
        "treatment": "Hide, cleanse, or defeat the marker.",
    },
    "prone": {
        "primary_effect": "Movement is required before normal repositioning.",
        "natural_duration_rounds": None,
        "treatment": "Stand (uses movement) or an allied assist.",
    },
}

MAX_TRACKED_STATUSES = 2  # §16.4: rarely more than two; a third replaces/escalates/consolidates

Combatant = HeroCombatant | EnemyCombatant


def status_damage_amount(status_id: str) -> int | None:
    return STATUS_DEFINITIONS[status_id].get("damage_per_tick")


def has_status(combatant: Combatant, status_id: str) -> bool:
    return status_id in combatant.statuses


def _oldest_status_id(combatant: Combatant) -> str:
    """Deterministic pick for consolidation: earliest-applied status, ties
    broken by status_id so replay never depends on dict ordering."""
    return min(
        combatant.statuses.values(),
        key=lambda inst: (inst.applied_round, inst.status_id),
    ).status_id


def apply_status(
    combatant: Combatant,
    status_id: str,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    actor_id: str | None = None,
    target_id: str,
    duration_rounds: int | None = None,
) -> list[dict]:
    """Apply `status_id` to `combatant`, enforcing the §16.4 two-status cap.

    - Already active -> escalate (refresh/extend, tag escalated=True).
    - Fewer than MAX_TRACKED_STATUSES active -> add plainly.
    - At cap with a different status -> consolidate: replace whichever
      existing status was applied longest ago with the new one.
    """
    if status_id not in STATUS_DEFINITIONS:
        raise ValueError(f"unknown status {status_id!r}")

    if status_id in combatant.statuses:
        inst = combatant.statuses[status_id]
        inst.rounds_remaining = duration_rounds if duration_rounds is not None else inst.rounds_remaining
        inst.escalated = True
        return [
            sequencer.emit(
                combat_round=combat_round,
                caused_by=caused_by,
                type=CombatEventType.STATUS_ESCALATED,
                actor_id=actor_id,
                target_id=target_id,
                visibility=Visibility.PARTY,
                payload={"status_id": status_id},
            )
        ]

    if len(combatant.statuses) < MAX_TRACKED_STATUSES:
        combatant.statuses[status_id] = StatusInstance(
            status_id=status_id, applied_round=combat_round, rounds_remaining=duration_rounds
        )
        return [
            sequencer.emit(
                combat_round=combat_round,
                caused_by=caused_by,
                type=CombatEventType.STATUS_APPLIED,
                actor_id=actor_id,
                target_id=target_id,
                visibility=Visibility.PARTY,
                payload={"status_id": status_id},
            )
        ]

    replaced_id = _oldest_status_id(combatant)
    del combatant.statuses[replaced_id]
    combatant.statuses[status_id] = StatusInstance(
        status_id=status_id, applied_round=combat_round, rounds_remaining=duration_rounds
    )
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.STATUS_CONSOLIDATED,
            actor_id=actor_id,
            target_id=target_id,
            visibility=Visibility.PARTY,
            payload={"replaced_status_id": replaced_id, "applied_status_id": status_id},
        )
    ]


def treat_status(
    combatant: Combatant,
    status_id: str,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
    actor_id: str | None = None,
    target_id: str,
) -> list[dict]:
    if status_id not in combatant.statuses:
        raise ValueError(f"{target_id} does not have status {status_id!r}")
    del combatant.statuses[status_id]
    return [
        sequencer.emit(
            combat_round=combat_round,
            caused_by=caused_by,
            type=CombatEventType.STATUS_TREATED,
            actor_id=actor_id,
            target_id=target_id,
            visibility=Visibility.PARTY,
            payload={"status_id": status_id},
        )
    ]
