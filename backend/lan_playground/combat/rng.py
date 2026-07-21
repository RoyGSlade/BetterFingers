"""Injectable RNG interface for the combat package.

Combat never imports domain.rng.StacksRNG directly -- that keeps this package
importable/testable without any dependency on the engine lane. Instead every
combat function that draws randomness accepts anything structurally matching
`CombatRNG` below, which is exactly the surface `domain.rng.StacksRNG` already
exposes (roll_d20, randint, choice, shuffled), so the real StacksRNG can be
passed in unmodified once wave-3 wiring lands.

Weapon/damage dice other than d20 (d4/d6/d8/d10) go through `randint(1, n)`
rather than dedicated `roll_dN` methods, since that is the one generic method
every draw-name convention in this codebase already agrees on.
"""
from __future__ import annotations

from typing import Protocol, Sequence, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class CombatRNG(Protocol):
    def roll_d20(self) -> int: ...

    def randint(self, a: int, b: int) -> int: ...

    def choice(self, seq: Sequence[T]) -> T: ...

    def shuffled(self, seq: Sequence[T]) -> list[T]: ...


def roll_die(rng: CombatRNG, faces: int) -> int:
    """Roll one die of the given face count (d4/d6/d8/d10/...) via randint."""
    if faces == 20:
        return rng.roll_d20()
    return rng.randint(1, faces)
