"""Independent solver for the ordering/sequence puzzle family (§10.3 #1).

This module deliberately shares NO code with `ordering_sequence.py`'s
generator. The generator builds an instance top-down: it picks a solution
first, then derives true facts from it. This solver goes the opposite
direction and touches only what a player would have: it reads each clue's
structured `reveals` dict, then brute-forces every permutation of the
referenced items and keeps the ones consistent with every clue.

`PuzzleInstance.solution` / `accepted_solutions` are NEVER read by `solve()`.
They exist only so a caller (tests, CI) can compare the solver's
independently-derived answer against the generator's claimed answer -- a real
cross-check, not a re-run of the same logic.
"""

from __future__ import annotations

from itertools import permutations
from typing import Sequence

from .. import schemas as S


def _items_from_clues(clues: Sequence[S.PuzzleClue]) -> list[str]:
    items: set[str] = set()
    for clue in clues:
        reveal = clue.reveals
        ftype = reveal.get("type")
        if ftype in ("position", "not_position"):
            items.add(reveal["item"])
        elif ftype in ("immediately_before", "before", "adjacent"):
            items.add(reveal["a"])
            items.add(reveal["b"])
        else:
            raise ValueError(f"solver does not understand clue fact type {ftype!r}")
    return sorted(items)


def _permutation_satisfies(perm: Sequence[str], clues: Sequence[S.PuzzleClue]) -> bool:
    pos = {item: i for i, item in enumerate(perm)}
    for clue in clues:
        reveal = clue.reveals
        ftype = reveal["type"]
        if ftype == "position":
            if pos[reveal["item"]] != reveal["position"]:
                return False
        elif ftype == "not_position":
            if pos[reveal["item"]] == reveal["position"]:
                return False
        elif ftype == "immediately_before":
            if pos[reveal["b"]] != pos[reveal["a"]] + 1:
                return False
        elif ftype == "before":
            if pos[reveal["a"]] >= pos[reveal["b"]]:
                return False
        elif ftype == "adjacent":
            if abs(pos[reveal["a"]] - pos[reveal["b"]]) != 1:
                return False
    return True


def solve(clues: Sequence[S.PuzzleClue]) -> list[tuple[str, ...]]:
    """Return every permutation of the clue-referenced items consistent with
    every clue. Independent of any instance's declared solution."""

    items = _items_from_clues(clues)
    return [perm for perm in permutations(items) if _permutation_satisfies(perm, clues)]


def solve_instance(instance: S.PuzzleInstance) -> list[tuple[str, ...]]:
    return solve(instance.clues)
