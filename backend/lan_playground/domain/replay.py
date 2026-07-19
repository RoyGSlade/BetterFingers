"""Replay a seed + event log to an authoritative state (infinite_stacks.md §22.1).

Replaying the initial seed and event log must reproduce authoritative state
exactly. Replay never touches the RNG -- events already carry the *results*
of every random draw, so this is pure `reduce()` folding.
"""
from __future__ import annotations

from .events import Event
from .reducer import reduce
from .state import RunState


def replay(run_id: str, seed: int, chapter_floor_index: int, events: list[Event]) -> RunState:
    state = RunState.initial(run_id=run_id, seed=seed, chapter_floor_index=chapter_floor_index)
    for event in events:
        state = reduce(state, event)
    return state


def verify_replay(run_id: str, seed: int, chapter_floor_index: int, events: list[Event], expected_hash: str) -> bool:
    return replay(run_id, seed, chapter_floor_index, events).state_hash() == expected_hash
