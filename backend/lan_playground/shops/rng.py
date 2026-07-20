"""Injectable RNG interface for the shops package (infinite_stacks.md §9.6:
"seeded inventories").

Same structural-Protocol pattern as `combat.rng.CombatRNG` / `heroes.rng.HeroesRNG`:
shops never imports `domain.rng.StacksRNG` directly, so it stays
importable/testable with zero dependency on the engine lane. `ShopsRNG`
mirrors the same method shape those Protocols already expose -- the real
`domain.rng.StacksRNG` satisfies it unmodified once wave-5 wiring lands.
"""
from __future__ import annotations

from typing import Protocol, Sequence, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class ShopsRNG(Protocol):
    def roll_d20(self) -> int: ...

    def randint(self, a: int, b: int) -> int: ...

    def choice(self, seq: Sequence[T]) -> T: ...

    def shuffled(self, seq: Sequence[T]) -> list[T]: ...
