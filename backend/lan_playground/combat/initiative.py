"""Initiative and the combat-round/world-round sync model (§14.1).

`d20 + Finesse` (hero) / `d20 + initiative_bonus` (enemy), resolved highest to
lowest with a fully deterministic tie rule so replay never depends on dict
or set ordering:

1. higher initiative bonus wins (the "who would plausibly go first" signal);
2. heroes act before enemies on a full tie (keeps the ability to react
   player-facing rather than arbitrary);
3. lowest combatant id, lexicographically, as the final tiebreak.

One combat round == one world round (§14.1 step 7: "begin the next world
round after every living hero and enemy group has acted"). A hero who joins
mid-fight (§15.3 rescue play / a distant hero arriving) is queued and only
enters the initiative order at the *next* cycle -- `roll_initiative` never
mutates an order already in progress; callers only ever call it between
rounds, and `integrate_joiners` is the explicit seam for folding new
arrivals into that next roll.
"""
from __future__ import annotations

from dataclasses import dataclass

from .events import CombatEventType, EventSequencer, Visibility
from .models import EnemyCombatant, HeroCombatant

Combatant = HeroCombatant | EnemyCombatant


def _combatant_id(c: Combatant) -> str:
    return c.hero_id if isinstance(c, HeroCombatant) else c.instance_id


def _initiative_bonus(c: Combatant) -> int:
    return c.initiative_bonus if isinstance(c, EnemyCombatant) else c.attributes.finesse


@dataclass(frozen=True)
class InitiativeEntry:
    combatant_id: str
    is_hero: bool
    roll: int
    bonus: int
    total: int


def _tie_key(entry: InitiativeEntry) -> tuple:
    # Sort descending on total/bonus, heroes-first, id ascending -- negate
    # the numeric fields so a single ascending sort produces the right order.
    return (-entry.total, -entry.bonus, 0 if entry.is_hero else 1, entry.combatant_id)


def roll_initiative(
    combatants: list[Combatant],
    rng,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> tuple[list[InitiativeEntry], list[dict]]:
    entries: list[InitiativeEntry] = []
    events: list[dict] = []
    for c in combatants:
        roll = rng.roll_d20()
        bonus = _initiative_bonus(c)
        cid = _combatant_id(c)
        entries.append(
            InitiativeEntry(
                combatant_id=cid,
                is_hero=isinstance(c, HeroCombatant),
                roll=roll,
                bonus=bonus,
                total=roll + bonus,
            )
        )
        events.append(
            sequencer.emit(
                combat_round=combat_round,
                caused_by=caused_by,
                type=CombatEventType.INITIATIVE_ROLLED,
                actor_id=cid,
                target_id=cid,
                visibility=Visibility.PUBLIC,
                payload={"roll": roll, "bonus": bonus, "total": roll + bonus},
            )
        )
    entries.sort(key=_tie_key)
    return entries, events


def integrate_joiners(
    order: list[InitiativeEntry],
    joiners: list[Combatant],
    rng,
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> tuple[list[InitiativeEntry], list[dict]]:
    """Roll initiative for newly-arrived combatants and merge them into the
    order for the upcoming cycle. Callers must only invoke this at a combat
    round boundary -- never mid-round -- so "joiners enter at next
    initiative cycle" (§14.1) holds by construction."""
    joiner_entries, events = roll_initiative(
        joiners, rng, combat_round=combat_round, sequencer=sequencer, caused_by=caused_by
    )
    for entry in joiner_entries:
        events.append(
            sequencer.emit(
                combat_round=combat_round,
                caused_by=caused_by,
                type=CombatEventType.JOINER_ENTERED,
                actor_id=entry.combatant_id,
                target_id=entry.combatant_id,
                visibility=Visibility.PARTY,
                payload={"total": entry.total},
            )
        )
    merged = sorted(order + joiner_entries, key=_tie_key)
    return merged, events


def start_combat_round(
    order: list[InitiativeEntry],
    *,
    combat_round: int,
    sequencer: EventSequencer,
    caused_by: str,
) -> dict:
    return sequencer.emit(
        combat_round=combat_round,
        caused_by=caused_by,
        type=CombatEventType.COMBAT_ROUND_STARTED,
        visibility=Visibility.PUBLIC,
        payload={"order": [e.combatant_id for e in order]},
    )


def active_order(order: list[InitiativeEntry], living_ids: set[str]) -> list[InitiativeEntry]:
    """The initiative order filtered to combatants still able to act this
    round (alive heroes, living enemies) -- Downed/Stable/Dead heroes and
    defeated enemies are skipped for turn purposes but stay in `order` for
    the next roll's tie bookkeeping."""
    return [e for e in order if e.combatant_id in living_ids]
