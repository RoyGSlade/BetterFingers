"""Run-summary fold (RUN-001 groundwork, board task #15 item 3): a pure fold
over a domain event log producing the end-of-run stats dict.

Reads *plain dicts* shaped like `domain.events.Event.to_dict()`
(docs/INFINITE_STACKS_CONTRACTS.md §3: `{event_id, run_id, world_round,
caused_by, type, visibility, actor_hero_id, room_id, payload}`) -- never a
domain `Event` object, so this module has zero import of `domain` (per the
package-wide "content/event data passed in, never imported" discipline).
`type` values are read from `domain/events.py`'s `EventType` string values as
documented in the contracts doc (§3, §5.1, §5.3); this module only ever
compares against the string, never the enum.

Tolerant of unknown event types by construction: `_HANDLERS` is a lookup
table, and any `type` not present in it is silently skipped rather than
raising. This is deliberate forward-compatibility -- future waves (item
pickup/drop events from the herowire lane, book/fragment events from a later
phase) can be wired in by adding a handler here without this module (or its
callers) needing to change shape.

Known gap, documented rather than guessed at: infinite_stacks.md's
`fragments_recovered` stat (§17.1 "Knowledge Restored") has no corresponding
domain event yet (books/library is Phase 8, out of scope through wave 5) --
it is always 0 until that vocabulary exists. Item pickup/drop/trade has no
domain event yet either (wave 4's herowire lane is wiring it into
`domain`/`systems` concurrently with this package); `items_gained`/
`items_lost` are likewise always 0 until those event types land and a
handler is added to `_HANDLERS` below.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

StatsDict = dict[str, Any]

_PUZZLE_STAT_KEYS = ("instantiated", "solved", "rejected", "forced", "hints_used")


def _empty_stats() -> StatsDict:
    return {
        "rooms_resolved": 0,
        "fragments_recovered": 0,
        "encounters_won": 0,
        "encounters_lost": 0,
        "heroes_downed": 0,
        "heroes_dead": 0,
        "items_gained": 0,
        "items_lost": 0,
        "puzzle_stats": {key: 0 for key in _PUZZLE_STAT_KEYS},
    }


class _FoldState:
    """Mutable scratch space threaded through the fold, private to this
    module -- `fold_run_summary`'s return value is only the plain `stats`
    dict."""

    __slots__ = ("stats", "seen_room_ids", "dead_hero_ids", "life_state_by_hero")

    def __init__(self) -> None:
        self.stats = _empty_stats()
        self.seen_room_ids: set[str] = set()
        self.dead_hero_ids: set[str] = set()
        self.life_state_by_hero: dict[str, str] = {}


def _handle_room_breached(fold: _FoldState, event: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    # The room_id lives on the envelope itself (docs/INFINITE_STACKS_CONTRACTS.md
    # §3: "room_id: str | None"), not inside payload -- payload's
    # from_room_id/to_room_id pair describes the move, the envelope's room_id
    # is "which room this event concerns" (systems/exploration.py sets it to
    # the breached room). Falls back to payload["to_room_id"] for callers
    # that hand this fold a payload-only dict without the full envelope.
    room_id = event.get("room_id") or payload.get("to_room_id")
    if room_id is not None and room_id not in fold.seen_room_ids:
        fold.seen_room_ids.add(room_id)
        fold.stats["rooms_resolved"] += 1


def _handle_puzzle_instantiated(fold: _FoldState, event: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    fold.stats["puzzle_stats"]["instantiated"] += 1


def _handle_puzzle_solution_accepted(fold: _FoldState, event: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    fold.stats["puzzle_stats"]["solved"] += 1


def _handle_puzzle_solution_rejected(fold: _FoldState, event: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    fold.stats["puzzle_stats"]["rejected"] += 1


def _handle_puzzle_force_progress(fold: _FoldState, event: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    fold.stats["puzzle_stats"]["forced"] += 1


def _handle_puzzle_hint_revealed(fold: _FoldState, event: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    fold.stats["puzzle_stats"]["hints_used"] += 1


def _process_hero_updates(fold: _FoldState, payload: Mapping[str, Any]) -> None:
    """Shared by conflict_encounter_started/conflict_turn_resolved/
    conflict_encounter_ended -- all three carry `hero_updates`
    (docs/INFINITE_STACKS_CONTRACTS.md §5.3, `systems/combat.py`'s
    `_end_or_continue`/`build_start_encounter_events`). `heroes_downed`
    counts transitions *into* "downed" (no explicit event exists yet, so this
    is derived from the life_state snapshot); `heroes_dead` reads the
    explicit `newly_dead_hero_ids` list the domain layer already computed,
    deduplicated defensively in case a hero somehow appears twice."""

    hero_updates = payload.get("hero_updates") or {}
    for hero_id, update in hero_updates.items():
        life_state = update.get("life_state")
        if life_state is None:
            continue
        prior = fold.life_state_by_hero.get(hero_id)
        if life_state == "downed" and prior != "downed":
            fold.stats["heroes_downed"] += 1
        fold.life_state_by_hero[hero_id] = life_state

    for hero_id in payload.get("newly_dead_hero_ids") or ():
        if hero_id not in fold.dead_hero_ids:
            fold.dead_hero_ids.add(hero_id)
            fold.stats["heroes_dead"] += 1


def _handle_conflict_started_or_resolved(
    fold: _FoldState, event: Mapping[str, Any], payload: Mapping[str, Any]
) -> None:
    _process_hero_updates(fold, payload)


def _handle_conflict_encounter_ended(
    fold: _FoldState, event: Mapping[str, Any], payload: Mapping[str, Any]
) -> None:
    _process_hero_updates(fold, payload)
    outcome = payload.get("outcome")
    if outcome == "victory":
        fold.stats["encounters_won"] += 1
    elif outcome == "party_wiped":
        fold.stats["encounters_lost"] += 1


_HANDLERS: dict[str, Callable[[_FoldState, Mapping[str, Any], Mapping[str, Any]], None]] = {
    "room_breached": _handle_room_breached,
    "mystery_puzzle_instantiated": _handle_puzzle_instantiated,
    "puzzle_solution_accepted": _handle_puzzle_solution_accepted,
    "puzzle_solution_rejected": _handle_puzzle_solution_rejected,
    "puzzle_force_progress": _handle_puzzle_force_progress,
    "puzzle_hint_revealed": _handle_puzzle_hint_revealed,
    "conflict_encounter_started": _handle_conflict_started_or_resolved,
    "conflict_turn_resolved": _handle_conflict_started_or_resolved,
    "conflict_encounter_ended": _handle_conflict_encounter_ended,
}


def fold_run_summary(event_log: Iterable[Mapping[str, Any]]) -> StatsDict:
    """Pure fold: same event log in, same stats dict out, every time. Events
    missing a `type` key, or carrying a `type` this module doesn't recognize,
    are skipped rather than raising (forward-compatible with event
    vocabulary this wave doesn't know about yet)."""

    fold = _FoldState()
    for event in event_log:
        event_type = event.get("type")
        if event_type is None:
            continue
        handler = _HANDLERS.get(event_type)
        if handler is None:
            continue
        handler(fold, event, event.get("payload") or {})
    return fold.stats
