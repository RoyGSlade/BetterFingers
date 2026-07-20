"""Compile a card's effect list to LIVE §5 effect ops (docs/INFINITE_STACKS_CONTRACTS.md §5).

`content.schemas.KNOWN_OPS` currently marks exactly four ops `OpStatus.LIVE`
(`reveal_room`, `grant_check`, `spend_energy`, `emit_fact` -- verified by
`tests/test_stacks_content.py::test_known_ops_marked_live_have_a_real_systems_handler`).
This module does not import `content.schemas` to read that set: it declares
its own `LIVE_EFFECT_OPS` constant, the same "duplicate the values, not the
import" choice `heroes.creation` makes for attribute/skill names, so heroes
stays at zero runtime coupling to the content lane. If a future wave flips
more ops to LIVE, this constant is the one place that needs to grow.

Building a deck is the "build time" checkpoint (infinite_stacks.md §13.2/§13.3):
`compile_card_effect_ops` walks every effect a card can produce -- its
`base_effects` plus, if it has a check, every one of the four §12.3 outcome
branches -- and raises immediately if any op is not LIVE. A card that will
only ever produce a non-LIVE op this wave (e.g. a called-maneuver card that
deals `damage`) simply cannot be compiled into a starting deck yet; it is not
a runtime surprise when the card is drawn or played.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, Mapping, Protocol, Sequence

if TYPE_CHECKING:  # pragma: no cover -- type hints only, never imported at runtime
    from ..content.schemas import Card

LIVE_EFFECT_OPS = frozenset({"reveal_room", "grant_check", "spend_energy", "emit_fact"})


class NonLiveEffectOpError(ValueError):
    """Raised at deck-build time when a card references an effect op that has
    no real engine handler yet."""


class EffectLike(Protocol):
    op: str
    args: Mapping[str, Any]


class CheckOutcomesLike(Protocol):
    strong_success: Sequence[EffectLike]
    success: Sequence[EffectLike]
    cost: Sequence[EffectLike]
    setback: Sequence[EffectLike]


class CardCheckLike(Protocol):
    outcomes: CheckOutcomesLike


class CardLike(Protocol):
    """Structural shape this module needs from a card -- exactly
    `content.schemas.Card`'s public fields, duck-typed."""

    id: str
    base_effects: Sequence[EffectLike]
    check: "CardCheckLike | None"


_OUTCOME_GROUPS = ("strong_success", "success", "cost", "setback")


def iter_card_effects(card: "CardLike | Card") -> Iterator[EffectLike]:
    """Every effect a card can produce: its unconditional base effects, plus
    (if it has a check) all four §12.3 degree-of-outcome branches."""

    yield from card.base_effects
    if card.check is not None:
        for group in _OUTCOME_GROUPS:
            yield from getattr(card.check.outcomes, group)


def compile_card_effect_ops(card: "CardLike | Card") -> list[dict[str, Any]]:
    """Compile every effect on `card` to the engine's `{"op", "args"}` wire
    shape. Raises `NonLiveEffectOpError` -- loudly, at this call, not when the
    op is later dispatched -- if any effect references an op outside
    `LIVE_EFFECT_OPS`."""

    compiled: list[dict[str, Any]] = []
    for effect in iter_card_effects(card):
        if effect.op not in LIVE_EFFECT_OPS:
            raise NonLiveEffectOpError(
                f"card {card.id!r} references effect op {effect.op!r}, which is not LIVE "
                f"this wave (LIVE ops: {sorted(LIVE_EFFECT_OPS)}) -- cannot build a deck "
                "containing this card yet"
            )
        compiled.append({"op": effect.op, "args": dict(effect.args)})
    return compiled


def compile_deck_card_pool(
    card_ids: Sequence[str], card_lookup: Mapping[str, "CardLike | Card"]
) -> dict[str, list[dict[str, Any]]]:
    """Compile every card id's effects. This is the single call site
    `heroes.deck.build_starting_deck` uses as its build-time gate -- every
    card in a deck must compile before the deck exists at all."""

    compiled: dict[str, list[dict[str, Any]]] = {}
    for card_id in card_ids:
        if card_id not in card_lookup:
            raise KeyError(f"unknown card id {card_id!r}")
        compiled[card_id] = compile_card_effect_ops(card_lookup[card_id])
    return compiled
