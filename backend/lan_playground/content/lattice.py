"""Meaning Lattice component/recipe schemas (wave 6B, board note #30).

`wavebasedgame.md` §2 locked decision 1 (2026-07-21) supersedes the old
`infinite_stacks.md` §7.3 `required_rooms = min(6 + floor, 12)` formula as a
floor-*completion gate*: a floor no longer unlocks its stair by resolving a
raw count of rooms. Instead each resolved room repairs some amount of one or
more **lattice components** (Truth, Memory, Binding, Identity, Sequence, plus
any later component types), and a floor declares a **recipe** -- a required
set of component thresholds -- that is satisfied once enough rooms have
contributed enough of each component. `required_rooms`/`maximum_rooms` still
exist as a floor-size/pacing dial (how many rooms *can* exist), but they are
no longer the unlock condition; the recipe is.

This module is pure data + a satisfiability check. It does not decide *when*
a room resolves (that is domain/systems wiring, explicitly out of scope for
this wave -- see docs/INFINITE_STACKS_STUDY_SLICE.md) -- it only describes
the shape of a contribution and a recipe, and answers "is this recipe
satisfied by this set of contributions" as a pure function so the later
wiring wave has an already-tested seam to call into.

Ground rules mirrored from `schemas.py`:
  - IDs are stable snake_case (`validate_id`).
  - A recipe is satisfiable-checkable from a plain list of contributions --
    no hidden global state, no room-count fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

from .schemas import ContentError, validate_id

# ---------------------------------------------------------------------------
# Component types (§2.1: "at minimum" Truth, Memory, Binding, Identity,
# Sequence -- the set is extensible, so this is a frozenset of currently
# authored components rather than a closed Enum with no growth path).
# ---------------------------------------------------------------------------


class LatticeComponent(str, Enum):
    TRUTH = "truth"
    MEMORY = "memory"
    BINDING = "binding"
    IDENTITY = "identity"
    SEQUENCE = "sequence"


# ---------------------------------------------------------------------------
# A room's lattice contribution (referenced by content/rooms.py::RoomTemplate)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatticeContribution:
    """How much of which component(s) a *resolved* room repairs.

    Entering a room contributes nothing (locked decision 1: "Entering a room
    alone does not repair it -- the room must resolve"). `RoomTemplate` is
    responsible for only ever surfacing this contribution through whatever
    domain signal represents "this room resolved" -- this dataclass itself
    has no opinion on that signal, it is just the declared amount.
    """

    amounts: Mapping[LatticeComponent, int]

    def __post_init__(self) -> None:
        if not self.amounts:
            raise ContentError("LatticeContribution must declare at least one component amount")
        for component, amount in self.amounts.items():
            if not isinstance(component, LatticeComponent):
                raise ContentError(f"lattice contribution key {component!r} is not a LatticeComponent")
            if amount <= 0:
                raise ContentError(
                    f"lattice contribution amount for {component.value!r} must be positive, got {amount}"
                )


# ---------------------------------------------------------------------------
# Floor recipe: a required threshold per component, NOT a room counter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatticeRecipe:
    """A floor's required set of component thresholds.

    Satisfied when the *summed* contributions from every resolved room in
    the floor meet or exceed every threshold declared here. A recipe that
    requires only one component satisfiable by one room is a legal minimal
    case (used by the one-room-satisfiable test floor in this wave's
    authored slice) -- there is no minimum room count baked into this shape,
    which is the point: the room counter is demoted to a pacing dial
    elsewhere, never reintroduced here.
    """

    id: str
    floor_id: str
    thresholds: Mapping[LatticeComponent, int]

    def __post_init__(self) -> None:
        validate_id(self.id, kind="lattice_recipe")
        if not self.floor_id.strip():
            raise ContentError(f"lattice recipe {self.id!r} must declare a floor_id")
        if not self.thresholds:
            raise ContentError(f"lattice recipe {self.id!r} must declare at least one component threshold")
        for component, threshold in self.thresholds.items():
            if not isinstance(component, LatticeComponent):
                raise ContentError(f"lattice recipe {self.id!r} threshold key {component!r} is not a LatticeComponent")
            if threshold <= 0:
                raise ContentError(
                    f"lattice recipe {self.id!r} threshold for {component.value!r} must be positive, got {threshold}"
                )

    def is_satisfied(self, contributions: Sequence[LatticeContribution]) -> bool:
        """Pure satisfiability check: sum every contribution's amounts per
        component, then compare against this recipe's thresholds. No side
        effects, no notion of "which room" contributed which amount -- the
        caller (a future wiring wave) is responsible for only ever passing
        the contributions of *resolved* rooms."""

        totals = totals_by_component(contributions)
        return all(totals.get(component, 0) >= threshold for component, threshold in self.thresholds.items())

    def missing(self, contributions: Sequence[LatticeContribution]) -> Mapping[LatticeComponent, int]:
        """How much of each component is still needed to satisfy the
        recipe -- useful for a future UI/narration hint, not required by
        this wave's tests but cheap to keep correct alongside is_satisfied."""

        totals = totals_by_component(contributions)
        gap = {}
        for component, threshold in self.thresholds.items():
            have = totals.get(component, 0)
            if have < threshold:
                gap[component] = threshold - have
        return gap


def totals_by_component(
    contributions: Sequence[LatticeContribution],
) -> Mapping[LatticeComponent, int]:
    totals: dict[LatticeComponent, int] = {}
    for contribution in contributions:
        for component, amount in contribution.amounts.items():
            totals[component] = totals.get(component, 0) + amount
    return totals
