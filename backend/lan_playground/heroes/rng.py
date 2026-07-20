"""Injectable RNG interface for the heroes package (infinite_stacks.md §11.1,
§13.2).

Same structural-Protocol pattern as `combat.rng.CombatRNG`: heroes never
imports `domain.rng.StacksRNG` directly, so it stays importable/testable with
zero dependency on the engine lane. `HeroesRNG` intentionally mirrors
`CombatRNG`'s exact method shape (`roll_d20`/`randint`/`choice`/`shuffled`) --
that is exactly the surface `domain.rng.StacksRNG` already exposes, so the
real RNG can be passed into heroes functions unmodified once wave-4 wiring
lands, with zero adapter code (same story as combat's wave-2 -> wave-3 wiring).
"""
from __future__ import annotations

from typing import Protocol, Sequence, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class HeroesRNG(Protocol):
    def roll_d20(self) -> int: ...

    def randint(self, a: int, b: int) -> int: ...

    def choice(self, seq: Sequence[T]) -> T: ...

    def shuffled(self, seq: Sequence[T]) -> list[T]: ...


def roll_d4(rng: HeroesRNG) -> int:
    """Roll one visible d4 (§11.1 attribute dice)."""
    return rng.randint(1, 4)
