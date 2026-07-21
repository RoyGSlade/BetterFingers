"""Seeded, injectable RNG. The only source of randomness handle() is allowed to use.

Every draw goes through a named method so call sites are easy to audit for
determinism. Nothing outside domain/reducer.py's handle() dispatch should ever
construct its own random.Random — systems receive this object instead.
"""
from __future__ import annotations

import random
from typing import Sequence, TypeVar

T = TypeVar("T")


class StacksRNG:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._random = random.Random(seed)

    def roll_d4(self) -> int:
        return self._random.randint(1, 4)

    def roll_d8(self) -> int:
        return self._random.randint(1, 8)

    def roll_d20(self) -> int:
        return self._random.randint(1, 20)

    def randint(self, a: int, b: int) -> int:
        return self._random.randint(a, b)

    def choice(self, seq: Sequence[T]) -> T:
        return self._random.choice(seq)

    def shuffled(self, seq: Sequence[T]) -> list[T]:
        items = list(seq)
        self._random.shuffle(items)
        return items
