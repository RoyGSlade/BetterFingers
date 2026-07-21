"""Combat event envelope.

Mirrors the shape of docs/INFINITE_STACKS_CONTRACTS.md §3 (event_id, caused_by,
type, visibility, payload) but is scoped to a combat encounter rather than a
run: `encounter_id` + `combat_round` stand in for `run_id` + `world_round`
because combat is a standalone package this wave and is not wired into
RunState (that wiring is explicitly wave 3). When it is wired, the adapter
that embeds these events into the run event log is expected to carry
`encounter_id`/`combat_round` through unchanged and can derive `run_id`/
`world_round` from context -- no renaming needed on this side.

See docs/INFINITE_STACKS_COMBAT.md for the full event-type vocabulary.
"""
from __future__ import annotations

from enum import Enum


class Visibility(str, Enum):
    PUBLIC = "public"
    PARTY = "party"
    PRIVATE = "private"   # payload["viewer_hero_id"] names the authorized viewer


class CombatEventType(str, Enum):
    ENCOUNTER_STARTED = "encounter_started"
    THREAT_BUDGET_CALCULATED = "threat_budget_calculated"
    REINFORCEMENTS_SCHEDULED = "reinforcements_scheduled"
    REINFORCEMENTS_ARRIVED = "reinforcements_arrived"
    INITIATIVE_ROLLED = "initiative_rolled"
    COMBAT_ROUND_STARTED = "combat_round_started"
    TURN_STARTED = "turn_started"
    MOVED = "moved"
    QUICK_INTERACTION_USED = "quick_interaction_used"
    ATTACK_RESOLVED = "attack_resolved"
    DAMAGE_APPLIED = "damage_applied"
    MANEUVER_RESOLVED = "maneuver_resolved"
    REACTION_RESOLVED = "reaction_resolved"
    INTENT_TELEGRAPHED = "intent_telegraphed"
    ENEMY_ACTION_RESOLVED = "enemy_action_resolved"
    STATUS_APPLIED = "status_applied"
    STATUS_ESCALATED = "status_escalated"
    STATUS_CONSOLIDATED = "status_consolidated"
    STATUS_TREATED = "status_treated"
    STATUS_EXPIRED = "status_expired"
    HERO_DOWNED = "hero_downed"
    DEATH_CHECK_RESOLVED = "death_check_resolved"
    HERO_STABILIZED = "hero_stabilized"
    HERO_REVIVED = "hero_revived"
    HERO_DIED = "hero_died"
    ENEMY_DEFEATED = "enemy_defeated"
    BARRICADE_ESTABLISHED = "barricade_established"
    JOINER_ENTERED = "joiner_entered"
    ENCOUNTER_ENDED = "encounter_ended"


def make_event_id(combat_round: int, seq: int) -> str:
    return f"cevt_{combat_round}_{seq:04d}"


def make_event(
    *,
    event_id: str,
    encounter_id: str,
    combat_round: int,
    caused_by: str,
    type: CombatEventType,
    actor_id: str | None = None,
    target_id: str | None = None,
    visibility: Visibility = Visibility.PUBLIC,
    payload: dict | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "encounter_id": encounter_id,
        "combat_round": combat_round,
        "caused_by": caused_by,
        "actor_id": actor_id,
        "target_id": target_id,
        "type": type.value,
        "visibility": visibility.value,
        "payload": payload or {},
    }


class EventSequencer:
    """Hands out monotonic event ids for one encounter so every module that
    emits combat events doesn't need to thread its own counter through."""

    def __init__(self, encounter_id: str) -> None:
        self.encounter_id = encounter_id
        self._seq = 0

    def emit(
        self,
        *,
        combat_round: int,
        caused_by: str,
        type: CombatEventType,
        actor_id: str | None = None,
        target_id: str | None = None,
        visibility: Visibility = Visibility.PUBLIC,
        payload: dict | None = None,
    ) -> dict:
        self._seq += 1
        return make_event(
            event_id=make_event_id(combat_round, self._seq),
            encounter_id=self.encounter_id,
            combat_round=combat_round,
            caused_by=caused_by,
            type=type,
            actor_id=actor_id,
            target_id=target_id,
            visibility=visibility,
            payload=payload,
        )
